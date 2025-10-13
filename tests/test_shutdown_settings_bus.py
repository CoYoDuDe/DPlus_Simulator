import argparse
import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

import dplus_sim  # noqa: E402


def _prepare_environment(monkeypatch):
    callbacks = []

    def fake_install_signal_handlers(_loop, callback):
        callbacks.append(callback)

    monkeypatch.setattr(dplus_sim, "install_signal_handlers", fake_install_signal_handlers)

    class DummyController:
        def __init__(self, settings, use_gpio=True):
            self.settings = dict(settings)
            self.use_gpio = use_gpio
            self._status_callback = None

        async def set_voltage_provider(self, *_args, **_kwargs):
            return None

        def set_status_callback(self, callback):
            self._status_callback = callback

        async def update_settings(self, updates):
            self.settings.update(updates)

        async def start(self):
            return None

        async def shutdown(self):
            return None

    monkeypatch.setattr(dplus_sim, "DPlusController", DummyController)

    class DummyVoltageReader:
        def __init__(self, *_args, **_kwargs):
            self.description = "dummy"
            self.metadata = {}

        async def initialize(self):
            return None

        async def close(self):
            return None

        async def read_voltage(self):
            return 12.34

    monkeypatch.setattr(dplus_sim, "DbusVoltageReader", DummyVoltageReader)

    class DummyService:
        def __init__(self, *_args, **_kwargs):
            pass

        def emit_status(self, _status):
            return None

    monkeypatch.setattr(dplus_sim, "DPlusSimService", DummyService)

    args = argparse.Namespace(
        bus=None,
        dry_run=True,
        no_dbus=False,
        simulate_waveform=0.0,
        log_level="INFO",
    )

    return callbacks, args


def test_settings_bus_disconnect(monkeypatch):
    asyncio.run(_run_settings_bus_disconnect(monkeypatch))


async def _run_settings_bus_disconnect(monkeypatch):
    callbacks, args = _prepare_environment(monkeypatch)

    class DummySettingsAdapter(dplus_sim.BaseSettingsAdapter):
        def __init__(self, bridge):
            super().__init__()
            self.bridge = bridge

        async def start(self):
            return {}

        async def apply(self, _updates):
            return None

        async def stop(self):
            return None

    monkeypatch.setattr(dplus_sim, "DbusNextSettingsAdapter", DummySettingsAdapter)

    class DummyBus:
        def __init__(self, bus_type):
            self.bus_type = bus_type
            self.disconnect_completed = False
            self.wait_called = False

        async def connect(self):
            return self

        def export(self, *_args, **_kwargs):
            return None

        async def request_name(self, *_args, **_kwargs):
            return None

        async def disconnect(self):
            await asyncio.sleep(0)
            self.disconnect_completed = True

        async def wait_for_disconnect(self):
            assert self.disconnect_completed
            self.wait_called = True

    buses = []

    class DummyMessageBus:
        def __init__(self, *, bus_type):
            self._bus = DummyBus(bus_type)
            buses.append(self._bus)

        async def connect(self):
            return self._bus

    monkeypatch.setattr(dplus_sim, "MessageBus", DummyMessageBus)
    monkeypatch.setattr(dplus_sim, "Message", object())

    run_task = asyncio.create_task(dplus_sim.run_async(args))
    while not callbacks:
        await asyncio.sleep(0)
    callbacks[0]()
    await run_task

    assert buses, "Es wurde kein MessageBus initialisiert"
    settings_bus = buses[0]
    assert settings_bus.disconnect_completed, "Disconnect wurde nicht vollständig abgeschlossen"
    assert settings_bus.wait_called, "wait_for_disconnect wurde nicht aufgerufen"


def test_settings_bus_disconnect_async_result(monkeypatch):
    asyncio.run(_run_settings_bus_disconnect_async_result(monkeypatch))


async def _run_settings_bus_disconnect_async_result(monkeypatch):
    callbacks, args = _prepare_environment(monkeypatch)

    class FailingSettingsAdapter(dplus_sim.BaseSettingsAdapter):
        def __init__(self, bridge):
            super().__init__()
            self.bridge = bridge

        async def start(self):
            raise RuntimeError("boom")

        async def apply(self, _updates):
            return None

        async def stop(self):
            return None

    monkeypatch.setattr(dplus_sim, "DbusNextSettingsAdapter", FailingSettingsAdapter)
    monkeypatch.setattr(dplus_sim, "VelibSettingsDevice", None)
    monkeypatch.setattr(dplus_sim, "dbus", None)
    monkeypatch.setattr(dplus_sim, "DBusGMainLoop", None)
    monkeypatch.setattr(dplus_sim, "GLib", None)

    class DummyBus:
        def __init__(self, bus_type):
            self.bus_type = bus_type
            self.disconnect_calls = 0
            self.disconnect_awaits = 0
            self.wait_calls = 0

        async def connect(self):
            return self

        def export(self, *_args, **_kwargs):
            return None

        async def request_name(self, *_args, **_kwargs):
            return None

        def add_message_handler(self, *_args, **_kwargs):
            return None

        def remove_message_handler(self, *_args, **_kwargs):
            return None

        async def call(self, *_args, **_kwargs):
            class DummyReply:
                body = []

            return DummyReply()

        async def disconnect(self):
            self.disconnect_calls += 1
            await asyncio.sleep(0)
            self.disconnect_awaits += 1

        async def wait_for_disconnect(self):
            assert self.disconnect_calls > 0
            assert self.disconnect_awaits == self.disconnect_calls
            self.wait_calls += 1

    buses = []

    class DummyMessageBus:
        def __init__(self, *, bus_type):
            self._bus = DummyBus(bus_type)
            buses.append(self._bus)

        async def connect(self):
            return self._bus

    monkeypatch.setattr(dplus_sim, "MessageBus", DummyMessageBus)
    monkeypatch.setattr(dplus_sim, "Message", object())

    run_task = asyncio.create_task(dplus_sim.run_async(args))
    while not callbacks:
        await asyncio.sleep(0)
    callbacks[0]()
    await run_task

    assert buses, "Es wurde kein MessageBus initialisiert"
    settings_bus = buses[0]
    assert settings_bus.disconnect_calls == 1, "Disconnect wurde nicht aufgerufen"
    assert (
        settings_bus.disconnect_awaits == settings_bus.disconnect_calls
    ), "Disconnect-Coroutine wurde nicht awaited"
    assert settings_bus.wait_calls == 1, "wait_for_disconnect wurde nicht aufgerufen"
