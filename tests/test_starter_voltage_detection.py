from __future__ import annotations

import asyncio
import types
from pathlib import Path
from typing import Any

import pytest


import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import dplus_sim
from dplus_sim import VoltageServiceDiscoveryError


class DummyMessage:
    def __init__(self, destination: str, path: str, interface: str, member: str, **_kwargs: Any) -> None:
        self.destination = destination
        self.path = path
        self.interface = interface
        self.member = member


class DummyReply:
    def __init__(self, body: Any) -> None:
        self.body = body
        self.message_type = 1


class SystemFirstBus:
    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        self.calls: list[tuple[str, str, str]] = []

    async def connect(self) -> "SystemFirstBus":
        return self

    async def call(self, message: DummyMessage) -> DummyReply:
        self.calls.append((message.destination, message.path, message.member))
        if message.member == "ListNames":
            return DummyReply([["com.victronenergy.battery.fake"]])
        if (
            message.destination == dplus_sim.SYSTEM_SERVICE_NAME
            and message.path == dplus_sim.STARTER_VOLTAGE_PATH
        ):
            return DummyReply([12.5])
        raise AssertionError(f"Unexpected call: {(message.destination, message.path, message.member)}")

    def disconnect(self) -> None:
        return None

    async def wait_for_disconnect(self) -> None:
        return None


class BatteryFallbackBus(SystemFirstBus):
    async def call(self, message: DummyMessage) -> DummyReply:  # type: ignore[override]
        if (
            message.destination == dplus_sim.SYSTEM_SERVICE_NAME
            and message.path == dplus_sim.STARTER_VOLTAGE_PATH
        ):
            raise RuntimeError("system missing")
        if message.member == "ListNames":
            return DummyReply([["com.victronenergy.battery.preferred", "com.victronenergy.battery.other"]])
        if message.path == dplus_sim.STARTER_VOLTAGE_PATH:
            return DummyReply([13.2])
        return await super().call(message)


class FailingBus(SystemFirstBus):
    async def call(self, message: DummyMessage) -> DummyReply:  # type: ignore[override]
        if message.member == "ListNames":
            return DummyReply([["com.victronenergy.battery.none"]])
        if message.path == dplus_sim.STARTER_VOLTAGE_PATH:
            return DummyReply([None])
        return await super().call(message)


def test_resolve_starter_voltage_service_prefers_system(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        monkeypatch.setattr(dplus_sim, "BusType", types.SimpleNamespace(SYSTEM="system", SESSION="session"))
        monkeypatch.setattr(dplus_sim, "MessageType", types.SimpleNamespace(METHOD_RETURN=1))
        monkeypatch.setattr(dplus_sim, "Message", DummyMessage)
        monkeypatch.setattr(dplus_sim, "MessageBus", SystemFirstBus)

        info = await dplus_sim.resolve_starter_voltage_service("system")

        assert info.service_name == dplus_sim.SYSTEM_SERVICE_NAME
        assert info.object_path == dplus_sim.STARTER_VOLTAGE_PATH

    asyncio.run(scenario())


def test_resolve_starter_voltage_service_checks_battery(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        monkeypatch.setattr(dplus_sim, "BusType", types.SimpleNamespace(SYSTEM="system", SESSION="session"))
        monkeypatch.setattr(dplus_sim, "MessageType", types.SimpleNamespace(METHOD_RETURN=1))
        monkeypatch.setattr(dplus_sim, "Message", DummyMessage)
        monkeypatch.setattr(dplus_sim, "MessageBus", BatteryFallbackBus)

        info = await dplus_sim.resolve_starter_voltage_service("system")

        assert info.service_name == "com.victronenergy.battery.preferred"
        assert info.object_path == dplus_sim.STARTER_VOLTAGE_PATH

    asyncio.run(scenario())


def test_resolve_starter_voltage_service_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        monkeypatch.setattr(dplus_sim, "BusType", types.SimpleNamespace(SYSTEM="system", SESSION="session"))
        monkeypatch.setattr(dplus_sim, "MessageType", types.SimpleNamespace(METHOD_RETURN=1))
        monkeypatch.setattr(dplus_sim, "Message", DummyMessage)
        monkeypatch.setattr(dplus_sim, "MessageBus", FailingBus)

        with pytest.raises(VoltageServiceDiscoveryError):
            await dplus_sim.resolve_starter_voltage_service("system")

    asyncio.run(scenario())

