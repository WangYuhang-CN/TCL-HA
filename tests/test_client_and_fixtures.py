"""Offline checks for the observed API contract and archived device samples."""

from __future__ import annotations

import asyncio
import importlib
import json
from pathlib import Path
import sys
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]

# The pure client and parser can be exercised without installing HA Core.
package = ModuleType("custom_components.tcl_plus")
package.__path__ = [str(ROOT / "custom_components" / "tcl_plus")]
sys.modules.setdefault("custom_components.tcl_plus", package)
api = importlib.import_module("custom_components.tcl_plus.api")
device = importlib.import_module("custom_components.tcl_plus.device")


def fixture(path: str) -> dict[str, Any]:
    return json.loads((ROOT / "tests" / "fixtures" / path).read_text(encoding="utf-8"))


class FakeResponse:
    def __init__(self, payload: dict[str, Any], status: int = 200) -> None:
        self.payload = payload
        self.status = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def json(self, **kwargs):
        return self.payload


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def request(self, method: str, url: str, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)


def test_archived_devices_and_state_edges() -> None:
    devices = device.supported_devices(
        fixture("device-list.minimal.sanitized.json")["response"]["data"]
    )
    assert [(item.kind, item.model) for item in devices] == [
        ("washer", "G100T7R-DIS"),
        ("dryer", "H100T7R-BS"),
    ]
    assert device.boolean_value("0") is False
    assert device.boolean_value("1") is True
    assert device.boolean_value("2") is None

    washer_off = fixture("washer-status-initial.sanitized.json")["response"]["data"][
        "status"
    ]
    dryer_running = fixture("dryer-status.sanitized.json")["response"]["data"]["status"]
    assert washer_off["lowerShellWashingTime"] == 71
    assert not device.active_status(devices[0], washer_off)
    assert device.active_status(devices[1], dryer_running)


def test_control_request_uses_envelope_and_encoded_device_id() -> None:
    async def run() -> None:
        session = FakeSession(
            [FakeResponse(fixture("washer-power-on-response.json")["response"])]
        )
        client = api.TclApi(session, "token", "refresh")
        await client.async_set_property("washer/id", "powerSwitch", 1)
        method, url, options = session.calls[0]
        assert method == "POST"
        assert url.endswith("/v1/control/property/washer%2Fid/openclaw")
        assert options["json"]["params"] == [{"powerSwitch": 1}]
        assert len(options["json"]["msgId"]) == 32
        assert options["headers"]["accessToken"] == "token"

    asyncio.run(run())


def test_washer_start_and_pause_use_run_status_property() -> None:
    async def run() -> None:
        response = fixture("washer-power-on-response.json")["response"]
        session = FakeSession([FakeResponse(response), FakeResponse(response)])
        client = api.TclApi(session, "token", "refresh")
        await client.async_set_property("washer", "lowerShellRunStatus", 2)
        await client.async_set_property("washer", "lowerShellRunStatus", 1)
        assert [call[2]["json"]["params"] for call in session.calls] == [
            [{"lowerShellRunStatus": 2}],
            [{"lowerShellRunStatus": 1}],
        ]

    asyncio.run(run())


def test_array_property_uses_one_array_value_in_control_envelope() -> None:
    async def run() -> None:
        session = FakeSession(
            [FakeResponse(fixture("washer-power-on-response.json")["response"])]
        )
        client = api.TclApi(session, "token", "refresh")
        await client.async_set_property("washer", "turnOffSpecNotification", [0, 1])
        assert session.calls[0][2]["json"]["params"] == [
            {"turnOffSpecNotification": [0, 1]}
        ]

    asyncio.run(run())


def test_qr_flow_uses_server_image_and_returns_token_pair() -> None:
    async def run() -> None:
        sample = fixture("qr-login-response.example.json")
        session = FakeSession(
            [FakeResponse(sample["generate"]), FakeResponse(sample["verify"])]
        )
        client = api.TclApi(session)
        qr = await client.async_create_qr()
        assert qr.image_url == sample["generate"]["data"]["imageUrl"]
        assert await client.async_check_qr(qr.code) == (
            "<ACCESS_TOKEN>",
            "<REFRESH_TOKEN>",
        )
        assert session.calls[1][2]["params"] == {"code": qr.code}

    asyncio.run(run())


def test_status_accepts_numeric_code_and_keeps_status_object() -> None:
    async def run() -> None:
        payload = fixture("dryer-status.sanitized.json")["response"]
        session = FakeSession([FakeResponse(payload)])
        status = await api.TclApi(session, "token", "refresh").async_get_status("dryer")
        assert status["powerSwitch"] == 1
        assert isinstance(status["errorCode"], list)
        assert session.calls[0][2]["json"] == {"deviceId": "dryer"}

    asyncio.run(run())


def test_model_request_encodes_product_key_and_checks_product_identity() -> None:
    async def run() -> None:
        session = FakeSession(
            [
                FakeResponse(
                    {
                        "code": 200,
                        "data": {"productKey": "new/product", "properties": []},
                    }
                )
            ]
        )
        model = await api.TclApi(session, "token", "refresh").async_get_model(
            "new/product"
        )
        assert model["properties"] == []
        assert session.calls[0][1].endswith("/tsl/new%2Fproduct/tsl/openclaw")
        for data in (
            {"productKey": "wrong", "properties": []},
            {"productKey": "new/product"},
        ):
            session = FakeSession([FakeResponse({"code": 200, "data": data})])
            with pytest.raises(api.TclConnectionError):
                await api.TclApi(session, "token", "refresh").async_get_model(
                    "new/product"
                )

    asyncio.run(run())


def test_401_refreshes_once_and_persists_both_tokens() -> None:
    async def run() -> None:
        session = FakeSession(
            [
                FakeResponse({"code": 401, "success": False}),
                FakeResponse(
                    {"code": 1, "accessToken": "new", "refreshToken": "new-refresh"}
                ),
                FakeResponse({"code": "200", "success": True, "data": []}),
            ]
        )
        saved: list[tuple[str, str]] = []
        client = api.TclApi(
            session, "old", "old-refresh", lambda a, b: saved.append((a, b))
        )
        assert await client.async_list_devices() == []
        assert saved == [("new", "new-refresh")]
        assert session.calls[1][1].endswith("/auth/auth/refershToken")
        assert session.calls[2][2]["headers"]["accessToken"] == "new"

    asyncio.run(run())


def test_failed_control_is_not_retried_without_auth_error() -> None:
    async def run() -> None:
        session = FakeSession([FakeResponse({"code": "500", "success": False})])
        client = api.TclApi(session, "token", "refresh")
        with pytest.raises(api.TclError):
            await client.async_set_property("washer", "powerSwitch", 1)
        assert len(session.calls) == 1

    asyncio.run(run())
