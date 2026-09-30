"""Concise, user-facing interpretation of G100T7R-DIS status."""

from __future__ import annotations

from typing import Any

from .device import boolean_value, integer_value


STAGES = {
    1: "洗涤中",
    2: "漂洗中",
    3: "脱水中",
    4: "烘干中",
    5: "清新中",
    6: "已完成",
    7: "除皱中",
    9: "进水中",
    10: "检测衣物量",
    11: "检测吸水性",
    12: "检测脏污度",
}

FAULTS = {
    1: "E0 变种设置错误",
    2: "E1 进水超时",
    3: "E2 排水超时",
    4: "E3 门锁故障",
    5: "E4 溢水报警/水位传感器故障",
    6: "E5 洗涤电机故障",
    7: "E6 水加热管故障",
    8: "E7 水加热温度传感器故障",
    9: "E8 变频器型号匹配错",
    10: "E9 变频器通讯故障",
    11: "E10 变频板故障",
    12: "E11 洗涤液自动投放泵故障",
    13: "E12 洗涤液液位传感器故障",
    14: "E13 烘干风机故障",
    15: "E14 烘干加热管故障",
    16: "E15 烘干出风口温度传感器故障",
    17: "E16 烘干进风口温度传感器故障",
    18: "nsp 脱水失败",
    19: "E21 消毒液自动投放泵故障",
    20: "E22 消毒液液位传感器故障",
}

CONSUMABLE_ALERTS = {1: "洗衣液不足", 2: "柔顺剂不足"}


def overview_status(status: dict[str, Any]) -> str | None:
    """Keep stale cycle data from making an off/idle washer look active."""
    power = boolean_value(status.get("powerSwitch"))
    if power is False:
        return "关机"
    if power is None:
        return None
    run = integer_value(status.get("lowerShellRunStatus"))
    if run == 0:
        return "待机"
    if run == 1:
        return "已暂停"
    if run != 2:
        return None

    stage = integer_value(status.get("lowerShellWashingStatus"))
    if stage == 0:
        return (
            "预约中" if boolean_value(status.get("lowerShellOrderMode")) else "运行中"
        )
    label = STAGES.get(stage, "运行中")
    if stage in (10, 11, 12):
        progress = integer_value(status.get("intelliDetectPercentage"))
        if progress is not None and 0 <= progress <= 100:
            return f"{label} {progress}%"
    return label


def fault_details(value: Any) -> list[str] | None:
    """Decode every reported fault while retaining unknown raw values."""
    if not isinstance(value, list):
        return None
    details = []
    for item in value:
        code = integer_value(item)
        details.append(FAULTS.get(code, f"未知故障码 ({item})"))
    return details


def brief_list(details: list[str] | None, empty: str) -> str | None:
    if details is None:
        return None
    if not details:
        return empty
    joined = "；".join(details)
    return joined if len(joined) <= 255 else f"{len(details)} 项，请查看详情"


def important_alerts(status: dict[str, Any]) -> list[str] | None:
    """Show only model-defined reminders; missing data stays unknown."""
    cleaning = boolean_value(status.get("cleaningReminder"))
    consumables = status.get("consumablesRemain")
    alerts = ["需要筒清洁"] if cleaning else []
    if isinstance(consumables, list):
        for item in consumables:
            code = integer_value(item)
            if code in CONSUMABLE_ALERTS:
                label = CONSUMABLE_ALERTS[code]
                if label not in alerts:
                    alerts.append(label)
            elif code != 0:
                alerts.append(f"耗材提醒 ({item})")
    if alerts:
        return alerts
    return [] if cleaning is not None and isinstance(consumables, list) else None
