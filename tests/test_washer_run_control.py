"""Start and pause must respect the washer's reported power and run state."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
package = ModuleType("custom_components.tcl_plus")
package.__path__ = [str(ROOT / "custom_components" / "tcl_plus")]
sys.modules.setdefault("custom_components.tcl_plus", package)

run_control = importlib.import_module("custom_components.tcl_plus.washer_run_control")


def test_start_pause_transitions_and_pending_guard() -> None:
    cases = (
        ({"powerSwitch": 0, "lowerShellRunStatus": 0}, False, False),
        ({"powerSwitch": 1, "lowerShellRunStatus": 0}, True, False),
        ({"powerSwitch": 1, "lowerShellRunStatus": 1}, True, False),
        ({"powerSwitch": 1, "lowerShellRunStatus": 2}, False, True),
        ({"powerSwitch": 1}, False, False),
        ({"lowerShellRunStatus": 2}, False, False),
    )
    for status, can_start, can_pause in cases:
        assert run_control.run_action_available(status, 2, False) is can_start
        assert run_control.run_action_available(status, 1, False) is can_pause
        assert not run_control.run_action_available(status, 2, True)
        assert not run_control.run_action_available(status, 1, True)

    assert not run_control.run_action_available(
        {"powerSwitch": 1, "lowerShellRunStatus": 2}, 0, False
    )
