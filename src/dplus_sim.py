#!/usr/bin/env python3
"""DPlus-Simulator Dienst.

Dieses Skript implementiert einen D-Bus-Dienst, der das Verhalten einer D+-Leitung
simuliert. Der Dienst bildet eine Hysterese mit einstellbaren Verzögerungen ab und
steuert optional einen GPIO-Pin. Er ist darauf ausgelegt, sowohl auf Hardware mit
vorhandener D-Bus- und GPIO-Unterstützung zu funktionieren als auch in reinen
Entwicklungsumgebungen ohne diese Abhängigkeiten lauffähig zu sein.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import inspect
import json
import logging
import math
import os
import queue
import signal as stdlib_signal
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, Iterable, Mapping, Optional, Set, Tuple

try:  # pragma: no-cover - Venus-OS asyncio D-Bus
    from dbus_fast import BusType, Message, Variant
    from dbus_fast.aio import MessageBus
    from dbus_fast.constants import MessageType
    from dbus_fast.service import ServiceInterface, method, signal
    DBUS_NEXT_BACKEND = "dbus_fast"
except Exception:  # pragma: no-cover - Fallback ohne asyncio-D-Bus
    DBUS_NEXT_BACKEND = None
    BusType = None
    Message = None
    MessageType = type("MessageType", (), {"SIGNAL": "signal"})

    class Variant:  # type: ignore[override]
        """Minimaler Ersatz, wenn keine asyncio-D-Bus-Bibliothek verfügbar ist."""

        def __init__(self, _signature: str, value: Any) -> None:
            self.value = value

    class ServiceInterface:  # type: ignore[override]
        def __init__(self, name: str) -> None:
            self.name = name

    def method(*_d_args: Any, **_d_kwargs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            return func

        return decorator

    def signal(*_d_args: Any, **_d_kwargs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            return func

        return decorator

    class MessageBus:  # type: ignore[override]
        @classmethod
        async def connect(cls, *_args: Any, **_kwargs: Any) -> "MessageBus":
            raise RuntimeError("D-Bus-Unterstützung ist nicht verfügbar (dbus_fast fehlt)")

    class BusType:  # type: ignore[override]
        SESSION = "session"
        SYSTEM = "system"



try:  # pragma: no-cover - optionale Abhängigkeit
    import dbus  # type: ignore
except Exception:  # pragma: no-cover
    dbus = None  # type: ignore

try:  # pragma: no-cover - optionale Abhängigkeit
    from dbus.mainloop.glib import DBusGMainLoop  # type: ignore
except Exception:  # pragma: no-cover
    DBusGMainLoop = None  # type: ignore

try:  # pragma: no-cover - optionale Abhängigkeit
    from gi.repository import GLib  # type: ignore
except Exception:  # pragma: no-cover
    GLib = None  # type: ignore

try:  # pragma: no-cover - optionale Abhängigkeit für velib_python
    from settingsdevice import SettingsDevice as VelibSettingsDevice  # type: ignore
except Exception:  # pragma: no-cover - Fallback ohne settingsdevice
    VelibSettingsDevice = None  # type: ignore

try:  # pragma: no-cover - optionale Abhängigkeit für vedbus
    from vedbus import VeDbusItemImport  # type: ignore
except Exception:  # pragma: no-cover - Fallback ohne vedbus
    VeDbusItemImport = None  # type: ignore


DEFAULT_GPIO_PIN = 17
DEFAULT_TARGET_VOLTAGE = 13.0
DEFAULT_HYSTERESIS = 0.4
DEFAULT_ACTIVATION_DELAY_SECONDS = 2.0
DEFAULT_DEACTIVATION_DELAY_SECONDS = 5.0
DEFAULT_ON_VOLTAGE = DEFAULT_TARGET_VOLTAGE + DEFAULT_HYSTERESIS / 2.0
DEFAULT_OFF_VOLTAGE = DEFAULT_TARGET_VOLTAGE - DEFAULT_HYSTERESIS / 2.0
DEFAULT_ON_DELAY_SECONDS = DEFAULT_ACTIVATION_DELAY_SECONDS
DEFAULT_OFF_DELAY_SECONDS = DEFAULT_DEACTIVATION_DELAY_SECONDS
DEFAULT_OUTPUT_MODE = "relay"
DEFAULT_RELAY_CHANNEL = "5"
DEFAULT_RELAY_TARGET = "system"
DEFAULT_VOLTAGE_SOURCE_MODE = "auto"
DEFAULT_STATUS_PUBLISH_INTERVAL = 2.0
RELAY_FUNCTION_TAG = "manual"
RELAY_FUNCTION_NEUTRAL = "manual"


DEV_FEATURE_FLAG_ENV_VAR = "DPLUS_SIM_DEV_MODE"
_TRUE_ENV_VALUES: Set[str] = {"1", "true", "yes", "on"}


def development_features_enabled() -> bool:
    """Return ``True`` if privileged development helpers are enabled."""

    value = os.getenv(DEV_FEATURE_FLAG_ENV_VAR, "").strip().lower()
    return bool(value) and value in _TRUE_ENV_VALUES


def normalize_relay_channel(channel: str) -> str:
    """Normalisiert Relay-Kanalnamen unabhängig von Groß-/Kleinschreibung."""

    text = str(channel or "").strip()
    if not text:
        return ""
    text = text.replace("\\", "/")
    text = text.strip("/")
    prefixes = [
        "com.victronenergy.system/",
        "settings/relays/",
        "relays/",
        "relay/",
    ]
    while text:
        lowered = text.lower()
        for prefix in prefixes:
            if lowered.startswith(prefix):
                text = text[len(prefix) :]
                break
        else:
            break
    lowered = text.lower()
    if lowered.endswith("/state"):
        text = text[: -len("/state")]
    return text


def map_system_relay_channel_to_internal(channel: str) -> str:
    """Wandelt die UI-/Settings-Nummerierung 1..N in interne 0..N-1 Kanäle um.

    Für bestehende Installationen bleiben bereits 0-basierte Werte kompatibel.
    Nicht-numerische Werte werden unverändert weitergereicht.
    """

    normalized = normalize_relay_channel(channel)
    if not normalized:
        return ""
    if not normalized.isdigit():
        return normalized
    number = int(normalized)
    if number <= 0:
        return "0"
    return str(number - 1)


def map_system_relay_channel_to_display(channel: str) -> str:
    """Wandelt interne 0-basierte System-Relay-Kanäle zurück in UI-Werte."""

    normalized = normalize_relay_channel(channel)
    if not normalized:
        return ""
    if not normalized.isdigit():
        return normalized
    return str(int(normalized) + 1)


def normalize_relay_target(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text == "bmv":
        return "bmv"
    return "system"


def normalize_bool(value: Any) -> bool:
    if isinstance(value, str):
        normalized = value.strip().lower()
        return normalized not in {"", "0", "false", "off", "no"}
    if isinstance(value, (int, float)):
        return value != 0
    return bool(value)


SETTINGS_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "enabled": {
        "path": "/Settings/Devices/DPlusSim/Enabled",
        "type": "b",
        "default": True,
        "description": "Aktiviert oder deaktiviert den D+-Simulator.",
        "min": 0,
        "max": 1,
    },
    "gpio_pin": {
        "path": "/Settings/Devices/DPlusSim/GpioPin",
        "type": "i",
        "default": DEFAULT_GPIO_PIN,
        "description": "GPIO-Pin, der die simulierte D+-Leitung schaltet.",
        "min": 0,
        "max": 0,
    },
    "on_voltage": {
        "path": "/Settings/Devices/DPlusSim/OnVoltage",
        "type": "d",
        "default": DEFAULT_ON_VOLTAGE,
        "description": "Spannung, ab der die D+-Simulation aktiviert werden soll.",
        "min": 0.0,
        "max": 0.0,
    },
    "off_voltage": {
        "path": "/Settings/Devices/DPlusSim/OffVoltage",
        "type": "d",
        "default": DEFAULT_OFF_VOLTAGE,
        "description": "Spannung, unter der die D+-Simulation deaktiviert wird.",
        "min": 0.0,
        "max": 0.0,
    },
    "on_delay_seconds": {
        "path": "/Settings/Devices/DPlusSim/OnDelaySec",
        "type": "d",
        "default": DEFAULT_ON_DELAY_SECONDS,
        "description": "Verzögerung in Sekunden bis zum Einschalten, sobald alle Bedingungen erfüllt sind.",
        "min": 0.0,
        "max": 0.0,
    },
    "off_delay_seconds": {
        "path": "/Settings/Devices/DPlusSim/OffDelaySec",
        "type": "d",
        "default": DEFAULT_OFF_DELAY_SECONDS,
        "description": "Verzögerung in Sekunden bis zum Ausschalten, wenn die Bedingungen entfallen.",
        "min": 0.0,
        "max": 0.0,
    },
    "manual_override": {
        "path": "/Settings/Devices/DPlusSim/ManualOverride",
        "type": "b",
        "default": False,
        "description": "Aktiviert die manuelle Übersteuerung des Ausgangs.",
        "min": 0,
        "max": 1,
    },
    "manual_state": {
        "path": "/Settings/Devices/DPlusSim/ManualState",
        "type": "b",
        "default": False,
        "description": "Gewünschter Ausgangszustand bei manueller Übersteuerung.",
        "min": 0,
        "max": 1,
    },
    "force_on": {
        "path": "/Settings/Devices/DPlusSim/ForceOn",
        "type": "b",
        "default": False,
        "description": "Kompatibilitätsalias für manuelles Einschalten aus älteren UI-Versionen.",
        "min": 0,
        "max": 1,
    },
    "force_off": {
        "path": "/Settings/Devices/DPlusSim/ForceOff",
        "type": "b",
        "default": False,
        "description": "Kompatibilitätsalias für manuelles Ausschalten aus älteren UI-Versionen.",
        "min": 0,
        "max": 1,
    },
    "output_state": {
        "path": "/Settings/Devices/DPlusSim/OutputState",
        "type": "b",
        "default": False,
        "description": "Aktueller Ausgangszustand des Simulators.",
        "min": 0,
        "max": 1,
    },
    "output_mode": {
        "path": "/Settings/Devices/DPlusSim/OutputMode",
        "type": "s",
        "default": DEFAULT_OUTPUT_MODE,
        "description": "Steuerungsmodus für den D+-Ausgang (gpio oder relay).",
        "min": 0,
        "max": 0,
    },
    "voltage_source_mode": {
        "path": "/Settings/Devices/DPlusSim/VoltageSourceMode",
        "type": "s",
        "default": DEFAULT_VOLTAGE_SOURCE_MODE,
        "description": "Auswahl der Spannungsquelle (auto oder manual).",
        "min": 0,
        "max": 0,
    },
    "relay_channel": {
        "path": "/Settings/Devices/DPlusSim/RelayChannel",
        "type": "s",
        "default": DEFAULT_RELAY_CHANNEL,
        "description": "Ausgewählter Relay-Kanal aus der gpiosetup-Konfiguration.",
        "min": 0,
        "max": 0,
    },
    "relay_target": {
        "path": "/Settings/Devices/DPlusSim/RelayTarget",
        "type": "s",
        "default": DEFAULT_RELAY_TARGET,
        "description": "Wählt zwischen System-Relay und BMV-Relay.",
        "min": 0,
        "max": 0,
    },
    "dbus_bus": {
        "path": "/Settings/Devices/DPlusSim/DbusBus",
        "type": "s",
        "default": "system",
        "description": "Zu verwendender D-Bus (system oder session).",
        "min": 0,
        "max": 0,
    },
    "service_path": {
        "path": "/Settings/Devices/DPlusSim/ServicePath",
        "type": "s",
        "default": "com.victronenergy.system",
        "description": (
            "D-Bus-Dienst, der die Starterspannung bereitstellt. Der Dienst wird "
            "automatisch erkannt; manuelle Änderungen werden verworfen."
        ),
        "min": 0,
        "max": 0,
    },
    "voltage_path": {
        "path": "/Settings/Devices/DPlusSim/VoltagePath",
        "type": "s",
        "default": "/StarterVoltage",
        "description": (
            "Objektpfad der Starterspannung innerhalb des automatisch erkannten "
            "Dienstes. Manuelle Änderungen werden verworfen."
        ),
        "min": 0,
        "max": 0,
    },
    "use_ignition": {
        "path": "/Settings/Devices/DPlusSim/UseIgnition",
        "type": "b",
        "default": False,
        "description": "Aktiviert die optionale Zündplus-Logik über vorhandene D-Bus-Digitaleingänge.",
        "min": 0,
        "max": 1,
    },
    "emergency_off_voltage": {
        "path": "/Settings/Devices/DPlusSim/EmergencyOffVoltage",
        "type": "d",
        "default": 11.8,
        "description": "Sicherheitsabschaltung bei extremer Unterspannung trotz aktiver Zündung.",
        "min": 0.0,
        "max": 0.0,
    },
    "emergency_off_delay_seconds": {
        "path": "/Settings/Devices/DPlusSim/EmergencyOffDelaySec",
        "type": "d",
        "default": 2.0,
        "description": "Verzögerung der Sicherheitsabschaltung bei extremer Unterspannung.",
        "min": 0.0,
        "max": 0.0,
    },
    "ignition_state": {
        "path": "/Settings/Devices/DPlusSim/IgnitionState",
        "type": "b",
        "default": False,
        "description": "Aktuell erkannter Zündstatus des automatischen D-Bus-Eingangs.",
        "min": 0,
        "max": 1,
    },
    "relay_function_backups": {
        "path": "/Settings/Devices/DPlusSim/RelayFunctionBackups",
        "type": "s",
        "default": "{}",
        "description": (
            "JSON-kodiertes Objekt, das die ursprünglichen Relay-Funktionen je Kanal sichert."
        ),
        "min": 0,
        "max": 0,
    },
}

DEFAULT_SETTINGS: Dict[str, Any] = {
    key: definition["default"] for key, definition in SETTINGS_DEFINITIONS.items()
}

StatusCallback = Callable[[Dict[str, Any]], Optional[Awaitable[None]]]
VoltageProvider = Callable[[], Awaitable[Optional[float]]]


SYSTEM_SERVICE_NAME = "com.victronenergy.system"
BATTERY_SERVICE_PREFIX = "com.victronenergy.battery."
SYSTEM_STARTER_VOLTAGE_PATHS = ("/StarterVoltage",)
SYSTEM_VOLTAGE_FALLBACK_PATHS = ("/Dc/Battery/Voltage",)
BATTERY_VOLTAGE_PATHS = ("/Dc/1/Voltage", "/Dc/0/Voltage", "/StarterVoltage")
STARTER_VOLTAGE_PATH = "/Dc/Battery/Voltage"
DIGITAL_INPUT_SERVICE_PREFIX = "com.victronenergy.digitalinput."
IGNITION_STATE_PATHS = ("/State", "/InputState")


class VoltageServiceDiscoveryError(RuntimeError):
    """Signalisiert, dass kein Dienst mit Starterspannung gefunden wurde."""


@dataclass(frozen=True)
class VoltageServiceInfo:
    service_name: str
    object_path: str
    bus_choice: str
    product_id: Optional[int] = None
    product_name: str = ""


IgnitionServiceInfo = VoltageServiceInfo


# Rückwärtskompatibilität zu älteren Namen
Bmv712DetectionError = VoltageServiceDiscoveryError
Bmv712ServiceInfo = VoltageServiceInfo


def _unwrap_dbus_value(value: Any) -> Any:
    if hasattr(value, "value"):
        return _unwrap_dbus_value(getattr(value, "value"))
    return value


async def _list_dbus_names(bus: MessageBus) -> Iterable[str]:
    reply = await bus.call(
        Message(
            destination="org.freedesktop.DBus",
            path="/org/freedesktop/DBus",
            interface="org.freedesktop.DBus",
            member="ListNames",
        )
    )
    if getattr(reply, "message_type", None) != getattr(MessageType, "METHOD_RETURN", None):
        raise VoltageServiceDiscoveryError(
            "Antwort von org.freedesktop.DBus.ListNames ist ungültig"
        )
    body = getattr(reply, "body", [])
    if not body:
        return []
    names = _unwrap_dbus_value(body[0])
    if isinstance(names, (list, tuple)):
        return [str(name) for name in names]
    raise VoltageServiceDiscoveryError("Antwort von org.freedesktop.DBus.ListNames ist leer")


async def _read_bus_value(bus: MessageBus, service: str, path: str) -> Any:
    reply = await bus.call(
        Message(
            destination=service,
            path=path,
            interface="com.victronenergy.BusItem",
            member="GetValue",
        )
    )
    if getattr(reply, "message_type", None) != getattr(MessageType, "METHOD_RETURN", None):
        raise VoltageServiceDiscoveryError(
            f"Dienst {service} hat keine gültige Antwort für {path} geliefert"
        )
    body = getattr(reply, "body", [])
    if not body:
        return None
    return _unwrap_dbus_value(body[0])


async def resolve_starter_voltage_service(bus_choice: str) -> VoltageServiceInfo:
    """Sucht einen Dienst, der die Starterspannung bereitstellt."""

    if BusType is None or MessageBus is None or Message is None:
        raise VoltageServiceDiscoveryError("D-Bus-Unterstützung ist nicht verfügbar")

    logger = logging.getLogger("StarterVoltageResolver")
    bus_choice_normalized, bus_type = resolve_bus_configuration(bus_choice)
    bus: Optional[MessageBus] = None
    try:
        connect_kwargs = {"bus_type": bus_type} if bus_type is not None else {}
        bus = await MessageBus(**connect_kwargs).connect()
    except Exception as exc:
        raise VoltageServiceDiscoveryError(
            f"Verbindung zum {bus_choice_normalized}-Bus fehlgeschlagen: {exc}"
        ) from exc

    try:
        for system_path in SYSTEM_STARTER_VOLTAGE_PATHS:
            try:
                value = await _read_bus_value(bus, SYSTEM_SERVICE_NAME, system_path)
            except Exception as exc:
                logger.debug(
                    "Systemdienst stellt keine Spannung über %s bereit: %s",
                    system_path,
                    exc,
                )
            else:
                if value is not None:
                    logger.info(
                        "Spannungsquelle über %s%s gefunden",
                        SYSTEM_SERVICE_NAME,
                        system_path,
                    )
                    return VoltageServiceInfo(
                        service_name=SYSTEM_SERVICE_NAME,
                        object_path=system_path,
                        bus_choice=bus_choice_normalized,
                    )

        names = await _list_dbus_names(bus)
        candidates = [name for name in names if name.startswith(BATTERY_SERVICE_PREFIX)]
        logger.debug("Gefundene Victron-Batteriedienste: %s", ", ".join(candidates))
        for candidate in candidates:
            for candidate_path in BATTERY_VOLTAGE_PATHS:
                try:
                    value = await _read_bus_value(bus, candidate, candidate_path)
                except Exception as exc:
                    logger.debug(
                        "Spannung bei %s%s konnte nicht gelesen werden: %s",
                        candidate,
                        candidate_path,
                        exc,
                    )
                    continue
                if value is None:
                    logger.debug(
                        "Spannung bei %s%s ist nicht verfügbar",
                        candidate,
                        candidate_path,
                    )
                    continue
                logger.info("Spannungsquelle über %s%s gefunden", candidate, candidate_path)
                return VoltageServiceInfo(
                    service_name=candidate,
                    object_path=candidate_path,
                    bus_choice=bus_choice_normalized,
                )

        for system_path in SYSTEM_VOLTAGE_FALLBACK_PATHS:
            try:
                value = await _read_bus_value(bus, SYSTEM_SERVICE_NAME, system_path)
            except Exception as exc:
                logger.debug(
                    "Systemdienst stellt keine Fallback-Spannung über %s bereit: %s",
                    system_path,
                    exc,
                )
            else:
                if value is not None:
                    logger.info(
                        "Fallback-Spannungsquelle über %s%s gefunden",
                        SYSTEM_SERVICE_NAME,
                        system_path,
                    )
                    return VoltageServiceInfo(
                        service_name=SYSTEM_SERVICE_NAME,
                        object_path=system_path,
                        bus_choice=bus_choice_normalized,
                    )
    finally:
        if bus is not None:
            disconnect = getattr(bus, "disconnect", None)
            if callable(disconnect):
                with contextlib.suppress(Exception):
                    result = disconnect()
                    if inspect.isawaitable(result):
                        await result
            wait_for_disconnect = getattr(bus, "wait_for_disconnect", None)
            if callable(wait_for_disconnect):
                with contextlib.suppress(Exception):
                    await wait_for_disconnect()

    raise VoltageServiceDiscoveryError(
        "Keine Starterspannung auf dem D-Bus gefunden"
    )


async def resolve_bmv712_service(bus_choice: str) -> VoltageServiceInfo:
    """Alias für Kompatibilität – verweist auf die Starterspannungs-Erkennung."""

    return await resolve_starter_voltage_service(bus_choice)


async def resolve_ignition_input_service(bus_choice: str) -> IgnitionServiceInfo:
    """Sucht einen vorhandenen Venus-OS-Digitaleingang für Zündplus."""

    if BusType is None or MessageBus is None or Message is None:
        raise VoltageServiceDiscoveryError("D-Bus-Unterstützung ist nicht verfügbar")

    logger = logging.getLogger("IgnitionInputResolver")
    bus_choice_normalized, bus_type = resolve_bus_configuration(bus_choice)
    bus: Optional[MessageBus] = None
    try:
        connect_kwargs = {"bus_type": bus_type} if bus_type is not None else {}
        bus = await MessageBus(**connect_kwargs).connect()
        names = await _list_dbus_names(bus)
        candidates = [name for name in names if name.startswith(DIGITAL_INPUT_SERVICE_PREFIX)]
        logger.debug("Gefundene digitale Eingänge: %s", ", ".join(candidates))
        for candidate in candidates:
            for candidate_path in IGNITION_STATE_PATHS:
                try:
                    value = await _read_bus_value(bus, candidate, candidate_path)
                except Exception as exc:
                    logger.debug("Digitalinput %s%s konnte nicht gelesen werden: %s", candidate, candidate_path, exc)
                    continue
                if value is None:
                    continue
                logger.info("Zündplus-Quelle über %s%s gefunden", candidate, candidate_path)
                return IgnitionServiceInfo(
                    service_name=candidate,
                    object_path=candidate_path,
                    bus_choice=bus_choice_normalized,
                )
    finally:
        if bus is not None:
            disconnect = getattr(bus, "disconnect", None)
            if callable(disconnect):
                with contextlib.suppress(Exception):
                    result = disconnect()
                    if inspect.isawaitable(result):
                        await result
            wait_for_disconnect = getattr(bus, "wait_for_disconnect", None)
            if callable(wait_for_disconnect):
                with contextlib.suppress(Exception):
                    await wait_for_disconnect()

    raise VoltageServiceDiscoveryError("Kein geeigneter DigitalInput für Zündplus gefunden")


def discover_battery_relay_service(bus_choice: str, preferred_service: str = "") -> str:
    """Findet einen Battery-/BMV-Dienst mit schaltbarem Relay automatisch.

    Bevorzugt den uebergebenen Dienst, falls er bereits auf einen Battery-Service zeigt.
    Faellt sonst auf den ersten vorhandenen Battery-Service mit /Relay/0/State zurueck,
    damit wechselnde ttyUSB-Nummern automatisch abgefangen werden.
    """

    preferred = str(preferred_service or "").strip()
    candidates = []
    if preferred.startswith(BATTERY_SERVICE_PREFIX):
        candidates.append(preferred)
    if dbus is None:
        return preferred if preferred.startswith(BATTERY_SERVICE_PREFIX) else ""
    try:
        bus = dbus.SystemBus() if (str(bus_choice or "system").strip().lower() != "session") else dbus.SessionBus()
        dbus_obj = bus.get_object("org.freedesktop.DBus", "/org/freedesktop/DBus")
        iface = dbus.Interface(dbus_obj, "org.freedesktop.DBus")
        names = [str(name) for name in iface.ListNames()]
        for name in names:
            if name.startswith(BATTERY_SERVICE_PREFIX) and name not in candidates:
                candidates.append(name)
        for service in candidates:
            try:
                item = VeDbusItemImport(bus, service, "/Relay/0/State", createsignal=False) if VeDbusItemImport is not None else None
                if item is not None:
                    item.get_value()
                    return service
            except Exception:
                continue
    except Exception:
        return preferred if preferred.startswith(BATTERY_SERVICE_PREFIX) else ""
    return preferred if preferred.startswith(BATTERY_SERVICE_PREFIX) else ""


def normalize_voltage_source_mode(value: Any) -> str:
    normalized = str(value or DEFAULT_VOLTAGE_SOURCE_MODE).strip().lower()
    if normalized == "manual":
        return "manual"
    return "auto"


class VoltageSourceError(RuntimeError):
    """Fehlerzustand beim Lesen einer externen Spannungsquelle."""


class DbusVoltageReader:
    """Liest Spannungswerte über den Victron D-Bus."""

    def __init__(self, service_name: str, object_path: str, bus_choice: str = "system") -> None:
        self._service_name = service_name
        self._object_path = object_path
        self._bus_choice = bus_choice
        self._bus: Optional[MessageBus] = None
        self._logger = logging.getLogger(self.__class__.__name__)
        self._lock = asyncio.Lock()
        self._sync_lock = threading.Lock()
        self._vedbus_item: Optional[Any] = None
        self._vedbus_bus: Optional[Any] = None
        self._use_vedbus = VeDbusItemImport is not None and dbus is not None
        self._reconnect_delay = 5.0
        self._next_attempt = 0.0
        self._failure_count = 0
        self._last_error: Optional[str] = None
        self._last_success = 0.0

    @property
    def description(self) -> str:
        return f"dbus:{self._service_name}{self._object_path}"

    @property
    def service_name(self) -> str:
        return self._service_name

    @property
    def object_path(self) -> str:
        return self._object_path

    @property
    def bus_choice(self) -> str:
        return self._bus_choice

    @property
    def failure_count(self) -> int:
        return self._failure_count

    @property
    def last_error(self) -> str:
        return self._last_error or ""

    @property
    def last_success(self) -> float:
        return self._last_success

    @property
    def metadata(self) -> Dict[str, Any]:
        return {
            "service": self._service_name,
            "path": self._object_path,
            "bus": self._bus_choice,
            "mode": "vedbus" if self._use_vedbus else "dbus-next",
        }

    async def initialize(self) -> None:
        if self._use_vedbus:
            loop = asyncio.get_running_loop()
            try:
                await loop.run_in_executor(None, self._initialize_vedbus)
            except VoltageSourceError as exc:
                self._failure_count += 1
                self._last_error = str(exc)
                raise
        else:
            async with self._lock:
                try:
                    await self._ensure_bus_locked()
                except VoltageSourceError as exc:
                    self._failure_count += 1
                    self._last_error = str(exc)
                    raise

    def _initialize_vedbus(self) -> None:
        with self._sync_lock:
            self._ensure_vedbus_locked(force=True)

    async def _ensure_bus_locked(self) -> None:
        if self._bus is not None:
            return
        if BusType is None or MessageBus is None or Message is None:
            raise VoltageSourceError("D-Bus-Unterstützung nicht verfügbar")
        bus_type = BusType.SYSTEM if self._bus_choice == "system" else BusType.SESSION
        try:
            self._bus = await MessageBus(bus_type=bus_type).connect()
        except Exception as exc:  # pragma: no-cover - Laufzeitabhängig
            raise VoltageSourceError(f"Verbindung zum D-Bus fehlgeschlagen: {exc}") from exc

    async def read_voltage(self) -> Optional[float]:
        if self._use_vedbus:
            try:
                value = await self._read_voltage_via_vedbus()
            except VoltageSourceError as exc:
                self._failure_count += 1
                self._last_error = str(exc)
                raise
        else:
            async with self._lock:
                try:
                    value = await self._read_voltage_via_dbusnext_locked()
                except VoltageSourceError as exc:
                    self._failure_count += 1
                    self._last_error = str(exc)
                    raise
        if value is not None:
            self._last_success = time.time()
            self._last_error = None
        return value

    async def _read_voltage_via_vedbus(self) -> Optional[float]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._read_voltage_via_vedbus_sync)

    def _read_voltage_via_vedbus_sync(self) -> Optional[float]:
        with self._sync_lock:
            try:
                self._ensure_vedbus_locked()
                if self._vedbus_item is None:
                    return None
                refresh = getattr(self._vedbus_item, "_refreshcachedvalue", None)
                if callable(refresh):
                    refresh()
                value = self._vedbus_item.get_value()
                if value is None:
                    return None
                return float(value)
            except VoltageSourceError:
                raise
            except Exception as exc:
                self._reset_vedbus_locked()
                raise VoltageSourceError(f"VeDbusItemImport konnte keinen Wert lesen: {exc}") from exc

    async def _read_voltage_via_dbusnext_locked(self) -> Optional[float]:
        await self._ensure_bus_locked()
        assert self._bus is not None
        message = Message(
            destination=self._service_name,
            path=self._object_path,
            interface="com.victronenergy.BusItem",
            member="GetValue",
        )
        try:
            reply = await self._bus.call(message)
        except Exception as exc:  # pragma: no-cover - Laufzeitabhängig
            await self._disconnect_locked()
            raise VoltageSourceError(f"Lesen des Spannungswertes fehlgeschlagen: {exc}") from exc
        if reply.message_type != MessageType.METHOD_RETURN:
            raise VoltageSourceError("Unerwartete Antwort vom D-Bus")
        if not reply.body:
            return None
        value = reply.body[0]
        if hasattr(value, "value"):
            value = getattr(value, "value")
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise VoltageSourceError(
                f"Antwort konnte nicht in eine Zahl umgewandelt werden: {value!r}"
            ) from exc

    async def _disconnect_locked(self) -> None:
        if self._bus is None:
            return
        disconnect = getattr(self._bus, "disconnect", None)
        if callable(disconnect):
            with contextlib.suppress(Exception):
                disconnect_result = disconnect()
                if inspect.isawaitable(disconnect_result):
                    await disconnect_result
        wait_for_disconnect = getattr(self._bus, "wait_for_disconnect", None)
        if callable(wait_for_disconnect):
            with contextlib.suppress(Exception):
                await wait_for_disconnect()
        self._bus = None

    async def close(self) -> None:
        async with self._lock:
            await self._disconnect_locked()
        with self._sync_lock:
            self._reset_vedbus_locked()

    def _ensure_vedbus_locked(self, *, force: bool = False) -> None:
        if not self._use_vedbus:
            raise VoltageSourceError("VeDbusItemImport ist nicht verfügbar")
        now = time.monotonic()
        if self._vedbus_item is not None:
            return
        if not force and now < self._next_attempt:
            raise VoltageSourceError("Verbindungsversuch wird später erneut durchgeführt")
        assert dbus is not None
        assert VeDbusItemImport is not None
        bus = dbus.SystemBus() if self._bus_choice == "system" else dbus.SessionBus()
        try:
            item = VeDbusItemImport(
                bus,
                self._service_name,
                self._object_path,
                createsignal=False,
            )
        except Exception as exc:  # pragma: no-cover - Laufzeitabhängig
            self._next_attempt = now + self._reconnect_delay
            with contextlib.suppress(Exception):
                close = getattr(bus, "close", None)
                if callable(close):
                    close()
            raise VoltageSourceError(
                f"VeDbusItemImport konnte nicht initialisiert werden: {exc}"
            ) from exc
        self._vedbus_bus = bus
        self._vedbus_item = item
        self._next_attempt = now

    def _reset_vedbus_locked(self) -> None:
        if self._vedbus_item is not None:
            self._vedbus_item = None
        if self._vedbus_bus is not None:
            with contextlib.suppress(Exception):
                close = getattr(self._vedbus_bus, "close", None)
                if callable(close):
                    close()
            self._vedbus_bus = None
        self._next_attempt = time.monotonic() + self._reconnect_delay


class DbusBinaryInputReader:
    """Liest boolesche Zustände über den Victron D-Bus."""

    def __init__(self, service_name: str, object_path: str, bus_choice: str = "system") -> None:
        self._reader = DbusVoltageReader(service_name, object_path, bus_choice)

    @property
    def description(self) -> str:
        return f"ignition:{self._reader.service_name}{self._reader.object_path}"

    @property
    def metadata(self) -> Dict[str, Any]:
        data = dict(self._reader.metadata)
        data["mode"] = "dbus-digitalinput"
        return data

    @property
    def failure_count(self) -> int:
        return self._reader.failure_count

    @property
    def last_error(self) -> str:
        return self._reader.last_error

    @property
    def last_success(self) -> float:
        return self._reader.last_success

    async def initialize(self) -> None:
        await self._reader.initialize()

    async def read_state(self) -> Optional[bool]:
        value = await self._reader.read_voltage()
        if value is None:
            return None
        return normalize_bool(value)

    async def close(self) -> None:
        await self._reader.close()


def _variant_signature(value: Any) -> str:
    if isinstance(value, bool):
        return "b"
    if isinstance(value, int):
        return "i"
    if isinstance(value, float):
        return "d"
    if isinstance(value, str):
        return "s"
    if isinstance(value, dict):
        return "a{sv}"
    if isinstance(value, (list, tuple)):
        return "av"
    raise TypeError(f"Unsupported value for Variant: {value!r}")


class RelayFunctionMonitor:
    """Überwacht Funktionszuweisungen im gpiosetup-Relaisbaum."""

    def __init__(
        self,
        bus: MessageBus,
        *,
        service_name: str = "com.victronenergy.settings",
        function_tag: str = RELAY_FUNCTION_TAG,
        neutral_value: str = RELAY_FUNCTION_NEUTRAL,
    ) -> None:
        self._bus = bus
        self._service_name = service_name
        self._function_tag = str(function_tag or RELAY_FUNCTION_TAG)
        self._neutral_value = str(neutral_value or RELAY_FUNCTION_NEUTRAL)
        self._logger = logging.getLogger(self.__class__.__name__)
        self._assignments: Dict[str, str] = {}
        self._callback: Optional[Callable[[Dict[str, str]], Awaitable[None] | None]] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._match_rule: Optional[str] = None
        self._handler_registered = False
        self._accepted_senders: Set[str] = {self._service_name}
        self._refreshed_unknown_senders: Set[str] = set()

    @property
    def neutral_value(self) -> str:
        return self._neutral_value

    @property
    def function_tag(self) -> str:
        return self._function_tag

    def set_callback(
        self, callback: Optional[Callable[[Dict[str, str]], Awaitable[None] | None]]
    ) -> None:
        self._callback = callback

    async def start(self) -> Dict[str, str]:
        if Message is None:
            raise RuntimeError("D-Bus-Unterstützung ist nicht verfügbar")
        self._loop = asyncio.get_running_loop()
        await self._register_match_rule()
        self._bus.add_message_handler(self._handle_message)
        self._handler_registered = True
        await self._update_unique_sender()
        assignments = await self._read_assignments()
        self._assignments = dict(assignments)
        return dict(assignments)

    async def stop(self) -> None:
        if self._handler_registered:
            self._bus.remove_message_handler(self._handle_message)
            self._handler_registered = False
        await self._remove_match_rule()

    async def refresh(self) -> Dict[str, str]:
        assignments = await self._read_assignments()
        self._assignments = assignments
        await self._emit_update(assignments)
        return dict(assignments)

    async def set_function(self, channel: str, value: str) -> None:
        if Message is None:
            raise RuntimeError("D-Bus-Unterstützung ist nicht verfügbar")
        normalized = normalize_relay_channel(channel)
        if not normalized:
            return
        typed_value = str(value)
        try:
            await self._bus.call(
                Message(
                    destination=self._service_name,
                    path=f"/Settings/Relays/{normalized}/Function",
                    interface="com.victronenergy.BusItem",
                    member="SetValue",
                    signature="v",
                    body=[Variant(_variant_signature(typed_value), typed_value)],
                )
            )
        except Exception as exc:  # pragma: no-cover - Laufzeitabhängig
            self._logger.warning(
                "SetValue für Relay-Funktion %s konnte nicht geschrieben werden: %s",
                normalized,
                exc,
            )

    async def _read_assignments(self) -> Dict[str, str]:
        if Message is None:
            return {}
        try:
            reply = await self._bus.call(
                Message(
                    destination=self._service_name,
                    path="/Settings/Relays",
                    interface="com.victronenergy.BusItem",
                    member="GetValue",
                )
            )
        except Exception as exc:  # pragma: no-cover - Laufzeitabhängig
            self._logger.debug(
                "Relais-Funktionen konnten nicht gelesen werden: %s",
                exc,
            )
            return {}
        body = reply.body[0] if reply.body else None
        root_value = self._unwrap_variant(body)
        assignments: Dict[str, str] = {}
        self._collect_assignments(root_value, "", assignments)
        return assignments

    def _collect_assignments(
        self, node: Any, prefix: str, assignments: Dict[str, str]
    ) -> None:
        if isinstance(node, dict):
            function_value: Optional[str] = None
            for key, value in node.items():
                key_text = str(key)
                if key_text.lower() == "function":
                    function_value = str(self._unwrap_variant(value))
                else:
                    new_prefix = f"{prefix}/{key_text}" if prefix else key_text
                    self._collect_assignments(value, new_prefix, assignments)
            if function_value is not None and prefix:
                assignments[normalize_relay_channel(prefix)] = function_value
        elif isinstance(node, (list, tuple)):
            for index, value in enumerate(node):
                new_prefix = f"{prefix}/{index}" if prefix else str(index)
                self._collect_assignments(value, new_prefix, assignments)

    def _handle_message(self, message: Any) -> bool:
        if message is None:
            return False
        if getattr(message, "message_type", None) != getattr(MessageType, "SIGNAL", None):
            return False
        sender = getattr(message, "sender", None)
        if sender not in self._accepted_senders:
            if (
                isinstance(sender, str)
                and sender.startswith(":")
                and sender not in self._refreshed_unknown_senders
            ):
                self._refreshed_unknown_senders.add(sender)
                self._schedule_unique_sender_update()
            return False
        path = getattr(message, "path", None)
        if not isinstance(path, str) or not path.startswith("/Settings/Relays/"):
            return False
        if getattr(message, "member", None) != "PropertiesChanged":
            return False
        body = getattr(message, "body", [])
        if len(body) < 2 or not isinstance(body[1], dict):
            return False
        changes = body[1]
        if "Value" not in changes:
            return False
        channel = self._extract_channel_from_path(path)
        if not channel:
            return False
        value = str(self._unwrap_variant(changes["Value"]))
        normalized = normalize_relay_channel(channel)
        previous = self._assignments.get(normalized)
        if previous == value:
            return False
        self._assignments[normalized] = value
        if self._loop is None:
            return False
        self._loop.create_task(self._emit_update(dict(self._assignments)))
        return True

    def _extract_channel_from_path(self, path: str) -> str:
        suffix = path[len("/Settings/Relays/") :]
        if suffix.endswith("/Function"):
            suffix = suffix[: -len("/Function")]
        return suffix

    async def _emit_update(self, assignments: Dict[str, str]) -> None:
        callback = self._callback
        if callback is None:
            return
        try:
            result = callback(dict(assignments))
            if asyncio.iscoroutine(result):
                await result
        except Exception as exc:  # pragma: no-cover - Laufzeitabhängig
            self._logger.exception(
                "Fehler beim Verarbeiten von Relay-Funktionsänderungen: %s",
                exc,
            )

    @staticmethod
    def _unwrap_variant(value: Any) -> Any:
        if isinstance(value, Variant):
            return RelayFunctionMonitor._unwrap_variant(value.value)
        if isinstance(value, dict):
            return {k: RelayFunctionMonitor._unwrap_variant(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [RelayFunctionMonitor._unwrap_variant(v) for v in value]
        return value

    async def _register_match_rule(self) -> None:
        if self._match_rule is not None or Message is None:
            return
        rule = (
            "type='signal',interface='com.victronenergy.BusItem',sender='"
            f"{self._service_name}',path_namespace='/Settings/Relays'"
        )
        try:
            await self._bus.call(
                Message(
                    destination="org.freedesktop.DBus",
                    path="/org/freedesktop/DBus",
                    interface="org.freedesktop.DBus",
                    member="AddMatch",
                    signature="s",
                    body=[rule],
                )
            )
            self._match_rule = rule
        except Exception as exc:  # pragma: no-cover - Laufzeitabhängig
            self._logger.debug("Konnte Match-Rule für Relay-Funktionen nicht setzen: %s", exc)

    async def _remove_match_rule(self) -> None:
        if self._match_rule is None or Message is None:
            return
        with contextlib.suppress(Exception):
            await self._bus.call(
                Message(
                    destination="org.freedesktop.DBus",
                    path="/org/freedesktop/DBus",
                    interface="org.freedesktop.DBus",
                    member="RemoveMatch",
                    signature="s",
                    body=[self._match_rule],
                )
            )
        self._match_rule = None

    async def _update_unique_sender(self) -> None:
        if Message is None:
            return
        try:
            reply = await self._bus.call(
                Message(
                    destination="org.freedesktop.DBus",
                    path="/org/freedesktop/DBus",
                    interface="org.freedesktop.DBus",
                    member="GetNameOwner",
                    signature="s",
                    body=[self._service_name],
                )
            )
        except Exception as exc:  # pragma: no-cover - Laufzeitabhängig
            self._logger.debug(
                "Konnte eindeutige Sender-ID für Relay-Funktionen nicht bestimmen: %s",
                exc,
            )
            return
        owner = reply.body[0] if reply.body else None
        owner = getattr(owner, "value", owner)
        if isinstance(owner, str) and owner:
            self._accepted_senders.add(owner)
            self._refreshed_unknown_senders.discard(owner)

    def _schedule_unique_sender_update(self) -> None:
        loop = self._loop
        if loop is None or not loop.is_running():
            return
        loop.create_task(self._update_unique_sender())

def _dbusify_sequence(sequence: Iterable[Any]) -> list[Variant]:
    return [Variant(_variant_signature(item), _dbusify_value(item)) for item in sequence]


def _dbusify_mapping(mapping: Mapping[Any, Any]) -> Dict[str, Variant]:
    return {
        str(key): Variant(_variant_signature(value), _dbusify_value(value))
        for key, value in mapping.items()
    }


def _dbusify_value(value: Any) -> Any:
    if Variant is None:  # type: ignore[truthy-bool]
        return value
    if isinstance(value, dict):
        return _dbusify_mapping(value)
    if isinstance(value, (list, tuple)):
        return _dbusify_sequence(value)
    return value


def dbusify(data: Dict[str, Any]) -> Dict[str, Any]:
    if Variant is None:  # type: ignore[truthy-bool]
        return data
    return _dbusify_mapping(data)


def normalize_variant_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    normalized: Dict[str, Any] = {}
    for key, value in data.items():
        key_str = str(key)
        if hasattr(value, "value"):
            normalized[key_str] = getattr(value, "value")
        else:
            normalized[key_str] = value
    return normalized


class SettingsBridge:
    """Synchronisiert Einstellungen mit com.victronenergy.settings."""

    def __init__(
        self,
        bus: MessageBus,
        definitions: Dict[str, Dict[str, Any]],
        callback: Optional[Callable[[str, Any], Awaitable[None] | None]] = None,
        service_name: str = "com.victronenergy.settings",
    ) -> None:
        self._bus = bus
        self._definitions = definitions
        self._callback = callback
        self._service_name = service_name
        self._logger = logging.getLogger(self.__class__.__name__)
        self._path_to_key = {meta["path"]: key for key, meta in definitions.items()}
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._match_rule: Optional[str] = None
        self._handler_registered = False
        self._accepted_senders: Set[str] = {self._service_name}
        self._refreshed_unknown_senders: Set[str] = set()

    def set_callback(
        self, callback: Optional[Callable[[str, Any], Awaitable[None] | None]]
    ) -> None:
        self._callback = callback

    async def start(self) -> Dict[str, Any]:
        if Message is None:
            raise RuntimeError("D-Bus-Unterstützung ist nicht verfügbar")
        self._loop = asyncio.get_running_loop()
        await self._register_match_rule()
        await self._update_unique_sender()
        initial_values = await self._ensure_settings()
        self._bus.add_message_handler(self._handle_message)
        self._handler_registered = True
        return initial_values

    async def stop(self) -> None:
        if self._handler_registered:
            self._bus.remove_message_handler(self._handle_message)
            self._handler_registered = False
        if self._match_rule is not None and Message is not None:
            with contextlib.suppress(Exception):
                await self._bus.call(
                    Message(
                        destination="org.freedesktop.DBus",
                        path="/org/freedesktop/DBus",
                        interface="org.freedesktop.DBus",
                        member="RemoveMatch",
                        signature="s",
                        body=[self._match_rule],
                    )
                )
            self._match_rule = None

    async def _register_match_rule(self) -> None:
        if self._match_rule is not None or Message is None:
            return
        rule = (
            "type='signal',interface='com.victronenergy.BusItem',sender='"
            f"{self._service_name}'"
        )
        try:
            await self._bus.call(
                Message(
                    destination="org.freedesktop.DBus",
                    path="/org/freedesktop/DBus",
                    interface="org.freedesktop.DBus",
                    member="AddMatch",
                    signature="s",
                    body=[rule],
                )
            )
            self._match_rule = rule
        except Exception as exc:
            self._logger.warning(
                "Konnte Signal-Filter für Einstellungen nicht setzen: %s", exc
            )

    async def _ensure_settings(self) -> Dict[str, Any]:
        if Message is None:
            return {key: meta["default"] for key, meta in self._definitions.items()}
        entries = []
        for meta in self._definitions.values():
            entry: Dict[str, Variant] = {
                "path": Variant("s", meta["path"]),
                "default": Variant(meta["type"], meta["default"]),
                "type": Variant("s", meta["type"]),
            }
            description = meta.get("description")
            if description:
                entry["description"] = Variant("s", description)
            entries.append(entry)

        try:
            reply = await self._bus.call(
                Message(
                    destination=self._service_name,
                    path="/",
                    interface="com.victronenergy.Settings",
                    member="AddSettings",
                    signature="aa{sv}",
                    body=[entries],
                )
            )
            self._log_registration_results(reply.body[0] if reply.body else [])
        except Exception as exc:
            self._logger.warning(
                "Registrierung der Einstellungen fehlgeschlagen: %s", exc
            )

        initial_values: Dict[str, Any] = {}
        for key, meta in self._definitions.items():
            try:
                initial_values[key] = await self._read_setting(meta)
            except Exception as exc:  # pragma: no-cover - Laufzeitabhängig
                self._logger.debug(
                    "Einstellung %s konnte nicht gelesen werden: %s", meta["path"], exc
                )
                initial_values[key] = meta["default"]
        return initial_values

    def _log_registration_results(self, results: Any) -> None:
        if not isinstance(results, list):
            return
        for item in results:
            if not isinstance(item, dict):
                continue
            path = self._unwrap_variant(item.get("path"))
            error = self._unwrap_variant(item.get("error"))
            if error not in (None, 0):
                self._logger.warning(
                    "Einstellung %s konnte nicht registriert werden (Fehler %s)",
                    path,
                    error,
                )

    async def _read_setting(self, meta: Dict[str, Any]) -> Any:
        if Message is None:
            return meta["default"]
        reply = await self._bus.call(
            Message(
                destination=self._service_name,
                path=meta["path"],
                interface="com.victronenergy.BusItem",
                member="GetValue",
            )
        )
        value = self._unwrap_variant(reply.body[0]) if reply.body else meta["default"]
        return self._coerce_value(meta["type"], value)

    def _handle_message(self, message: Any) -> bool:
        if message is None:
            return False
        if getattr(message, "message_type", None) != getattr(MessageType, "SIGNAL", None):
            return False
        sender = getattr(message, "sender", None)
        if sender not in self._accepted_senders:
            if (
                isinstance(sender, str)
                and sender.startswith(":")
                and sender not in self._refreshed_unknown_senders
            ):
                self._refreshed_unknown_senders.add(sender)
                self._schedule_unique_sender_update()
            return False
        path = getattr(message, "path", None)
        if path not in self._path_to_key:
            return False
        if getattr(message, "member", None) != "PropertiesChanged":
            return False
        body = getattr(message, "body", [])
        if len(body) < 2 or not isinstance(body[1], dict):
            return False
        changes = body[1]
        if "Value" not in changes:
            return False
        value = self._coerce_value(
            self._definitions[self._path_to_key[path]]["type"],
            self._unwrap_variant(changes["Value"]),
        )
        if self._loop is None:
            return False
        self._loop.create_task(self._emit_update(self._path_to_key[path], value))
        return True

    async def _emit_update(self, key: str, value: Any) -> None:
        callback = self._callback
        if callback is None:
            return
        try:
            result = callback(key, value)
            if asyncio.iscoroutine(result):
                await result
        except Exception as exc:  # pragma: no-cover - Laufzeitabhängig
            self._logger.exception(
                "Fehler bei der Verarbeitung der Einstellungsänderung %s: %s",
                key,
                exc,
            )

    @staticmethod
    def _unwrap_variant(value: Any) -> Any:
        return getattr(value, "value", value)

    @staticmethod
    def _coerce_value(type_code: str, value: Any) -> Any:
        if type_code == "i":
            return int(value)
        if type_code in {"d", "f"}:
            return float(value)
        if type_code == "b":
            if isinstance(value, str):
                normalized = value.strip().lower()
                return normalized not in {"", "0", "false", "off"}
            if isinstance(value, (int, float)):
                return value != 0
            return bool(value)
        return str(value)

    async def _update_unique_sender(self) -> None:
        if Message is None:
            return
        try:
            reply = await self._bus.call(
                Message(
                    destination="org.freedesktop.DBus",
                    path="/org/freedesktop/DBus",
                    interface="org.freedesktop.DBus",
                    member="GetNameOwner",
                    signature="s",
                    body=[self._service_name],
                )
            )
        except Exception as exc:  # pragma: no-cover - Laufzeitabhängig
            self._logger.debug(
                "Konnte eindeutige Sender-ID nicht ermitteln: %s", exc
            )
            return
        owner = reply.body[0] if reply.body else None
        owner = self._unwrap_variant(owner)
        if isinstance(owner, str) and owner:
            self._accepted_senders.add(owner)
            self._refreshed_unknown_senders.discard(owner)

    def _schedule_unique_sender_update(self) -> None:
        loop = self._loop
        if loop is None or not loop.is_running():
            return
        loop.create_task(self._update_unique_sender())

    async def write_setting(self, key: str, value: Any) -> None:
        if Message is None:
            return
        if key not in self._definitions:
            return
        meta = self._definitions[key]
        typed_value = self._coerce_value(meta["type"], value)
        try:
            await self._bus.call(
                Message(
                    destination=self._service_name,
                    path=meta["path"],
                    interface="com.victronenergy.BusItem",
                    member="SetValue",
                    signature="v",
                    body=[Variant(_variant_signature(typed_value), typed_value)],
                )
            )
        except Exception as exc:  # pragma: no-cover - Laufzeitabhängig
            self._logger.warning(
                "SetValue für %s ist fehlgeschlagen: %s",
                meta["path"],
                exc,
            )

    async def write_settings(self, updates: Dict[str, Any]) -> None:
        if Message is None:
            return
        for key, value in updates.items():
            await self.write_setting(key, value)


class BaseSettingsAdapter:
    """Abstraktion zur Verwaltung von Einstellungen über unterschiedliche Backends."""

    def __init__(self) -> None:
        self._callback: Optional[Callable[[str, Any], Awaitable[None] | None]] = None

    def set_callback(
        self, callback: Optional[Callable[[str, Any], Awaitable[None] | None]]
    ) -> None:
        self._callback = callback

    async def start(self) -> Dict[str, Any]:
        raise NotImplementedError

    async def apply(self, updates: Dict[str, Any]) -> None:
        raise NotImplementedError

    async def stop(self) -> None:
        raise NotImplementedError

    def _dispatch_update(self, key: str, value: Any) -> Optional[Awaitable[None]]:
        callback = self._callback
        if callback is None:
            return None
        result = callback(key, value)
        return result if asyncio.iscoroutine(result) else None


class DbusNextSettingsAdapter(BaseSettingsAdapter):
    def __init__(self, bridge: SettingsBridge) -> None:
        super().__init__()
        self._bridge = bridge

    async def start(self) -> Dict[str, Any]:
        self._bridge.set_callback(self._handle_bridge_update)
        return await self._bridge.start()

    async def apply(self, updates: Dict[str, Any]) -> None:
        await self._bridge.write_settings(updates)

    async def stop(self) -> None:
        await self._bridge.stop()

    def _handle_bridge_update(self, key: str, value: Any) -> Optional[Awaitable[None]]:
        return self._dispatch_update(key, value)


class VelibSettingsAdapter(BaseSettingsAdapter):
    """Verwaltung der Einstellungen über velib_python.SettingsDevice."""

    def __init__(self, definitions: Dict[str, Dict[str, Any]], bus_choice: str) -> None:
        super().__init__()
        self._definitions = definitions
        self._bus_choice = bus_choice
        self._thread: Optional[threading.Thread] = None
        self._main_loop: Optional[Any] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._start_future: Optional[asyncio.Future[Dict[str, Any]]] = None
        self._command_queue: "queue.Queue[tuple[str, Any]]" = queue.Queue()
        self._device: Optional[VelibSettingsDevice] = None
        self._logger = logging.getLogger(self.__class__.__name__)
        self._last_snapshot: Dict[str, Any] = {}
        self._poll_interval_ms = 250

    async def start(self) -> Dict[str, Any]:
        if (
            VelibSettingsDevice is None
            or dbus is None
            or DBusGMainLoop is None
            or GLib is None
        ):
            raise RuntimeError("SettingsDevice ist nicht verfügbar")
        loop = asyncio.get_running_loop()
        self._loop = loop
        future: asyncio.Future[Dict[str, Any]] = loop.create_future()
        self._start_future = future
        self._thread = threading.Thread(target=self._run, name="SettingsDevice", daemon=True)
        self._thread.start()
        return await future

    async def apply(self, updates: Dict[str, Any]) -> None:
        if not updates:
            return
        if self._loop is None:
            raise RuntimeError("SettingsDevice wurde nicht initialisiert")
        future: asyncio.Future[None] = self._loop.create_future()
        self._command_queue.put(("apply", (dict(updates), future)))
        await future

    async def stop(self) -> None:
        if self._loop is None:
            return
        future: asyncio.Future[None] = self._loop.create_future()
        self._command_queue.put(("stop", future))
        await future
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _run(self) -> None:
        assert self._loop is not None
        start_future = self._start_future
        try:
            assert VelibSettingsDevice is not None
            assert DBusGMainLoop is not None
            assert dbus is not None
            assert GLib is not None
            DBusGMainLoop(set_as_default=True)
            bus = (
                dbus.SystemBus()
                if self._bus_choice.lower() != "session"
                else dbus.SessionBus()
            )
            supported = self._build_supported_settings()
            self._device = VelibSettingsDevice(bus, supported, self._handle_change)
            initial = {
                key: self._coerce_value(meta["type"], self._device[key])
                for key, meta in self._definitions.items()
            }
            self._last_snapshot = dict(initial)
            if start_future is not None and not start_future.done():
                self._loop.call_soon_threadsafe(start_future.set_result, initial)
            self._main_loop = GLib.MainLoop()
            GLib.timeout_add(100, self._process_commands)
            GLib.timeout_add(self._poll_interval_ms, self._poll_settings_snapshot)
            self._main_loop.run()
        except Exception as exc:  # pragma: no-cover - Laufzeitabhängig
            if start_future is not None and not start_future.done():
                self._loop.call_soon_threadsafe(start_future.set_exception, exc)
            else:
                self._logger.exception("SettingsDevice-Thread wurde mit Fehler beendet: %s", exc)
        finally:
            if start_future is not None and not start_future.done():
                self._loop.call_soon_threadsafe(
                    start_future.set_exception,
                    RuntimeError("Initialisierung des SettingsDevice ist fehlgeschlagen"),
                )

    def _process_commands(self) -> bool:
        processed_stop = False
        while True:
            try:
                command, payload = self._command_queue.get_nowait()
            except queue.Empty:
                break
            if command == "apply":
                updates, future = payload
                exc: Optional[BaseException] = None
                try:
                    self._apply_updates_sync(updates)
                except Exception as err:  # pragma: no-cover - Laufzeitabhängig
                    exc = err
                    self._logger.warning("Konnte Einstellungen nicht schreiben: %s", err)
                if self._loop is not None:
                    if exc is None:
                        self._loop.call_soon_threadsafe(future.set_result, None)
                    else:
                        self._loop.call_soon_threadsafe(future.set_exception, exc)
            elif command == "stop":
                future = payload
                processed_stop = True
                if self._loop is not None:
                    self._loop.call_soon_threadsafe(future.set_result, None)
            else:
                self._logger.debug("Unbekannter Befehl für SettingsDevice: %s", command)
        if processed_stop:
            if self._main_loop is not None:
                self._main_loop.quit()
            return False
        return True

    def _poll_settings_snapshot(self) -> bool:
        device = self._device
        if device is None or self._main_loop is None:
            return False
        try:
            for key, meta in self._definitions.items():
                current = self._coerce_value(meta["type"], device[key])
                previous = self._last_snapshot.get(key)
                if previous != current:
                    self._last_snapshot[key] = current
                    self._handle_change(key, previous, current)
        except Exception as exc:  # pragma: no-cover - Laufzeitabhängig
            self._logger.debug("Polling der SettingsDevice-Werte fehlgeschlagen: %s", exc)
        return True

    def _apply_updates_sync(self, updates: Dict[str, Any]) -> None:
        if self._device is None:
            raise RuntimeError("SettingsDevice ist nicht verfügbar")
        for key, value in updates.items():
            if key not in self._definitions:
                continue
            typed_value = self._coerce_value(self._definitions[key]["type"], value)
            self._device[key] = typed_value
            self._last_snapshot[key] = typed_value

    def _handle_change(self, key: str, _old: Any, new: Any) -> None:
        callback = self._callback
        if callback is None or self._loop is None:
            return
        value = self._coerce_value(self._definitions[key]["type"], new)
        self._last_snapshot[key] = value

        def dispatch() -> None:
            result = callback(key, value)
            if asyncio.iscoroutine(result):
                asyncio.create_task(result)

        self._loop.call_soon_threadsafe(dispatch)

    def _build_supported_settings(self) -> Dict[str, list[Any]]:
        supported: Dict[str, list[Any]] = {}
        for key, meta in self._definitions.items():
            supported[key] = [
                meta["path"],
                meta["default"],
                meta.get("min", 0),
                meta.get("max", 0),
            ]
        return supported

    @staticmethod
    def _coerce_value(type_code: str, value: Any) -> Any:
        if type_code == "i":
            return int(value)
        if type_code in {"d", "f"}:
            return float(value)
        if type_code == "b":
            if isinstance(value, str):
                normalized = value.strip().lower()
                return normalized not in {"", "0", "false", "off"}
            if isinstance(value, (int, float)):
                return value != 0
            return bool(value)
        return str(value)

class GPIOController:
    """Interner Platzhalter für den lokalen GPIO-Ausgang.

    Auf Venus OS wird der D+-Ausgang bevorzugt über vorhandene Relays geschaltet.
    Diese Klasse hält nur den gewünschten Zustand vor, damit der GPIO-Modus
    weiterhin kompatibel bleibt, ohne RPi.GPIO vorauszusetzen.
    """

    def __init__(self, pin: int, enabled: bool = True) -> None:
        self._pin = pin
        self._enabled = bool(enabled)
        self._state = False
        self._logger = logging.getLogger(self.__class__.__name__)
        self._logger.debug("GPIOController läuft ohne RPi.GPIO-Unterstützung im internen Modus")

    @property
    def pin(self) -> int:
        return self._pin

    def reconfigure(self, new_pin: int) -> None:
        if new_pin == self._pin:
            return
        self._logger.info("GPIO-Konfiguration wechselt von Pin %s auf Pin %s", self._pin, new_pin)
        self._pin = new_pin

    def write(self, state: bool) -> None:
        self._state = bool(state)

    def read(self) -> bool:
        return self._state

    @property
    def description(self) -> str:
        return f"gpio:{self._pin}"

    def close(self) -> None:
        self._state = False


class RelayController:
    """Schaltet D-Bus-basierte Relays über com.victronenergy.system."""

    def __init__(
        self,
        channel: str,
        *,
        bus_choice: str = "system",
        enabled: bool = True,
        service: str = "com.victronenergy.system",
    ) -> None:
        self._logger = logging.getLogger(self.__class__.__name__)
        self._service = service or "com.victronenergy.system"
        self._bus_choice = bus_choice or "system"
        self._channel = self._normalize_channel(channel)
        self._state = False
        self._lock = threading.Lock()
        self._enabled = enabled and dbus is not None
        self._item: Optional[Any] = None
        self._bus: Optional[Any] = None
        self._bus_item_iface: Optional[Any] = None
        if not self._enabled:
            self._logger.debug("RelayController läuft im Simulationsmodus")

    @staticmethod
    def _normalize_channel(channel: str) -> str:
        return map_system_relay_channel_to_internal(channel)

    @staticmethod
    def _is_disconnected_error(exc: Exception) -> bool:
        text = str(exc)
        return "Connection is closed" in text or "org.freedesktop.DBus.Error.Disconnected" in text

    @property
    def channel(self) -> str:
        return self._channel

    @property
    def service(self) -> str:
        return self._service

    @property
    def bus_choice(self) -> str:
        return self._bus_choice

    @property
    def description(self) -> str:
        if self._service.startswith(BATTERY_SERVICE_PREFIX):
            return "relay:bmv/0"
        suffix = map_system_relay_channel_to_display(self._channel) or "unset"
        return f"relay:{suffix}"

    def set_bus_choice(self, new_choice: str) -> None:
        normalized = str(new_choice or "system").strip().lower()
        if normalized not in {"system", "session"}:
            normalized = "system"
        if normalized == self._bus_choice:
            return
        self._logger.info("RelayController nutzt nun den %s-Bus", normalized)
        self._bus_choice = normalized
        self._reset()

    def reconfigure(self, new_channel: str) -> None:
        normalized = self._normalize_channel(new_channel)
        if normalized == self._channel:
            return
        if self._channel:
            self._logger.info(
                "RelayController wechselt von '%s' auf '%s'",
                self._channel,
                normalized or "(kein Relay)",
            )
        else:
            self._logger.info("RelayController setzt Kanal auf '%s'", normalized)
        self._channel = normalized
        self._reset()
        self._state = False

    def set_service(self, service: str) -> None:
        normalized = str(service or "").strip()
        if normalized == self._service:
            return
        self._service = normalized
        self._reset()

    def write(self, state: bool) -> None:
        state_bool = bool(state)
        if state_bool == self._state:
            # trotzdem sicherstellen, dass der Zustand synchronisiert ist
            if state_bool and not self._enabled:
                self._state = state_bool
            else:
                self._sync_state(state_bool, force=False)
            return
        self._state = state_bool
        self._sync_state(state_bool, force=True)

    def read(self) -> bool:
        if not self._enabled or not self._channel:
            return self._state
        value: Any = None
        with self._lock:
            for attempt in range(2):
                iface = self._ensure_item_locked()
                if iface is None:
                    return self._state
                try:
                    value = iface.GetValue()
                    value = getattr(value, "value", value)
                    break
                except Exception as exc:  # pragma: no-cover - Laufzeitabhängig
                    if attempt == 0 and self._is_disconnected_error(exc):
                        self._logger.info(
                            "Relay-D-Bus-Verbindung für %s wurde getrennt, verbinde erneut",
                            self.description,
                        )
                        self._reset_locked()
                        continue
                    self._logger.debug("Konnte Relay-Zustand nicht lesen: %s", exc)
                    return self._state
        if value is not None:
            try:
                self._state = bool(int(value))
            except (TypeError, ValueError):
                self._state = bool(value)
        return self._state

    def close(self) -> None:
        self._reset()
        self._state = False

    def _reset(self) -> None:
        with self._lock:
            self._reset_locked()

    def _reset_locked(self) -> None:
        if self._item is not None:
            self._item = None
        if self._bus_item_iface is not None:
            self._bus_item_iface = None
        if self._bus is not None:
            with contextlib.suppress(Exception):
                close = getattr(self._bus, "close", None)
                if callable(close):
                    close()
            self._bus = None

    def _sync_state(self, state: bool, *, force: bool) -> None:
        if not self._enabled or not self._channel:
            return
        with self._lock:
            last_exc: Optional[Exception] = None
            for attempt in range(2):
                iface = self._ensure_item_locked()
                if iface is None:
                    return
                try:
                    result = iface.SetValue(dbus.Int32(1 if state else 0))
                    self._logger.info(
                        "Relay-Write %s -> %s%s returned %s",
                        int(state),
                        self._service,
                        f"/Relay/{self._channel}/State",
                        result,
                    )
                    return
                except Exception as exc:  # pragma: no-cover - Laufzeitabhängig
                    last_exc = exc
                    if attempt == 0 and self._is_disconnected_error(exc):
                        self._logger.info(
                            "Relay-D-Bus-Verbindung für %s wurde getrennt, erneuter Schreibversuch",
                            self.description,
                        )
                        self._reset_locked()
                        continue
                    break
            if last_exc is None:
                return
            if force:
                self._logger.warning(
                    "Setzen des Relay-Zustands auf '%s' für %s ist fehlgeschlagen: %s",
                    state,
                    self.description,
                    last_exc,
                )
            else:
                self._logger.debug(
                    "Synchronisieren des Relay-Zustands auf '%s' für %s ist fehlgeschlagen: %s",
                    state,
                    self.description,
                    last_exc,
                )

    def _ensure_item_locked(self) -> Optional[Any]:
        if not self._enabled or not self._channel or not self._service:
            return None
        if self._bus_item_iface is not None:
            return self._bus_item_iface
        assert dbus is not None
        bus = dbus.SystemBus() if self._bus_choice == "system" else dbus.SessionBus()
        path = f"/Relay/{self._channel}/State"
        try:
            obj = bus.get_object(self._service, path)
            iface = dbus.Interface(obj, "com.victronenergy.BusItem")
        except Exception as exc:  # pragma: no-cover - Laufzeitabhängig
            self._logger.warning(
                "Verbindung zu %s%s konnte nicht aufgebaut werden: %s",
                self._service,
                path,
                exc,
            )
            with contextlib.suppress(Exception):
                close = getattr(bus, "close", None)
                if callable(close):
                    close()
            return None
        self._bus = bus
        self._bus_item_iface = iface
        self._item = obj
        return iface

@dataclass
class SwitchLogic:
    on_threshold: float
    off_threshold: float
    on_delay: float
    off_delay: float
    state: bool = False
    pending_state: Optional[bool] = None
    deadline: Optional[float] = None

    def configure(
        self,
        on_threshold: float,
        off_threshold: float,
        on_delay: float,
        off_delay: float,
    ) -> None:
        self.on_threshold = on_threshold
        self.off_threshold = off_threshold
        self.on_delay = on_delay
        self.off_delay = off_delay
        self.pending_state = None
        self.deadline = None

    def _compute_thresholds(self) -> Tuple[float, float]:
        upper = float(self.on_threshold)
        lower = float(self.off_threshold)
        if upper < lower:
            midpoint = (upper + lower) / 2.0
            upper = midpoint
            lower = midpoint
        return upper, lower

    def thresholds(self) -> Tuple[float, float]:
        return self._compute_thresholds()

    def evaluate(
        self,
        voltage: float,
        now: float,
        *,
        on_dependencies: Dict[str, bool],
        off_dependencies: Dict[str, bool],
        voltage_on: Optional[bool] = None,
        voltage_off: Optional[bool] = None,
        on_delay: Optional[float] = None,
        off_delay: Optional[float] = None,
    ) -> Dict[str, Any]:
        upper, lower = self._compute_thresholds()
        voltage_on = voltage >= upper if voltage_on is None else bool(voltage_on)
        voltage_off = voltage <= lower if voltage_off is None else bool(voltage_off)
        effective_on_delay = self.on_delay if on_delay is None else max(0.0, float(on_delay))
        effective_off_delay = self.off_delay if off_delay is None else max(0.0, float(off_delay))
        conditions_on: Dict[str, bool] = {"voltage": voltage_on}
        conditions_off: Dict[str, bool] = {"voltage": voltage_off}
        conditions_on.update(on_dependencies)
        conditions_off.update(off_dependencies)
        on_ready = all(conditions_on.values()) if conditions_on else True
        off_required = any(conditions_off.values()) if conditions_off else False

        changed = False
        if self.state:
            if off_required:
                if self.pending_state is not False:
                    self.pending_state = False
                    self.deadline = now + effective_off_delay
                elif self.deadline is not None and now >= self.deadline:
                    self.state = False
                    self.pending_state = None
                    self.deadline = None
                    changed = True
            elif self.pending_state is False:
                self.pending_state = None
                self.deadline = None
        else:
            if on_ready:
                if self.pending_state is not True:
                    self.pending_state = True
                    self.deadline = now + effective_on_delay
                elif self.deadline is not None and now >= self.deadline:
                    self.state = True
                    self.pending_state = None
                    self.deadline = None
                    changed = True
            elif self.pending_state is True:
                self.pending_state = None
                self.deadline = None

        pending_direction = "none"
        on_delay_remaining = 0.0
        off_delay_remaining = 0.0
        if self.pending_state is True and self.deadline is not None:
            pending_direction = "on"
            on_delay_remaining = max(0.0, self.deadline - now)
        elif self.pending_state is False and self.deadline is not None:
            pending_direction = "off"
            off_delay_remaining = max(0.0, self.deadline - now)

        return {
            "state": self.state,
            "pending_state": self.pending_state,
            "deadline": self.deadline,
            "changed": changed,
            "upper_threshold": upper,
            "lower_threshold": lower,
            "conditions_on": conditions_on,
            "conditions_off": conditions_off,
            "on_ready": on_ready,
            "off_required": off_required,
            "pending_direction": pending_direction,
            "on_delay_remaining": on_delay_remaining,
            "off_delay_remaining": off_delay_remaining,
        }


@dataclass
class SimulatorStatus:
    running: bool
    voltage: float
    gpio_state: bool
    on_voltage: float
    off_voltage: float
    on_delay_seconds: float
    off_delay_seconds: float
    output_mode: str = DEFAULT_OUTPUT_MODE
    output_target: str = ""
    relay_channel: str = ""
    relay_target: str = DEFAULT_RELAY_TARGET
    manual_override: bool = False
    manual_state: bool = False
    pending_state: Optional[bool] = None
    deadline: Optional[float] = None
    effective_on_voltage: float = 0.0
    effective_off_voltage: float = 0.0
    allow_on: bool = True
    off_required: bool = False
    conditions_on: Dict[str, bool] = field(default_factory=dict)
    conditions_off: Dict[str, bool] = field(default_factory=dict)
    pending_direction: str = "none"
    on_delay_remaining: float = 0.0
    off_delay_remaining: float = 0.0
    timestamp: float = field(default_factory=lambda: time.time())
    voltage_source: str = "unavailable"
    voltage_source_state: str = "unavailable"
    voltage_source_message: str = "Keine Spannungsquelle verfügbar"
    voltage_source_service: str = ""
    voltage_source_path: str = ""
    voltage_source_bus: str = ""
    voltage_source_mode: str = "dbus"
    voltage_source_available: bool = False
    voltage_source_failures: int = 0
    voltage_source_last_error: str = ""
    voltage_source_last_update: float = 0.0
    use_ignition: bool = False
    ignition_state: bool = False
    ignition_source: str = "unavailable"
    ignition_source_state: str = "unavailable"
    ignition_source_message: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "running": self.running,
            "voltage": self.voltage,
            "gpio_state": self.gpio_state,
            "on_voltage": self.on_voltage,
            "off_voltage": self.off_voltage,
            "on_delay_seconds": self.on_delay_seconds,
            "off_delay_seconds": self.off_delay_seconds,
            "output_mode": self.output_mode,
            "output_target": self.output_target,
            "relay_channel": self.relay_channel,
            "relay_target": self.relay_target,
            "manual_override": self.manual_override,
            "manual_state": self.manual_state,
            "pending_state": self.pending_state if self.pending_state is not None else "none",
            "deadline": self.deadline or 0.0,
            "effective_on_voltage": self.effective_on_voltage,
            "effective_off_voltage": self.effective_off_voltage,
            "allow_on": self.allow_on,
            "off_required": self.off_required,
            "conditions_on": dict(self.conditions_on),
            "conditions_off": dict(self.conditions_off),
            "pending_direction": self.pending_direction,
            "on_delay_remaining": self.on_delay_remaining,
            "off_delay_remaining": self.off_delay_remaining,
            "timestamp": self.timestamp,
            "voltage_source": self.voltage_source,
            "voltage_source_state": self.voltage_source_state,
            "voltage_source_message": self.voltage_source_message,
            "voltage_source_service": self.voltage_source_service,
            "voltage_source_path": self.voltage_source_path,
            "voltage_source_bus": self.voltage_source_bus,
            "voltage_source_mode": self.voltage_source_mode,
            "voltage_source_available": self.voltage_source_available,
            "voltage_source_failures": self.voltage_source_failures,
            "voltage_source_last_error": self.voltage_source_last_error,
            "voltage_source_last_update": self.voltage_source_last_update,
            "use_ignition": self.use_ignition,
            "ignition_state": self.ignition_state,
            "ignition_source": self.ignition_source,
            "ignition_source_state": self.ignition_source_state,
            "ignition_source_message": self.ignition_source_message,
            "delays": {
                "pending_state": self.pending_state if self.pending_state is not None else "none",
                "deadline": self.deadline or 0.0,
                "pending_direction": self.pending_direction,
                "on_remaining": self.on_delay_remaining,
                "off_remaining": self.off_delay_remaining,
            },
        }


class DPlusController:
    def __init__(self, settings: Dict[str, Any], use_gpio: bool = True) -> None:
        self._logger = logging.getLogger(self.__class__.__name__)
        self._settings = DEFAULT_SETTINGS.copy()
        self._settings.update(settings)
        self._gpio = GPIOController(self._settings["gpio_pin"], enabled=use_gpio)
        self._relay = RelayController(
            self._settings.get("relay_channel", DEFAULT_RELAY_CHANNEL),
            bus_choice=self._settings.get("dbus_bus", "system"),
            enabled=use_gpio,
        )
        self._output_mode = self._normalize_output_mode(
            self._settings.get("output_mode", DEFAULT_OUTPUT_MODE)
        )
        self._relay_target = normalize_relay_target(
            self._settings.get("relay_target", DEFAULT_RELAY_TARGET)
        )
        self._output_controller: Any = self._gpio
        self._switch = SwitchLogic(
            on_threshold=self._resolve_on_voltage(),
            off_threshold=self._resolve_off_voltage(),
            on_delay=self._resolve_on_delay(),
            off_delay=self._resolve_off_delay(),
        )
        upper_threshold, lower_threshold = self._switch.thresholds()
        self._status = SimulatorStatus(
            running=False,
            voltage=0.0,
            gpio_state=False,
            on_voltage=self._resolve_on_voltage(),
            off_voltage=self._resolve_off_voltage(),
            on_delay_seconds=self._resolve_on_delay(),
            off_delay_seconds=self._resolve_off_delay(),
            output_mode=self._output_mode,
            output_target="",
            relay_channel=str(self._settings.get("relay_channel", "")),
            relay_target=self._relay_target,
            manual_override=bool(self._settings.get("manual_override", False))
            or bool(self._settings.get("force_on", False))
            or bool(self._settings.get("force_off", False)),
            manual_state=(
                False
                if bool(self._settings.get("force_off", False))
                else True
                if bool(self._settings.get("force_on", False))
                else bool(self._settings.get("manual_state", False))
            ),
        )
        self._apply_output_configuration(initial=True)
        self._status.effective_on_voltage = upper_threshold
        self._status.effective_off_voltage = lower_threshold
        self._voltage = 0.0
        self._loop_task: Optional[asyncio.Task[None]] = None
        self._running = False
        self._status_callback: Optional[StatusCallback] = None
        self._lock = asyncio.Lock()
        self._voltage_provider: Optional[VoltageProvider] = None
        self._voltage_source_label = "unavailable"
        self._status.voltage_source = self._voltage_source_label
        self._status.voltage_source_service = ""
        self._status.voltage_source_path = ""
        self._status.voltage_source_bus = ""
        self._status.voltage_source_mode = "dbus"
        self._status.voltage_source_available = False
        self._status.voltage_source_failures = 0
        self._status.voltage_source_last_error = "Keine Spannungsquelle verfügbar"
        self._status.voltage_source_last_update = 0.0
        self._status.use_ignition = bool(self._settings.get("use_ignition", False))
        self._status.ignition_state = False
        self._status.ignition_source = "unavailable"
        self._status.ignition_source_state = "unavailable"
        self._status.ignition_source_message = "Zündquelle nicht aktiv"
        self._voltage_provider_details: Dict[str, Any] = {
            "state": "unavailable",
            "message": "Keine Spannungsquelle verfügbar",
            "available": False,
        }
        self._voltage_source_available = False
        self._ignition_provider: Optional[Callable[[], Awaitable[Optional[bool]]]] = None
        self._ignition_source_label = "unavailable"
        self._ignition_provider_details: Dict[str, Any] = {
            "state": "unavailable",
            "message": "Zündquelle nicht aktiv",
            "available": False,
        }
        self._ignition_source_available = False
        self._ignition_state = False
        self._emergency_off_latched = False
        self._relay_function_monitor: Optional[RelayFunctionMonitor] = None
        self._relay_function_assignments: Dict[str, str] = {}
        self._assigned_function_channel: Optional[str] = None
        self._relay_function_backups: Dict[str, str] = {}
        self._relay_backup_persist: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None
        self._relay_backup_dirty = False

    def set_relay_backup_persist(
        self, callback: Optional[Callable[[Dict[str, Any]], Awaitable[None]]]
    ) -> None:
        self._relay_backup_persist = callback

    def set_status_callback(self, callback: Optional[StatusCallback]) -> None:
        self._status_callback = callback

    def attach_relay_function_monitor(self, monitor: RelayFunctionMonitor) -> None:
        self._relay_function_monitor = monitor
        monitor.set_callback(self._handle_relay_function_update)

    def _supports_relay_assignment(self) -> bool:
        return False

    def _resolve_relay_service(self) -> str:
        if self._relay_target == "system":
            return SYSTEM_SERVICE_NAME
        preferred_service = str(self._settings.get("service_path", "")).strip()
        return discover_battery_relay_service(
            self._settings.get("dbus_bus", "system"),
            preferred_service=preferred_service,
        )

    async def initialize_relay_function_assignments(
        self, assignments: Dict[str, str]
    ) -> None:
        await self._process_relay_function_assignments(assignments, initial=True)

    def _handle_relay_function_update(
        self, assignments: Dict[str, str]
    ) -> Optional[Awaitable[None]]:
        return self._process_relay_function_assignments(assignments)

    async def _process_relay_function_assignments(
        self, assignments: Dict[str, str], *, initial: bool = False
    ) -> None:
        if not self._supports_relay_assignment():
            return
        normalized = {
            normalize_relay_channel(channel): str(value)
            for channel, value in assignments.items()
            if channel
        }
        release_channel: Optional[str] = None
        backups_changed = False
        async with self._lock:
            self._relay_function_assignments = normalized
            target_channel = self._select_relay_assignment_channel(normalized)
            changed = False
            if target_channel:
                backups_changed = self._ensure_backup_for_channel_locked(target_channel)
                changed = await self._apply_relay_assignment_locked(
                    target_channel,
                    initial=initial,
                )
            else:
                changed, release_channel = await self._apply_relay_release_locked(
                    initial=initial
                )
            if changed:
                self._evaluate_locked()
                await self._notify_status_locked()
        if release_channel:
            await self._reset_relay_function_assignment(release_channel)
        if backups_changed:
            await self._persist_relay_backups()

    def _select_relay_assignment_channel(self, assignments: Dict[str, str]) -> str:
        tag = self._relay_function_tag.lower()
        candidates = [
            channel
            for channel, value in assignments.items()
            if str(value).strip().lower() == tag
        ]
        if not candidates:
            return ""
        current_channel = normalize_relay_channel(self._settings.get("relay_channel", ""))
        if current_channel in candidates:
            return current_channel
        if self._assigned_function_channel in candidates:
            return str(self._assigned_function_channel)
        candidates.sort()
        return candidates[0]

    async def _apply_relay_assignment_locked(
        self, channel: str, *, initial: bool = False
    ) -> bool:
        normalized = normalize_relay_channel(channel)
        previous_mode = self._output_mode
        previous_channel = normalize_relay_channel(self._settings.get("relay_channel", ""))
        if previous_mode != "relay" or previous_channel != normalized:
            self._settings["relay_channel"] = normalized
            self._settings["output_mode"] = "relay"
            self._output_mode = "relay"
            self._apply_output_configuration(initial=initial)
            self._status.output_mode = "relay"
            self._status.relay_channel = normalized
            self._status.output_target = getattr(
                self._output_controller,
                "description",
                self._status.output_target,
            )
            self._status.gpio_state = self._output_controller.read()
            self._assigned_function_channel = normalized
            return True
        self._assigned_function_channel = normalized
        return False

    async def _apply_relay_release_locked(
        self, *, initial: bool = False
    ) -> Tuple[bool, Optional[str]]:
        release_channel = self._assigned_function_channel
        if self._output_mode == "gpio":
            if self._assigned_function_channel:
                self._assigned_function_channel = None
            return False, release_channel
        self._settings["output_mode"] = "gpio"
        self._output_mode = "gpio"
        self._apply_output_configuration(initial=initial)
        self._status.output_mode = "gpio"
        self._status.relay_channel = ""
        self._status.output_target = getattr(
            self._output_controller,
            "description",
            self._status.output_target,
        )
        self._status.gpio_state = self._output_controller.read()
        if not release_channel:
            release_channel = normalize_relay_channel(self._relay.channel)
        if release_channel == "":
            release_channel = None
        self._assigned_function_channel = None
        return True, release_channel

    async def _release_relay_assignment(self) -> None:
        if not self._supports_relay_assignment():
            async with self._lock:
                self._assigned_function_channel = None
            return
        monitor = self._relay_function_monitor
        neutral = self._relay_function_neutral
        channel_to_release: Optional[str]
        restore_value = neutral
        async with self._lock:
            channel_to_release = self._assigned_function_channel
            if not channel_to_release:
                return
            self._assigned_function_channel = None
            backup_value = self._pop_relay_function_backup_locked(channel_to_release)
            if backup_value is not None:
                restore_value = backup_value
            self._relay_function_assignments[channel_to_release] = restore_value
        if monitor is not None and channel_to_release is not None:
            try:
                await monitor.set_function(channel_to_release, restore_value)
            except Exception as exc:  # pragma: no-cover - Laufzeitabhängig
                self._logger.warning(
                    "Konnte Funktionskennzeichnung für Relay %s nicht zurücksetzen: %s",
                    channel_to_release,
                    exc,
                )
        await self._persist_relay_backups()

    async def _reset_relay_function_assignment(
        self, channel: Optional[str] = None
    ) -> None:
        if not self._supports_relay_assignment():
            async with self._lock:
                self._assigned_function_channel = None
            return
        if channel is None:
            await self._release_relay_assignment()
            return
        neutral = self._relay_function_neutral
        monitor = self._relay_function_monitor
        restore_value = neutral
        async with self._lock:
            backup_value = self._pop_relay_function_backup_locked(channel)
            if backup_value is not None:
                restore_value = backup_value
            self._relay_function_assignments[channel] = restore_value
            if self._assigned_function_channel == channel:
                self._assigned_function_channel = None
        if monitor is not None:
            try:
                await monitor.set_function(channel, restore_value)
            except Exception as exc:  # pragma: no-cover - Laufzeitabhängig
                self._logger.warning(
                    "Konnte Funktionskennzeichnung für Relay %s nicht zurücksetzen: %s",
                    channel,
                    exc,
                )
        await self._persist_relay_backups()

    async def _update_relay_function_assignment_locked(self) -> bool:
        monitor = self._relay_function_monitor
        if monitor is None:
            return False
        target_channel = self._relay.channel if self._supports_relay_assignment() else ""
        previous_channel = self._assigned_function_channel
        neutral = self._relay_function_neutral
        backups_changed = False
        if previous_channel and previous_channel != target_channel:
            try:
                restore_value = self._pop_relay_function_backup_locked(previous_channel)
                if restore_value is None:
                    restore_value = neutral
                else:
                    backups_changed = True
                await monitor.set_function(previous_channel, restore_value)
                self._relay_function_assignments[previous_channel] = restore_value
            except Exception as exc:  # pragma: no-cover - Laufzeitabhängig
                self._logger.warning(
                    "Konnte Funktionskennzeichnung für Relay %s nicht zurücksetzen: %s",
                    previous_channel,
                    exc,
                )
        if target_channel:
            try:
                if self._ensure_backup_for_channel_locked(target_channel):
                    backups_changed = True
                await monitor.set_function(target_channel, self._relay_function_tag)
                self._relay_function_assignments[target_channel] = self._relay_function_tag
                self._assigned_function_channel = target_channel
            except Exception as exc:  # pragma: no-cover - Laufzeitabhängig
                self._logger.warning(
                    "Konnte Relay-Funktion für %s nicht setzen: %s",
                    target_channel,
                    exc,
                )
        else:
            self._assigned_function_channel = None
        return backups_changed

    def _parse_relay_backups(self, value: Any) -> Dict[str, str]:
        if isinstance(value, Mapping):
            items = value.items()
        elif isinstance(value, str):
            text = value.strip()
            if not text:
                return {}
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                self._logger.warning(
                    "Konnte RelayFunctionBackups nicht parsen – verwende leeres Mapping"
                )
                return {}
            if isinstance(parsed, Mapping):
                items = parsed.items()
            else:
                self._logger.warning(
                    "Unerwartetes Format für RelayFunctionBackups (%s) – verwende leeres Mapping",
                    type(parsed).__name__,
                )
                return {}
        else:
            return {}
        backups: Dict[str, str] = {}
        for key, original in items:
            channel = normalize_relay_channel(key)
            if not channel:
                continue
            backups[channel] = str(original)
        return backups

    def _ensure_backup_for_channel_locked(self, channel: str) -> bool:
        normalized = normalize_relay_channel(channel)
        if not normalized:
            return False
        previous_value = self._relay_function_assignments.get(normalized)
        if not previous_value or previous_value == self._relay_function_tag:
            previous_value = self._relay_function_backups.get(normalized)
        if not previous_value or previous_value == self._relay_function_tag:
            return False
        if self._relay_function_backups.get(normalized) == previous_value:
            return False
        self._relay_function_backups[normalized] = str(previous_value)
        self._relay_backup_dirty = True
        return True

    def _pop_relay_function_backup_locked(self, channel: str) -> Optional[str]:
        normalized = normalize_relay_channel(channel)
        if not normalized:
            return None
        if normalized not in self._relay_function_backups:
            return None
        original = self._relay_function_backups.pop(normalized)
        self._relay_backup_dirty = True
        return str(original)

    async def _persist_relay_backups(self) -> None:
        callback = self._relay_backup_persist
        payload: Optional[str] = None
        async with self._lock:
            if not self._relay_backup_dirty:
                return
            payload = json.dumps(
                {k: v for k, v in sorted(self._relay_function_backups.items())}
            )
            self._settings["relay_function_backups"] = payload
            self._relay_backup_dirty = False
        if callback is None or payload is None:
            return
        try:
            await callback({"relay_function_backups": payload})
        except Exception as exc:  # pragma: no-cover - Laufzeitabhängig
            self._logger.warning(
                "Persistierung der RelayFunctionBackups schlug fehl: %s",
                exc,
            )

    def _resolve_on_voltage(self) -> float:
        return float(self._settings["on_voltage"])

    def _resolve_off_voltage(self) -> float:
        return float(self._settings["off_voltage"])

    def _resolve_on_delay(self) -> float:
        return float(self._settings["on_delay_seconds"])

    def _resolve_off_delay(self) -> float:
        return float(self._settings["off_delay_seconds"])

    @staticmethod
    def _normalize_output_mode(mode: Any) -> str:
        normalized = str(mode or "").strip().lower()
        if normalized == "relay":
            return "relay"
        return "gpio"

    def _apply_output_configuration(self, *, initial: bool = False) -> None:
        previous = getattr(self, "_output_controller", None)
        target_mode = self._normalize_output_mode(self._output_mode)
        self._relay_target = normalize_relay_target(
            self._settings.get("relay_target", DEFAULT_RELAY_TARGET)
        )
        other_controller: Optional[Any] = None
        if target_mode == "relay":
            relay_service = self._resolve_relay_service()
            channel = "0" if self._relay_target == "bmv" else str(self._settings.get("relay_channel") or "").strip()
            if not channel:
                channel = DEFAULT_RELAY_CHANNEL
                self._settings["relay_channel"] = channel
            self._relay.set_bus_choice(self._settings.get("dbus_bus", "system"))
            self._relay.set_service(relay_service)
            self._relay.reconfigure(channel)
            self._output_controller = self._relay
            other_controller = self._gpio
        else:
            self._output_controller = self._gpio
            other_controller = self._relay
        if previous is not None and previous is not self._output_controller:
            with contextlib.suppress(Exception):
                previous.write(False)
        if other_controller is not None and other_controller is not self._output_controller:
            with contextlib.suppress(Exception):
                other_controller.write(False)
        self._output_mode = target_mode
        self._status.output_mode = target_mode
        self._status.output_target = getattr(self._output_controller, "description", "")
        self._status.relay_channel = (
            map_system_relay_channel_to_display(self._relay.channel)
            if target_mode == "relay" and self._relay_target == "system"
            else self._relay.channel if target_mode == "relay" else ""
        )
        self._status.relay_target = self._relay_target
        self._status.gpio_state = self._output_controller.read()
        if initial and target_mode == "relay" and not self._relay.channel:
            self._status.relay_channel = ""

    async def set_voltage_provider(
        self,
        provider: Optional[VoltageProvider],
        source_label: Optional[str] = None,
        *,
        source_info: Optional[Dict[str, Any]] = None,
    ) -> None:
        async with self._lock:
            self._voltage_provider = provider
            if source_label is not None:
                self._voltage_source_label = source_label
            elif provider is None:
                self._voltage_source_label = "unavailable"
            info: Dict[str, Any] = dict(source_info or {})
            reader = info.get("reader")
            combined_info = dict(info)
            if reader is not None:
                try:
                    reader_metadata = getattr(reader, "metadata")
                    if callable(reader_metadata):  # pragma: no branch - defensive
                        reader_metadata = reader_metadata()
                    reader_metadata_dict = dict(reader_metadata)
                except Exception:  # pragma: no-cover - nur bei inkompatiblen Readern
                    reader_metadata_dict = {}
                for key, value in reader_metadata_dict.items():
                    combined_info.setdefault(key, value)
            self._voltage_provider_details = combined_info
            self._status.voltage_source = self._voltage_source_label
            if provider is None:
                state = str(combined_info.get("state", "unavailable"))
                message = str(
                    combined_info.get("message", "Keine Spannungsquelle verfügbar")
                )
                self._status.voltage_source_state = state
                self._status.voltage_source_message = message
                self._status.voltage_source_service = str(combined_info.get("service", ""))
                self._status.voltage_source_path = str(combined_info.get("path", ""))
                self._status.voltage_source_bus = str(combined_info.get("bus", ""))
                self._status.voltage_source_mode = str(combined_info.get("mode", "dbus"))
                self._status.voltage_source_available = bool(
                    combined_info.get("available", False)
                )
                self._status.voltage_source_last_error = message
                self._status.voltage_source_failures = int(
                    combined_info.get("failures", self._status.voltage_source_failures)
                )
                self._status.voltage_source_last_update = 0.0
            else:
                self._status.voltage_source_state = "initializing"
                self._status.voltage_source_message = ""
                self._status.voltage_source_service = str(combined_info.get("service", ""))
                self._status.voltage_source_path = str(combined_info.get("path", ""))
                self._status.voltage_source_bus = str(combined_info.get("bus", ""))
                self._status.voltage_source_mode = str(combined_info.get("mode", "dbus"))
                self._status.voltage_source_available = False
                self._status.voltage_source_last_error = ""
                self._status.voltage_source_failures = 0
                self._status.voltage_source_last_update = 0.0
            if provider is None:
                self._voltage_source_available = bool(
                    combined_info.get("available", False)
                )
            else:
                self._voltage_source_available = False
            await self._notify_status_locked()

    async def set_ignition_provider(
        self,
        provider: Optional[Callable[[], Awaitable[Optional[bool]]]],
        source_label: Optional[str] = None,
        *,
        source_info: Optional[Dict[str, Any]] = None,
    ) -> None:
        async with self._lock:
            self._ignition_provider = provider
            if source_label is not None:
                self._ignition_source_label = source_label
            elif provider is None:
                self._ignition_source_label = "unavailable"
            combined_info = dict(source_info or {})
            self._ignition_provider_details = combined_info
            self._status.use_ignition = bool(self._settings.get("use_ignition", False))
            self._status.ignition_source = self._ignition_source_label
            if provider is None:
                self._ignition_source_available = bool(combined_info.get("available", False))
                self._ignition_state = False
                self._status.ignition_state = False
                self._status.ignition_source_state = str(combined_info.get("state", "unavailable"))
                self._status.ignition_source_message = str(combined_info.get("message", "Zündquelle nicht aktiv"))
            else:
                self._ignition_source_available = False
                self._ignition_state = False
                self._status.ignition_state = False
                self._status.ignition_source_state = str(combined_info.get("state", "initializing"))
                self._status.ignition_source_message = str(combined_info.get("message", ""))
            self._evaluate_locked()
            await self._notify_status_locked()

    async def start(self) -> None:
        async with self._lock:
            if self._running:
                return
            self._running = True
            self._status.running = True
            self._loop_task = asyncio.create_task(self._run_loop())
            self._logger.info("DPlusController wurde gestartet")
            await self._notify_status_locked()

    async def stop(self) -> None:
        loop_task: Optional[asyncio.Task[None]] = None
        async with self._lock:
            was_running = self._running
            if was_running:
                self._running = False
                self._status.running = False
                loop_task = self._loop_task
                if loop_task:
                    loop_task.cancel()
        await self._release_relay_assignment()
        if not was_running:
            return
        async with self._lock:
            with contextlib.suppress(Exception):
                self._output_controller.write(False)
            if self._output_controller is not self._gpio:
                with contextlib.suppress(Exception):
                    self._gpio.write(False)
            if self._output_controller is not self._relay:
                with contextlib.suppress(Exception):
                    self._relay.write(False)
            self._status.gpio_state = self._output_controller.read()
            await self._notify_status_locked()
        if loop_task:
            try:
                await loop_task
            except asyncio.CancelledError:
                pass
        async with self._lock:
            if self._loop_task is loop_task:
                self._loop_task = None
        self._logger.info("DPlusController wurde gestoppt")

    async def update_settings(self, new_settings: Dict[str, Any]) -> Dict[str, Any]:
        release_required = False
        backups_changed = False
        async with self._lock:
            previous_output_mode = self._output_mode
            previous_relay_channel = self._relay.channel
            previous_relay_target = self._relay_target
            self._settings.update(new_settings)
            self._switch.configure(
                on_threshold=self._resolve_on_voltage(),
                off_threshold=self._resolve_off_voltage(),
                on_delay=self._resolve_on_delay(),
                off_delay=self._resolve_off_delay(),
            )
            relay_channel_changed = False
            output_mode_changed = False
            relay_target_changed = False
            if "gpio_pin" in new_settings:
                self._gpio.reconfigure(int(self._settings["gpio_pin"]))
            if "dbus_bus" in new_settings:
                self._relay.set_bus_choice(self._settings.get("dbus_bus", "system"))
            if "relay_target" in new_settings:
                self._relay_target = normalize_relay_target(
                    self._settings.get("relay_target", DEFAULT_RELAY_TARGET)
                )
                relay_target_changed = self._relay_target != previous_relay_target
            if "relay_channel" in new_settings:
                new_channel = normalize_relay_channel(
                    self._settings.get("relay_channel", "")
                )
                relay_channel_changed = new_channel != previous_relay_channel
                self._relay.reconfigure(self._settings.get("relay_channel", ""))
            if "output_mode" in new_settings:
                new_mode = self._normalize_output_mode(self._settings.get("output_mode"))
                if new_mode != self._output_mode:
                    output_mode_changed = new_mode != previous_output_mode
                    self._output_mode = new_mode
                    self._apply_output_configuration()
            elif (
                "relay_channel" in new_settings
                or "dbus_bus" in new_settings
                or "relay_target" in new_settings
                or "service_path" in new_settings
            ):
                if self._output_mode == "relay":
                    self._apply_output_configuration()
            self._status.on_voltage = self._resolve_on_voltage()
            self._status.off_voltage = self._resolve_off_voltage()
            self._status.on_delay_seconds = self._resolve_on_delay()
            self._status.off_delay_seconds = self._resolve_off_delay()
            self._status.manual_override = (
                bool(self._settings.get("manual_override", False))
                or bool(self._settings.get("force_on", False))
                or bool(self._settings.get("force_off", False))
            )
            if bool(self._settings.get("force_off", False)):
                self._status.manual_state = False
            elif bool(self._settings.get("force_on", False)):
                self._status.manual_state = True
            else:
                self._status.manual_state = bool(self._settings.get("manual_state", False))
            self._status.output_mode = self._output_mode
            self._status.use_ignition = bool(self._settings.get("use_ignition", False))
            self._status.output_target = getattr(
                self._output_controller, "description", self._status.output_target
            )
            self._status.relay_channel = (
                map_system_relay_channel_to_display(self._relay.channel)
                if self._output_mode == "relay" and self._relay_target == "system"
                else self._relay.channel if self._output_mode == "relay" else ""
            )
            self._status.relay_target = self._relay_target
            self._status.gpio_state = self._output_controller.read()
            if output_mode_changed or relay_channel_changed or relay_target_changed:
                backups_changed = await self._update_relay_function_assignment_locked()
            release_required = self._output_mode == "gpio" and bool(
                self._assigned_function_channel
            )
            self._evaluate_locked()
            await self._notify_status_locked()
            status = self.get_status()
        if release_required:
            await self._reset_relay_function_assignment()
        elif backups_changed:
            await self._persist_relay_backups()
        return status

    async def inject_voltage(self, voltage: float) -> Dict[str, Any]:
        async with self._lock:
            self._voltage = float(voltage)
            self._evaluate_locked()
            await self._notify_status_locked()
            return self.get_status()

    async def shutdown(self) -> None:
        await self.stop()
        await self._release_relay_assignment()
        self._gpio.close()
        self._relay.close()

    def get_settings(self) -> Dict[str, Any]:
        return dict(self._settings)

    def get_status(self) -> Dict[str, Any]:
        return self._status.as_dict()

    async def _run_loop(self) -> None:
        try:
            while True:
                provider: Optional[VoltageProvider]
                ignition_provider: Optional[Callable[[], Awaitable[Optional[bool]]]]
                async with self._lock:
                    provider = self._voltage_provider
                    ignition_provider = self._ignition_provider
                    interval = DEFAULT_STATUS_PUBLISH_INTERVAL
                    provider_details = dict(self._voltage_provider_details)
                    ignition_details = dict(self._ignition_provider_details)
                new_voltage: Optional[float] = None
                provider_error: Optional[VoltageSourceError] = None
                provider_state = (
                    str(provider_details.get("state", "unavailable"))
                    if provider is None
                    else "initializing"
                )
                if provider is not None:
                    try:
                        new_voltage = await provider()
                        provider_state = "ok" if new_voltage is not None else "no-data"
                    except VoltageSourceError as exc:
                        provider_error = exc
                        provider_state = "error"
                    except Exception as exc:  # pragma: no-cover - Schutz vor unbekannten Fehlern
                        provider_error = VoltageSourceError(f"Unbekannter Fehler: {exc}")
                        provider_state = "error"

                ignition_value: Optional[bool] = None
                ignition_error: Optional[VoltageSourceError] = None
                ignition_state = (
                    str(ignition_details.get("state", "unavailable"))
                    if ignition_provider is None
                    else "initializing"
                )
                if ignition_provider is not None:
                    try:
                        ignition_value = await ignition_provider()
                        ignition_state = "ok" if ignition_value is not None else "no-data"
                    except VoltageSourceError as exc:
                        ignition_error = exc
                        ignition_state = "error"
                    except Exception as exc:
                        ignition_error = VoltageSourceError(f"Unbekannter Fehler: {exc}")
                        ignition_state = "error"

                async with self._lock:
                    previous_state = self._status.voltage_source_state
                    previous_message = self._status.voltage_source_message
                    reader = provider_details.get("reader") if provider is not None else None
                    failure_count = (
                        int(getattr(reader, "failure_count", self._status.voltage_source_failures))
                        if reader is not None
                        else 0
                    )
                    last_success = (
                        float(getattr(reader, "last_success", self._status.voltage_source_last_update))
                        if reader is not None
                        else 0.0
                    )
                    if provider is None:
                        state = str(provider_details.get("state", "unavailable"))
                        message = str(
                            provider_details.get("message", "Keine Spannungsquelle verfügbar")
                        )
                        available_flag = bool(provider_details.get("available", False))
                        failures = int(provider_details.get("failures", 0))
                        last_update_hint = float(provider_details.get("last_update", 0.0))
                        self._status.voltage_source_state = state
                        self._status.voltage_source_message = message
                        self._status.voltage_source_available = available_flag
                        self._status.voltage_source_failures = failures
                        self._status.voltage_source_last_error = message
                        self._status.voltage_source_last_update = (
                            last_update_hint if last_update_hint else time.time()
                        )
                        self._voltage_source_available = available_flag
                        self._voltage = 0.0
                    elif provider_error is not None:
                        self._status.voltage_source_state = "error"
                        self._status.voltage_source_message = str(provider_error)
                        self._status.voltage_source_last_error = str(provider_error)
                        self._status.voltage_source_available = False
                        self._status.voltage_source_failures = max(failure_count, 1)
                        self._status.voltage_source_last_update = last_success
                        self._voltage_source_available = False
                        self._voltage = 0.0
                    else:
                        self._status.voltage_source_state = provider_state
                        if new_voltage is None:
                            self._status.voltage_source_message = "Keine Daten von der Spannungsquelle"
                            self._status.voltage_source_available = False
                            self._status.voltage_source_last_error = "Keine Daten von der Spannungsquelle"
                            self._status.voltage_source_failures = failure_count
                            self._status.voltage_source_last_update = last_success
                            self._voltage_source_available = False
                            self._voltage = 0.0
                        else:
                            self._status.voltage_source_message = ""
                            self._status.voltage_source_last_error = ""
                            self._status.voltage_source_available = True
                            self._status.voltage_source_failures = failure_count
                            self._status.voltage_source_last_update = (
                                last_success if last_success else time.time()
                            )
                            self._voltage_source_available = True
                            self._voltage = float(new_voltage)
                    self._status.use_ignition = bool(self._settings.get("use_ignition", False))
                    previous_ignition_state = self._status.ignition_source_state
                    previous_ignition_message = self._status.ignition_source_message
                    if ignition_provider is None:
                        self._status.ignition_source = self._ignition_source_label
                        self._status.ignition_source_state = str(ignition_details.get("state", "unavailable"))
                        self._status.ignition_source_message = str(ignition_details.get("message", "Zündquelle nicht aktiv"))
                        self._ignition_source_available = bool(ignition_details.get("available", False))
                        self._ignition_state = False
                    elif ignition_error is not None:
                        self._status.ignition_source = self._ignition_source_label
                        self._status.ignition_source_state = "error"
                        self._status.ignition_source_message = str(ignition_error)
                        self._ignition_source_available = False
                        self._ignition_state = False
                    else:
                        self._status.ignition_source = self._ignition_source_label
                        self._status.ignition_source_state = ignition_state
                        if ignition_value is None:
                            self._status.ignition_source_message = "Keine Daten von der Zündquelle"
                            self._ignition_source_available = False
                            self._ignition_state = False
                        else:
                            self._status.ignition_source_message = ""
                            self._ignition_source_available = True
                            self._ignition_state = bool(ignition_value)
                    self._status.ignition_state = self._ignition_state
                    self._evaluate_locked()
                    if (
                        previous_state != self._status.voltage_source_state
                        or previous_message != self._status.voltage_source_message
                    ):
                        message_suffix = (
                            f" ({self._status.voltage_source_message})"
                            if self._status.voltage_source_message
                            else ""
                        )
                        self._logger.info(
                            "Status der Spannungsquelle %s: %s%s",
                            self._status.voltage_source,
                            self._status.voltage_source_state,
                            message_suffix,
                        )
                    if (
                        previous_ignition_state != self._status.ignition_source_state
                        or previous_ignition_message != self._status.ignition_source_message
                    ):
                        ignition_message_suffix = (
                            f" ({self._status.ignition_source_message})"
                            if self._status.ignition_source_message
                            else ""
                        )
                        self._logger.info(
                            "Status der Zündquelle %s: %s%s",
                            self._status.ignition_source,
                            self._status.ignition_source_state,
                            ignition_message_suffix,
                        )
                    await self._notify_status_locked()
                    interval = DEFAULT_STATUS_PUBLISH_INTERVAL
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            self._logger.debug("Kontrollschleife wurde beendet")
        except Exception as exc:  # pragma: no-cover - Schutz gegen unerwartete Fehler
            self._logger.exception("Unbehandelter Fehler in der Kontrollschleife: %s", exc)

    def _evaluate_locked(self) -> None:
        now = time.monotonic()
        simulator_enabled = bool(self._settings.get("enabled", True))
        legacy_force_on = bool(self._settings.get("force_on", False))
        legacy_force_off = bool(self._settings.get("force_off", False))
        manual_override = bool(self._settings.get("manual_override", False)) or legacy_force_on or legacy_force_off
        manual_state = bool(self._settings.get("manual_state", False))
        if legacy_force_off:
            manual_state = False
        elif legacy_force_on:
            manual_state = True
        source_available = bool(self._voltage_provider) and self._voltage_source_available
        self._status.voltage_source_available = source_available
        use_ignition = bool(self._settings.get("use_ignition", False))
        ignition_available = bool(self._ignition_provider) and self._ignition_source_available
        ignition_on = bool(self._ignition_state) if use_ignition and ignition_available else False
        emergency_off_voltage = float(self._settings.get("emergency_off_voltage", 11.8))
        emergency_triggered = use_ignition and ignition_on and self._voltage < emergency_off_voltage
        if manual_override:
            desired_state = simulator_enabled and manual_state
            switch_state = {
                "changed": desired_state != self._status.gpio_state,
                "state": desired_state,
                "pending_state": None,
                "deadline": None,
                "upper_threshold": self._switch.on_threshold,
                "lower_threshold": self._switch.off_threshold,
                "conditions_on": {
                    "enabled": simulator_enabled,
                    "manual_override": True,
                    "manual_state": manual_state,
                },
                "conditions_off": {"enabled": not simulator_enabled},
                "on_ready": simulator_enabled,
                "off_required": not desired_state,
                "pending_direction": "none",
                "on_delay_remaining": 0.0,
                "off_delay_remaining": 0.0,
            }
            self._emergency_off_latched = False
        else:
            on_dependencies: Dict[str, bool] = {}
            off_dependencies: Dict[str, bool] = {}
            if not simulator_enabled:
                off_dependencies["enabled"] = True
            on_dependencies["voltage_source"] = source_available
            if not source_available:
                off_dependencies["voltage_source"] = True

            if use_ignition:
                on_dependencies["ignition"] = ignition_on
                off_dependencies["ignition"] = not ignition_on
                if emergency_triggered:
                    off_dependencies["emergency_voltage"] = True
                switch_state = self._switch.evaluate(
                    self._voltage,
                    now,
                    on_dependencies=on_dependencies,
                    off_dependencies=off_dependencies,
                    voltage_on=self._voltage >= self._switch.on_threshold,
                    voltage_off=emergency_triggered,
                    off_delay=0.0 if not ignition_on else float(self._settings.get("emergency_off_delay_seconds", 2.0)),
                )
            else:
                self._emergency_off_latched = False
                switch_state = self._switch.evaluate(
                    self._voltage,
                    now,
                    on_dependencies=on_dependencies,
                    off_dependencies=off_dependencies,
                )
        if switch_state["changed"]:
            self._logger.info(
                "Ausgang (%s) wechselt zu %s (Spannung %.3f V)",
                self._status.output_mode,
                switch_state["state"],
                self._voltage,
            )
        try:
            self._output_controller.write(switch_state["state"])
        except Exception as exc:  # pragma: no-cover - Laufzeitabhängig
            self._logger.warning(
                "Konnte Ausgang im Modus %s nicht schalten: %s",
                self._status.output_mode,
                exc,
            )
        if self._output_controller is self._relay:
            with contextlib.suppress(Exception):
                self._gpio.write(False)
        else:
            with contextlib.suppress(Exception):
                self._relay.write(False)
        self._status.gpio_state = self._output_controller.read()
        self._status.output_target = getattr(
            self._output_controller, "description", self._status.output_target
        )
        if use_ignition and switch_state["changed"] and not switch_state["state"] and not ignition_on:
            self._logger.info("Zündung ist AUS – Ausgang wird sofort deaktiviert")
        if use_ignition and switch_state["changed"] and not switch_state["state"] and emergency_triggered:
            self._logger.warning("Not-Aus wegen Unterspannung aktiv (%.3f V < %.3f V)", self._voltage, emergency_off_voltage)
        self._status.voltage = self._voltage
        self._status.use_ignition = use_ignition
        self._status.ignition_state = ignition_on
        self._status.manual_override = manual_override
        self._status.manual_state = manual_state
        self._status.pending_state = switch_state["pending_state"]
        self._status.deadline = switch_state["deadline"] or 0.0
        self._status.effective_on_voltage = switch_state["upper_threshold"]
        self._status.effective_off_voltage = switch_state["lower_threshold"]
        self._status.allow_on = simulator_enabled and switch_state["on_ready"]
        self._status.off_required = switch_state["off_required"]
        self._status.conditions_on = dict(switch_state["conditions_on"])
        self._status.conditions_off = dict(switch_state["conditions_off"])
        self._status.pending_direction = switch_state["pending_direction"]
        self._status.on_delay_remaining = switch_state["on_delay_remaining"]
        self._status.off_delay_remaining = switch_state["off_delay_remaining"]
        self._status.timestamp = time.time()

    async def _notify_status_locked(self) -> None:
        callback = self._status_callback
        if callback is None:
            return
        status = self.get_status()
        result = callback(status)
        if asyncio.iscoroutine(result):
            await result


class DPlusSimService(ServiceInterface):
    def __init__(
        self,
        controller: DPlusController,
        shutdown_callback: Callable[[], None],
        settings_persist: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
        *,
        debug_enabled: bool = False,
        voltage_constraints: Optional[Dict[str, str]] = None,
    ) -> None:
        super().__init__("com.coyodude.dplussim")
        self._controller = controller
        self._shutdown_callback = shutdown_callback
        self._persist_settings = settings_persist
        self._debug_enabled = bool(debug_enabled)
        self._voltage_constraints = {
            key: str(value).strip()
            for key, value in (voltage_constraints or {}).items()
            if str(value).strip()
        }

    @method()
    async def Start(self) -> "b":
        await self._controller.start()
        return True

    @method()
    async def Stop(self) -> "b":
        await self._controller.stop()
        return True

    @method()
    async def Shutdown(self) -> "b":
        await self._controller.shutdown()
        self._shutdown_callback()
        return True

    @method()
    async def UpdateSettings(self, settings: "a{sv}") -> "a{sv}":  # type: ignore[override]
        normalized = normalize_variant_dict(settings)
        sanitized: Dict[str, Any] = {}
        for key, value in normalized.items():
            expected = self._voltage_constraints.get(key)
            if expected is None:
                sanitized[key] = value
                continue
            actual = str(value).strip()
            if actual != expected:
                logging.getLogger("DPlusSimService").error(
                    "Einstellung %s darf nicht auf %s geändert werden (erwartet %s)",
                    key,
                    actual,
                    expected,
                )
                raise RuntimeError(
                    "Die Spannungsquelle wird automatisch erkannt. "
                    "Manuelle Änderungen an ServicePath/VoltagePath sind nicht erlaubt."
                )
        if sanitized:
            result = await self._controller.update_settings(sanitized)
        else:
            result = self._controller.get_status()
        if self._persist_settings is not None:
            persist_payload = dict(sanitized)
            for key, expected in self._voltage_constraints.items():
                if key in normalized:
                    persist_payload[key] = expected
            if persist_payload:
                await self._persist_settings(persist_payload)
        return dbusify(result)

    @method()
    async def InjectVoltageSample(self, voltage: "d") -> "a{sv}":  # type: ignore[override]
        if not self._debug_enabled:
            logging.getLogger("DPlusSimService").error(
                "InjectVoltageSample wurde ohne Debug-Modus angefordert"
            )
            raise RuntimeError(
                "InjectVoltageSample ist nur im Debug-Modus verfügbar. "
                "Starten Sie den Dienst mit --enable-debug."
            )
        if not development_features_enabled():
            logging.getLogger("DPlusSimService").error(
                "InjectVoltageSample wurde ohne gesetzte %s-Umgebungsvariable blockiert",
                DEV_FEATURE_FLAG_ENV_VAR,
            )
            raise RuntimeError(
                "Manuelle Spannungsinjektionen sind deaktiviert. "
                f"Setzen Sie {DEV_FEATURE_FLAG_ENV_VAR}=1 für den Entwicklungsmodus."
            )
        result = await self._controller.inject_voltage(float(voltage))
        return dbusify(result)

    @method()
    def GetSettings(self) -> "a{sv}":  # type: ignore[override]
        return dbusify(self._controller.get_settings())

    @method()
    def GetStatus(self) -> "a{sv}":  # type: ignore[override]
        return dbusify(self._controller.get_status())

    @signal()
    def StatusChanged(self, status: "a{sv}") -> "a{sv}":  # type: ignore[override]
        return status

    def emit_status(self, status: Dict[str, Any]) -> None:
        self.StatusChanged(dbusify(status))
def setup_logging(level: str) -> None:
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def install_signal_handlers(loop: asyncio.AbstractEventLoop, stop_callback: Callable[[], None]) -> None:
    for sig in (stdlib_signal.SIGINT, stdlib_signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_callback)
        except NotImplementedError:  # pragma: no-cover - Windows Fallback
            stdlib_signal.signal(sig, lambda *_: stop_callback())


def resolve_bus_configuration(bus_value: Any) -> Tuple[str, Optional[Any]]:
    """Normalisiere die Bus-Auswahl und leite einen ``BusType`` ab."""

    fallback_bus = "system"
    normalized = str(bus_value if bus_value is not None else fallback_bus).strip().lower()
    if not normalized:
        normalized = fallback_bus
    if normalized not in ("system", "session"):
        logging.getLogger("DPlusSim").warning(
            "Unbekannter D-Bus-Typ '%s', verwende '%s'", normalized, fallback_bus
        )
        normalized = fallback_bus

    bus_type: Optional[Any] = None
    if BusType is not None:
        if normalized == "session":
            bus_type = getattr(BusType, "SESSION", getattr(BusType, "SYSTEM", None))
        else:
            bus_type = getattr(BusType, "SYSTEM", getattr(BusType, "SESSION", None))

    return normalized, bus_type


async def run_async(args: argparse.Namespace) -> None:
    debug_enabled = bool(getattr(args, "enable_debug", False))
    merged_settings = DEFAULT_SETTINGS.copy()
    if args.bus:
        merged_settings["dbus_bus"] = args.bus

    settings_backend: Optional[BaseSettingsAdapter] = None
    settings_bus: Optional[MessageBus] = None
    settings_overrides: Dict[str, Any] = {}

    loop = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()

    def request_shutdown() -> None:
        if not shutdown_event.is_set():
            logging.getLogger("DPlusSim").info("Beende Dienst nach Shutdown-Anforderung")
            shutdown_event.set()

    install_signal_handlers(loop, request_shutdown)

    selected_bus, bus_type_for_connection = resolve_bus_configuration(
        args.bus if args.bus else merged_settings.get("dbus_bus", "system")
    )
    merged_settings["dbus_bus"] = selected_bus

    if not args.no_dbus:
        logger = logging.getLogger("DPlusSim")
        native_settings_available = (
            VelibSettingsDevice is not None
            and dbus is not None
            and DBusGMainLoop is not None
            and GLib is not None
        )

        if native_settings_available:
            try:
                settings_backend = VelibSettingsAdapter(
                    SETTINGS_DEFINITIONS,
                    merged_settings.get("dbus_bus", "system"),
                )
                settings_overrides = await settings_backend.start()
                logger.info("Einstellungen werden über SettingsDevice verwaltet")
            except Exception as exc:  # pragma: no-cover - Laufzeitabhängig
                logger.warning(
                    "SettingsDevice konnte nicht initialisiert werden (%s). "
                    "Wechsle auf direkten D-Bus-Settings-Adapter.",
                    exc,
                )
                settings_backend = None

        if settings_backend is None:
            if BusType is None or MessageBus is None or Message is None:
                logger.warning(
                    "Weder SettingsDevice noch dbus_fast sind verfügbar. "
                    "Starte mit Standardeinstellungen ohne Settings-Synchronisierung."
                )
            else:
                try:
                    connect_kwargs = (
                        {"bus_type": bus_type_for_connection}
                        if bus_type_for_connection is not None
                        else {}
                    )
                    settings_bus = await MessageBus(**connect_kwargs).connect()
                    bridge = SettingsBridge(settings_bus, SETTINGS_DEFINITIONS)
                    settings_backend = DbusNextSettingsAdapter(bridge)
                    settings_overrides = await settings_backend.start()
                    logger.info(
                        "Einstellungen werden über den direkten D-Bus-Adapter verwaltet"
                    )
                except Exception as exc:  # pragma: no-cover - Laufzeitabhängig
                    logger.warning(
                        "Direkter D-Bus-Settings-Adapter konnte nicht initialisiert werden (%s). "
                        "Starte mit Standardeinstellungen ohne Settings-Synchronisierung.",
                        exc,
                    )
                    settings_backend = None
                    settings_overrides = {}

    merged_settings.update(settings_overrides)
    if args.bus:
        merged_settings["dbus_bus"] = selected_bus
    else:
        merged_settings["dbus_bus"], _ = resolve_bus_configuration(
            merged_settings.get("dbus_bus", selected_bus)
        )
    merged_settings["voltage_source_mode"] = normalize_voltage_source_mode(
        merged_settings.get("voltage_source_mode", DEFAULT_VOLTAGE_SOURCE_MODE)
    )

    resolved_voltage_source: Optional[VoltageServiceInfo] = None
    voltage_constraints: Dict[str, str] = {}

    controller = DPlusController(merged_settings, use_gpio=not args.dry_run)
    relay_function_monitor: Optional[RelayFunctionMonitor] = None
    startup_failed = shutdown_event.is_set()

    async def mark_voltage_failure(
        message: str,
        *,
        state: str = "unavailable",
        service: str = "",
        path: str = "",
        bus_choice: Optional[str] = None,
    ) -> None:
        info = {
            "state": state,
            "message": message,
            "service": service,
            "path": path,
            "bus": bus_choice
            if bus_choice is not None
            else merged_settings.get("dbus_bus", "system"),
            "mode": "dbus",
            "available": False,
        }
        await controller.set_voltage_provider(None, "unavailable", source_info=info)

    if False:
        pass

    voltage_reader: Optional[DbusVoltageReader] = None
    ignition_reader: Optional[DbusBinaryInputReader] = None

    async def configure_voltage_source(*, fail_hard: bool) -> bool:
        nonlocal voltage_reader, startup_failed, resolved_voltage_source, voltage_constraints
        if voltage_reader is not None:
            with contextlib.suppress(Exception):
                await voltage_reader.close()
            voltage_reader = None
        resolved_voltage_source = None
        voltage_constraints = {}

        if (
            args.no_dbus
            or BusType is None
            or MessageBus is None
            or Message is None
        ):
            reason = "D-Bus-Unterstützung nicht verfügbar – der Dienst wird beendet"
            logging.getLogger("DPlusSim").error(reason)
            await mark_voltage_failure(reason)
            if fail_hard:
                request_shutdown()
                startup_failed = True
            return False

        bus_choice = merged_settings.get("dbus_bus", "system")
        source_mode = normalize_voltage_source_mode(
            merged_settings.get("voltage_source_mode", DEFAULT_VOLTAGE_SOURCE_MODE)
        )
        merged_settings["voltage_source_mode"] = source_mode

        if source_mode == "manual":
            service_name = str(merged_settings.get("service_path", "")).strip()
            object_path = str(merged_settings.get("voltage_path", "")).strip()
            if not service_name or not object_path:
                reason = "Manuelle Spannungsquelle ist nicht vollständig konfiguriert"
                logging.getLogger("DPlusSim").error(reason)
                await mark_voltage_failure(
                    reason,
                    state="not-configured",
                    service=service_name,
                    path=object_path,
                    bus_choice=bus_choice,
                )
                if fail_hard:
                    request_shutdown()
                    startup_failed = True
                return False
            resolved_voltage_source = VoltageServiceInfo(
                service_name=service_name,
                object_path=object_path,
                bus_choice=bus_choice,
            )
        else:
            try:
                resolved_voltage_source = await resolve_starter_voltage_service(bus_choice)
            except VoltageServiceDiscoveryError as exc:
                reason = f"Starterspannung konnte nicht gefunden werden: {exc}"
                logging.getLogger("DPlusSim").error(reason)
                await mark_voltage_failure(
                    reason,
                    state="not-found",
                    service="",
                    path=STARTER_VOLTAGE_PATH,
                    bus_choice=bus_choice,
                )
                if fail_hard:
                    request_shutdown()
                    startup_failed = True
                return False
            voltage_constraints = {
                "service_path": resolved_voltage_source.service_name,
                "voltage_path": resolved_voltage_source.object_path,
            }
            merged_settings.update(voltage_constraints)
            if settings_backend is not None:
                try:
                    await settings_backend.apply(voltage_constraints)
                except Exception as exc:
                    logging.getLogger("DPlusSim").warning(
                        "Automatische Übernahme der Starterspannungs-Einstellungen fehlgeschlagen: %s",
                        exc,
                    )

        voltage_reader = DbusVoltageReader(
            resolved_voltage_source.service_name,
            resolved_voltage_source.object_path,
            resolved_voltage_source.bus_choice,
        )
        try:
            await voltage_reader.initialize()
        except VoltageSourceError as exc:
            reason = f"Initiale Verbindung zur Spannungsquelle fehlgeschlagen: {exc}"
            logging.getLogger("DPlusSim").error(reason)
            await mark_voltage_failure(
                reason,
                state="error",
                service=resolved_voltage_source.service_name,
                path=resolved_voltage_source.object_path,
                bus_choice=resolved_voltage_source.bus_choice,
            )
            if fail_hard:
                request_shutdown()
                startup_failed = True
            voltage_reader = None
            return False

        await controller.update_settings(
            {
                "service_path": resolved_voltage_source.service_name,
                "voltage_path": resolved_voltage_source.object_path,
            }
        )

        await controller.set_voltage_provider(
            voltage_reader.read_voltage,
            voltage_reader.description,
            source_info={
                **voltage_reader.metadata,
                "reader": voltage_reader,
                "available": False,
                "product_id": resolved_voltage_source.product_id,
                "product_name": resolved_voltage_source.product_name,
            },
        )
        logging.getLogger("DPlusSim").info(
            "Externe Spannungsquelle aktiviert: %s",
            voltage_reader.description,
        )
        return True

    async def configure_ignition_source() -> bool:
        nonlocal ignition_reader
        if ignition_reader is not None:
            with contextlib.suppress(Exception):
                await ignition_reader.close()
            ignition_reader = None

        if not bool(merged_settings.get("use_ignition", False)):
            await controller.set_ignition_provider(
                None,
                "disabled",
                source_info={
                    "state": "disabled",
                    "message": "Zündplus ist deaktiviert",
                    "mode": "dbus-digitalinput",
                    "available": False,
                },
            )
            return True

        if args.no_dbus or BusType is None or MessageBus is None or Message is None:
            await controller.set_ignition_provider(
                None,
                "unavailable",
                source_info={
                    "state": "unavailable",
                    "message": "D-Bus-Unterstützung für Zündplus ist nicht verfügbar",
                    "mode": "dbus-digitalinput",
                    "available": False,
                },
            )
            return False

        bus_choice = merged_settings.get("dbus_bus", "system")
        try:
            ignition_source = await resolve_ignition_input_service(bus_choice)
        except VoltageServiceDiscoveryError as exc:
            await controller.set_ignition_provider(
                None,
                "unavailable",
                source_info={
                    "state": "not-found",
                    "message": f"Keine Zündquelle gefunden: {exc}",
                    "mode": "dbus-digitalinput",
                    "available": False,
                },
            )
            logging.getLogger("DPlusSim").warning("Zündplus aktiv, aber keine DigitalInput-Quelle gefunden: %s", exc)
            return False

        ignition_reader = DbusBinaryInputReader(
            ignition_source.service_name,
            ignition_source.object_path,
            ignition_source.bus_choice,
        )
        try:
            await ignition_reader.initialize()
        except VoltageSourceError as exc:
            await controller.set_ignition_provider(
                None,
                "unavailable",
                source_info={
                    "state": "error",
                    "message": f"Zündquelle konnte nicht initialisiert werden: {exc}",
                    "mode": "dbus-digitalinput",
                    "available": False,
                },
            )
            logging.getLogger("DPlusSim").warning("Initialisierung der Zündquelle fehlgeschlagen: %s", exc)
            ignition_reader = None
            return False

        await controller.set_ignition_provider(
            ignition_reader.read_state,
            ignition_reader.description,
            source_info={
                **ignition_reader.metadata,
                "reader": ignition_reader,
                "available": False,
            },
        )
        logging.getLogger("DPlusSim").info("Zündquelle aktiviert: %s", ignition_reader.description)
        return True

    if not startup_failed:
        await configure_voltage_source(fail_hard=True)
    if not startup_failed:
        await configure_ignition_source()


    async def persist_settings(updates: Dict[str, Any]) -> None:
        if not updates:
            return
        payload = dict(updates)
        if voltage_constraints:
            for key, expected in voltage_constraints.items():
                if key in payload:
                    payload[key] = expected
        merged_settings.update(payload)
        if settings_backend is not None:
            await settings_backend.apply(payload)

    controller.set_relay_backup_persist(persist_settings)

    async def handle_setting_update(key: str, value: Any) -> None:
        nonlocal voltage_reader, startup_failed, resolved_voltage_source, voltage_constraints
        if key == "dbus_bus":
            merged_settings[key] = value
            await controller.update_settings({key: value})
            await configure_voltage_source(fail_hard=False)
            await configure_ignition_source()
            return
        if key == "voltage_source_mode":
            merged_settings[key] = normalize_voltage_source_mode(value)
            if settings_backend is not None:
                await settings_backend.apply({key: merged_settings[key]})
            await configure_voltage_source(fail_hard=False)
            return
        if key == "use_ignition":
            merged_settings[key] = normalize_bool(value)
            await controller.update_settings({key: merged_settings[key]})
            await configure_ignition_source()
            return
        if key in {"service_path", "voltage_path"}:
            merged_settings[key] = str(value).strip()
            expected = voltage_constraints.get(key)
            if normalize_voltage_source_mode(
                merged_settings.get("voltage_source_mode", DEFAULT_VOLTAGE_SOURCE_MODE)
            ) == "manual":
                await configure_voltage_source(fail_hard=False)
                return
            if expected is None and resolved_voltage_source is not None:
                expected = (
                    resolved_voltage_source.service_name
                    if key == "service_path"
                    else resolved_voltage_source.object_path
                )
            normalized_value = str(value).strip()
            if expected is None:
                logging.getLogger("DPlusSim").warning(
                    "Keine automatische Starterspannungs-Erkennung aktiv – ignorierte Änderung %s=%s",
                    key,
                    normalized_value,
                )
                return
            if normalized_value != expected:
                logging.getLogger("DPlusSim").error(
                    "Einstellung %s kann nicht auf %s geändert werden – verwendet wird %s",
                    key,
                    normalized_value,
                    expected,
                )
                if settings_backend is not None:
                    await settings_backend.apply({key: expected})
                return
            merged_settings[key] = expected
            return
        merged_settings[key] = value
        await controller.update_settings({key: value})

    if settings_backend is not None:
        settings_backend.set_callback(handle_setting_update)

    async def _read_runtime_setting_value(poll_bus: MessageBus, key: str) -> Any:
        meta = SETTINGS_DEFINITIONS[key]
        reply = await poll_bus.call(
            Message(
                destination="com.victronenergy.settings",
                path=meta["path"],
                interface="com.victronenergy.BusItem",
                member="GetValue",
            )
        )
        value = SettingsBridge._unwrap_variant(reply.body[0]) if getattr(reply, "body", None) else meta["default"]
        return SettingsBridge._coerce_value(meta["type"], value)

    async def poll_runtime_settings() -> None:
        tracked_keys = (
            "enabled",
            "gpio_pin",
            "on_voltage",
            "off_voltage",
            "on_delay_seconds",
            "off_delay_seconds",
            "manual_override",
            "manual_state",
            "force_on",
            "force_off",
            "output_mode",
            "relay_channel",
            "relay_target",
            "dbus_bus",
            "voltage_source_mode",
            "service_path",
            "voltage_path",
            "use_ignition",
            "emergency_off_voltage",
            "emergency_off_delay_seconds",
        )
        poll_bus: Optional[MessageBus] = None
        last_seen: Dict[str, Any] = {}
        logger = logging.getLogger("DPlusSimSettingsPoll")
        try:
            if BusType is None or MessageBus is None or Message is None:
                return
            poll_bus_type = BusType.SYSTEM if merged_settings.get("dbus_bus", "system") == "system" else BusType.SESSION
            poll_bus = await MessageBus(bus_type=poll_bus_type).connect()
            while not shutdown_event.is_set():
                changed: Dict[str, Any] = {}
                for key in tracked_keys:
                    try:
                        value = await _read_runtime_setting_value(poll_bus, key)
                    except Exception as exc:
                        logger.debug("Konnte Einstellung %s nicht pollen: %s", key, exc)
                        continue
                    if key not in last_seen or last_seen[key] != value:
                        last_seen[key] = value
                        changed[key] = value
                for key, value in changed.items():
                    logger.info("Einstellung erkannt: %s=%r", key, value)
                    await handle_setting_update(key, value)
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Polling der DPlus-Einstellungen fehlgeschlagen: %s", exc)
        finally:
            if poll_bus is not None:
                disconnect = getattr(poll_bus, "disconnect", None)
                if callable(disconnect):
                    with contextlib.suppress(Exception):
                        result = disconnect()
                        if inspect.isawaitable(result):
                            await result
                wait_for_disconnect = getattr(poll_bus, "wait_for_disconnect", None)
                if callable(wait_for_disconnect):
                    with contextlib.suppress(Exception):
                        await wait_for_disconnect()

    bus: Optional[MessageBus] = None
    service: Optional[DPlusSimService] = None
    if not shutdown_event.is_set() and BusType is not None and not args.no_dbus:
        try:
            bus_type = (
                BusType.SYSTEM
                if merged_settings.get("dbus_bus", "system") == "system"
                else BusType.SESSION
            )
            bus = await MessageBus(bus_type=bus_type).connect()
            service = DPlusSimService(
                controller,
                request_shutdown,
                persist_settings,
                debug_enabled=debug_enabled,
                voltage_constraints=voltage_constraints,
            )
            controller.set_status_callback(service.emit_status)
            bus.export("/com/coyodude/dplussim", service)
            await bus.request_name("com.coyodude.dplussim")
            logging.getLogger("DPlusSim").info("D-Bus-Dienst erfolgreich registriert")
        except Exception as exc:  # pragma: no-cover - Laufzeitabhängig
            logging.getLogger("DPlusSim").warning(
                "D-Bus konnte nicht initialisiert werden (%s). Wechsel in lokalen Modus.",
                exc,
            )
            bus = None
            service = None

    last_output_state: Optional[bool] = None

    async def handle_status(status: Dict[str, Any]) -> None:
        nonlocal last_output_state
        if service is not None:
            service.emit_status(status)
        current_state = bool(status.get("gpio_state", False))
        ignition_state = int(bool(status.get("ignition_state", False)))
        payload: Dict[str, Any] = {"ignition_state": ignition_state}
        if current_state != last_output_state:
            last_output_state = current_state
            payload["output_state"] = int(current_state)
        await persist_settings(payload)

    controller.set_status_callback(handle_status)

    if not shutdown_event.is_set():
        await controller.start()

    settings_poll_task: Optional[asyncio.Task[None]] = None
    if not shutdown_event.is_set():
        settings_poll_task = asyncio.create_task(poll_runtime_settings())

    waveform_task: Optional[asyncio.Task[None]] = None
    if debug_enabled and getattr(args, "simulate_waveform", 0.0) and not shutdown_event.is_set():
        waveform_task = asyncio.create_task(simulate_waveform(controller, args.simulate_waveform))

    try:
        await shutdown_event.wait()
    except Exception:
        logging.getLogger("DPlusSim").exception("Unerwarteter Fehler – Shutdown wird erzwungen")
        request_shutdown()
        raise
    finally:
        if waveform_task is not None:
            waveform_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await waveform_task

        if settings_poll_task is not None:
            settings_poll_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await settings_poll_task

        if relay_function_monitor is not None:
            with contextlib.suppress(Exception):
                await relay_function_monitor.stop()

        with contextlib.suppress(Exception):
            await controller.set_voltage_provider(
                None,
                "offline",
                source_info={
                    "state": "offline",
                    "message": "Dienst wird beendet",
                    "mode": "dbus",
                    "available": False,
                },
            )

        with contextlib.suppress(Exception):
            await controller.shutdown()

        if voltage_reader is not None:
            with contextlib.suppress(Exception):
                await voltage_reader.close()

        if ignition_reader is not None:
            with contextlib.suppress(Exception):
                await ignition_reader.close()

        if bus is not None:
            disconnect = getattr(bus, "disconnect", None)
            if callable(disconnect):
                with contextlib.suppress(Exception):
                    result = disconnect()
                    if inspect.isawaitable(result):
                        await result
            with contextlib.suppress(Exception):
                await bus.wait_for_disconnect()

        if settings_backend is not None:
            with contextlib.suppress(Exception):
                await settings_backend.stop()

        if settings_bus is not None:
            disconnect = getattr(settings_bus, "disconnect", None)
            if callable(disconnect):
                disconnected_successfully = False
                try:
                    result = disconnect()
                except Exception:
                    pass
                else:
                    if inspect.isawaitable(result):
                        try:
                            await result
                        except Exception:
                            pass
                        else:
                            disconnected_successfully = True
                    else:
                        disconnected_successfully = True
                if disconnected_successfully:
                    wait_for_disconnect = getattr(settings_bus, "wait_for_disconnect", None)
                    if callable(wait_for_disconnect):
                        with contextlib.suppress(Exception):
                            await wait_for_disconnect()


async def simulate_waveform(controller: DPlusController, amplitude: float) -> None:
    logger = logging.getLogger("Waveform")
    start_time = time.monotonic()
    while True:
        elapsed = time.monotonic() - start_time
        voltage = amplitude + amplitude * 0.5 * (1 + math.sin(elapsed))
        await controller.inject_voltage(voltage)
        logger.debug("Simulierte Spannung: %.3f V", voltage)
        await asyncio.sleep(0.5)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DPlus Simulator Dienst")
    parser.add_argument("--bus", choices=("system", "session"), help="Zu verwendender D-Bus", default=None)
    parser.add_argument("--dry-run", action="store_true", help="GPIO-Befehle nicht an Hardware weiterreichen")
    parser.add_argument(
        "--no-dbus", action="store_true", help="D-Bus-Registrierung deaktivieren, auch wenn verfügbar"
    )
    parser.add_argument(
        "--enable-debug",
        action="store_true",
        help="Schaltet Debug-Funktionen frei (nicht im Produktivbetrieb verwenden)",
    )
    parser.add_argument(
        "--simulate-waveform",
        type=float,
        default=0.0,
        metavar="AMP",
        help=(
            "Aktiviert eine Sinus-Simulation mit gegebener Amplitude (nur Entwicklung). "
            f"Erfordert {DEV_FEATURE_FLAG_ENV_VAR}=1."
        ),
    )
    parser.add_argument(
        "--log-level",
        default=os.getenv("DPLUS_SIM_LOG", "INFO"),
        help="Logging-Level (z. B. DEBUG, INFO)",
    )
    return parser


def validate_runtime_options(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    debug_enabled = bool(getattr(args, "enable_debug", False))
    development_enabled = development_features_enabled()
    amplitude = float(getattr(args, "simulate_waveform", 0.0) or 0.0)
    if amplitude > 0.0:
        if not debug_enabled:
            parser.error("--simulate-waveform ist nur gemeinsam mit --enable-debug zulässig")
        if not development_enabled:
            parser.error(
                "--simulate-waveform erfordert den Entwicklungsmodus via "
                f"{DEV_FEATURE_FLAG_ENV_VAR}=1"
            )
    if debug_enabled and not development_enabled:
        logging.getLogger("DPlusSim").warning(
            "--enable-debug wurde ohne gesetztes %s verwendet. "
            "Manuelle Spannungsinjektionen bleiben deaktiviert.",
            DEV_FEATURE_FLAG_ENV_VAR,
        )


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    validate_runtime_options(args, parser)
    setup_logging(args.log_level)
    try:
        asyncio.run(run_async(args))
    except KeyboardInterrupt:
        logging.getLogger("DPlusSim").info("Beendet durch Benutzer")
    except RuntimeError as exc:
        logging.getLogger("DPlusSim").error("Fehler beim Start: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
