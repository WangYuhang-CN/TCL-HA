"""Reported TCL+ washer and dryer values."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TclRuntime
from .capabilities import entity_naming
from .device import active_status, boolean_value, integer_value, running_field
from .dryer_control_data import DRYER_CONTROL_SPECS
from .entity import TclEntity
from .washer_fields import (
    raw_attributes,
    raw_native_value,
)
from .washer_presentation import (
    brief_list,
    fault_details,
    important_alerts,
    overview_status,
)

RUN_STATES = {0: "待机", 1: "暂停", 2: "运行"}
WASHER_STAGES = {
    0: "预约等待",
    1: "洗涤",
    2: "漂洗",
    3: "脱水",
    4: "烘干",
    5: "清新",
    6: "已完成",
    7: "除皱",
    9: "进水",
    10: "检测衣物量",
    11: "检测吸水性",
    12: "检测脏污度",
}
DRYER_STAGES = {
    0: "预约等待",
    1: "烘干",
    2: "已完成",
    3: "防皱",
    4: "数据同步中",
    5: "检测含水率",
    6: "自动",
}
WASHER_MODES = {
    0: "混合",
    1: "快洗",
    2: "羊毛",
    3: "大件",
    4: "真丝",
    5: "超净",
    6: "热力除菌",
    9: "单脱水",
    10: "漂+脱",
    11: "筒清洁",
    14: "羽绒",
    15: "棉麻",
    16: "运动服",
    17: "衬衫",
    18: "内衣",
    21: "巴氏除菌",
    23: "除菌螨",
    26: "童装",
    29: "护色",
    33: "冲锋衣",
    35: "AI智慧洗",
}
DRYER_MODES = {
    0: "混合",
    1: "快烘",
    2: "衬衫",
    4: "婴儿服",
    5: "羽绒",
    6: "棉麻",
    7: "羊毛",
    8: "真丝",
    10: "除菌螨",
    12: "大件",
    14: "空气洗",
    15: "热风清新",
    16: "童装",
    17: "内衣",
    18: "毛巾",
    19: "运动服",
    20: "冷风护理",
    21: "家纺",
    22: "冲锋衣",
    23: "轻柔",
    24: "化纤",
    25: "牛仔",
    26: "蚕丝被",
    27: "AI智慧烘",
}
DRYER_FAULTS = dict(DRYER_CONTROL_SPECS["errorCode"]["options"])

COMMON = (
    SensorEntityDescription(key="run_state", translation_key="run_state"),
    SensorEntityDescription(key="stage", translation_key="stage"),
    SensorEntityDescription(key="mode", translation_key="selected_program"),
    SensorEntityDescription(key="faults", translation_key="faults"),
)
WASHER = (
    SensorEntityDescription(key="overview", translation_key="overview"),
    SensorEntityDescription(key="alerts", translation_key="important_alerts"),
    SensorEntityDescription(key="remaining", translation_key="remaining_time"),
    SensorEntityDescription(
        key="clean_count",
        translation_key="cleaning_current_count",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="clean_max",
        translation_key="cleaning_threshold",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)
DRYER = (
    SensorEntityDescription(
        key="remaining",
        translation_key="remaining_time",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    runtime: TclRuntime = entry.runtime_data
    entities = [
        TclSensor(runtime.coordinator, device, description)
        for device in runtime.devices
        if device.legacy_kind
        for description in COMMON + (WASHER if device.kind == "washer" else DRYER)
    ]
    entities.extend(
        TclModelSensor(runtime.coordinator, device, field)
        for device in runtime.devices
        if not device.legacy_kind
        for field, prop in runtime.coordinator.capabilities[
            device.device_id
        ].properties.items()
        if prop.access_mode == "r" and prop.data_type != "bool"
    )
    async_add_entities(entities)
    added: dict[str, set[str]] = {device.device_id: set() for device in runtime.devices}

    def discover_fields() -> None:
        """New status keys become sensors during polling, without another release."""
        new_entities = []
        for device in runtime.devices:
            fields = runtime.coordinator.capabilities[device.device_id].fields
            for field in sorted(fields - added[device.device_id]):
                new_entities.append(TclRawSensor(runtime.coordinator, device, field))
                added[device.device_id].add(field)
        if new_entities:
            async_add_entities(new_entities)

    discover_fields()
    entry.async_on_unload(runtime.coordinator.async_add_listener(discover_fields))


class TclSensor(TclEntity, SensorEntity):
    """A decoded TCL+ status value."""

    def __init__(
        self, coordinator, device, description: SensorEntityDescription
    ) -> None:
        super().__init__(coordinator, device, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> str | int | None:
        status = self.status
        key = self.entity_description.key
        if key == "overview":
            return overview_status(status)
        if key == "alerts":
            return brief_list(important_alerts(status), "暂无提醒")
        if key == "run_state":
            if boolean_value(status.get("powerSwitch")) is False:
                return "关机"
            value = integer_value(status.get(running_field(self.device)))
            return RUN_STATES.get(
                value, f"未知 ({value})" if value is not None else None
            )
        if key == "stage":
            if not active_status(self.device, status):
                return None
            value = integer_value(status.get("lowerShellWashingStatus"))
            stages = WASHER_STAGES if self.device.kind == "washer" else DRYER_STAGES
            stages = self._enum_labels("lowerShellWashingStatus", stages)
            return stages.get(value, f"未知 ({value})" if value is not None else None)
        if key == "mode":
            field = (
                "lowerShellMode" if self.device.kind == "washer" else "washShellMode"
            )
            value = integer_value(status.get(field))
            modes = WASHER_MODES if self.device.kind == "washer" else DRYER_MODES
            modes = self._enum_labels(field, modes)
            return modes.get(value, f"未知 ({value})" if value is not None else None)
        if key == "remaining":
            if not active_status(self.device, status):
                return None
            field = (
                "lowerShellWashingTime"
                if self.device.kind == "washer"
                else "washShellWashingTime"
            )
            return integer_value(status.get(field))
        if key == "faults":
            return brief_list(self._fault_details(), "无故障")
        if key == "clean_count":
            return integer_value(status.get("dirtyRemindWashCurTimes"))
        if key == "clean_max":
            return integer_value(status.get("dirtyRemindWashMaxTimes"))
        return None

    def _enum_labels(self, field: str, fallback: dict[int, str]) -> dict[int, str]:
        prop = self.coordinator.capabilities[self.device.device_id].properties.get(
            field
        )
        if prop and prop.spec and prop.spec["kind"] in ("enum", "array"):
            return dict(prop.spec["options"])
        return fallback

    def _fault_details(self) -> list[str] | None:
        faults = self.status.get("errorCode")
        if not isinstance(faults, list):
            return None
        prop = self.coordinator.capabilities[self.device.device_id].properties.get(
            "errorCode"
        )
        if self.device.kind == "washer" and not (prop and prop.spec):
            return fault_details(faults)
        labels = self._enum_labels("errorCode", DRYER_FAULTS)
        return [
            labels.get(integer_value(fault), f"未知故障码 ({fault})")
            for fault in faults
        ]

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.key == "overview":
            return {
                "stage_code": self.status.get("lowerShellWashingStatus"),
                "ai_detection_progress_percent": self.status.get(
                    "intelliDetectPercentage"
                ),
            }
        if self.entity_description.key == "alerts":
            return {"details": important_alerts(self.status)}
        if self.entity_description.key == "mode":
            field = (
                "lowerShellMode" if self.device.kind == "washer" else "washShellMode"
            )
            return {"raw_code": self.status.get(field)}
        if self.entity_description.key == "faults":
            return {
                "raw_codes": self.status.get("errorCode"),
                "details": self._fault_details(),
            }
        return None


class TclRawSensor(TclEntity, SensorEntity):
    """One complete, unmodified cloud field from appliance status."""

    def __init__(self, coordinator, device, field: str) -> None:
        super().__init__(coordinator, device, f"raw_{field}")
        self.field = field
        self.entity_description = SensorEntityDescription(
            key=f"raw_{field}",
            **entity_naming(device, coordinator.capabilities[device.device_id], field),
            entity_category=EntityCategory.DIAGNOSTIC,
        )

    @property
    def native_value(self) -> str | int | float | None:
        return raw_native_value(self.reported_status.get(self.field))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return raw_attributes(self.field, self.reported_status.get(self.field))


class TclModelSensor(TclRawSensor):
    """Readable status for new products, using their own enum labels."""

    def __init__(self, coordinator, device, field: str) -> None:
        super().__init__(coordinator, device, field)
        self._attr_unique_id = f"{device.device_id}_property_{field}"
        self.entity_description = SensorEntityDescription(
            key=f"property_{field}",
            name=coordinator.capabilities[device.device_id].name(field),
        )

    @property
    def native_value(self) -> str | int | float | None:
        value = self.status.get(self.field)
        spec = (
            self.coordinator.capabilities[self.device.device_id]
            .properties[self.field]
            .spec
        )
        if spec and spec["kind"] == "enum":
            return raw_native_value(
                dict(spec["options"]).get(integer_value(value), value)
            )
        if spec and spec["kind"] == "array" and isinstance(value, list):
            labels = dict(spec["options"])
            return raw_native_value(
                "; ".join(labels.get(integer_value(code), str(code)) for code in value)
            )
        return raw_native_value(value)
