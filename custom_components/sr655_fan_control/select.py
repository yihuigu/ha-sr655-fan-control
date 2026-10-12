"""Mode select: follow presence, or force a profile."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import SR655ConfigEntry
from .const import MODE_AUTO, MODES
from .coordinator import SR655Coordinator
from .entity import SR655Entity


async def async_setup_entry(
    hass: HomeAssistant, entry: SR655ConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([SR655ModeSelect(entry.runtime_data)])


class SR655ModeSelect(SR655Entity, SelectEntity, RestoreEntity):
    _attr_translation_key = "mode"
    _attr_options = MODES

    def __init__(self, coordinator: SR655Coordinator) -> None:
        super().__init__(coordinator, "mode")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) and last.state in MODES:
            self.coordinator.restore_mode(last.state)

    @property
    def current_option(self) -> str:
        return self.coordinator.data.mode or MODE_AUTO

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_set_mode(option)
