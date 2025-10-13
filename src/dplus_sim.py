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
import logging
import math
import os
import queue
import signal
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, Optional, Set, Tuple

try:  # pragma: no-cover - optionale Abhängigkeiten
    from dbus_next import BusType, Message, Variant
    from dbus_next.aio import MessageBus
    from dbus_next.constants import MessageType
    from dbus_next.service import ServiceInterface, method, signal
except Exception:  # pragma: no-cover - Fallback ohne D-Bus
    BusType = None
    Message = None
    MessageType = type("MessageType", (), {"SIGNAL": "signal"})

    class Variant:  # type: ignore[override]
        """Minimaler Ersatz, wenn dbus-next nicht verfügbar ist."""

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
            raise RuntimeError("D-Bus-Unterstützung ist nicht verfügbar (dbus-next fehlt)")

    class BusType:  # type: ignore[override]
        SESSION = "session"
        SYSTEM = "system"


try:  # pragma: no-cover - optional Abhängigkeit
    import RPi.GPIO as _RPiGPIO
except Exception:  # pragma: no-cover - Entwicklungsfallback
    _RPiGPIO = None

try:  # pragma: no-cover - optionale Abhängigkeiten für velib_python
    import dbus  # type: ignore
    from dbus.mainloop.glib import DBusGMainLoop  # type: ignore
    from gi.repository import GLib  # type: ignore
    from settingsdevice import SettingsDevice as VelibSettingsDevice  # type: ignore
except Exception:  # pragma: no-cover - Fallback ohne velib_python
    dbus = None  # type: ignore
    DBusGMainLoop = None  # type: ignore
    GLib = None  # type: ignore
    VelibSettingsDevice = None  # type: ignore

try:  # pragma: no-cover - optionale Abhängigkeit für vedbus
    from vedbus import VeDbusItemImport  # type: ignore
except Exception:  # pragma: no-cover - Fallback ohne vedbus
    VeDbusItemImport = None  # type: ignore


DEFAULT_GPIO_PIN = 17
DEFAULT_TARGET_VOLTAGE = 3.3
DEFAULT_HYSTERESIS = 0.1
DEFAULT_ACTIVATION_DELAY_SECONDS = 2.0
DEFAULT_DEACTIVATION_DELAY_SECONDS = 5.0
DEFAULT_ON_VOLTAGE = DEFAULT_TARGET_VOLTAGE + DEFAULT_HYSTERESIS / 2.0
DEFAULT_OFF_VOLTAGE = DEFAULT_TARGET_VOLTAGE - DEFAULT_HYSTERESIS / 2.0
DEFAULT_ON_DELAY_SECONDS = DEFAULT_ACTIVATION_DELAY_SECONDS
DEFAULT_OFF_DELAY_SECONDS = DEFAULT_DEACTIVATION_DELAY_SECONDS
DEFAULT_IGNITION_GPIO = 4
DEFAULT_IGNITION_PULL = "down"


SETTINGS_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "gpio_pin": {
        "path": "/Settings/Devices/DPlusSim/GpioPin",
        "type": "i",
        "default": DEFAULT_GPIO_PIN,
        "description": "GPIO-Pin, der die simulierte D+-Leitung schaltet.",
        "min": 0,
        "max": 0,
    },
    "target_voltage": {
        "path": "/Settings/Devices/DPlusSim/TargetVoltage",
        "type": "d",
        "default": DEFAULT_TARGET_VOLTAGE,
        "description": "Zielspannung in Volt, die durch die Simulation angestrebt wird.",
        "min": 0.0,
        "max": 0.0,
    },
    "hysteresis": {
        "path": "/Settings/Devices/DPlusSim/Hysteresis",
        "type": "d",
        "default": DEFAULT_HYSTERESIS,
        "description": "Hystereseband in Volt, bevor der GPIO neu geschaltet wird.",
        "min": 0.0,
        "max": 0.0,
    },
    "activation_delay_seconds": {
        "path": "/Settings/Devices/DPlusSim/ActivationDelaySeconds",
        "type": "d",
        "default": DEFAULT_ACTIVATION_DELAY_SECONDS,
        "description": "Verzögerung in Sekunden, bevor der GPIO bei steigender Spannung eingeschaltet wird.",
        "min": 0.0,
        "max": 0.0,
    },
    "deactivation_delay_seconds": {
        "path": "/Settings/Devices/DPlusSim/DeactivationDelaySeconds",
        "type": "d",
        "default": DEFAULT_DEACTIVATION_DELAY_SECONDS,
        "description": "Verzögerung in Sekunden, bevor der GPIO bei fallender Spannung ausgeschaltet wird.",
        "min": 0.0,
        "max": 0.0,
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
    "use_ignition": {
        "path": "/Settings/Devices/DPlusSim/UseIgnition",
        "type": "b",
        "default": False,
        "description": "Aktiviert die Abhängigkeit vom Zündplus-Eingang.",
        "min": 0,
        "max": 1,
    },
    "ignition_gpio": {
        "path": "/Settings/Devices/DPlusSim/IgnitionGpio",
        "type": "i",
        "default": DEFAULT_IGNITION_GPIO,
        "description": "GPIO-Pin, an dem das Zündplus-Signal eingelesen wird.",
        "min": 0,
        "max": 0,
    },
    "ignition_pull": {
        "path": "/Settings/Devices/DPlusSim/IgnitionPull",
        "type": "s",
        "default": DEFAULT_IGNITION_PULL,
        "description": "Pull-Up/-Down-Konfiguration für den Zündplus-Eingang (up/down/none).",
        "min": 0,
        "max": 0,
    },
    "force_on": {
        "path": "/Settings/Devices/DPlusSim/ForceOn",
        "type": "b",
        "default": False,
        "description": "Erzwingt dauerhaft ein aktives D+-Signal, unabhängig von den Eingangswerten.",
        "min": 0,
        "max": 1,
    },
    "force_off": {
        "path": "/Settings/Devices/DPlusSim/ForceOff",
        "type": "b",
        "default": False,
        "description": "Erzwingt ein dauerhaft deaktiviertes D+-Signal, unabhängig von den Eingangswerten.",
        "min": 0,
        "max": 1,
    },
    "status_publish_interval": {
        "path": "/Settings/Devices/DPlusSim/StatusPublishInterval",
        "type": "d",
        "default": 2.0,
        "description": "Intervall in Sekunden zur Veröffentlichung des Status über D-Bus-Signale.",
        "min": 0.2,
        "max": 0.0,
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
        "default": "com.victronenergy.battery",
        "description": "D-Bus-Service, aus dem die Starterbatterie-Spannung gelesen wird.",
        "min": 0,
        "max": 0,
    },
    "voltage_path": {
        "path": "/Settings/Devices/DPlusSim/VoltagePath",
        "type": "s",
        "default": "/Dc/0/Voltage",
        "description": "Objektpfad des Spannungswertes innerhalb des Service.",
        "min": 0,
        "max": 0,
    },
}

DEFAULT_SETTINGS: Dict[str, Any] = {
    key: definition["default"] for key, definition in SETTINGS_DEFINITIONS.items()
}

StatusCallback = Callable[[Dict[str, Any]], Optional[Awaitable[None]]]
VoltageProvider = Callable[[], Awaitable[Optional[float]]]


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
    if isinstance(value, list):
        return "av"
    raise TypeError(f"Unsupported value for Variant: {value!r}")


def dbusify(data: Dict[str, Any]) -> Dict[str, Any]:
    if Variant is None:  # type: ignore[truthy-bool]
        return data
    return {key: Variant(_variant_signature(value), value) for key, value in data.items()}


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
            if start_future is not None and not start_future.done():
                self._loop.call_soon_threadsafe(start_future.set_result, initial)
            self._main_loop = GLib.MainLoop()
            GLib.timeout_add(100, self._process_commands)
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

    def _apply_updates_sync(self, updates: Dict[str, Any]) -> None:
        if self._device is None:
            raise RuntimeError("SettingsDevice ist nicht verfügbar")
        for key, value in updates.items():
            if key not in self._definitions:
                continue
            typed_value = self._coerce_value(self._definitions[key]["type"], value)
            self._device[key] = typed_value

    def _handle_change(self, key: str, _old: Any, new: Any) -> None:
        callback = self._callback
        if callback is None or self._loop is None:
            return
        value = self._coerce_value(self._definitions[key]["type"], new)

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
            return bool(value)
        return str(value)

class GPIOController:
    """Abstraktion über GPIO, um Tests ohne Hardware zu ermöglichen."""

    def __init__(self, pin: int, enabled: bool = True) -> None:
        self._pin = pin
        self._enabled = enabled and _RPiGPIO is not None
        self._state = False
        self._logger = logging.getLogger(self.__class__.__name__)
        if self._enabled:
            _RPiGPIO.setmode(_RPiGPIO.BCM)
            _RPiGPIO.setup(self._pin, _RPiGPIO.OUT)
        else:
            self._logger.debug("GPIO wird im Simulationsmodus betrieben")

    @property
    def pin(self) -> int:
        return self._pin

    def reconfigure(self, new_pin: int) -> None:
        if new_pin == self._pin:
            return
        self._logger.info("GPIO wird von Pin %s auf Pin %s umkonfiguriert", self._pin, new_pin)
        previous_state = self._state
        if self._enabled:
            _RPiGPIO.cleanup(self._pin)
            _RPiGPIO.setup(new_pin, _RPiGPIO.OUT)
            _RPiGPIO.output(
                new_pin,
                _RPiGPIO.HIGH if previous_state else _RPiGPIO.LOW,
            )
        self._pin = new_pin

    def write(self, state: bool) -> None:
        if state == self._state:
            return
        self._logger.debug("GPIO-Pin %s wird auf %s gesetzt", self._pin, state)
        self._state = state
        if self._enabled:
            _RPiGPIO.output(self._pin, _RPiGPIO.HIGH if state else _RPiGPIO.LOW)

    def read(self) -> bool:
        return self._state

    def close(self) -> None:
        if self._enabled:
            self._logger.debug("GPIO-Pin %s wird freigegeben", self._pin)
            _RPiGPIO.cleanup(self._pin)
        self._state = False


class GPIOInput:
    def __init__(
        self,
        pin: int,
        *,
        enabled: bool = True,
        pull_mode: str = DEFAULT_IGNITION_PULL,
    ) -> None:
        self._logger = logging.getLogger(self.__class__.__name__)
        self._pin = int(pin)
        self._enabled = enabled and _RPiGPIO is not None
        self._pull_mode = self._normalize_pull_mode(pull_mode)
        self._state = False
        if self._enabled:
            self._configure_hardware()

    def _configure_hardware(self) -> None:
        if not self._enabled:
            return
        pud = self._resolve_pull_constant()
        if pud is None:
            _RPiGPIO.setup(self._pin, _RPiGPIO.IN)
        else:
            _RPiGPIO.setup(self._pin, _RPiGPIO.IN, pull_up_down=pud)

    @property
    def pin(self) -> int:
        return self._pin

    @property
    def pull_mode(self) -> str:
        return self._pull_mode

    def reconfigure(self, new_pin: int) -> None:
        new_pin = int(new_pin)
        if new_pin == self._pin:
            return
        self._logger.info("GPIO-Eingang wird von Pin %s auf Pin %s umkonfiguriert", self._pin, new_pin)
        if self._enabled:
            _RPiGPIO.cleanup(self._pin)
            self._pin = new_pin
            self._configure_hardware()
        else:
            self._pin = new_pin

    def set_pull_mode(self, pull_mode: str) -> None:
        normalized = self._normalize_pull_mode(pull_mode)
        if normalized == self._pull_mode:
            return
        self._logger.info(
            "GPIO-Eingang %s verwendet nun Pull-%s", self._pin, normalized
        )
        self._pull_mode = normalized
        if self._enabled:
            _RPiGPIO.cleanup(self._pin)
            self._configure_hardware()

    def read(self) -> bool:
        if self._enabled:
            return bool(_RPiGPIO.input(self._pin))
        return self._state

    def simulate(self, state: bool) -> None:
        if self._enabled:
            self._logger.warning(
                "Simulierter Zustand für GPIO-Eingang %s wurde angefordert, aber Hardware ist aktiv – Befehl wird ignoriert",
                self._pin,
            )
            return
        self._state = bool(state)

    def close(self) -> None:
        if self._enabled:
            self._logger.debug("GPIO-Eingang %s wird freigegeben", self._pin)
            _RPiGPIO.cleanup(self._pin)

    def _normalize_pull_mode(self, mode: str) -> str:
        normalized = str(mode or "").strip().lower()
        if normalized in {"up", "pullup", "pud_up"}:
            return "up"
        if normalized in {"none", "off", "floating"}:
            return "none"
        return "down"

    def _resolve_pull_constant(self) -> Optional[int]:
        if _RPiGPIO is None:
            return None
        if self._pull_mode == "up":
            return getattr(_RPiGPIO, "PUD_UP", None)
        if self._pull_mode == "none":
            pud_off = getattr(_RPiGPIO, "PUD_OFF", None)
            if pud_off is None:
                self._logger.warning(
                    "GPIO-Bibliothek unterstützt keinen PUD_OFF, Pull-Mode 'none' fällt auf 'down' zurück"
                )
                return getattr(_RPiGPIO, "PUD_DOWN", None)
            return pud_off
        return getattr(_RPiGPIO, "PUD_DOWN", None)


@dataclass
class SwitchLogic:
    on_threshold: float
    off_threshold: float
    hysteresis: float
    on_delay: float
    off_delay: float
    state: bool = False
    pending_state: Optional[bool] = None
    deadline: Optional[float] = None

    def configure(
        self,
        on_threshold: float,
        off_threshold: float,
        hysteresis: float,
        on_delay: float,
        off_delay: float,
    ) -> None:
        self.on_threshold = on_threshold
        self.off_threshold = off_threshold
        self.hysteresis = hysteresis
        self.on_delay = on_delay
        self.off_delay = off_delay
        self.pending_state = None
        self.deadline = None

    def _compute_thresholds(self) -> Tuple[float, float]:
        upper = float(self.on_threshold)
        lower = float(self.off_threshold)
        if self.hysteresis > 0:
            half = self.hysteresis / 2.0
            upper += half
            lower -= half
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
        force_on: bool,
        force_off: bool,
    ) -> Dict[str, Any]:
        upper, lower = self._compute_thresholds()
        voltage_on = voltage >= upper
        voltage_off = voltage <= lower
        conditions_on: Dict[str, bool] = {"voltage": voltage_on}
        conditions_off: Dict[str, bool] = {"voltage": voltage_off}
        conditions_on.update(on_dependencies)
        conditions_off.update(off_dependencies)
        on_ready = all(conditions_on.values()) if conditions_on else True
        off_required = any(conditions_off.values()) if conditions_off else False

        changed = False
        force_off_active = bool(force_off)
        force_on_active = bool(force_on and not force_off_active)

        if force_off_active:
            if self.state:
                changed = True
            self.state = False
            self.pending_state = None
            self.deadline = None
        elif force_on_active:
            if not self.state:
                changed = True
            self.state = True
            self.pending_state = None
            self.deadline = None
        elif self.state:
            if off_required:
                if self.pending_state is not False:
                    self.pending_state = False
                    self.deadline = now + self.off_delay
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
                    self.deadline = now + self.on_delay
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
            "force_on_active": force_on_active,
            "force_off_active": force_off_active,
            "pending_direction": pending_direction,
            "on_delay_remaining": on_delay_remaining,
            "off_delay_remaining": off_delay_remaining,
        }


@dataclass
class SimulatorStatus:
    running: bool
    voltage: float
    gpio_state: bool
    target_voltage: float
    hysteresis: float
    activation_delay_seconds: float
    deactivation_delay_seconds: float
    on_voltage: float
    off_voltage: float
    on_delay_seconds: float
    off_delay_seconds: float
    pending_state: Optional[bool] = None
    deadline: Optional[float] = None
    effective_on_voltage: float = 0.0
    effective_off_voltage: float = 0.0
    ignition_enabled: bool = False
    ignition_state: bool = False
    ignition_gpio: int = 0
    ignition_pull_mode: str = DEFAULT_IGNITION_PULL
    allow_on: bool = True
    off_required: bool = False
    force_on_configured: bool = False
    force_on_active: bool = False
    force_off_configured: bool = False
    force_off_active: bool = False
    conditions_on: Dict[str, bool] = field(default_factory=dict)
    conditions_off: Dict[str, bool] = field(default_factory=dict)
    pending_direction: str = "none"
    on_delay_remaining: float = 0.0
    off_delay_remaining: float = 0.0
    timestamp: float = field(default_factory=lambda: time.time())
    voltage_source: str = "manual"
    voltage_source_state: str = "manual"
    voltage_source_message: str = ""
    voltage_source_service: str = ""
    voltage_source_path: str = ""
    voltage_source_bus: str = ""
    voltage_source_mode: str = ""
    voltage_source_available: bool = True
    voltage_source_failures: int = 0
    voltage_source_last_error: str = ""
    voltage_source_last_update: float = 0.0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "running": self.running,
            "voltage": self.voltage,
            "gpio_state": self.gpio_state,
            "target_voltage": self.target_voltage,
            "hysteresis": self.hysteresis,
            "activation_delay_seconds": self.activation_delay_seconds,
            "deactivation_delay_seconds": self.deactivation_delay_seconds,
            "on_voltage": self.on_voltage,
            "off_voltage": self.off_voltage,
            "on_delay_seconds": self.on_delay_seconds,
            "off_delay_seconds": self.off_delay_seconds,
            "pending_state": self.pending_state if self.pending_state is not None else "none",
            "deadline": self.deadline or 0.0,
            "effective_on_voltage": self.effective_on_voltage,
            "effective_off_voltage": self.effective_off_voltage,
            "ignition_enabled": self.ignition_enabled,
            "ignition_state": self.ignition_state,
            "ignition_gpio": self.ignition_gpio,
            "ignition_pull_mode": self.ignition_pull_mode,
            "allow_on": self.allow_on,
            "off_required": self.off_required,
            "force_on": self.force_on_configured,
            "force_on_active": self.force_on_active,
            "force_off": self.force_off_configured,
            "force_off_active": self.force_off_active,
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
            "ignition": {
                "enabled": self.ignition_enabled,
                "state": self.ignition_state,
                "gpio": self.ignition_gpio,
                "pull_mode": self.ignition_pull_mode,
            },
            "force_mode": {
                "configured_on": self.force_on_configured,
                "configured_off": self.force_off_configured,
                "active_on": self.force_on_active,
                "active_off": self.force_off_active,
            },
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
        self._ignition_input = GPIOInput(
            self._settings["ignition_gpio"],
            enabled=use_gpio,
            pull_mode=self._settings.get("ignition_pull", DEFAULT_IGNITION_PULL),
        )
        self._switch = SwitchLogic(
            on_threshold=self._resolve_on_voltage(),
            off_threshold=self._resolve_off_voltage(),
            hysteresis=self._settings["hysteresis"],
            on_delay=self._resolve_on_delay(),
            off_delay=self._resolve_off_delay(),
        )
        upper_threshold, lower_threshold = self._switch.thresholds()
        self._status = SimulatorStatus(
            running=False,
            voltage=0.0,
            gpio_state=False,
            target_voltage=self._settings["target_voltage"],
            hysteresis=self._settings["hysteresis"],
            activation_delay_seconds=self._settings["activation_delay_seconds"],
            deactivation_delay_seconds=self._settings["deactivation_delay_seconds"],
            on_voltage=self._resolve_on_voltage(),
            off_voltage=self._resolve_off_voltage(),
            on_delay_seconds=self._resolve_on_delay(),
            off_delay_seconds=self._resolve_off_delay(),
            ignition_enabled=bool(self._settings["use_ignition"]),
            ignition_gpio=int(self._settings["ignition_gpio"]),
            ignition_pull_mode=str(self._settings.get("ignition_pull", DEFAULT_IGNITION_PULL)),
            force_on_configured=bool(self._settings["force_on"]),
            force_off_configured=bool(self._settings.get("force_off", False)),
        )
        self._status.effective_on_voltage = upper_threshold
        self._status.effective_off_voltage = lower_threshold
        self._status.ignition_state = self._ignition_input.read()
        self._voltage = 0.0
        self._loop_task: Optional[asyncio.Task[None]] = None
        self._running = False
        self._status_callback: Optional[StatusCallback] = None
        self._lock = asyncio.Lock()
        self._voltage_provider: Optional[VoltageProvider] = None
        self._voltage_source_label = "manual"
        self._status.voltage_source = self._voltage_source_label
        self._status.voltage_source_service = ""
        self._status.voltage_source_path = ""
        self._status.voltage_source_bus = ""
        self._status.voltage_source_mode = "manual"
        self._status.voltage_source_available = True
        self._status.voltage_source_failures = 0
        self._status.voltage_source_last_error = ""
        self._status.voltage_source_last_update = 0.0
        self._voltage_provider_details: Dict[str, Any] = {}
        self._voltage_source_available = True

    def set_status_callback(self, callback: Optional[StatusCallback]) -> None:
        self._status_callback = callback

    def _resolve_on_voltage(self) -> float:
        value = self._settings.get("on_voltage")
        if value is None:
            return float(self._settings["target_voltage"] + self._settings["hysteresis"] / 2.0)
        return float(value)

    def _resolve_off_voltage(self) -> float:
        value = self._settings.get("off_voltage")
        if value is None:
            return float(self._settings["target_voltage"] - self._settings["hysteresis"] / 2.0)
        return float(value)

    def _resolve_on_delay(self) -> float:
        value = self._settings.get("on_delay_seconds")
        if value is None:
            return float(self._settings["activation_delay_seconds"])
        return float(value)

    def _resolve_off_delay(self) -> float:
        value = self._settings.get("off_delay_seconds")
        if value is None:
            return float(self._settings["deactivation_delay_seconds"])
        return float(value)

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
                self._voltage_source_label = "manual"
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
                self._status.voltage_source_state = "manual"
                self._status.voltage_source_message = ""
                self._status.voltage_source_service = ""
                self._status.voltage_source_path = ""
                self._status.voltage_source_bus = ""
                self._status.voltage_source_mode = "manual"
                self._status.voltage_source_available = True
            else:
                self._status.voltage_source_state = "initializing"
                self._status.voltage_source_message = ""
                self._status.voltage_source_service = str(combined_info.get("service", ""))
                self._status.voltage_source_path = str(combined_info.get("path", ""))
                self._status.voltage_source_bus = str(combined_info.get("bus", ""))
                self._status.voltage_source_mode = str(combined_info.get("mode", "dbus"))
                self._status.voltage_source_available = False
            self._status.voltage_source_failures = 0
            self._status.voltage_source_last_error = ""
            self._status.voltage_source_last_update = 0.0
            self._voltage_source_available = provider is None
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
        async with self._lock:
            if not self._running:
                return
            self._running = False
            self._status.running = False
            if self._loop_task:
                self._loop_task.cancel()
            self._gpio.write(False)
            await self._notify_status_locked()
        if self._loop_task:
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
            self._loop_task = None
        self._logger.info("DPlusController wurde gestoppt")

    async def update_settings(self, new_settings: Dict[str, Any]) -> Dict[str, Any]:
        async with self._lock:
            self._settings.update(new_settings)
            self._switch.configure(
                on_threshold=self._resolve_on_voltage(),
                off_threshold=self._resolve_off_voltage(),
                hysteresis=self._settings["hysteresis"],
                on_delay=self._resolve_on_delay(),
                off_delay=self._resolve_off_delay(),
            )
            if "gpio_pin" in new_settings:
                self._gpio.reconfigure(int(self._settings["gpio_pin"]))
            if "ignition_gpio" in new_settings:
                self._ignition_input.reconfigure(int(self._settings["ignition_gpio"]))
            if "ignition_pull" in new_settings:
                self._ignition_input.set_pull_mode(self._settings["ignition_pull"])
            self._status.target_voltage = float(self._settings["target_voltage"])
            self._status.hysteresis = float(self._settings["hysteresis"])
            self._status.activation_delay_seconds = float(
                self._settings["activation_delay_seconds"]
            )
            self._status.deactivation_delay_seconds = float(
                self._settings["deactivation_delay_seconds"]
            )
            self._status.on_voltage = self._resolve_on_voltage()
            self._status.off_voltage = self._resolve_off_voltage()
            self._status.on_delay_seconds = self._resolve_on_delay()
            self._status.off_delay_seconds = self._resolve_off_delay()
            self._status.ignition_enabled = bool(self._settings["use_ignition"])
            self._status.ignition_gpio = int(self._settings["ignition_gpio"])
            self._status.ignition_pull_mode = str(
                self._settings.get("ignition_pull", DEFAULT_IGNITION_PULL)
            )
            self._status.force_on_configured = bool(self._settings["force_on"])
            self._status.force_off_configured = bool(self._settings.get("force_off", False))
            self._evaluate_locked()
            await self._notify_status_locked()
            return self.get_status()

    async def inject_voltage(self, voltage: float) -> Dict[str, Any]:
        async with self._lock:
            self._voltage = float(voltage)
            self._evaluate_locked()
            await self._notify_status_locked()
            return self.get_status()

    async def shutdown(self) -> None:
        await self.stop()
        self._gpio.close()
        self._ignition_input.close()

    def get_settings(self) -> Dict[str, Any]:
        return dict(self._settings)

    def get_status(self) -> Dict[str, Any]:
        return self._status.as_dict()

    async def _run_loop(self) -> None:
        try:
            while True:
                provider: Optional[VoltageProvider]
                async with self._lock:
                    provider = self._voltage_provider
                    interval = float(self._settings["status_publish_interval"])
                    provider_details = dict(self._voltage_provider_details)
                new_voltage: Optional[float] = None
                provider_error: Optional[VoltageSourceError] = None
                provider_state = "manual" if provider is None else "initializing"
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
                        self._status.voltage_source_state = "manual"
                        self._status.voltage_source_message = ""
                        self._status.voltage_source_available = True
                        self._status.voltage_source_failures = 0
                        self._status.voltage_source_last_error = ""
                        self._status.voltage_source_last_update = time.time()
                        self._voltage_source_available = True
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
                    await self._notify_status_locked()
                    interval = float(self._settings["status_publish_interval"])
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            self._logger.debug("Kontrollschleife wurde beendet")
        except Exception as exc:  # pragma: no-cover - Schutz gegen unerwartete Fehler
            self._logger.exception("Unbehandelter Fehler in der Kontrollschleife: %s", exc)

    def _evaluate_locked(self) -> None:
        now = time.monotonic()
        ignition_state = self._ignition_input.read() if self._ignition_input else False
        ignition_required = bool(self._settings.get("use_ignition", False))
        source_available = self._voltage_source_available or self._voltage_provider is None
        self._status.voltage_source_available = source_available
        on_dependencies: Dict[str, bool] = {}
        off_dependencies: Dict[str, bool] = {}
        if ignition_required:
            on_dependencies["ignition"] = ignition_state
            off_dependencies["ignition"] = not ignition_state
        on_dependencies["voltage_source"] = source_available
        if not source_available:
            off_dependencies["voltage_source"] = True
        force_on = bool(self._settings.get("force_on", False))
        force_off = bool(self._settings.get("force_off", False))
        switch_state = self._switch.evaluate(
            self._voltage,
            now,
            on_dependencies=on_dependencies,
            off_dependencies=off_dependencies,
            force_on=force_on,
            force_off=force_off,
        )
        if switch_state["changed"]:
            self._logger.info(
                "GPIO-Status wechselt zu %s (Spannung %.3f V)",
                switch_state["state"],
                self._voltage,
            )
        self._gpio.write(switch_state["state"])
        self._status.gpio_state = self._gpio.read()
        self._status.voltage = self._voltage
        self._status.pending_state = switch_state["pending_state"]
        self._status.deadline = switch_state["deadline"] or 0.0
        self._status.effective_on_voltage = switch_state["upper_threshold"]
        self._status.effective_off_voltage = switch_state["lower_threshold"]
        self._status.ignition_enabled = ignition_required
        self._status.ignition_state = ignition_state
        self._status.ignition_pull_mode = str(self._settings.get("ignition_pull", DEFAULT_IGNITION_PULL))
        self._status.allow_on = switch_state["on_ready"]
        self._status.off_required = switch_state["off_required"]
        self._status.conditions_on = dict(switch_state["conditions_on"])
        self._status.conditions_off = dict(switch_state["conditions_off"])
        self._status.pending_direction = switch_state["pending_direction"]
        self._status.on_delay_remaining = switch_state["on_delay_remaining"]
        self._status.off_delay_remaining = switch_state["off_delay_remaining"]
        self._status.force_on_active = switch_state["force_on_active"]
        self._status.force_off_active = switch_state["force_off_active"]
        self._status.force_on_configured = force_on
        self._status.force_off_configured = force_off
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
    ) -> None:
        super().__init__("com.coyodude.dplussim")
        self._controller = controller
        self._shutdown_callback = shutdown_callback
        self._persist_settings = settings_persist

    @method()
    async def Start(self) -> bool:
        await self._controller.start()
        return True

    @method()
    async def Stop(self) -> bool:
        await self._controller.stop()
        return True

    @method()
    async def Shutdown(self) -> bool:
        await self._controller.shutdown()
        self._shutdown_callback()
        return True

    @method()
    async def UpdateSettings(self, settings: "a{sv}") -> "a{sv}":  # type: ignore[override]
        normalized = normalize_variant_dict(settings)
        result = await self._controller.update_settings(normalized)
        if self._persist_settings is not None:
            await self._persist_settings(normalized)
        return dbusify(result)

    @method()
    async def InjectVoltageSample(self, voltage: "d") -> "a{sv}":  # type: ignore[override]
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
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_callback)
        except NotImplementedError:  # pragma: no-cover - Windows Fallback
            signal.signal(sig, lambda *_: stop_callback())


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
    merged_settings = DEFAULT_SETTINGS.copy()
    if args.bus:
        merged_settings["dbus_bus"] = args.bus

    settings_backend: Optional[BaseSettingsAdapter] = None
    settings_bus: Optional[MessageBus] = None
    settings_overrides: Dict[str, Any] = {}

    selected_bus, bus_type_for_connection = resolve_bus_configuration(
        args.bus if args.bus else merged_settings.get("dbus_bus", "system")
    )
    merged_settings["dbus_bus"] = selected_bus

    if not args.no_dbus:
        if (
            VelibSettingsDevice is not None
            and dbus is not None
            and DBusGMainLoop is not None
            and GLib is not None
        ):
            try:
                settings_backend = VelibSettingsAdapter(
                    SETTINGS_DEFINITIONS,
                    merged_settings.get("dbus_bus", "system"),
                )
                settings_overrides = await settings_backend.start()
            except Exception as exc:  # pragma: no-cover - Laufzeitabhängig
                logging.getLogger("DPlusSim").warning(
                    "SettingsDevice konnte nicht initialisiert werden: %s",
                    exc,
                )
                settings_backend = None
                settings_overrides = {}
        if (
            settings_backend is None
            and BusType is not None
            and Message is not None
        ):
            try:
                if bus_type_for_connection is not None:
                    settings_bus = await MessageBus(bus_type=bus_type_for_connection).connect()
                else:
                    settings_bus = await MessageBus().connect()
                bridge = SettingsBridge(settings_bus, SETTINGS_DEFINITIONS)
                settings_backend = DbusNextSettingsAdapter(bridge)
                settings_overrides = await settings_backend.start()
            except Exception as exc:  # pragma: no-cover - Laufzeitabhängig
                logging.getLogger("DPlusSim").warning(
                    "Konnte Einstellungen nicht mit com.victronenergy.settings synchronisieren: %s",
                    exc,
                )
                if settings_bus is not None:
                    disconnect = getattr(settings_bus, "disconnect", None)
                    disconnect_result: Any
                    disconnect_started = False
                    if callable(disconnect):
                        try:
                            disconnect_result = disconnect()
                        except Exception:
                            pass
                        else:
                            if inspect.isawaitable(disconnect_result) or asyncio.isfuture(
                                disconnect_result
                            ):
                                try:
                                    await disconnect_result
                                except Exception:
                                    pass
                                else:
                                    disconnect_started = True
                            else:
                                disconnect_started = True
                    if disconnect_started:
                        wait_for_disconnect = getattr(settings_bus, "wait_for_disconnect", None)
                        if callable(wait_for_disconnect):
                            with contextlib.suppress(Exception):
                                await wait_for_disconnect()
                settings_backend = None
                settings_bus = None
                settings_overrides = {}

    merged_settings.update(settings_overrides)
    if args.bus:
        merged_settings["dbus_bus"] = selected_bus
    else:
        merged_settings["dbus_bus"], _ = resolve_bus_configuration(
            merged_settings.get("dbus_bus", selected_bus)
        )

    controller = DPlusController(merged_settings, use_gpio=not args.dry_run)

    voltage_reader: Optional[DbusVoltageReader] = None
    if (
        not args.no_dbus
        and BusType is not None
        and MessageBus is not None
        and Message is not None
    ):
        service_name = str(merged_settings.get("service_path", "")).strip()
        voltage_path = str(merged_settings.get("voltage_path", "")).strip()
        if service_name and voltage_path:
            voltage_reader = DbusVoltageReader(
                service_name,
                voltage_path,
                merged_settings.get("dbus_bus", "system"),
            )
            try:
                await voltage_reader.initialize()
            except VoltageSourceError as exc:
                logging.getLogger("DPlusSim").warning(
                    "Initiale Verbindung zur Spannungsquelle fehlgeschlagen: %s",
                    exc,
                )
            await controller.set_voltage_provider(
                voltage_reader.read_voltage,
                voltage_reader.description,
                source_info={**voltage_reader.metadata, "reader": voltage_reader},
            )
            logging.getLogger("DPlusSim").info(
                "Externe Spannungsquelle aktiviert: %s",
                voltage_reader.description,
            )
        else:
            await controller.set_voltage_provider(
                None,
                "manual",
                source_info={"mode": "manual"},
            )
            logging.getLogger("DPlusSim").info(
                "Keine externe Spannungsquelle konfiguriert – Spannung muss manuell vorgegeben werden",
            )
    else:
        await controller.set_voltage_provider(
            None,
            "manual",
            source_info={"mode": "manual"},
        )
        if not args.no_dbus:
            logging.getLogger("DPlusSim").warning(
                "D-Bus-Unterstützung nicht verfügbar – es wird auf manuelle Spannung umgeschaltet",
            )

    loop = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()

    def request_shutdown() -> None:
        if not shutdown_event.is_set():
            logging.getLogger("DPlusSim").info("Beende Dienst nach Shutdown-Anforderung")
            shutdown_event.set()

    install_signal_handlers(loop, request_shutdown)

    async def persist_settings(updates: Dict[str, Any]) -> None:
        if not updates:
            return
        merged_settings.update(updates)
        if settings_backend is not None:
            await settings_backend.apply(updates)

    if settings_backend is not None:

        async def handle_setting_update(key: str, value: Any) -> None:
            nonlocal voltage_reader
            if key == "dbus_bus":
                logging.getLogger("DPlusSim").warning(
                    "Änderungen am D-Bus-Typ (%s) werden erst nach einem Neustart wirksam",
                    value,
                )
                return
            merged_settings[key] = value
            await controller.update_settings({key: value})
            if key in {"service_path", "voltage_path"}:
                if args.no_dbus or BusType is None or MessageBus is None or Message is None:
                    if voltage_reader is not None:
                        await voltage_reader.close()
                        voltage_reader = None
                    await controller.set_voltage_provider(
                        None,
                        "manual",
                        source_info={"mode": "manual"},
                    )
                    logging.getLogger("DPlusSim").warning(
                        "Spannungsquelle kann ohne D-Bus nicht aktualisiert werden – manuelle Eingabe aktiv",
                    )
                    return
                service_name = str(merged_settings.get("service_path", "")).strip()
                voltage_path = str(merged_settings.get("voltage_path", "")).strip()
                if not service_name or not voltage_path:
                    if voltage_reader is not None:
                        await voltage_reader.close()
                        voltage_reader = None
                    await controller.set_voltage_provider(
                        None,
                        "manual",
                        source_info={"mode": "manual"},
                    )
                    logging.getLogger("DPlusSim").info(
                        "Externe Spannungsquelle deaktiviert – es wird auf manuelle Spannung gewechselt",
                    )
                    return
                bus_choice = merged_settings.get("dbus_bus", "system")
                if (
                    voltage_reader is None
                    or voltage_reader.service_name != service_name
                    or voltage_reader.object_path != voltage_path
                    or voltage_reader.bus_choice != bus_choice
                ):
                    if voltage_reader is not None:
                        await voltage_reader.close()
                    voltage_reader = DbusVoltageReader(service_name, voltage_path, bus_choice)
                if voltage_reader is not None:
                    try:
                        await voltage_reader.initialize()
                    except VoltageSourceError as exc:
                        logging.getLogger("DPlusSim").warning(
                            "Verbindung zur Spannungsquelle konnte nicht aufgebaut werden: %s",
                            exc,
                        )
                await controller.set_voltage_provider(
                    voltage_reader.read_voltage,
                    voltage_reader.description,
                    source_info={**voltage_reader.metadata, "reader": voltage_reader},
                )
                logging.getLogger("DPlusSim").info(
                    "Externe Spannungsquelle aktualisiert: %s",
                    voltage_reader.description,
                )
                return

        settings_backend.set_callback(handle_setting_update)

    await controller.start()

    bus: Optional[MessageBus] = None
    service: Optional[DPlusSimService] = None
    if BusType is not None and not args.no_dbus:
        try:
            bus_type = (
                BusType.SYSTEM
                if merged_settings.get("dbus_bus", "system") == "system"
                else BusType.SESSION
            )
            bus = await MessageBus(bus_type=bus_type).connect()
            service = DPlusSimService(controller, request_shutdown, persist_settings)
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

    if service is None:
        controller.set_status_callback(lambda _status: None)

    waveform_task: Optional[asyncio.Task[None]] = None
    if args.simulate_waveform:
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

        with contextlib.suppress(Exception):
            await controller.set_voltage_provider(
                None,
                "manual",
                source_info={"mode": "manual"},
            )

        with contextlib.suppress(Exception):
            await controller.shutdown()

        if voltage_reader is not None:
            with contextlib.suppress(Exception):
                await voltage_reader.close()

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
        "--simulate-waveform",
        type=float,
        default=0.0,
        metavar="AMP",
        help="Aktiviert eine Sinus-Simulation mit gegebener Amplitude (nur Testzwecke)",
    )
    parser.add_argument(
        "--log-level",
        default=os.getenv("DPLUS_SIM_LOG", "INFO"),
        help="Logging-Level (z. B. DEBUG, INFO)",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
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
