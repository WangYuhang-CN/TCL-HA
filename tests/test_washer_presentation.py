"""Daily washer status must not mistake retained cloud fields for a live cycle."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
package = ModuleType("custom_components.tcl_plus")
package.__path__ = [str(ROOT / "custom_components" / "tcl_plus")]
sys.modules.setdefault("custom_components.tcl_plus", package)

presentation = importlib.import_module("custom_components.tcl_plus.washer_presentation")


def test_overview_prioritizes_power_and_run_state() -> None:
    old_cycle = {
        "powerSwitch": 0,
        "lowerShellRunStatus": 2,
        "lowerShellWashingStatus": 10,
        "intelliDetectPercentage": 60,
    }
    assert presentation.overview_status(old_cycle) == "关机"
    assert (
        presentation.overview_status(
            {**old_cycle, "powerSwitch": 1, "lowerShellRunStatus": 0}
        )
        == "待机"
    )
    assert (
        presentation.overview_status(
            {**old_cycle, "powerSwitch": 1, "lowerShellRunStatus": 1}
        )
        == "已暂停"
    )
    assert (
        presentation.overview_status({**old_cycle, "powerSwitch": 1})
        == "检测衣物量 60%"
    )
    assert presentation.overview_status({"lowerShellRunStatus": 2}) is None


def test_faults_include_code_description_and_unknown_fallback() -> None:
    details = presentation.fault_details([2, "4", 999])
    assert details == ["E1 进水超时", "E3 门锁故障", "未知故障码 (999)"]
    assert (
        presentation.brief_list(details, "无故障")
        == "E1 进水超时；E3 门锁故障；未知故障码 (999)"
    )
    assert presentation.fault_details(None) is None


def test_alerts_only_report_known_active_conditions() -> None:
    status = {"cleaningReminder": 1, "consumablesRemain": [0, 1, 2]}
    assert presentation.important_alerts(status) == [
        "需要筒清洁",
        "洗衣液不足",
        "柔顺剂不足",
    ]
    assert (
        presentation.important_alerts({"cleaningReminder": 0, "consumablesRemain": []})
        == []
    )
    assert presentation.important_alerts({"cleaningReminder": 0}) is None
    assert presentation.important_alerts({"cleaningReminder": 1}) == ["需要筒清洁"]
    assert presentation.important_alerts({"consumablesRemain": [2]}) == ["柔顺剂不足"]
