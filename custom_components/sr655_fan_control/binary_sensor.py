"""Binary sensors: is the NAS reachable, and is the controller healthy."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import SR655ConfigEntry
from .coordinator import SR655Coordinator
from .entity import SR655Entity


async def async_setup_entry(
    hass: HomeAssistant, entry: SR655ConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities([SR655LinkSensor(coordinator), SR655ProblemSensor(coordinator)])


class SR655LinkSensor(SR655Entity, BinarySensorEntity):
    """On while the NAS-side bridge says it is online (broker last-will makes this reliable)."""

    _attr_translation_key = "link"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, coordinator: SR655Coordinator) -> None:
        super().__init__(coordinator, "link")

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.data.link_online


class SR655ProblemSensor(SR655Entity, BinarySensorEntity):
    """On when the controller reports an error (fans are then at the failsafe speed) or has gone silent."""

    _attr_translation_key = "problem"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: SR655Coordinator) -> None:
        super().__init__(coordinator, "problem")

    @property
    def is_on(self) -> bool | None:
        telemetry = self.coordinator.data.telemetry
        if telemetry is None:
            return None
        return telemetry.get("ok") is not True

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        error = (self.coordinator.data.telemetry or {}).get("error")
        # Controller errors can be multi-line tracebacks; keep the attribute readable.
        return {"error": str(error)[:255]} if error else None
