"""Completeness and state-fidelity checks for the washer field catalog."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
fields = importlib.import_module("custom_components.tcl_plus.washer_fields")
controls = importlib.import_module("custom_components.tcl_plus.washer_control_data")
validation = importlib.import_module("custom_components.tcl_plus.washer_validation")


def test_catalog_covers_model_and_every_observed_status_key() -> None:
    model = json.loads(
        (ROOT / "tests/fixtures/models/washer-G100T7R-DIS.json").read_text(
            encoding="utf-8"
        )
    )["response"]["data"]["properties"]
    status = json.loads(
        (ROOT / "tests/fixtures/washer-status-initial.sanitized.json").read_text(
            encoding="utf-8"
        )
    )["response"]["data"]["status"]
    expected = {item["identifier"] for item in model} | set(status)
    assert len(expected) == 67
    assert len(fields.WASHER_FIELDS) == len(set(fields.WASHER_FIELDS))
    assert set(fields.WASHER_FIELDS) == expected
    assert len({fields.translation_key(key) for key in expected}) == 67

    for locale in ("zh-Hans", "en"):
        translated = json.loads(
            (ROOT / f"custom_components/tcl_plus/translations/{locale}.json").read_text(
                encoding="utf-8"
            )
        )["entity"]["sensor"]
        assert all(fields.translation_key(key) in translated for key in expected)


def test_raw_values_keep_types_and_full_complex_data() -> None:
    assert fields.raw_native_value(0) == 0
    assert fields.raw_native_value(0.1) == 0.1
    assert fields.raw_native_value("0") == "0"
    assert fields.raw_native_value(None) is None
    assert fields.raw_native_value([35, 0, 1]) == "[35,0,1]"

    long_list = list(range(200))
    assert fields.raw_native_value(long_list) == "200 items"
    assert fields.raw_attributes("capabilities", long_list)["raw_value"] == long_list

    long_text = "x" * 300
    assert fields.raw_native_value(long_text) == "Text (300 chars)"
    assert fields.raw_attributes("wifiSSID", long_text)["raw_value"] == long_text


def test_every_writable_model_property_has_a_validated_control() -> None:
    model = json.loads(
        (ROOT / "tests/fixtures/models/washer-G100T7R-DIS.json").read_text(
            encoding="utf-8"
        )
    )["response"]["data"]["properties"]
    writable = {item["identifier"] for item in model if item["accessMode"] == "rw"}
    assert len(writable) == 29
    assert set(controls.WASHER_CONTROL_SPECS) == writable
    assert (
        sorted(spec["kind"] for spec in controls.WASHER_CONTROL_SPECS.values()).count(
            "bool"
        )
        == 14
    )
    assert (
        sorted(spec["kind"] for spec in controls.WASHER_CONTROL_SPECS.values()).count(
            "enum"
        )
        == 8
    )
    assert (
        sorted(spec["kind"] for spec in controls.WASHER_CONTROL_SPECS.values()).count(
            "int"
        )
        == 6
    )
    assert (
        sorted(spec["kind"] for spec in controls.WASHER_CONTROL_SPECS.values()).count(
            "array"
        )
        == 1
    )

    translations = json.loads(
        (ROOT / "custom_components/tcl_plus/translations/zh-Hans.json").read_text(
            encoding="utf-8"
        )
    )["entity"]
    for field, spec in controls.WASHER_CONTROL_SPECS.items():
        base = fields.translation_key(field).replace("raw_", "control_", 1)
        if spec["kind"] == "array":
            assert all(
                f"{base}_{code}" in translations["switch"]
                for code, _ in spec["options"]
            )
        else:
            platform = {"bool": "switch", "enum": "select", "int": "number"}[
                spec["kind"]
            ]
            assert base in translations[platform]


def test_washer_write_validation_rejects_invalid_values() -> None:
    assert validation.validate_control_value("powerSwitch", 1) == 1
    assert validation.validate_control_value("lowerShellMode", 35) == 35
    assert validation.validate_control_value("freshnessTime", 20) == 20
    assert validation.validate_control_value("turnOffSpecNotification", [0, 1]) == [
        0,
        1,
    ]
    for field, value in (
        ("powerSwitch", 2),
        ("powerSwitch", True),
        ("lowerShellMode", 99),
        ("freshnessTime", 21),
        ("freshnessTime", 1.5),
        ("turnOffSpecNotification", [0, 0]),
        ("turnOffSpecNotification", [2]),
        ("turnOffSpecNotification", [{}]),
    ):
        with pytest.raises(ValueError):
            validation.validate_control_value(field, value)
