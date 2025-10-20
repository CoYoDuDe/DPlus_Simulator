from __future__ import annotations

import asyncio
import argparse
import logging
import types
from typing import List

import pytest

import dplus_sim
from dplus_sim import (
    Bmv712DetectionError,
    Bmv712ServiceInfo,
    DEFAULT_SETTINGS,
    DPlusController,
    VoltageSourceError,
)


def test_controller_initial_state_unavailable() -> None:
    async def scenario() -> None:
        controller = DPlusController(DEFAULT_SETTINGS, use_gpio=False)
        status = controller.get_status()
        assert status["voltage_source_state"] == "unavailable"
        assert status["voltage_source_message"] == "Keine Spannungsquelle verfügbar"
        assert status["voltage_source_available"] is False
        await controller.shutdown()

    asyncio.run(scenario())


def test_set_voltage_provider_error_marks_state() -> None:
    async def scenario() -> None:
        controller = DPlusController(DEFAULT_SETTINGS, use_gpio=False)
        await controller.set_voltage_provider(
            None,
            "unavailable",
            source_info={
                "state": "error",
                "message": "Testfehler",
                "service": "com.victronenergy.test",
                "path": "/Dc/0/Voltage",
                "bus": "system",
                "available": False,
            },
        )
        status = controller.get_status()
        assert status["voltage_source_state"] == "error"
        assert status["voltage_source_message"] == "Testfehler"
        assert status["voltage_source_service"] == "com.victronenergy.test"
        assert status["voltage_source_path"] == "/Dc/0/Voltage"
        assert status["voltage_source_available"] is False
        await controller.shutdown()

    asyncio.run(scenario())


def test_run_async_aborts_without_dbus(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def scenario() -> None:
        created: List[DPlusController] = []

        original_controller = dplus_sim.DPlusController

        class TrackingController(original_controller):  # type: ignore[misc]
            def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
                super().__init__(*args, **kwargs)
                created.append(self)
                self.recorded_states: List[dict[str, object]] = []

            async def set_voltage_provider(  # type: ignore[override]
                self,
                provider,
                source_label=None,
                *,
                source_info=None,
            ) -> None:
                await super().set_voltage_provider(provider, source_label, source_info=source_info)
                self.recorded_states.append(self.get_status())

        monkeypatch.setattr(dplus_sim, "DPlusController", TrackingController)

        args = argparse.Namespace(
            bus=None,
            no_dbus=True,
            dry_run=True,
            simulate_waveform=0.0,
            log_level="INFO",
        )
        caplog.set_level(logging.ERROR, logger="DPlusSim")

        await dplus_sim.run_async(args)

        assert created, "Controller wurde nicht erzeugt"
        states = created[0].recorded_states
        assert any(state["voltage_source_state"] == "unavailable" for state in states)
        assert any(
            "D-Bus-Unterstützung nicht verfügbar" in record.getMessage()
            for record in caplog.records
        )

    asyncio.run(scenario())


def test_run_async_aborts_on_voltage_reader_failure(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def scenario() -> None:
        created: List[DPlusController] = []

        original_controller = dplus_sim.DPlusController

        class TrackingController(original_controller):  # type: ignore[misc]
            def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
                super().__init__(*args, **kwargs)
                created.append(self)
                self.recorded_states: List[dict[str, object]] = []

            async def set_voltage_provider(  # type: ignore[override]
                self,
                provider,
                source_label=None,
                *,
                source_info=None,
            ) -> None:
                await super().set_voltage_provider(provider, source_label, source_info=source_info)
                self.recorded_states.append(self.get_status())

        monkeypatch.setattr(dplus_sim, "DPlusController", TrackingController)

        class FailingReader:
            def __init__(self, service_name: str, object_path: str, bus_choice: str) -> None:
                self.service_name = service_name
                self.object_path = object_path
                self.bus_choice = bus_choice
                self.description = f"dbus:{service_name}{object_path}"

            @property
            def metadata(self) -> dict[str, str]:
                return {
                    "service": self.service_name,
                    "path": self.object_path,
                    "bus": self.bus_choice,
                    "mode": "dbus",
                }

            async def initialize(self) -> None:
                raise VoltageSourceError("boom")

            async def close(self) -> None:  # pragma: no cover - defensive
                return None

        monkeypatch.setattr(dplus_sim, "DbusVoltageReader", FailingReader)

        class DummyMessageBus:
            def __init__(self, *args, **kwargs) -> None:
                pass

            async def connect(self) -> "DummyMessageBus":
                return self

            def add_message_handler(self, _handler) -> None:
                return None

            def remove_message_handler(self, _handler) -> None:
                return None

            async def call(self, *args, **kwargs):
                class _Reply:
                    body: list[object] = []
                    message_type = 1

                return _Reply()

            def export(self, *args, **kwargs) -> None:
                return None

            async def request_name(self, *args, **kwargs) -> None:
                return None

            def disconnect(self) -> None:
                return None

            async def wait_for_disconnect(self) -> None:
                return None

        class DummyMonitor:
            def __init__(self, _bus) -> None:
                pass

            def set_callback(self, _cb) -> None:
                return None

            async def start(self) -> dict[str, str]:
                return {}

            async def stop(self) -> None:
                return None

        class DummySettingsBridge:
            def __init__(self, _bus, _definitions, callback=None, service_name="") -> None:
                self._callback = callback

            def set_callback(self, callback) -> None:
                self._callback = callback

            async def start(self) -> dict[str, object]:
                return {}

            async def write_settings(self, _updates) -> None:
                return None

            async def stop(self) -> None:
                return None

        class DummyDbusSettingsAdapter:
            def __init__(self, bridge) -> None:
                self._bridge = bridge

            async def start(self) -> dict[str, object]:
                return await self._bridge.start()

            async def apply(self, updates) -> None:
                await self._bridge.write_settings(updates)

            async def stop(self) -> None:
                await self._bridge.stop()

            def set_callback(self, callback) -> None:
                self._bridge.set_callback(lambda key, value: callback(key, value))

        monkeypatch.setattr(dplus_sim, "BusType", types.SimpleNamespace(SYSTEM="system", SESSION="session"))
        monkeypatch.setattr(dplus_sim, "Message", object)
        monkeypatch.setattr(dplus_sim, "MessageType", types.SimpleNamespace(METHOD_RETURN=1))
        monkeypatch.setattr(dplus_sim, "MessageBus", DummyMessageBus)
        monkeypatch.setattr(dplus_sim, "RelayFunctionMonitor", DummyMonitor)
        monkeypatch.setattr(dplus_sim, "SettingsBridge", DummySettingsBridge)
        monkeypatch.setattr(dplus_sim, "DbusNextSettingsAdapter", DummyDbusSettingsAdapter)

        async def fake_resolver(bus_choice: str) -> Bmv712ServiceInfo:
            return Bmv712ServiceInfo(
                service_name="com.victronenergy.battery.fake",
                object_path="/Dc/0/Voltage",
                bus_choice=bus_choice,
                product_id=0xA381,
                product_name="BMV-712 Smart",
            )

        monkeypatch.setattr(dplus_sim, "resolve_bmv712_service", fake_resolver)

        args = argparse.Namespace(
            bus=None,
            no_dbus=False,
            dry_run=True,
            simulate_waveform=0.0,
            log_level="INFO",
        )
        caplog.set_level(logging.ERROR, logger="DPlusSim")

        await dplus_sim.run_async(args)

        assert created, "Controller wurde nicht erzeugt"
        states = created[0].recorded_states
        assert any(state["voltage_source_state"] == "error" for state in states)
        assert any(
            "Initiale Verbindung zur Spannungsquelle fehlgeschlagen" in record.getMessage()
            for record in caplog.records
        )

    asyncio.run(scenario())


def test_run_async_aborts_when_bmv712_missing(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def scenario() -> None:
        created: List[DPlusController] = []

        original_controller = dplus_sim.DPlusController

        class TrackingController(original_controller):  # type: ignore[misc]
            def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
                super().__init__(*args, **kwargs)
                created.append(self)
                self.recorded_states: List[dict[str, object]] = []

            async def set_voltage_provider(  # type: ignore[override]
                self,
                provider,
                source_label=None,
                *,
                source_info=None,
            ) -> None:
                await super().set_voltage_provider(provider, source_label, source_info=source_info)
                self.recorded_states.append(self.get_status())

        monkeypatch.setattr(dplus_sim, "DPlusController", TrackingController)

        class DummyMessageBus:
            def __init__(self, *args, **kwargs) -> None:
                pass

            async def connect(self) -> "DummyMessageBus":
                return self

            def add_message_handler(self, _handler) -> None:
                return None

            def remove_message_handler(self, _handler) -> None:
                return None

            async def call(self, *args, **kwargs):
                class _Reply:
                    body: list[object] = []
                    message_type = 1

                return _Reply()

            def export(self, *args, **kwargs) -> None:
                return None

            async def request_name(self, *args, **kwargs) -> None:
                return None

            def disconnect(self) -> None:
                return None

            async def wait_for_disconnect(self) -> None:
                return None

        class DummySettingsBridge:
            def __init__(self, *args, **kwargs) -> None:
                pass

            async def start(self) -> dict[str, object]:
                return {}

            async def write_settings(self, _updates) -> None:
                return None

            async def stop(self) -> None:
                return None

            def set_callback(self, _callback) -> None:
                return None

        class DummyDbusSettingsAdapter:
            def __init__(self, bridge) -> None:
                self._bridge = bridge

            async def start(self) -> dict[str, object]:
                return await self._bridge.start()

            async def apply(self, _updates) -> None:
                return None

            async def stop(self) -> None:
                return None

            def set_callback(self, _callback) -> None:
                return None

        monkeypatch.setattr(dplus_sim, "BusType", types.SimpleNamespace(SYSTEM="system", SESSION="session"))
        monkeypatch.setattr(dplus_sim, "Message", object)
        monkeypatch.setattr(dplus_sim, "MessageType", types.SimpleNamespace(METHOD_RETURN=1))
        monkeypatch.setattr(dplus_sim, "MessageBus", DummyMessageBus)
        monkeypatch.setattr(dplus_sim, "SettingsBridge", DummySettingsBridge)
        monkeypatch.setattr(dplus_sim, "DbusNextSettingsAdapter", DummyDbusSettingsAdapter)

        async def failing_resolver(_bus_choice: str) -> Bmv712ServiceInfo:
            raise Bmv712DetectionError("kein Gerät gefunden")

        monkeypatch.setattr(dplus_sim, "resolve_bmv712_service", failing_resolver)

        args = argparse.Namespace(
            bus=None,
            no_dbus=False,
            dry_run=True,
            simulate_waveform=0.0,
            log_level="INFO",
        )

        caplog.set_level(logging.ERROR, logger="DPlusSim")

        await dplus_sim.run_async(args)

        assert created, "Controller wurde nicht erzeugt"
        states = created[0].recorded_states
        assert any(state["voltage_source_state"] == "not-found" for state in states)
        assert any(
            "BMV712-Dienst konnte nicht gefunden werden" in record.getMessage()
            for record in caplog.records
        )

    asyncio.run(scenario())
