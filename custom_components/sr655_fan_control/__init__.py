"""SR655 Fan Control: Home Assistant side of the SR655 fan controller."""

from __future__ import annotations

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .coordinator import SR655Coordinator

PLATFORMS = [Platform.SELECT, Platform.SENSOR, Platform.BINARY_SENSOR]

type SR655ConfigEntry = ConfigEntry[SR655Coordinator]


async def async_setup_entry(hass: HomeAssistant, entry: SR655ConfigEntry) -> bool:
    if not await mqtt.async_wait_for_mqtt_client(hass):
        raise ConfigEntryNotReady("The MQTT integration is not available")
    coordinator = SR655Coordinator(hass, entry)
    await coordinator.async_setup()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # After the platforms: the mode select has restored its last state by now.
    await coordinator.async_start()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SR655ConfigEntry) -> bool:
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        entry.runtime_data.async_stop()
    return unload_ok
