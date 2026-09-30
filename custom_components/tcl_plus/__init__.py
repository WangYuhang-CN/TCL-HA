"""TCL+ Home Assistant integration."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryError,
    ConfigEntryNotReady,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import TclApi, TclAuthError, TclError
from .capabilities import async_discover_capabilities
from .const import CONF_ACCESS_TOKEN, CONF_REFRESH_TOKEN
from .coordinator import TclCoordinator
from .device import TclDevice, supported_devices

PLATFORMS = (
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
    Platform.BUTTON,
    Platform.SWITCH,
    Platform.SELECT,
    Platform.NUMBER,
)


@dataclass
class TclRuntime:
    client: TclApi
    coordinator: TclCoordinator
    devices: list[TclDevice]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a TCL+ account."""

    def save_tokens(access_token: str, refresh_token: str) -> None:
        hass.config_entries.async_update_entry(
            entry,
            data={
                **entry.data,
                CONF_ACCESS_TOKEN: access_token,
                CONF_REFRESH_TOKEN: refresh_token,
            },
        )

    client = TclApi(
        async_get_clientsession(hass),
        entry.data[CONF_ACCESS_TOKEN],
        entry.data[CONF_REFRESH_TOKEN],
        save_tokens,
    )
    try:
        devices = supported_devices(await client.async_list_devices())
        capabilities = await async_discover_capabilities(client, devices)
    except TclAuthError as err:
        raise ConfigEntryAuthFailed("TCL+ authorization failed") from err
    except TclError as err:
        raise ConfigEntryNotReady("Cannot load TCL+ devices") from err
    if not devices:
        raise ConfigEntryError("No identifiable TCL+ devices in this account")

    coordinator = TclCoordinator(hass, entry, client, devices, capabilities)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = TclRuntime(client, coordinator, devices)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a TCL+ account."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.coordinator.async_shutdown()
    return unloaded
