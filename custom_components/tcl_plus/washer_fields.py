"""Complete G100T7R-DIS field catalog and lossless HA state conversion.

The catalog is the union of the archived 56 model properties and 59 status
keys. Keep it in the installed integration, which does not include ``data/``.
"""

from __future__ import annotations

import json
import re
from typing import Any


WASHER_FIELDS: tuple[str, ...] = (
    "ECO",
    "ECOStatus",
    "aiSmartControlSource",
    "capabilities",
    "childLock",
    "cleaningCount",
    "cleaningReminder",
    "collectionRun",
    "consumablesRemain",
    "detergentIntellect",
    "detergentIntellectGear",
    "dirtyRemindWashCurTimes",
    "dirtyRemindWashMaxTimes",
    "errorCode",
    "fabricSoftenerIntellect",
    "freshWaterRinseMode",
    "freshWaterRinseStatus",
    "freshnessMode",
    "freshnessState",
    "freshnessTime",
    "intelliDetectPercentage",
    "lowerShellMainRunningTime",
    "lowerShellMode",
    "lowerShellModeCapabilities",
    "lowerShellOrderMode",
    "lowerShellOrderTime",
    "lowerShellProgramRunningRime",
    "lowerShellRinseCount",
    "lowerShellRotateSpeed",
    "lowerShellRunStatus",
    "lowerShellStainsType",
    "lowerShellWashingCount",
    "lowerShellWashingStatus",
    "lowerShellWashingTemp",
    "lowerShellWashingTempSet",
    "lowerShellWashingTempSetInt",
    "lowerShellWashingTime",
    "lowerShellWashingTimeSet",
    "nightWashMode",
    "nightWashState",
    "nspCurAttempts",
    "nspFittingEccentricityValue",
    "nspFittingWeight",
    "nspMotorErrorStatus",
    "nspMotorPower",
    "nspOriginalEccentricityValue",
    "nspOriginalWeight",
    "nspRotateSpeed",
    "nspWaterLevelFreq",
    "powerSwitch",
    "programMemory",
    "soak",
    "soakStatus",
    "speedUpMode",
    "speedUpStatus",
    "tslLatestVersion",
    "tslQueryTime",
    "tslReqVersion",
    "turnOffSpecNotification",
    "washerDryerLinkage",
    "wifiDropPacketRate",
    "wifiIP",
    "wifiMacAddr",
    "wifiMode",
    "wifiRSSI",
    "wifiSSID",
    "wifiSignalStrength",
)


def translation_key(field: str) -> str:
    """Use stable, lower-case Home Assistant translation identifiers."""
    return "raw_" + re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", field).lower()


def raw_native_value(value: Any) -> str | int | float | None:
    """Represent a cloud field as a legal HA sensor state.

    Lists and objects remain in ``raw_value`` when their JSON is too long for
    the HA state limit, while ordinary values keep their original type.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        return value if len(value) <= 255 else f"Text ({len(value)} chars)"
    if isinstance(value, (list, dict)):
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        if len(encoded) <= 255:
            return encoded
        return f"{len(value)} items"
    return str(value)[:255]


def raw_attributes(field: str, value: Any) -> dict[str, Any]:
    """Preserve the complete underlying value for complex fields."""
    attributes: dict[str, Any] = {"cloud_field": field}
    if isinstance(value, (list, dict)) or isinstance(value, str) and len(value) > 255:
        attributes["raw_value"] = value
    return attributes
