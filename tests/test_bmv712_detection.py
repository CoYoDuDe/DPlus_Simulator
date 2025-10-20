import asyncio
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import dplus_sim
from dplus_sim import Bmv712DetectionError


class DummyMessage:
    def __init__(self, destination: str, path: str, interface: str, member: str, **_kwargs) -> None:
        self.destination = destination
        self.path = path
        self.interface = interface
        self.member = member


class DummyReply:
    def __init__(self, body):
        self.body = body
        self.message_type = 1


class SuccessfulBus:
    def __init__(self, *args, **kwargs) -> None:
        self._calls = []

    async def connect(self) -> "SuccessfulBus":
        return self

    async def call(self, message: DummyMessage) -> DummyReply:
        self._calls.append((message.destination, message.path, message.member))
        if message.member == "ListNames":
            return DummyReply([["com.victronenergy.battery.fake", "com.victronenergy.battery.other"]])
        if message.path == "/ProductId":
            return DummyReply([0xA381])
        if message.path == "/ProductName":
            return DummyReply(["BMV-712 Smart"])
        if message.path == "/Dc/0/Voltage":
            return DummyReply([12.6])
        raise AssertionError(f"Unexpected call: {message.path}")

    def disconnect(self) -> None:
        return None

    async def wait_for_disconnect(self) -> None:
        return None


class FailingBus(SuccessfulBus):
    async def call(self, message: DummyMessage) -> DummyReply:  # type: ignore[override]
        if message.member == "ListNames":
            return DummyReply([["com.victronenergy.battery.unknown"]])
        if message.path == "/ProductId":
            return DummyReply([0x9999])
        if message.path == "/ProductName":
            return DummyReply(["Not a BMV"])
        if message.path == "/Dc/0/Voltage":
            return DummyReply([None])
        return await super().call(message)


def test_resolve_bmv712_service_success(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        monkeypatch.setattr(dplus_sim, "BusType", types.SimpleNamespace(SYSTEM="system", SESSION="session"))
        monkeypatch.setattr(dplus_sim, "MessageType", types.SimpleNamespace(METHOD_RETURN=1))
        monkeypatch.setattr(dplus_sim, "Message", DummyMessage)
        monkeypatch.setattr(dplus_sim, "MessageBus", SuccessfulBus)

        info = await dplus_sim.resolve_bmv712_service("system")

        assert info.service_name == "com.victronenergy.battery.fake"
        assert info.object_path == dplus_sim.BMV712_VOLTAGE_PATH
        assert info.product_id == 0xA381
        assert "BMV" in info.product_name

    asyncio.run(scenario())


def test_resolve_bmv712_service_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        monkeypatch.setattr(dplus_sim, "BusType", types.SimpleNamespace(SYSTEM="system", SESSION="session"))
        monkeypatch.setattr(dplus_sim, "MessageType", types.SimpleNamespace(METHOD_RETURN=1))
        monkeypatch.setattr(dplus_sim, "Message", DummyMessage)
        monkeypatch.setattr(dplus_sim, "MessageBus", FailingBus)

        with pytest.raises(Bmv712DetectionError):
            await dplus_sim.resolve_bmv712_service("system")

    asyncio.run(scenario())
