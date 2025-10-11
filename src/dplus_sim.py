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

try:  # pragma: no-cover - optional Abhängigkeiten
    from dbus_next import BusType, Variant
    from dbus_next.aio import MessageBus
    from dbus_next.service import ServiceInterface, method, signal
except Exception:  # pragma: no-cover - Fallback ohne D-Bus
    BusType = None

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


DEFAULT_SETTINGS: Dict[str, Any] = {
    "gpio_pin": 17,
    "target_voltage": 3.3,
    "hysteresis": 0.1,
    "activation_delay_seconds": 2.0,
    "deactivation_delay_seconds": 5.0,
    "dbus_bus": "system",
    "status_publish_interval": 2.0,
}

StatusCallback = Callable[[Dict[str, Any]], Optional[Awaitable[None]]]


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

    def set_status_callback(self, callback: Optional[StatusCallback]) -> None:
        self._status_callback = callback

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
                async with self._lock:
                    self._evaluate_locked()
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
    settings = load_settings(config_path)
    if args.bus:
        settings["dbus_bus"] = args.bus
    controller = DPlusController(settings, use_gpio=not args.dry_run)

    loop = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()

    def request_shutdown() -> None:
        if not shutdown_event.is_set():
            logging.getLogger("DPlusSim").info("Beende Dienst nach Shutdown-Anforderung")
            shutdown_event.set()

    install_signal_handlers(loop, request_shutdown)

    if config_path and args.write_defaults:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with config_path.open("w", encoding="utf-8") as handle:
            json.dump(controller.get_settings(), handle, indent=2, ensure_ascii=False)

    await controller.start()

    bus: Optional[MessageBus] = None
    service: Optional[DPlusSimService] = None
    if BusType is not None and not args.no_dbus:
        try:
            bus_type = BusType.SYSTEM if settings["dbus_bus"] == "system" else BusType.SESSION
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
    await controller.shutdown()
    if bus is not None:
        await bus.wait_for_disconnect()


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
