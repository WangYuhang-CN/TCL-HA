"""Shared polling for TCL+ devices."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import TclApi, TclAuthError, TclError
from .capabilities import DeviceCapabilities
from .const import POLL_INTERVAL_SECONDS
from .device import TclDevice
from .pending import PendingWrites

_LOGGER = logging.getLogger(__name__)
WRITE_CONFIRM_TIMEOUT_SECONDS = 90
WRITE_CONFIRM_DELAYS = (5, 15, 30, 40)


class TclCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Request one full status document per device and share it among entities."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: TclApi,
        devices: list[TclDevice],
        capabilities: dict[str, DeviceCapabilities],
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="TCL+",
            config_entry=entry,
            update_interval=timedelta(seconds=POLL_INTERVAL_SECONDS),
            always_update=False,
        )
        self.client = client
        self.devices = devices
        self.capabilities = capabilities
        self.write_locks = {device.device_id: asyncio.Lock() for device in devices}
        self.pending = PendingWrites(WRITE_CONFIRM_TIMEOUT_SECONDS)
        self.last_write_status: dict[tuple[str, str], str] = {}
        self._pending_changed = False
        self._confirmation_tasks: set[asyncio.Task[None]] = set()

    def effective_status(self, device_id: str) -> dict[str, Any]:
        """Latest cloud status with ACKed writes held until confirmation."""
        return self.pending.effective_status(device_id, self.data.get(device_id, {}))

    async def async_track_write(
        self, device_id: str, field: str, value: int | float | list[int]
    ) -> None:
        """Update HA immediately and check the cloud until it catches up."""
        generation = self.pending.register(device_id, field, value)
        self.last_write_status[(device_id, field)] = "pending"
        self.async_update_listeners()
        await self.async_refresh()
        if self.pending.is_current(device_id, field, generation):
            task = self.hass.async_create_background_task(
                self._async_confirm_later(device_id, field, generation),
                name=f"TCL+ confirm {field}",
            )
            self._confirmation_tasks.add(task)
            task.add_done_callback(self._confirmation_tasks.discard)

    async def _async_confirm_later(
        self, device_id: str, field: str, generation: int
    ) -> None:
        """Retry a few reads without repeatedly sending the control command."""
        for delay in WRITE_CONFIRM_DELAYS:
            await asyncio.sleep(delay)
            if not self.pending.is_current(device_id, field, generation):
                return
            await self.async_refresh()
            if not self.pending.is_current(device_id, field, generation):
                return
        if self.pending.expire(device_id, field, generation):
            self.last_write_status[(device_id, field)] = "not_confirmed"
            _LOGGER.warning(
                "TCL+ did not confirm %s for device %s within %s seconds",
                field,
                device_id,
                WRITE_CONFIRM_TIMEOUT_SECONDS,
            )
            self.async_update_listeners()

    def _async_refresh_finished(self) -> None:
        """Publish confirmation even when the raw status stayed unchanged."""
        if self._pending_changed:
            self._pending_changed = False
            self.async_update_listeners()

    async def async_shutdown(self) -> None:
        """Stop write confirmation tasks when this config entry unloads."""
        for task in self._confirmation_tasks:
            task.cancel()
        if self._confirmation_tasks:
            await asyncio.gather(*self._confirmation_tasks, return_exceptions=True)
        self._confirmation_tasks.clear()
        await super().async_shutdown()

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for device in self.devices:
            try:
                status = await self.client.async_get_status(device.device_id)
                result[device.device_id] = status
                self.capabilities[device.device_id].observe_status(status)
                for field in self.pending.observe(device.device_id, status):
                    self.last_write_status[(device.device_id, field)] = "confirmed"
                    self._pending_changed = True
            except TclAuthError as err:
                raise ConfigEntryAuthFailed("TCL+ authorization failed") from err
            except TclError as err:
                _LOGGER.warning(
                    "Could not update TCL+ %s status: %s", device.model, err
                )
        if not result:
            raise UpdateFailed("Cannot update any TCL+ device status")
        return result
