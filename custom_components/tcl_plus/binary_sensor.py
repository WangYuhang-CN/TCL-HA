"""Binary states for TCL+ appliances."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TclRuntime
from .device import boolean_value
from .entity import TclEntity

COMMON = (
    BinarySensorEntityDescription(key="powerSwitch", translation_key="power"),
    BinarySensorEntityDescription(key="childLock", translation_key="child_lock"),
)
WASHER = (
    BinarySensorEntityDescription(
        key="cleaningReminder", translation_key="cleaning_reminder"
    ),
)
DRYER = (
    BinarySensorEntityDescription(
        key="waterBoxStatus", translation_key="water_box_full"
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    runtime: TclRuntime = entry.runtime_data
    entities = [
        TclBinarySensor(runtime.coordinator, device, description)
        for device in runtime.devices
        if device.legacy_kind
        for description in COMMON + (WASHER if device.kind == "washer" else DRYER)
    ]
    entities.extend(
        TclBinarySensor(
            runtime.coordinator,
            device,
            BinarySensorEntityDescription(
                key=field,
                name=prop.name,
            ),
        )
        for device in runtime.devices
        if not device.legacy_kind
        for field, prop in runtime.coordinator.capabilities[
            device.device_id
        ].properties.items()
        if prop.data_type == "bool"
        and prop.spec is not None
        and prop.access_mode == "r"
    )
    async_add_entities(entities)


class TclBinarySensor(TclEntity, BinarySensorEntity):
    """A reported TCL+ 0/1 state."""

    def __init__(
        self, coordinator, device, description: BinarySensorEntityDescription
    ) -> None:
        super().__init__(coordinator, device, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        value = self.status.get(self.entity_description.key)
        return value if isinstance(value, bool) else boolean_value(value)
