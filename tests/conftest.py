"""Fixtures: real Home Assistant core, with only the MQTT transport faked."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.exceptions import HomeAssistantError

from custom_components.sr655_fan_control.const import (
    CONF_AWAY_DELAY,
    CONF_HEARTBEAT,
    CONF_PRESENCE_ENTITY,
    CONF_TOPIC_PREFIX,
    DOMAIN,
)

PREFIX = "homeassistant/sr655"
PRESENCE = "binary_sensor.anyone_home"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


class FakeMQTT:
    """Records publishes and lets a test deliver messages to the integration's subscriptions."""

    def __init__(self) -> None:
        self.published: list[tuple[str, str, bool]] = []
        self.subscriptions: dict[str, object] = {}
        self.fail = False

    async def async_subscribe(self, hass, topic, msg_callback, qos=0, encoding="utf-8"):
        self.subscriptions[topic] = msg_callback
        return lambda: self.subscriptions.pop(topic, None)

    async def async_publish(self, hass, topic, payload, qos=0, retain=False, encoding="utf-8"):
        if self.fail:
            raise HomeAssistantError("broker unreachable")
        self.published.append((topic, payload, retain))

    def deliver(self, topic: str, payload: str, retain: bool = False) -> None:
        self.subscriptions[topic](SimpleNamespace(topic=topic, payload=payload, retain=retain))

    def profiles(self) -> list[str]:
        return [p for t, p, _ in self.published if t == f"{PREFIX}/profile/set"]


@pytest.fixture
def mqtt_fake():
    fake = FakeMQTT()
    with (
        patch("homeassistant.components.mqtt.async_subscribe", fake.async_subscribe),
        patch("homeassistant.components.mqtt.async_publish", fake.async_publish),
        patch("homeassistant.components.mqtt.async_wait_for_mqtt_client", AsyncMock(return_value=True)),
    ):
        yield fake


def make_entry(**options) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="SR655 Fan Control",
        unique_id=PREFIX,
        data={CONF_TOPIC_PREFIX: PREFIX},
        options={CONF_PRESENCE_ENTITY: PRESENCE, CONF_AWAY_DELAY: 10, CONF_HEARTBEAT: 30, **options},
    )
