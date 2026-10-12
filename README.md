# SR655 Fan Control for Home Assistant

Home Assistant side of a fan controller for a Lenovo ThinkSystem SR655 running TrueNAS SCALE. The controller on the NAS owns the fan curves and all safety logic; Home Assistant only chooses between its **quiet** and **normal** profiles and shows what the NAS is doing. Nothing here can change a fan speed directly.

* **Presence-driven.** Quiet while a presence entity is on or home; normal once everyone has been away for a configurable time.
* **Heartbeat built in.** The profile is re-sent every 30 s. The NAS falls back to normal after 120 s without a request, so a stopped Home Assistant, broker or network never leaves the server in quiet mode. No automation is needed.
* **Manual override.** A *Mode* select: Auto (follow presence), Quiet, or Normal. The choice survives restarts.
* **Visibility.** Requested and active profile, CPU / HDD / NVMe temperatures, per-fan speeds, a NAS link sensor and a controller problem sensor.

It needs the NAS-side package (`sr655-fan-control-ha`, a separate download) running and the **MQTT** integration set up in Home Assistant.

## Install

**With HACS** (as a custom repository; it does not appear in the default store):

1. In HACS open the ⋮ menu → *Custom repositories*.
2. Repository: `https://github.com/yihuigu/ha-sr655-fan-control`, type: *Integration*, then *Add*.
3. Find *SR655 Fan Control* in HACS, *Download*, and restart Home Assistant.

HACS follows this repository's GitHub releases, so it offers updates when a new version is released. HACS can only use public repositories.

**Manually:** copy `custom_components/sr655_fan_control/` into `<config>/custom_components/` and restart Home Assistant. Repeat for updates.

## Set up

*Settings → Devices & services → Add integration → SR655 Fan Control.*

| Field | Meaning |
|---|---|
| Name | Device name; also prefixes the entity names. |
| MQTT topic prefix | Default `homeassistant/sr655`. Must match the topics in the NAS package's `config.json` (below). |
| Presence entity | A `binary_sensor`, `person`, `device_tracker`, `group` or `input_boolean`. On or `home` counts as present. |
| Quiet for this long after the last person leaves | Minutes, default 10. `0` switches to normal the moment everyone has left. |
| Heartbeat interval | Seconds, default 30, range 5–60. Keep it well below the NAS fallback (120 s). |

Presence, delay and heartbeat can be changed later under *Configure*. A second NAS can be added with a different topic prefix.

## What the profile logic does

* Mode **Quiet** or **Normal** forces that profile and ignores presence; the heartbeat keeps running, so a forced mode still lapses if Home Assistant dies.
* Mode **Auto**: present means quiet. After the last person leaves, quiet continues for the delay, then normal.
* A presence entity that is `unavailable` or `unknown` counts as away, with the same delay. A presence entity that does not exist means normal.
* Only a change of the presence entity's *state* triggers a publish; GPS attribute updates do not.
* Unloading the integration stops the heartbeat, which hands control back to the NAS fallback.

## Entities

| Entity | Notes |
|---|---|
| `select` Mode | Auto / Quiet / Normal. |
| `sensor` Requested profile | What this integration is publishing. |
| `sensor` Active profile | What the NAS controller reports running; attribute `source` says why (`ha`, `fallback: request expired`, ...). `unknown` if the controller is silent. |
| `sensor` *Name* temperature | One per sensor the NAS reports (CPU, HDD, NVMe, ...), created when first seen. |
| `sensor` Fan *n* speed | Commanded fan speed in %, one per fan. |
| `binary_sensor` NAS link | The bridge's availability topic (its MQTT last-will makes this reliable). |
| `binary_sensor` Controller problem | On when the controller reports an error, which means the fans are at the failsafe speed, or has stopped reporting. Attribute `error`. |

If the NAS stops reporting for 120 s its temperature and fan sensors become unavailable.

## MQTT contract

With prefix `P` (all QoS 0, none retained except availability):

| Topic | Direction | Payload |
|---|---|---|
| `P/profile/set` | HA → NAS | `quiet` or `normal`, repeated every heartbeat |
| `P/profile` | NAS → HA | `quiet`, `normal` or `unknown`, every 30 s |
| `P/availability` | NAS → HA | `online` / `offline` (retained, last-will) |
| `P/telemetry` | NAS → HA | JSON, every 30 s: `{"ok": true, "profile": "quiet", "source": "ha", "temps": {"cpu": 42.25, ...}, "fans": {"1": 5, ...}, "error": null}` |

In the NAS package these are `integration.mqtt.command_topic`, `state_topic`, `availability_topic` and `telemetry_topic`. Do not publish the command with *retain*: the NAS bridge ignores retained messages because they say nothing about whether Home Assistant is alive.

## Troubleshooting

* *Requested profile* changes but *Active profile* stays `unknown`: the NAS bridge is not receiving, or the controller is not running. Check *NAS link*, the broker, and `fanctl.log` on the NAS.
* *Active profile* says `fallback: request expired`: requests are not arriving often enough. Check the heartbeat interval and that both sides use the same broker and prefix.
* Nothing is published: the MQTT integration must be connected; the log shows `Could not publish the fan profile` once per outage.

## Development

```bash
pip install -r requirements_test.txt
pytest
```

The tests run against the real Home Assistant core (via `pytest-homeassistant-custom-component`). `tests/test_real_mqtt.py` connects Home Assistant's own MQTT integration to a small in-process broker over a real socket. `tests/fixtures/` holds payloads produced by running the real NAS-side bridge on real controller output, so the two sides are tested against each other. The workflows in `.github/workflows` (hassfest, HACS validation, pytest) have not been run.

Tested with Home Assistant 2026.2.3 on Python 3.13. Brand images (`brand/`) need Home Assistant 2026.3 or newer to be shown; older versions ignore them.
