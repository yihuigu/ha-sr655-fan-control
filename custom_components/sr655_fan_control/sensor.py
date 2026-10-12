"""Sensors: what is requested, what the NAS runs, and its temperatures and fan speeds."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import SR655ConfigEntry
from .const import PROFILES, SENSOR_LABELS
from .coordinator import SR655Coordinator
from .entity import SR655Entity


async def async_setup_entry(
    hass: HomeAssistant, entry: SR655ConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities([SR655ProfileSensor(coordinator, "requested"), SR655ProfileSensor(coordinator, "active")])

    known: set[str] = set()

    @callback
    def add_telemetry_sensors() -> None:
        """Create a sensor for every temperature and fan the NAS reports, once."""
        telemetry = coordinator.data.telemetry or {}
        new: list[SR655Entity] = []
        for name in telemetry.get("temps") or {}:
            if (key := f"temp_{name}") not in known:
                known.add(key)
                new.append(SR655TemperatureSensor(coordinator, name))
        for fan in telemetry.get("fans") or {}:
            if (key := f"fan_{fan}") not in known:
                known.add(key)
                new.append(SR655FanSensor(coordinator, fan))
        if new:
            async_add_entities(new)

    add_telemetry_sensors()
    entry.async_on_unload(coordinator.async_add_listener(add_telemetry_sensors))


class SR655ProfileSensor(SR655Entity, SensorEntity):
    """`requested` is what this integration publishes; `active` is what the NAS runs."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = PROFILES

    def __init__(self, coordinator: SR655Coordinator, which: str) -> None:
        super().__init__(coordinator, f"{which}_profile")
        self._which = which
        self._attr_translation_key = f"{which}_profile"

    @property
    def native_value(self) -> str | None:
        return getattr(self.coordinator.data, self._which)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self._which != "active":
            return None
        source = (self.coordinator.data.telemetry or {}).get("source")
        return {"source": source} if source else None


class _TelemetrySensor(SR655Entity, SensorEntity):
    _attr_state_class = SensorStateClass.MEASUREMENT
    _section: str

    def __init__(self, coordinator: SR655Coordinator, key: str, name: str) -> None:
        super().__init__(coordinator, key)
        self._name = name

    @property
    def native_value(self) -> float | None:
        value = ((self.coordinator.data.telemetry or {}).get(self._section) or {}).get(self._name)
        return value if isinstance(value, (int, float)) else None

    @property
    def available(self) -> bool:
        return super().available and self.native_value is not None


class SR655TemperatureSensor(_TelemetrySensor):
    _section = "temps"
    _attr_translation_key = "temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator: SR655Coordinator, name: str) -> None:
        super().__init__(coordinator, f"temp_{name}", name)
        self._attr_translation_placeholders = {"sensor": SENSOR_LABELS.get(name, name.upper())}


class SR655FanSensor(_TelemetrySensor):
    _section = "fans"
    _attr_translation_key = "fan_speed"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_suggested_display_precision = 0

    def __init__(self, coordinator: SR655Coordinator, fan: str) -> None:
        super().__init__(coordinator, f"fan_{fan}", fan)
        self._attr_translation_placeholders = {"fan": fan}
