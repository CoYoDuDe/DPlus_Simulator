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
import json
import logging
import os
import signal
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional

import math

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


SETTINGS_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "gpio_pin": {
        "path": "/Settings/Devices/DPlusSim/GpioPin",
        "type": "i",
        "default": 17,
        "description": "GPIO-Pin, der die simulierte D+-Leitung schaltet.",
    },
    "target_voltage": {
        "path": "/Settings/Devices/DPlusSim/TargetVoltage",
        "type": "d",
        "default": 3.3,
        "description": "Zielspannung in Volt, die durch die Simulation angestrebt wird.",
    },
    "hysteresis": {
        "path": "/Settings/Devices/DPlusSim/Hysteresis",
        "type": "d",
        "default": 0.1,
        "description": "Hystereseband in Volt, bevor der GPIO neu geschaltet wird.",
    },
    "activation_delay_seconds": {
        "path": "/Settings/Devices/DPlusSim/ActivationDelaySeconds",
        "type": "d",
        "default": 2.0,
        "description": "Verzögerung in Sekunden, bevor der GPIO bei steigender Spannung eingeschaltet wird.",
    },
    "deactivation_delay_seconds": {
        "path": "/Settings/Devices/DPlusSim/DeactivationDelaySeconds",
        "type": "d",
        "default": 5.0,
        "description": "Verzögerung in Sekunden, bevor der GPIO bei fallender Spannung ausgeschaltet wird.",
    },
    "status_publish_interval": {
        "path": "/Settings/Devices/DPlusSim/StatusPublishInterval",
        "type": "d",
        "default": 2.0,
        "description": "Intervall in Sekunden zur Veröffentlichung des Status über D-Bus-Signale.",
    },
    "dbus_bus": {
        "path": "/Settings/Devices/DPlusSim/DbusBus",
        "type": "s",
        "default": "system",
        "description": "Zu verwendender D-Bus (system oder session).",
    },
    "service_path": {
        "path": "/Settings/Devices/DPlusSim/ServicePath",
        "type": "s",
        "default": "com.victronenergy.battery",
        "description": "D-Bus-Service, aus dem die Starterbatterie-Spannung gelesen wird.",
    },
    "voltage_path": {
        "path": "/Settings/Devices/DPlusSim/VoltagePath",
        "type": "s",
        "default": "/Dc/0/Voltage",
        "description": "Objektpfad des Spannungswertes innerhalb des Service.",
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
        async with self._lock:
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
                raise VoltageSourceError(f"Antwort konnte nicht in eine Zahl umgewandelt werden: {value!r}") from exc

    async def _disconnect_locked(self) -> None:
        if self._bus is None:
            return
        disconnect = getattr(self._bus, "disconnect", None)
        if callable(disconnect):
            with contextlib.suppress(Exception):
                disconnect()
        wait_for_disconnect = getattr(self._bus, "wait_for_disconnect", None)
        if callable(wait_for_disconnect):
            with contextlib.suppress(Exception):
                await wait_for_disconnect()
        self._bus = None

    async def close(self) -> None:
        async with self._lock:
            await self._disconnect_locked()


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

    def set_callback(
        self, callback: Optional[Callable[[str, Any], Awaitable[None] | None]]
    ) -> None:
        self._callback = callback

    async def start(self) -> Dict[str, Any]:
        if Message is None:
            raise RuntimeError("D-Bus-Unterstützung ist nicht verfügbar")
        self._loop = asyncio.get_running_loop()
        await self._register_match_rule()
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
        if getattr(message, "sender", None) != self._service_name:
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
        if self._enabled:
            _RPiGPIO.cleanup(self._pin)
            _RPiGPIO.setup(new_pin, _RPiGPIO.OUT)
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


@dataclass
class HysteresisWindow:
    target: float
    hysteresis: float
    activation_delay: float
    deactivation_delay: float
    state: bool = False
    pending_state: Optional[bool] = None
    deadline: Optional[float] = None

    def configure(
        self,
        target: float,
        hysteresis: float,
        activation_delay: float,
        deactivation_delay: float,
    ) -> None:
        self.target = target
        self.hysteresis = hysteresis
        self.activation_delay = activation_delay
        self.deactivation_delay = deactivation_delay
        self.pending_state = None
        self.deadline = None

    def evaluate(self, voltage: float, now: float) -> Dict[str, Any]:
        upper = self.target + self.hysteresis / 2.0
        lower = self.target - self.hysteresis / 2.0
        changed = False

        if self.state:
            if voltage <= lower:
                if self.pending_state is not False:
                    self.pending_state = False
                    self.deadline = now + self.deactivation_delay
                elif self.deadline is not None and now >= self.deadline:
                    self.state = False
                    self.pending_state = None
                    self.deadline = None
                    changed = True
            else:
                if self.pending_state is False:
                    self.pending_state = None
                    self.deadline = None
        else:
            if voltage >= upper:
                if self.pending_state is not True:
                    self.pending_state = True
                    self.deadline = now + self.activation_delay
                elif self.deadline is not None and now >= self.deadline:
                    self.state = True
                    self.pending_state = None
                    self.deadline = None
                    changed = True
            else:
                if self.pending_state is True:
                    self.pending_state = None
                    self.deadline = None

        return {
            "state": self.state,
            "pending_state": self.pending_state,
            "deadline": self.deadline,
            "changed": changed,
            "upper_threshold": upper,
            "lower_threshold": lower,
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
    pending_state: Optional[bool] = None
    deadline: Optional[float] = None
    timestamp: float = field(default_factory=lambda: time.time())
    voltage_source: str = "manual"
    voltage_source_state: str = "manual"
    voltage_source_message: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "running": self.running,
            "voltage": self.voltage,
            "gpio_state": self.gpio_state,
            "target_voltage": self.target_voltage,
            "hysteresis": self.hysteresis,
            "activation_delay_seconds": self.activation_delay_seconds,
            "deactivation_delay_seconds": self.deactivation_delay_seconds,
            "pending_state": self.pending_state if self.pending_state is not None else "none",
            "deadline": self.deadline or 0.0,
            "timestamp": self.timestamp,
            "voltage_source": self.voltage_source,
            "voltage_source_state": self.voltage_source_state,
            "voltage_source_message": self.voltage_source_message,
        }


class DPlusController:
    def __init__(self, settings: Dict[str, Any], use_gpio: bool = True) -> None:
        self._logger = logging.getLogger(self.__class__.__name__)
        self._settings = DEFAULT_SETTINGS.copy()
        self._settings.update(settings)
        self._gpio = GPIOController(self._settings["gpio_pin"], enabled=use_gpio)
        self._hysteresis = HysteresisWindow(
            target=self._settings["target_voltage"],
            hysteresis=self._settings["hysteresis"],
            activation_delay=self._settings["activation_delay_seconds"],
            deactivation_delay=self._settings["deactivation_delay_seconds"],
        )
        self._status = SimulatorStatus(
            running=False,
            voltage=0.0,
            gpio_state=False,
            target_voltage=self._settings["target_voltage"],
            hysteresis=self._settings["hysteresis"],
            activation_delay_seconds=self._settings["activation_delay_seconds"],
            deactivation_delay_seconds=self._settings["deactivation_delay_seconds"],
        )
        self._voltage = 0.0
        self._loop_task: Optional[asyncio.Task[None]] = None
        self._running = False
        self._status_callback: Optional[StatusCallback] = None
        self._lock = asyncio.Lock()
        self._voltage_provider: Optional[VoltageProvider] = None
        self._voltage_source_label = "manual"
        self._status.voltage_source = self._voltage_source_label

    def set_status_callback(self, callback: Optional[StatusCallback]) -> None:
        self._status_callback = callback

    async def set_voltage_provider(
        self,
        provider: Optional[VoltageProvider],
        source_label: Optional[str] = None,
    ) -> None:
        async with self._lock:
            self._voltage_provider = provider
            if source_label is not None:
                self._voltage_source_label = source_label
            elif provider is None:
                self._voltage_source_label = "manual"
            if provider is None:
                self._status.voltage_source_state = "manual"
                self._status.voltage_source_message = ""
            else:
                self._status.voltage_source_state = "initializing"
                self._status.voltage_source_message = ""
            self._status.voltage_source = self._voltage_source_label
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
            self._hysteresis.configure(
                target=self._settings["target_voltage"],
                hysteresis=self._settings["hysteresis"],
                activation_delay=self._settings["activation_delay_seconds"],
                deactivation_delay=self._settings["deactivation_delay_seconds"],
            )
            if "gpio_pin" in new_settings:
                self._gpio.reconfigure(int(self._settings["gpio_pin"]))
            self._status.target_voltage = self._settings["target_voltage"]
            self._status.hysteresis = self._settings["hysteresis"]
            self._status.activation_delay_seconds = self._settings["activation_delay_seconds"]
            self._status.deactivation_delay_seconds = self._settings["deactivation_delay_seconds"]
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
                    if provider is None:
                        self._status.voltage_source_state = "manual"
                        self._status.voltage_source_message = ""
                    elif provider_error is not None:
                        self._status.voltage_source_state = "error"
                        self._status.voltage_source_message = str(provider_error)
                    else:
                        self._status.voltage_source_state = provider_state
                        self._status.voltage_source_message = ""
                        if new_voltage is not None:
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
        hysteresis_state = self._hysteresis.evaluate(self._voltage, now)
        if hysteresis_state["changed"]:
            self._logger.info(
                "GPIO-Status wechselt zu %s (Spannung %.3f V)",
                hysteresis_state["state"],
                self._voltage,
            )
        self._gpio.write(hysteresis_state["state"])
        self._status.gpio_state = self._gpio.read()
        self._status.voltage = self._voltage
        self._status.pending_state = hysteresis_state["pending_state"]
        self._status.deadline = hysteresis_state["deadline"] or 0.0
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
    ) -> None:
        super().__init__("com.coyodude.dplussim")
        self._controller = controller
        self._shutdown_callback = shutdown_callback

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


def load_settings(path: Optional[Path]) -> Dict[str, Any]:
    settings = DEFAULT_SETTINGS.copy()
    if path and path.exists():
        with path.open("r", encoding="utf-8") as handle:
            file_settings = json.load(handle)
        settings.update(file_settings)
    return settings


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


async def run_async(args: argparse.Namespace) -> None:
    config_path = Path(args.config) if args.config else None
    base_settings = load_settings(config_path)

    settings_bus: Optional[MessageBus] = None
    settings_bridge: Optional[SettingsBridge] = None
    settings_overrides: Dict[str, Any] = {}
    if (
        BusType is not None
        and Message is not None
        and not args.no_dbus
    ):
        try:
            settings_bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
            settings_bridge = SettingsBridge(settings_bus, SETTINGS_DEFINITIONS)
            settings_overrides = await settings_bridge.start()
        except Exception as exc:  # pragma: no-cover - Laufzeitabhängig
            logging.getLogger("DPlusSim").warning(
                "Konnte Einstellungen nicht mit com.victronenergy.settings synchronisieren: %s",
                exc,
            )
            if settings_bus is not None:
                disconnect = getattr(settings_bus, "disconnect", None)
                if callable(disconnect):
                    disconnect()
            settings_bridge = None
            settings_bus = None
            settings_overrides = {}

    merged_settings = base_settings.copy()
    merged_settings.update(settings_overrides)
    if args.bus:
        merged_settings["dbus_bus"] = args.bus

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
            await controller.set_voltage_provider(
                voltage_reader.read_voltage,
                voltage_reader.description,
            )
            logging.getLogger("DPlusSim").info(
                "Externe Spannungsquelle aktiviert: %s",
                voltage_reader.description,
            )
        else:
            await controller.set_voltage_provider(None, "manual")
            logging.getLogger("DPlusSim").info(
                "Keine externe Spannungsquelle konfiguriert – Spannung muss manuell vorgegeben werden",
            )
    else:
        await controller.set_voltage_provider(None, "manual")
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

    if settings_bridge is not None:
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
                    await controller.set_voltage_provider(None, "manual")
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
                    await controller.set_voltage_provider(None, "manual")
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
                await controller.set_voltage_provider(
                    voltage_reader.read_voltage,
                    voltage_reader.description,
                )
                logging.getLogger("DPlusSim").info(
                    "Externe Spannungsquelle aktualisiert: %s",
                    voltage_reader.description,
                )
                return

        settings_bridge.set_callback(handle_setting_update)

    if config_path and args.write_defaults:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with config_path.open("w", encoding="utf-8") as handle:
            json.dump(controller.get_settings(), handle, indent=2, ensure_ascii=False)

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
            service = DPlusSimService(controller, request_shutdown)
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

    if args.simulate_waveform:
        asyncio.create_task(simulate_waveform(controller, args.simulate_waveform))

    await shutdown_event.wait()
    await controller.set_voltage_provider(None, "manual")
    await controller.shutdown()
    if voltage_reader is not None:
        await voltage_reader.close()
    if bus is not None:
        await bus.wait_for_disconnect()
    if settings_bridge is not None:
        await settings_bridge.stop()
    if settings_bus is not None:
        disconnect = getattr(settings_bus, "disconnect", None)
        if callable(disconnect):
            disconnect()
        with contextlib.suppress(Exception):
            await settings_bus.wait_for_disconnect()


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
    parser.add_argument("--config", help="Pfad zur Einstellungsdatei", default=None)
    parser.add_argument("--bus", choices=("system", "session"), help="Zu verwendender D-Bus", default=None)
    parser.add_argument("--dry-run", action="store_true", help="GPIO-Befehle nicht an Hardware weiterreichen")
    parser.add_argument(
        "--no-dbus", action="store_true", help="D-Bus-Registrierung deaktivieren, auch wenn verfügbar"
    )
    parser.add_argument(
        "--write-defaults",
        action="store_true",
        help="Aktuelle Einstellungen in die angegebene Datei schreiben",
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
