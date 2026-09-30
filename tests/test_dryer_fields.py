"""Completeness and write constraints for the H100T7R-BS dryer."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
fields = importlib.import_module("custom_components.tcl_plus.dryer_fields")
controls = importlib.import_module("custom_components.tcl_plus.dryer_control_data")
validation = importlib.import_module("custom_components.tcl_plus.washer_validation")
run_control = importlib.import_module("custom_components.tcl_plus.washer_run_control")
washer_fields = importlib.import_module("custom_components.tcl_plus.washer_fields")


def test_dryer_catalog_covers_model_and_reported_status() -> None:
    model = json.loads(
        (ROOT / "tests/fixtures/models/dryer-H100T7R-BS.json").read_text(
            encoding="utf-8"
        )
    )["response"]["data"]["properties"]
    status = json.loads(
        (ROOT / "tests/fixtures/dryer-status.sanitized.json").read_text(
            encoding="utf-8"
        )
    )["response"]["data"]["status"]
    expected = {item["identifier"] for item in model} | set(status)
    writable = {item["identifier"] for item in model if item["accessMode"] == "rw"}
    assert len(expected) == 37
    assert len(fields.DRYER_FIELDS) == len(set(fields.DRYER_FIELDS))
    assert set(fields.DRYER_FIELDS) == expected
    assert len(writable) == 20
    assert set(controls.DRYER_CONTROL_SPECS) == writable
    assert {
        kind: sum(
            spec["kind"] == kind for spec in controls.DRYER_CONTROL_SPECS.values()
        )
        for kind in ("bool", "enum", "int", "array")
    } == {"bool": 8, "enum": 7, "int": 4, "array": 1}

    for locale in ("zh-Hans", "en"):
        entity = json.loads(
            (ROOT / f"custom_components/tcl_plus/translations/{locale}.json").read_text(
                encoding="utf-8"
            )
        )["entity"]
        for field in expected:
            key = "dryer_" + washer_fields.translation_key(field)
            assert key in entity["sensor"]
        for field, spec in controls.DRYER_CONTROL_SPECS.items():
            base = "dryer_" + washer_fields.translation_key(field).replace(
                "raw_", "control_", 1
            )
            platform = {
                "bool": "switch",
                "enum": "select",
                "int": "number",
                "array": "switch",
            }[spec["kind"]]
            keys = (
                [f"{base}_{code}" for code, _ in spec["options"]]
                if spec["kind"] == "array"
                else [base]
            )
            assert all(key in entity[platform] for key in keys)
        assert all(
            f"dryer_{action}" in entity["button"]
            for action in ("power_on", "start", "pause")
        )


def test_dryer_write_validation_and_start_pause() -> None:
    def validate(field, value):
        return validation.validate_control_value(field, value, "dryer")

    assert validate("washShellMode", 27) == 27
    assert validate("washingTime", 1440) == 1440
    assert validate("errorCode", [1, 16]) == [1, 16]
    for field, value in (
        ("washShellMode", 3),
        ("washingTime", 1441),
        ("washingTime", True),
        ("washShellDryMode", 4),
        ("errorCode", [1, 1]),
        ("errorCode", [17]),
    ):
        with pytest.raises(ValueError):
            validate(field, value)

    running = {"powerSwitch": 1, "washShellRunStatus": 2}
    assert run_control.run_action_available(running, 1, False, "washShellRunStatus")
    assert not run_control.run_action_available(running, 2, False, "washShellRunStatus")
    assert not run_control.run_action_available(running, 1, True, "washShellRunStatus")
