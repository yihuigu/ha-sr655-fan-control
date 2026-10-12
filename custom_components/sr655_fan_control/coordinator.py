"""Publishes the fan profile to the NAS and holds what the NAS reports back."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
import json
import logging
from typing import Any

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    CONF_AWAY_DELAY,
    CONF_HEARTBEAT,
    CONF_PRESENCE_ENTITY,
    CONF_TOPIC_PREFIX,
    DEFAULT_AWAY_DELAY,
    DEFAULT_HEARTBEAT,
    DOMAIN,
    HOME_STATES,
    MODE_AUTO,
    MODE_NORMAL,
    MODE_QUIET,
    PROFILES,
    TELEMETRY_STALE,
    availability_topic,
    command_topic,
    state_topic,
    telemetry_topic,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class SR655Data:
    """Everything the entities show."""

    mode: str = MODE_AUTO
    requested: str | None = None  # profile this integration is asking for
    link_online: bool | None = None  # the NAS bridge's availability topic
    active: str | None = None  # profile the controller says it is running
    telemetry: dict[str, Any] | None = None


class SR655Coordinator(DataUpdateCoordinator[SR655Data]):
    """Push-based: updated by MQTT messages, presence changes and the mode select."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, _LOGGER, config_entry=entry, name=DOMAIN, update_interval=None)
        self.prefix: str = entry.data[CONF_TOPIC_PREFIX]
        self.presence_entity: str | None = entry.options.get(CONF_PRESENCE_ENTITY)
        self.away_delay = timedelta(minutes=entry.options.get(CONF_AWAY_DELAY, DEFAULT_AWAY_DELAY))
        self.heartbeat = timedelta(seconds=entry.options.get(CONF_HEARTBEAT, DEFAULT_HEARTBEAT))
        self.data = SR655Data()
        self._unsubs: list[Callable[[], None]] = []
        self._last_telemetry: datetime | None = None
        self._publish_failed = False

    # ------------------------------------------------------------------ lifecycle
    async def async_setup(self) -> None:
        """Subscribe and start the timers. Nothing is published until async_start."""
        self._unsubs += [
            await mqtt.async_subscribe(self.hass, availability_topic(self.prefix), self._on_availability),
            await mqtt.async_subscribe(self.hass, state_topic(self.prefix), self._on_state),
            await mqtt.async_subscribe(self.hass, telemetry_topic(self.prefix), self._on_telemetry),
            async_track_time_interval(self.hass, self._on_heartbeat, self.heartbeat),
        ]
        if self.presence_entity:
            self._unsubs.append(
                async_track_state_change_event(self.hass, [self.presence_entity], self._on_presence)
            )

    async def async_start(self) -> None:
        """Send the first request; called once the select has restored its mode."""
        await self.async_publish_profile()

    @callback
    def async_stop(self) -> None:
        # Stopping the heartbeat is the intended way to hand control back: the
        # controller falls back to its own profile once requests stop arriving.
        while self._unsubs:
            self._unsubs.pop()()

    # ------------------------------------------------------------------ profile
    def desired_profile(self) -> str:
        """Profile to request right now."""
        if self.data.mode in PROFILES:
            return self.data.mode
        if not self.presence_entity:
            return MODE_NORMAL
        state = self.hass.states.get(self.presence_entity)
        if state is None:
            return MODE_NORMAL
        if state.state in HOME_STATES:
            return MODE_QUIET
        # Away, unknown or unavailable: stay quiet until it has lasted away_delay.
        if dt_util.utcnow() - state.last_changed < self.away_delay:
            return MODE_QUIET
        return MODE_NORMAL

    def restore_mode(self, mode: str) -> None:
        """Set the mode without publishing; the first publish comes from async_start."""
        self.data = replace(self.data, mode=mode)

    async def async_set_mode(self, mode: str) -> None:
        self.async_set_updated_data(replace(self.data, mode=mode))
        await self.async_publish_profile()

    async def async_publish_profile(self) -> None:
        profile = self.desired_profile()
        if profile != self.data.requested:
            self.async_set_updated_data(replace(self.data, requested=profile))
        try:
            await mqtt.async_publish(self.hass, command_topic(self.prefix), profile, qos=0, retain=False)
        except (HomeAssistantError, TimeoutError, OSError) as err:
            if not self._publish_failed:
                _LOGGER.warning("Could not publish the fan profile: %s", err)
            self._publish_failed = True
        else:
            if self._publish_failed:
                _LOGGER.info("Publishing the fan profile works again")
            self._publish_failed = False

    # ------------------------------------------------------------------ listeners
    async def _on_heartbeat(self, now: datetime) -> None:
        self._expire_telemetry(now)
        await self.async_publish_profile()

    async def _on_presence(self, event: Event[EventStateChangedData]) -> None:
        old, new = event.data["old_state"], event.data["new_state"]
        # Person/tracker entities update attributes (GPS) constantly; only a
        # change of the state itself can change the profile.
        if old is None or new is None or old.state != new.state:
            await self.async_publish_profile()

    def _expire_telemetry(self, now: datetime) -> None:
        if self._last_telemetry and now - self._last_telemetry > TELEMETRY_STALE:
            self._last_telemetry = None
            self.async_set_updated_data(replace(self.data, active=None, telemetry=None))

    @callback
    def _on_availability(self, msg: mqtt.ReceiveMessage) -> None:
        online = str(msg.payload).strip().lower() == "online"
        if online:
            self.async_set_updated_data(replace(self.data, link_online=True))
        else:
            self._last_telemetry = None
            self.async_set_updated_data(replace(self.data, link_online=False, active=None, telemetry=None))

    @callback
    def _on_state(self, msg: mqtt.ReceiveMessage) -> None:
        profile = str(msg.payload).strip().lower()
        self.async_set_updated_data(replace(self.data, active=profile if profile in PROFILES else None))

    @callback
    def _on_telemetry(self, msg: mqtt.ReceiveMessage) -> None:
        try:
            telemetry = json.loads(msg.payload)
        except (TypeError, ValueError):
            _LOGGER.debug("Ignoring telemetry that is not JSON: %r", msg.payload)
            return
        if not isinstance(telemetry, dict):
            return
        self._last_telemetry = dt_util.utcnow()
        self.async_set_updated_data(replace(self.data, telemetry=telemetry))
