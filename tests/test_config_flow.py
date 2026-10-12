"""Config flow and options flow."""

from unittest.mock import patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType

from custom_components.sr655_fan_control.const import (
    CONF_AWAY_DELAY,
    CONF_HEARTBEAT,
    CONF_PRESENCE_ENTITY,
    CONF_TOPIC_PREFIX,
    DOMAIN,
)

from .conftest import PRESENCE, make_entry

FORM = {
    "name": "NAS fans",
    CONF_TOPIC_PREFIX: "homeassistant/sr655",
    CONF_PRESENCE_ENTITY: PRESENCE,
    CONF_AWAY_DELAY: 15,
    CONF_HEARTBEAT: 20,
}


async def _start(hass):
    return await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})


async def test_aborts_without_mqtt(hass):
    result = await _start(hass)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "mqtt_not_configured"


async def test_creates_entry(hass):
    MockConfigEntry(domain="mqtt").add_to_hass(hass)
    result = await _start(hass)
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "user"
    with patch("custom_components.sr655_fan_control.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {**FORM, CONF_TOPIC_PREFIX: " /homeassistant/sr655/ "}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "NAS fans"
    assert result["data"] == {CONF_TOPIC_PREFIX: "homeassistant/sr655"}  # slashes and spaces trimmed
    assert result["options"] == {CONF_PRESENCE_ENTITY: PRESENCE, CONF_AWAY_DELAY: 15, CONF_HEARTBEAT: 20}
    assert result["result"].unique_id == "homeassistant/sr655"


async def test_rejects_bad_prefix(hass):
    MockConfigEntry(domain="mqtt").add_to_hass(hass)
    for bad in ("", "   ", "home/#", "home/+/x", "has space", "a//b", "$SYS/x"):
        result = await _start(hass)
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {**FORM, CONF_TOPIC_PREFIX: bad})
        assert result["type"] is FlowResultType.FORM, bad
        assert result["errors"] == {CONF_TOPIC_PREFIX: "invalid_topic"}, bad


async def test_duplicate_prefix_aborts(hass):
    MockConfigEntry(domain="mqtt").add_to_hass(hass)
    make_entry().add_to_hass(hass)
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], FORM)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_second_server_with_other_prefix(hass):
    MockConfigEntry(domain="mqtt").add_to_hass(hass)
    make_entry().add_to_hass(hass)
    result = await _start(hass)
    with patch("custom_components.sr655_fan_control.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {**FORM, CONF_TOPIC_PREFIX: "homeassistant/sr655-b"}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_options_flow_updates_and_reloads(hass, mqtt_fake):
    hass.states.async_set(PRESENCE, "on")
    entry = make_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "init"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_PRESENCE_ENTITY: "person.me", CONF_AWAY_DELAY: 0, CONF_HEARTBEAT: 45}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {CONF_PRESENCE_ENTITY: "person.me", CONF_AWAY_DELAY: 0, CONF_HEARTBEAT: 45}
    # reloaded with the new options: the coordinator now follows person.me with a 45 s heartbeat
    assert entry.runtime_data.presence_entity == "person.me"
    assert entry.runtime_data.heartbeat.total_seconds() == 45
