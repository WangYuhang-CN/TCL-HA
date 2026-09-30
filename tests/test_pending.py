"""Regression checks for cloud status lag after a control ACK."""

from __future__ import annotations

import importlib


pending_module = importlib.import_module("custom_components.tcl_plus.pending")


def test_float_and_boolean_confirmation_from_cloud_strings():
    assert pending_module.values_match("22.50", 22.5)
    assert not pending_module.values_match("22.51", 22.5)
    assert not pending_module.values_match(True, 22.5)
    assert pending_module.values_match(True, 1)
    pending = pending_module.PendingWrites(90)
    pending.register("ac", "targetTemp", 22.5)
    assert pending.observe("ac", {"targetTemp": "22.5"}) == ["targetTemp"]


def test_stale_reads_do_not_flip_an_acked_control_back() -> None:
    now = [0.0]
    pending = pending_module.PendingWrites(90, lambda: now[0])
    token = pending.register("washer", "powerSwitch", 1)
    reported = {"powerSwitch": 0, "childLock": 0}

    assert pending.effective_status("washer", reported) == {
        "powerSwitch": 1,
        "childLock": 0,
    }
    assert reported["powerSwitch"] == 0
    now[0] = 30
    assert pending.observe("washer", reported) == []
    assert pending.is_current("washer", "powerSwitch", token)
    assert pending.effective_status("washer", reported)["powerSwitch"] == 1

    now[0] = 40
    assert pending.observe("washer", {"powerSwitch": "1"}) == ["powerSwitch"]
    assert pending.effective_status("washer", reported)["powerSwitch"] == 0


def test_array_confirmation_and_newer_write_survive_old_timeout() -> None:
    now = [0.0]
    pending = pending_module.PendingWrites(90, lambda: now[0])
    first = pending.register("washer", "turnOffSpecNotification", [0])
    now[0] = 20
    second = pending.register("washer", "turnOffSpecNotification", [0, 1])
    assert not pending.expire("washer", "turnOffSpecNotification", first)
    assert pending.effective_status("washer", {"turnOffSpecNotification": []})[
        "turnOffSpecNotification"
    ] == [0, 1]
    assert pending.observe("washer", {"turnOffSpecNotification": ["1", 0]}) == [
        "turnOffSpecNotification"
    ]
    assert not pending.is_current("washer", "turnOffSpecNotification", second)


def test_unconfirmed_write_expires_only_after_deadline() -> None:
    now = [0.0]
    pending = pending_module.PendingWrites(90, lambda: now[0])
    token = pending.register("washer", "lowerShellMode", 35)
    assert pending.effective_status("dryer", {"lowerShellMode": 0}) == {
        "lowerShellMode": 0
    }
    now[0] = 89
    assert not pending.expire("washer", "lowerShellMode", token)
    now[0] = 90
    assert pending.expire("washer", "lowerShellMode", token)
    assert pending.effective_status("washer", {"lowerShellMode": 0}) == {
        "lowerShellMode": 0
    }
