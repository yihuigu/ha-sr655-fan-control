"""Behaviour of the running integration."""

from datetime import timedelta
import json
import logging

from freezegun.api import FrozenDateTimeFactory
from pytest_homeassistant_custom_component.common import async_fire_time_changed, mock_restore_cache

from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import State
from homeassistant.util import dt as dt_util

from custom_components.sr655_fan_control.const import DOMAIN

from .conftest import PREFIX, PRESENCE, make_entry

MODE = "select.sr655_fan_control_mode"
REQUESTED = "sensor.sr655_fan_control_requested_profile"
ACTIVE = "sensor.sr655_fan_control_active_profile"
LINK = "binary_sensor.sr655_fan_control_nas_link"
PROBLEM = "binary_sensor.sr655_fan_control_controller_problem"
CPU = "sensor.sr655_fan_control_cpu_temperature"
FAN1 = "sensor.sr655_fan_control_fan_1_speed"

TELEMETRY = {
    "ok": True,
    "profile": "quiet",
    "source": "ha",
    "temps": {"cpu": 42.25, "hdd": 40.0, "nvme": 46.85},
    "fans": {"1": 5, "2": 5, "3": 5, "4": 7, "5": 7, "6": 7},
    "error": None,
}


async def setup(hass, mqtt_fake, presence="on", **options):
    if presence is not None:
        hass.states.async_set(PRESENCE, presence)
    entry = make_entry(**options)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def tick(hass, freezer: FrozenDateTimeFactory, seconds: float):
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_publishes_on_setup_and_per_presence(hass, mqtt_fake):
    await setup(hass, mqtt_fake, presence="on")
    assert mqtt_fake.published == [(f"{PREFIX}/profile/set", "quiet", False)]  # not retained
    assert hass.states.get(REQUESTED).state == "quiet"
    assert hass.states.get(MODE).state == "auto"
    assert set(mqtt_fake.subscriptions) == {f"{PREFIX}/availability", f"{PREFIX}/profile", f"{PREFIX}/telemetry"}


async def test_heartbeat_repeats_the_profile(hass, mqtt_fake, freezer):
    await setup(hass, mqtt_fake)
    for _ in range(3):
        await tick(hass, freezer, 30)
    assert mqtt_fake.profiles() == ["quiet"] * 4


async def test_away_stays_quiet_for_the_delay_then_normal(hass, mqtt_fake, freezer):
    await setup(hass, mqtt_fake, presence="on")
    hass.states.async_set(PRESENCE, STATE_OFF)
    await hass.async_block_till_done()
    assert mqtt_fake.profiles()[-1] == "quiet"  # left just now: published immediately, still quiet
    await tick(hass, freezer, 9 * 60)
    assert mqtt_fake.profiles()[-1] == "quiet"
    await tick(hass, freezer, 90)  # 10.5 minutes away: picked up by the next heartbeat
    assert mqtt_fake.profiles()[-1] == "normal"
    assert hass.states.get(REQUESTED).state == "normal"
    hass.states.async_set(PRESENCE, STATE_ON)
    await hass.async_block_till_done()
    assert mqtt_fake.profiles()[-1] == "quiet"  # coming home switches back at once


async def test_zero_delay_means_normal_as_soon_as_everyone_leaves(hass, mqtt_fake, freezer):
    await setup(hass, mqtt_fake, presence="on", away_delay=0)
    hass.states.async_set(PRESENCE, STATE_OFF)
    await hass.async_block_till_done()
    assert mqtt_fake.profiles()[-1] == "normal"


async def test_only_a_state_change_publishes_not_attribute_updates(hass, mqtt_fake):
    await setup(hass, mqtt_fake, presence="home")
    before = len(mqtt_fake.published)
    for lat in (1.0, 1.1, 1.2):  # GPS noise on a person entity
        hass.states.async_set(PRESENCE, "home", {"latitude": lat})
        await hass.async_block_till_done()
    assert len(mqtt_fake.published) == before


async def test_person_and_zone_states(hass, mqtt_fake, freezer):
    await setup(hass, mqtt_fake, presence="home")
    assert mqtt_fake.profiles()[-1] == "quiet"
    hass.states.async_set(PRESENCE, "work")  # a named zone counts as away
    await hass.async_block_till_done()
    await tick(hass, freezer, 11 * 60)
    assert mqtt_fake.profiles()[-1] == "normal"


async def test_unavailable_presence_is_treated_as_away(hass, mqtt_fake, freezer):
    await setup(hass, mqtt_fake, presence="on")
    hass.states.async_set(PRESENCE, STATE_UNAVAILABLE)
    await hass.async_block_till_done()
    assert mqtt_fake.profiles()[-1] == "quiet"  # grace period
    await tick(hass, freezer, 11 * 60)
    assert mqtt_fake.profiles()[-1] == "normal"


async def test_missing_presence_entity_fails_towards_normal(hass, mqtt_fake):
    await setup(hass, mqtt_fake, presence=None)
    assert mqtt_fake.profiles() == ["normal"]


async def test_mode_select_overrides_presence(hass, mqtt_fake):
    await setup(hass, mqtt_fake, presence="on")
    await hass.services.async_call("select", "select_option", {"entity_id": MODE, "option": "normal"}, blocking=True)
    assert mqtt_fake.profiles()[-1] == "normal" and hass.states.get(MODE).state == "normal"
    hass.states.async_set(PRESENCE, STATE_OFF)
    hass.states.async_set(PRESENCE, STATE_ON)
    await hass.async_block_till_done()
    assert mqtt_fake.profiles()[-1] == "normal"  # presence is ignored while forced
    await hass.services.async_call("select", "select_option", {"entity_id": MODE, "option": "quiet"}, blocking=True)
    assert mqtt_fake.profiles()[-1] == "quiet"
    await hass.services.async_call("select", "select_option", {"entity_id": MODE, "option": "auto"}, blocking=True)
    assert mqtt_fake.profiles()[-1] == "quiet" and hass.states.get(MODE).state == "auto"


async def test_forced_mode_keeps_the_heartbeat(hass, mqtt_fake, freezer):
    await setup(hass, mqtt_fake)
    await hass.services.async_call("select", "select_option", {"entity_id": MODE, "option": "quiet"}, blocking=True)
    n = len(mqtt_fake.profiles())
    await tick(hass, freezer, 30)
    assert len(mqtt_fake.profiles()) == n + 1  # a forced mode must still lapse if HA dies


async def test_mode_is_restored_before_the_first_publish(hass, mqtt_fake):
    mock_restore_cache(hass, [State(MODE, "normal")])
    await setup(hass, mqtt_fake, presence="on")
    assert mqtt_fake.profiles() == ["normal"]  # never a wrong "quiet" first
    assert hass.states.get(MODE).state == "normal"


async def test_nas_link_and_active_profile(hass, mqtt_fake):
    await setup(hass, mqtt_fake)
    assert hass.states.get(LINK).state == STATE_UNKNOWN
    mqtt_fake.deliver(f"{PREFIX}/availability", "online", retain=True)
    mqtt_fake.deliver(f"{PREFIX}/profile", "quiet")
    await hass.async_block_till_done()
    assert hass.states.get(LINK).state == STATE_ON
    assert hass.states.get(ACTIVE).state == "quiet"
    mqtt_fake.deliver(f"{PREFIX}/profile", "unknown")  # the controller stopped reporting
    await hass.async_block_till_done()
    assert hass.states.get(ACTIVE).state == STATE_UNKNOWN
    mqtt_fake.deliver(f"{PREFIX}/profile", "normal")
    mqtt_fake.deliver(f"{PREFIX}/availability", "offline", retain=True)
    await hass.async_block_till_done()
    assert hass.states.get(LINK).state == STATE_OFF
    assert hass.states.get(ACTIVE).state == STATE_UNKNOWN  # stale value dropped when the bridge is gone


async def test_telemetry_creates_sensors(hass, mqtt_fake):
    await setup(hass, mqtt_fake)
    assert hass.states.get(CPU) is None  # nothing yet
    mqtt_fake.deliver(f"{PREFIX}/telemetry", json.dumps(TELEMETRY))
    await hass.async_block_till_done()
    assert float(hass.states.get(CPU).state) == 42.25
    assert hass.states.get(CPU).attributes["unit_of_measurement"] == "°C"
    assert hass.states.get(CPU).attributes["friendly_name"] == "SR655 Fan Control CPU temperature"
    assert float(hass.states.get("sensor.sr655_fan_control_hdd_temperature").state) == 40.0
    assert hass.states.get("sensor.sr655_fan_control_nvme_temperature").attributes["friendly_name"].endswith("NVMe temperature")
    assert hass.states.get(FAN1).state == "5" and hass.states.get(FAN1).attributes["unit_of_measurement"] == "%"
    assert hass.states.get("sensor.sr655_fan_control_fan_6_speed").state == "7"
    assert hass.states.get(PROBLEM).state == STATE_OFF
    assert hass.states.get(ACTIVE).attributes["source"] == "ha"  # why the NAS runs this profile
    assert hass.states.get(ACTIVE).state == STATE_UNKNOWN  # the plain profile topic has not been heard yet


async def test_new_sensor_in_later_telemetry_is_added_once(hass, mqtt_fake):
    await setup(hass, mqtt_fake)
    mqtt_fake.deliver(f"{PREFIX}/telemetry", json.dumps(TELEMETRY))
    await hass.async_block_till_done()
    count = len(hass.states.async_entity_ids("sensor"))
    more = {**TELEMETRY, "temps": {**TELEMETRY["temps"], "gpu": 55.0}}
    mqtt_fake.deliver(f"{PREFIX}/telemetry", json.dumps(more))
    mqtt_fake.deliver(f"{PREFIX}/telemetry", json.dumps(more))
    await hass.async_block_till_done()
    assert len(hass.states.async_entity_ids("sensor")) == count + 1
    assert float(hass.states.get("sensor.sr655_fan_control_gpu_temperature").state) == 55.0


async def test_problem_sensor_when_the_controller_reports_an_error(hass, mqtt_fake):
    await setup(hass, mqtt_fake)
    failing = {"ok": False, "profile": "normal", "source": "fallback: no request from HA", "error": "sensor hdd unavailable"}
    mqtt_fake.deliver(f"{PREFIX}/telemetry", json.dumps(failing))
    await hass.async_block_till_done()
    assert hass.states.get(PROBLEM).state == STATE_ON
    assert hass.states.get(PROBLEM).attributes["error"] == "sensor hdd unavailable"
    mqtt_fake.deliver(f"{PREFIX}/telemetry", json.dumps({"ok": False, "profile": "unknown", "error": "controller is not reporting"}))
    await hass.async_block_till_done()
    assert hass.states.get(PROBLEM).state == STATE_ON
    mqtt_fake.deliver(f"{PREFIX}/telemetry", json.dumps(TELEMETRY))
    await hass.async_block_till_done()
    assert hass.states.get(PROBLEM).state == STATE_OFF


async def test_sensors_without_a_value_become_unavailable(hass, mqtt_fake):
    await setup(hass, mqtt_fake)
    mqtt_fake.deliver(f"{PREFIX}/telemetry", json.dumps(TELEMETRY))
    await hass.async_block_till_done()
    mqtt_fake.deliver(f"{PREFIX}/telemetry", json.dumps({"ok": False, "profile": "unknown", "error": "x"}))
    await hass.async_block_till_done()
    assert hass.states.get(CPU).state == STATE_UNAVAILABLE
    assert hass.states.get(FAN1).state == STATE_UNAVAILABLE


async def test_silence_from_the_nas_expires_the_telemetry(hass, mqtt_fake, freezer):
    await setup(hass, mqtt_fake)
    mqtt_fake.deliver(f"{PREFIX}/availability", "online")
    mqtt_fake.deliver(f"{PREFIX}/profile", "quiet")
    mqtt_fake.deliver(f"{PREFIX}/telemetry", json.dumps(TELEMETRY))
    await hass.async_block_till_done()
    await tick(hass, freezer, 90)
    assert hass.states.get(CPU).state != STATE_UNAVAILABLE  # still within the 120 s window
    await tick(hass, freezer, 60)
    assert hass.states.get(CPU).state == STATE_UNAVAILABLE
    assert hass.states.get(ACTIVE).state == STATE_UNKNOWN
    assert hass.states.get(PROBLEM).state == STATE_UNKNOWN


async def test_garbage_telemetry_is_ignored(hass, mqtt_fake):
    await setup(hass, mqtt_fake)
    for payload in ("{not json", "[1, 2]", "42", ""):
        mqtt_fake.deliver(f"{PREFIX}/telemetry", payload)
    await hass.async_block_till_done()
    assert hass.states.get(CPU) is None


async def test_publish_failures_are_survived_and_logged_once(hass, mqtt_fake, freezer, caplog):
    await setup(hass, mqtt_fake)
    mqtt_fake.fail = True
    with caplog.at_level(logging.INFO):
        for _ in range(3):
            await tick(hass, freezer, 30)
        assert sum("Could not publish" in r.message for r in caplog.records) == 1
        mqtt_fake.fail = False
        await tick(hass, freezer, 30)
        assert any("works again" in r.message for r in caplog.records)
    assert mqtt_fake.profiles()[-1] == "quiet"
    assert hass.states.get(REQUESTED).state == "quiet"


async def test_unload_stops_the_heartbeat_so_the_nas_falls_back(hass, mqtt_fake, freezer):
    entry = await setup(hass, mqtt_fake)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    n = len(mqtt_fake.published)
    await tick(hass, freezer, 120)
    hass.states.async_set(PRESENCE, STATE_OFF)
    await hass.async_block_till_done()
    assert len(mqtt_fake.published) == n
    assert mqtt_fake.subscriptions == {}


async def test_two_servers_are_independent(hass, mqtt_fake):
    await setup(hass, mqtt_fake, presence="on")
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from custom_components.sr655_fan_control.const import CONF_AWAY_DELAY, CONF_HEARTBEAT, CONF_PRESENCE_ENTITY, CONF_TOPIC_PREFIX

    other = MockConfigEntry(
        domain=DOMAIN, title="Second NAS", unique_id="homeassistant/sr655-b",
        data={CONF_TOPIC_PREFIX: "homeassistant/sr655-b"},
        options={CONF_PRESENCE_ENTITY: PRESENCE, CONF_AWAY_DELAY: 10, CONF_HEARTBEAT: 30},
    )
    other.add_to_hass(hass)
    assert await hass.config_entries.async_setup(other.entry_id)
    await hass.async_block_till_done()
    assert ("homeassistant/sr655-b/profile/set", "quiet", False) in mqtt_fake.published
    assert hass.states.get("select.second_nas_mode") is not None


# --- contract: payloads produced by the real NAS-side bridge (tests/fixtures) -------------
# Generated by running the real controller, then ha_bridge.telemetry() on its state.json.
def _fixture(name: str) -> str:
    from pathlib import Path

    return (Path(__file__).parent / "fixtures" / f"bridge_telemetry_{name}.json").read_text()


async def test_real_bridge_payload_healthy(hass, mqtt_fake):
    await setup(hass, mqtt_fake)
    mqtt_fake.deliver(f"{PREFIX}/telemetry", _fixture("ok"))
    await hass.async_block_till_done()
    assert float(hass.states.get(CPU).state) == 42.25
    assert float(hass.states.get("sensor.sr655_fan_control_hdd_temperature").state) == 40.0
    assert {hass.states.get(f"sensor.sr655_fan_control_fan_{n}_speed").state for n in range(1, 7)} == {"50"}
    assert hass.states.get(PROBLEM).state == STATE_OFF
    assert hass.states.get(ACTIVE).attributes["source"] == "cli"


async def test_real_bridge_payload_controller_error(hass, mqtt_fake):
    await setup(hass, mqtt_fake)
    mqtt_fake.deliver(f"{PREFIX}/telemetry", _fixture("ok"))
    mqtt_fake.deliver(f"{PREFIX}/telemetry", _fixture("error"))
    await hass.async_block_till_done()
    assert hass.states.get(PROBLEM).state == STATE_ON
    assert "failed" in hass.states.get(PROBLEM).attributes["error"]
    assert hass.states.get(CPU).state == STATE_UNAVAILABLE  # no readings while the controller is in failsafe


async def test_real_bridge_payload_when_the_controller_is_silent(hass, mqtt_fake):
    await setup(hass, mqtt_fake)
    mqtt_fake.deliver(f"{PREFIX}/telemetry", _fixture("ok"))
    mqtt_fake.deliver(f"{PREFIX}/telemetry", _fixture("stale"))
    await hass.async_block_till_done()
    assert hass.states.get(PROBLEM).state == STATE_ON
    assert hass.states.get(PROBLEM).attributes["error"] == "controller is not reporting"


async def test_long_error_text_is_truncated(hass, mqtt_fake):
    await setup(hass, mqtt_fake)
    mqtt_fake.deliver(f"{PREFIX}/telemetry", json.dumps({"ok": False, "error": "Traceback\n" + "x" * 5000}))
    await hass.async_block_till_done()
    assert len(hass.states.get(PROBLEM).attributes["error"]) == 255
