"""Exercise account renewal against HA's real flow helpers when HA is installed."""

import asyncio
import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

ha_config_entries = pytest.importorskip("homeassistant.config_entries")
flow_module = importlib.import_module("custom_components.tcl_plus.config_flow")


@pytest.fixture
def setup_flow(monkeypatch):
    entry = SimpleNamespace(
        entry_id="existing-entry",
        title="TCL+",
        data={
            "access_token": "old",
            "refresh_token": "old-refresh",
            "device_ids": ["washer"],
            "other_setting": "keep",
        },
    )
    manager = SimpleNamespace(
        async_get_known_entry=Mock(return_value=entry),
        async_update_entry=Mock(return_value=True),
        async_schedule_reload=Mock(),
        flow=SimpleNamespace(async_progress_by_handler=Mock(return_value=[])),
    )
    client = SimpleNamespace(
        async_create_qr=AsyncMock(
            return_value=flow_module.TclQrCode("qr", "https://cn.account.tcl.com/qr")
        ),
        async_check_qr=AsyncMock(return_value=("new", "new-refresh")),
        async_list_devices=AsyncMock(
            return_value=[SimpleNamespace(device_id="washer")]
        ),
    )
    monkeypatch.setattr(flow_module, "TclApi", lambda *args: client)
    monkeypatch.setattr(flow_module, "async_get_clientsession", lambda hass: None)
    monkeypatch.setattr(flow_module, "supported_devices", lambda devices: devices)
    monkeypatch.setattr(
        ha_config_entries.persistent_notification, "async_dismiss", Mock()
    )

    def create(source):
        flow = flow_module.TclPlusConfigFlow()
        flow.hass = SimpleNamespace(config_entries=manager)
        flow.context = {"source": source, "entry_id": entry.entry_id}
        return flow

    return create, entry, manager, client


@pytest.mark.parametrize("source", ["reauth", "reconfigure"])
def test_renewal_updates_and_reloads_original_entry(setup_flow, source):
    async def run():
        create, entry, manager, client = setup_flow
        flow = create(source)
        result = await getattr(flow, f"async_step_{source}")({})
        assert result["step_id"] == "scan"
        result = await flow.async_step_scan({})
        assert result["type"] == "abort"
        assert result["reason"] == f"{source}_successful"
        update = manager.async_update_entry.call_args.kwargs
        assert update["entry"] is entry
        assert update["data"] == {
            **entry.data,
            "access_token": "new",
            "refresh_token": "new-refresh",
        }
        manager.async_schedule_reload.assert_called_once_with(entry.entry_id)
        client.async_check_qr.assert_awaited_once()

    asyncio.run(run())


@pytest.mark.parametrize("source", ["reauth", "reconfigure"])
def test_wrong_account_cannot_replace_original_credentials(setup_flow, source):
    async def run():
        create, entry, manager, client = setup_flow
        client.async_list_devices.return_value = [SimpleNamespace(device_id="other")]
        flow = create(source)
        await getattr(flow, f"async_step_{source}")({})
        result = await flow.async_step_scan({})
        assert result["errors"] == {"base": "wrong_account"}
        manager.async_update_entry.assert_not_called()
        manager.async_schedule_reload.assert_not_called()
        assert entry.data["access_token"] == "old"

    asyncio.run(run())


def test_network_failure_keeps_authorization_for_retry_and_can_generate_new_qr(
    setup_flow,
):
    async def run():
        create, entry, manager, client = setup_flow
        flow = create("reconfigure")
        await flow.async_step_reconfigure()
        client.async_list_devices.side_effect = flow_module.TclError("unavailable")
        result = await flow.async_step_scan({})
        assert result["errors"] == {"base": "cannot_connect"}
        manager.async_update_entry.assert_not_called()
        client.async_list_devices.side_effect = None
        result = await flow.async_step_scan({})
        assert result["reason"] == "reconfigure_successful"
        client.async_check_qr.assert_awaited_once()
        await flow.async_step_scan({"new_code": True})
        assert client.async_create_qr.await_count == 2
        assert flow._credentials is None

    asyncio.run(run())
