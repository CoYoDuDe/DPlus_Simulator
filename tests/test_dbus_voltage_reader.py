import asyncio
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

import dplus_sim  # noqa: E402


class _AsyncDisconnectBus:
    def __init__(self) -> None:
        self.disconnect_called = False
        self.disconnect_awaited = False
        self.wait_called = False

    async def call(self, _message: object) -> object:
        raise RuntimeError("boom")

    def disconnect(self) -> asyncio.Future[None]:
        async def _coro() -> None:
            self.disconnect_called = True
            await asyncio.sleep(0)
            self.disconnect_awaited = True

        return asyncio.ensure_future(_coro())

    async def wait_for_disconnect(self) -> None:
        self.wait_called = True


def test_disconnect_handles_async_disconnect() -> None:
    class _FakeMessage:
        def __init__(self, *args: object, **kwargs: object) -> None:  # noqa: D401 - Dummy
            """Einfache Attrappen-Implementierung für dbus_next.Message."""

    original_message = dplus_sim.Message
    dplus_sim.Message = _FakeMessage

    async def _run_scenario() -> None:
        reader = dplus_sim.DbusVoltageReader("com.example.service", "/Ac/Voltage")
        reader._use_vedbus = False
        fake_bus = _AsyncDisconnectBus()
        reader._bus = fake_bus

        async def _noop() -> None:
            return None

        reader._ensure_bus_locked = _noop  # type: ignore[attr-defined]

        with pytest.raises(dplus_sim.VoltageSourceError):
            await reader._read_voltage_via_dbusnext_locked()

        assert reader._bus is None
        assert fake_bus.disconnect_called is True
        assert fake_bus.disconnect_awaited is True
        assert fake_bus.wait_called is True

    try:
        asyncio.run(_run_scenario())
    finally:
        dplus_sim.Message = original_message
