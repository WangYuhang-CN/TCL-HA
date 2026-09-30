"""Unknown products must use their own schema and never inherit washer controls."""

import asyncio
import importlib
import json
from pathlib import Path

import pytest

caps = importlib.import_module("custom_components.tcl_plus.capabilities")
device = importlib.import_module("custom_components.tcl_plus.device")
api = importlib.import_module("custom_components.tcl_plus.api")
ROOT = Path(__file__).resolve().parents[1]


def prop(field, kind, specs, access="rw", **extra):
    return {
        "identifier": field,
        "name": field + " label",
        "accessMode": access,
        "dataType": {"type": kind, "specs": specs, **extra},
    }


def appliance(device_id="new", kind="generic", product_key="unseen"):
    return device.TclDevice(device_id, product_key, "New appliance", "New model", kind)


def schema(*properties):
    return {"productKey": "unseen", "tslVersion": "V1", "properties": list(properties)}


def test_discover_unknown_categories_and_model_variants_without_allowlist():
    result = device.supported_devices(
        [
            {
                "deviceId": "washer",
                "productKey": "new-washer",
                "category": "DW",
                "deviceType": "Other washer",
            },
            {
                "deviceId": "ac",
                "productKey": 123,
                "category": "AC",
                "deviceType": "AC model",
                "isControl": "0",
                "identifiers": [{"identifier": "ambientTemp", "value": 24}, None],
            },
            {"deviceId": "washer", "productKey": "duplicate"},
            {"deviceId": "invalid", "productKey": None},
            {"deviceId": "invalid2", "productKey": True},
            {"productKey": "no-id"},
            None,
        ]
    )
    assert [(d.kind, d.model) for d in result] == [
        ("washer", "Other washer"),
        ("generic", "AC model"),
    ]
    assert all(d.legacy_kind is None for d in result)
    assert result[1].initial_status == {"ambientTemp": 24}
    assert result[1].controllable is False


def test_model_drives_switch_select_number_and_readonly_fields():
    definition = schema(
        prop("powerSwitch", "bool", {"0": "Off", "1": "On"}),
        prop("fan", "enum", {"1": "Low", "9": "High"}),
        prop("temperature", "int", {"min": "16", "max": "30", "step": "2"}),
        prop("humidity", "float", {"min": "0", "max": "100", "step": "0.5"}),
        prop("ambientTemp", "int", {"min": "-40", "max": "60", "step": "1"}, "r"),
        prop("doorOpen", "bool", {"0": "Closed", "1": "Open"}, "r"),
        prop(
            "faults",
            "array",
            {"size": 2, "item": {"type": "enum", "specs": {"1": "Fault"}}},
        ),
        prop("opaque", "struct", {}),
        prop("command", "bool", {"0": "Off", "1": "On"}, "w"),
    )
    profile = caps.build_capabilities(appliance(), definition)
    assert profile.source == "cloud"
    assert set(profile.control_specs) == {
        "powerSwitch",
        "fan",
        "temperature",
        "humidity",
    }
    assert profile.fields == {p["identifier"] for p in definition["properties"]}
    assert profile.properties["faults"].spec["options"] == ((1, "Fault"),)
    assert caps.entity_naming(appliance(), profile, "fan", control=True) == {
        "name": "fan label"
    }
    assert (
        caps.validate_spec_value(
            "temperature", 18, profile.control_specs["temperature"]
        )
        == 18
    )
    for value in (17, 32, True, 18.0, "18"):
        with pytest.raises(ValueError):
            caps.validate_spec_value(
                "temperature", value, profile.control_specs["temperature"]
            )
    assert (
        caps.validate_spec_value("humidity", 22.5, profile.control_specs["humidity"])
        == 22.5
    )
    for value in (22.1, float("nan"), float("inf"), True):
        with pytest.raises(ValueError):
            caps.validate_spec_value(
                "humidity", value, profile.control_specs["humidity"]
            )
    assert (
        type(
            caps.validate_spec_value("humidity", 22, profile.control_specs["humidity"])
        )
        is float
    )


@pytest.mark.parametrize("value", ["--1", "²", "-", "1.0", True])
def test_malformed_enum_numbers_stay_unknown(value):
    assert device.integer_value(value) is None


@pytest.mark.parametrize(
    "definition",
    [
        prop("x", "bool", {"0": "Off", "2": "On"}),
        prop("x", "enum", {"auto": "Auto"}),
        prop("x", "enum", {"1": "One", "01": "Ambiguous"}),
        prop("x", "int", {"min": 0, "max": 10}),
        prop("x", "int", {"min": 10, "max": 0, "step": 1}),
        prop("x", "int", {"min": 0, "max": 10, "step": 0}),
        prop("x", "int", {"min": 0, "max": 10, "step": 0.5}),
        prop("x", "float", {"min": 0, "max": "NaN", "step": 1}),
        prop("x", "float", {"min": 0, "max": "1e999", "step": 1}),
        prop(
            "x", "float", {"min": 0, "max": 10, "step": 0.01}, mappingType="int32_100"
        ),
        prop("x", "string", {"length": 10}),
    ],
)
def test_unsupported_or_malformed_specs_are_readonly(definition):
    profile = caps.build_capabilities(appliance(), schema(definition))
    assert profile.fields == {"x"}
    assert profile.control_specs == {}


def test_ambiguous_duplicate_identifiers_and_readonly_accounts_cannot_write():
    boolean = prop("power", "bool", {"0": "Off", "1": "On"})
    assert (
        caps.build_capabilities(appliance(), schema(boolean, boolean)).control_specs
        == {}
    )
    readonly = device.TclDevice(
        "r", "unseen", "Read only", "New model", "generic", controllable=False
    )
    assert caps.build_capabilities(readonly, schema(boolean)).control_specs == {}


def test_missing_model_uses_exact_archived_profile_or_only_status():
    unknown = device.TclDevice(
        "x", "other-washer", "Other", "Other", "washer", initial_status={"custom": 1}
    )
    profile = caps.build_capabilities(unknown, None)
    assert profile.source == "status_only"
    assert profile.fields == {"custom"}
    assert profile.control_specs == {}
    known = appliance("old", "washer", "11160101096")
    archived = caps.build_capabilities(known, None)
    assert archived.source == "archived"
    assert len(archived.control_specs) == 29
    # A successful, empty live model removes controls, rather than borrowing old ones.
    assert caps.build_capabilities(known, schema()).control_specs == {}


def test_program_options_are_device_specific_and_handle_missing_ai_program():
    profile = caps.build_capabilities(
        appliance(kind="washer"),
        schema(prop("lowerShellMode", "enum", {"0": "Mix", "1": "Quick", "35": "AI"})),
    )
    spec = profile.control_spec("lowerShellMode", {"lowerShellModeCapabilities": ["1"]})
    assert spec["options"] == ((1, "Quick"),)
    with pytest.raises(ValueError):
        caps.validate_spec_value("lowerShellMode", 35, spec)
    for codes in ([], None, [True], ["bad"]):
        assert not profile.control_spec(
            "lowerShellMode", {"lowerShellModeCapabilities": codes}
        )["options"]
    assert len(profile.control_spec("lowerShellMode", {})["options"]) == 3


def test_inspected_products_keep_legacy_entity_keys_and_writable_coverage():
    for filename, kind, key, count in (
        ("washer-G100T7R-DIS.json", "washer", "11160101096", 29),
        ("dryer-H100T7R-BS.json", "dryer", "11160501018", 20),
    ):
        model = json.loads(
            (ROOT / "tests/fixtures/models" / filename).read_text(encoding="utf-8")
        )["response"]["data"]
        known = appliance("old", kind, key)
        profile = caps.build_capabilities(known, model)
        assert len(profile.control_specs) == count
        assert (
            caps.control_key(known, "powerSwitch")
            == ("dryer_" if kind == "dryer" else "") + "control_powerSwitch"
        )
        assert "translation_key" in caps.entity_naming(
            known, profile, "powerSwitch", control=True
        )


def test_device_list_and_last_reported_program_capabilities_are_retained():
    dev = device.TclDevice(
        "one",
        "unseen",
        "One",
        "One",
        "washer",
        initial_status={"lowerShellModeCapabilities": [1]},
    )
    profile = caps.build_capabilities(
        dev,
        schema(prop("lowerShellMode", "enum", {"0": "Mix", "1": "Quick", "35": "AI"})),
    )
    assert profile.control_spec("lowerShellMode", {})["options"] == ((1, "Quick"),)
    profile.observe_status({"lowerShellModeCapabilities": [35]})
    assert profile.control_spec("lowerShellMode", {})["options"] == ((35, "AI"),)
    profile.observe_status({"lowerShellMode": 35})
    assert profile.control_spec("lowerShellMode", {})["options"] == ((35, "AI"),)
    profile.observe_status({"lowerShellModeCapabilities": []})
    assert profile.control_spec("lowerShellMode", {})["options"] == ()


def test_one_model_request_per_product_and_auth_errors_propagate():
    class Client:
        def __init__(self, error=None):
            self.calls = []
            self.error = error

        async def async_get_model(self, key):
            self.calls.append(key)
            if self.error:
                raise self.error
            return schema(prop("power", "bool", {"0": "Off", "1": "On"}))

    async def run():
        devices = [appliance("one"), appliance("two")]
        client = Client()
        profiles = await caps.async_discover_capabilities(client, devices)
        assert client.calls == ["unseen"]
        assert profiles["one"] is not profiles["two"]
        profiles["one"].fields.add("newStatus")
        assert "newStatus" not in profiles["two"].fields
        client = Client(api.TclConnectionError("unavailable"))
        assert all(
            p.source == "status_only"
            for p in (await caps.async_discover_capabilities(client, devices)).values()
        )
        assert client.calls == ["unseen"]
        with pytest.raises(api.TclAuthError):
            await caps.async_discover_capabilities(
                Client(api.TclAuthError("expired")), devices
            )

    asyncio.run(run())
