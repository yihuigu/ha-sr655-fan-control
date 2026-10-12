"""Shared base class for the integration's entities."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SR655Coordinator


class SR655Entity(CoordinatorEntity[SR655Coordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: SR655Coordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            model="SR655 fan controller",
        )
