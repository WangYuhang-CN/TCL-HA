"""Shared write path for TCL+ writable model properties."""

from __future__ import annotations

from homeassistant.exceptions import HomeAssistantError

from .api import TclError
from .capabilities import validate_spec_value
from .entity import TclEntity


class TclPropertyControl(TclEntity):
    """An explicit user initiated property write, followed by status refresh."""

    def __init__(self, coordinator, device, field: str, key: str) -> None:
        super().__init__(coordinator, device, key)
        self.field = field

    @property
    def extra_state_attributes(self) -> dict[str, str] | None:
        result = self.coordinator.last_write_status.get(
            (self.device.device_id, self.field)
        )
        return {"last_write_status": result} if result else None

    async def async_write_value(self, value: int | float | list[int]) -> None:
        async with self.coordinator.write_locks[self.device.device_id]:
            await self._async_write_value_unlocked(value)

    async def async_set_array_option(self, option: int, enabled: bool) -> None:
        """Write the full array while preserving the other selected option."""
        async with self.coordinator.write_locks[self.device.device_id]:
            current = self.status.get(self.field)
            if not isinstance(current, list) or any(
                type(item) is not int for item in current
            ):
                raise HomeAssistantError(
                    f"Cannot change {self.field} without its current cloud value"
                )
            values = [item for item in current if item != option]
            if enabled:
                values.append(option)
            await self._async_write_value_unlocked(sorted(values))

    async def _async_write_value_unlocked(self, value: int | float | list[int]) -> None:
        try:
            spec = self.coordinator.capabilities[self.device.device_id].control_spec(
                self.field, self.reported_status
            )
            validated = validate_spec_value(self.field, value, spec)
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err
        try:
            await self.coordinator.client.async_set_property(
                self.device.device_id, self.field, validated
            )
        except TclError as err:
            raise HomeAssistantError(f"TCL+ rejected {self.field}") from err
        await self.coordinator.async_track_write(
            self.device.device_id, self.field, validated
        )
