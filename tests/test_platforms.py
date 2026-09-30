"""Exercise the actual entity factories and write path with minimal HA contracts.

These stubs test our integration behavior; they do not certify HA Core runtime
compatibility, which requires installing the release in Home Assistant.
"""

import asyncio
import importlib
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
caps = importlib.import_module("custom_components.tcl_plus.capabilities")
device_module = importlib.import_module("custom_components.tcl_plus.device")


@pytest.fixture
def platforms(monkeypatch):
    def module(name, **attrs):
        result = ModuleType(name)
        result.__dict__.update(attrs)
        monkeypatch.setitem(sys.modules, name, result)
        return result

    class Entity:
        pass

    class CoordinatorEntity(Entity):
        def __class_getitem__(cls, item):
            return cls

        def __init__(self, coordinator):
            self.coordinator = coordinator

        @property
        def available(self):
            return self.coordinator.last_update_success

    class Coordinator:
        def __class_getitem__(cls, item):
            return cls

        def __init__(self, hass, *args, **kwargs):
            self.hass = hass
            self.data = {}
            self.listeners = []
            self.last_update_success = True

        async def async_refresh(self):
            self.data = await self._async_update_data()
            self.async_update_listeners()

        def async_update_listeners(self):
            for listener in self.listeners:
                listener()

        def async_add_listener(self, listener):
            self.listeners.append(listener)
            return lambda: self.listeners.remove(listener)

    class Description(SimpleNamespace):
        pass

    class HAError(Exception):
        pass

    module("homeassistant")
    module("homeassistant.components")
    module("homeassistant.config_entries", ConfigEntry=SimpleNamespace)
    module("homeassistant.core", HomeAssistant=SimpleNamespace)
    module(
        "homeassistant.exceptions",
        HomeAssistantError=HAError,
        ConfigEntryAuthFailed=HAError,
    )
    module("homeassistant.helpers")
    module(
        "homeassistant.helpers.entity",
        EntityCategory=SimpleNamespace(CONFIG="config", DIAGNOSTIC="diagnostic"),
    )
    module("homeassistant.helpers.entity_platform", AddEntitiesCallback=object)
    module("homeassistant.helpers.device_registry", DeviceInfo=dict)
    module(
        "homeassistant.helpers.update_coordinator",
        CoordinatorEntity=CoordinatorEntity,
        DataUpdateCoordinator=Coordinator,
        UpdateFailed=HAError,
    )
    module("homeassistant.const", UnitOfTime=SimpleNamespace(MINUTES="min"))
    for name, prefix in (
        ("sensor", "Sensor"),
        ("binary_sensor", "BinarySensor"),
        ("switch", "Switch"),
        ("select", "Select"),
        ("number", "Number"),
        ("button", "Button"),
    ):
        attrs = {
            prefix + "Entity": type(prefix + "Entity", (Entity,), {}),
            prefix + "EntityDescription": Description,
        }
        if name == "sensor":
            attrs["SensorDeviceClass"] = SimpleNamespace(DURATION="duration")
        module("homeassistant.components." + name, **attrs)
    package = sys.modules["custom_components.tcl_plus"]
    monkeypatch.setattr(package, "TclRuntime", SimpleNamespace, raising=False)
    names = (
        "coordinator",
        "entity",
        "control",
        "sensor",
        "binary_sensor",
        "switch",
        "select",
        "number",
        "button",
        "diagnostics",
    )
    loaded = {
        name: importlib.import_module("custom_components.tcl_plus." + name)
        for name in names
    }
    yield SimpleNamespace(**loaded)
    for name in names:
        sys.modules.pop("custom_components.tcl_plus." + name, None)
        if hasattr(package, name):
            delattr(package, name)


class Client:
    def __init__(self, statuses):
        self.statuses = statuses
        self.writes = []

    async def async_get_status(self, device_id):
        return dict(self.statuses[device_id])

    async def async_set_property(self, device_id, field, value):
        self.writes.append((device_id, field, value))
        self.statuses[device_id][field] = value


def runtime(platforms, devices, profiles, statuses):
    client = Client(statuses)
    coordinator = platforms.coordinator.TclCoordinator(
        SimpleNamespace(), SimpleNamespace(), client, devices, profiles
    )
    return SimpleNamespace(coordinator=coordinator, devices=devices, client=client)


async def create_entities(platforms, rt):
    await rt.coordinator.async_refresh()
    entry = SimpleNamespace(runtime_data=rt, async_on_unload=lambda callback: None)
    entities = {}
    for name in ("sensor", "binary_sensor", "switch", "select", "number", "button"):
        entities[name] = []
        await getattr(platforms, name).async_setup_entry(
            None, entry, entities[name].extend
        )
    return entities


def test_legacy_entity_counts_unique_ids_and_program_filtering(platforms):
    async def run():
        devices = device_module.supported_devices(
            json.loads(
                (ROOT / "tests/fixtures/device-list.minimal.sanitized.json").read_text(
                    encoding="utf-8"
                )
            )["response"]["data"]
        )
        profiles, statuses = {}, {}
        for dev, filename, statefile in zip(
            devices,
            ("washer-G100T7R-DIS.json", "dryer-H100T7R-BS.json"),
            ("washer-status-initial.sanitized.json", "dryer-status.sanitized.json"),
        ):
            model = json.loads(
                (ROOT / "tests/fixtures/models" / filename).read_text(encoding="utf-8")
            )["response"]["data"]
            profiles[dev.device_id] = caps.build_capabilities(dev, model)
            statuses[dev.device_id] = json.loads(
                (ROOT / "tests/fixtures" / statefile).read_text(encoding="utf-8")
            )["response"]["data"]["status"]
        rt = runtime(platforms, devices, profiles, statuses)
        entities = await create_entities(platforms, rt)
        for dev, count in zip(devices, (112, 83)):
            assert (
                sum(e.device == dev for group in entities.values() for e in group)
                == count
            )
        for group in entities.values():
            assert len({e._attr_unique_id for e in group}) == len(group)
        ids = {e._attr_unique_id for group in entities.values() for e in group}
        assert devices[0].device_id + "_control_powerSwitch" in ids
        assert devices[1].device_id + "_dryer_control_powerSwitch" in ids
        assert devices[0].device_id + "_run_start" in ids
        assert devices[0].device_id + "_raw_powerSwitch" in ids
        mode = next(
            e
            for e in entities["select"]
            if e.device == devices[0] and e.field == "lowerShellMode"
        )
        assert mode.options[0] == mode._code_to_option[35]
        statuses[devices[0].device_id]["lowerShellModeCapabilities"] = [1]
        await rt.coordinator.async_refresh()
        assert mode.options == [mode._code_to_option[1]]
        with pytest.raises(Exception, match="Invalid.*option"):
            await mode.async_select_option(mode._code_to_option[35])
        assert rt.client.writes == []
        await mode.async_select_option(mode._code_to_option[1])
        assert rt.client.writes == [(devices[0].device_id, "lowerShellMode", 1)]
        assert (
            rt.coordinator.last_write_status[(devices[0].device_id, "lowerShellMode")]
            == "confirmed"
        )

    asyncio.run(run())


def test_new_product_entities_float_writes_and_late_status_fields(platforms):
    async def run():
        dev = device_module.TclDevice("ac", "new", "AC", "New AC", "generic")
        model = {
            "properties": [
                {
                    "identifier": "power",
                    "name": "Power",
                    "accessMode": "rw",
                    "dataType": {"type": "bool", "specs": {"0": "Off", "1": "On"}},
                },
                {
                    "identifier": "targetTemp",
                    "name": "Target temperature",
                    "accessMode": "rw",
                    "dataType": {
                        "type": "float",
                        "specs": {"min": 16, "max": 30, "step": 0.5},
                    },
                },
                {
                    "identifier": "state",
                    "name": "State",
                    "accessMode": "r",
                    "dataType": {"type": "enum", "specs": {"9": "Cooling"}},
                },
                {
                    "identifier": "door",
                    "name": "Door",
                    "accessMode": "r",
                    "dataType": {"type": "bool", "specs": {"0": "Closed", "1": "Open"}},
                },
            ]
        }
        profile = caps.build_capabilities(dev, model)
        rt = runtime(
            platforms,
            [dev],
            {dev.device_id: profile},
            {
                dev.device_id: {
                    "power": 1,
                    "targetTemp": "22.5",
                    "state": 9,
                    "door": True,
                }
            },
        )
        entities = await create_entities(platforms, rt)
        assert entities["button"] == []
        assert len(entities["switch"]) == 1
        assert entities["binary_sensor"][0].is_on is True
        state = next(
            e for e in entities["sensor"] if e._attr_unique_id == "ac_property_state"
        )
        assert state.native_value == "Cooling"
        number = entities["number"][0]
        assert number.native_value == 22.5
        assert number._attr_native_step == 0.5
        with pytest.raises(Exception, match="range or step"):
            await number.async_set_native_value(22.1)
        assert rt.client.writes == []
        await number.async_set_native_value(23.5)
        assert rt.client.writes == [("ac", "targetTemp", 23.5)]
        rt.client.statuses["ac"]["newFirmwareField"] = {"unexpected": "value"}
        await rt.coordinator.async_refresh()
        raw = next(
            e
            for e in entities["sensor"]
            if e._attr_unique_id == "ac_raw_newFirmwareField"
        )
        assert raw.extra_state_attributes["raw_value"] == {"unexpected": "value"}
        before = len(entities["sensor"])
        await rt.coordinator.async_refresh()
        assert len(entities["sensor"]) == before
        diagnostic = await platforms.diagnostics.async_get_config_entry_diagnostics(
            None, SimpleNamespace(runtime_data=rt)
        )
        encoded = json.dumps(diagnostic)
        assert "newFirmwareField" in encoded
        assert "unexpected" not in encoded
        assert "device_id" not in encoded
        assert "access_token" not in encoded

    asyncio.run(run())


def test_unknown_product_without_model_has_status_and_no_controls(platforms):
    async def run():
        dev = device_module.TclDevice(
            "other", "unknown", "Other", "Other washer", "washer"
        )
        rt = runtime(
            platforms,
            [dev],
            {dev.device_id: caps.build_capabilities(dev, None)},
            {dev.device_id: {"powerSwitch": 1}},
        )
        entities = await create_entities(platforms, rt)
        assert len(entities["sensor"]) == 1
        assert not any(
            entities[name] for name in ("switch", "select", "number", "button")
        )

    asyncio.run(run())
