"""Tests für Debug-Einschränkungen von DPlusSim."""

import asyncio

import pytest

from dplus_sim import (
    DEFAULT_SETTINGS,
    DEV_FEATURE_FLAG_ENV_VAR,
    DPlusController,
    DPlusSimService,
    RELAY_FUNCTION_NEUTRAL,
    RELAY_FUNCTION_TAG,
    Variant,
    build_arg_parser,
    validate_runtime_options,
)


class DummyController:
    def __init__(self) -> None:
        self.injected: list[float] = []

    async def inject_voltage(self, voltage: float):
        self.injected.append(voltage)
        return {"voltage": voltage}


def test_inject_voltage_sample_requires_debug_flag(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv(DEV_FEATURE_FLAG_ENV_VAR, raising=False)
    controller = DummyController()
    service = DPlusSimService(controller, lambda: None)
    with pytest.raises(RuntimeError):
        asyncio.run(service.InjectVoltageSample(1.0))
    assert controller.injected == []


def test_inject_voltage_sample_requires_development_flag(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv(DEV_FEATURE_FLAG_ENV_VAR, raising=False)
    controller = DummyController()
    service = DPlusSimService(controller, lambda: None, debug_enabled=True)
    with pytest.raises(RuntimeError):
        asyncio.run(service.InjectVoltageSample(1.0))
    assert controller.injected == []


def test_inject_voltage_sample_allowed_with_development_flag(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(DEV_FEATURE_FLAG_ENV_VAR, "1")
    controller = DummyController()
    service = DPlusSimService(controller, lambda: None, debug_enabled=True)
    result = asyncio.run(service.InjectVoltageSample(2.5))
    assert controller.injected == [pytest.approx(2.5)]
    voltage_value = result["voltage"]
    if Variant is not None:  # type: ignore[truthy-bool]
        voltage_value = getattr(voltage_value, "value", voltage_value)
    assert voltage_value == pytest.approx(2.5)


def test_waveform_simulation_requires_debug_flag(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv(DEV_FEATURE_FLAG_ENV_VAR, raising=False)
    parser = build_arg_parser()
    args = parser.parse_args(["--simulate-waveform", "1.0"])
    with pytest.raises(SystemExit):
        validate_runtime_options(args, parser)


def test_waveform_simulation_requires_development_flag(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv(DEV_FEATURE_FLAG_ENV_VAR, raising=False)
    parser = build_arg_parser()
    args = parser.parse_args(["--simulate-waveform", "1.0", "--enable-debug"])
    with pytest.raises(SystemExit):
        validate_runtime_options(args, parser)


def test_waveform_simulation_allowed_with_development_flag(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(DEV_FEATURE_FLAG_ENV_VAR, "true")
    parser = build_arg_parser()
    args = parser.parse_args(["--simulate-waveform", "1.0", "--enable-debug"])
    validate_runtime_options(args, parser)
    assert args.enable_debug


def test_stop_and_shutdown_release_assigned_relay_channel():
    class DummyMonitor:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        def set_callback(self, _callback):
            return None

        async def set_function(self, channel: str, function: str) -> None:
            self.calls.append((channel, function))

    async def scenario() -> None:
        relay_channel = DEFAULT_SETTINGS["relay_channel"]

        controller = DPlusController(DEFAULT_SETTINGS, use_gpio=False)
        monitor = DummyMonitor()
        controller.attach_relay_function_monitor(monitor)
        await controller.initialize_relay_function_assignments(
            {relay_channel: RELAY_FUNCTION_TAG}
        )
        await controller.start()
        await asyncio.sleep(0)
        await controller.stop()
        assert (relay_channel, RELAY_FUNCTION_NEUTRAL) in monitor.calls
        await controller.shutdown()

        controller_shutdown = DPlusController(DEFAULT_SETTINGS, use_gpio=False)
        monitor_shutdown = DummyMonitor()
        controller_shutdown.attach_relay_function_monitor(monitor_shutdown)
        await controller_shutdown.initialize_relay_function_assignments(
            {relay_channel: RELAY_FUNCTION_TAG}
        )
        await controller_shutdown.shutdown()
        assert monitor_shutdown.calls == [
            (relay_channel, RELAY_FUNCTION_NEUTRAL)
        ]

    asyncio.run(scenario())
