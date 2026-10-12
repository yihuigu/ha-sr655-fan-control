"""The integration over a real socket: Home Assistant's own MQTT integration talking to a broker.

The broker is a minimal MQTT 3.1.1 implementation that records what it receives and lets the
test push messages to HA, so nothing about HA's publish/subscribe API is faked here.
"""

import asyncio
from pathlib import Path
import socket
import threading
from unittest.mock import AsyncMock, patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.const import STATE_OFF, STATE_ON

from .conftest import PREFIX, PRESENCE, make_entry

CPU = "sensor.sr655_fan_control_cpu_temperature"
LINK = "binary_sensor.sr655_fan_control_nas_link"
ACTIVE = "sensor.sr655_fan_control_active_profile"
PROBLEM = "binary_sensor.sr655_fan_control_controller_problem"
FIXTURES = Path(__file__).parent / "fixtures"


def _varlen(n: int) -> bytes:
    out = b""
    while True:
        n, d = divmod(n, 128)
        out += bytes([d | (128 if n else 0)])
        if not n:
            return out


def _publish_packet(topic: str, payload: str) -> bytes:
    t = topic.encode()
    body = len(t).to_bytes(2, "big") + t + payload.encode()
    return bytes([0x30]) + _varlen(len(body)) + body


class Broker:
    def __init__(self) -> None:
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(5)
        self.port = self.srv.getsockname()[1]
        self.received: list[tuple[str, str]] = []
        self.subscribed: set[str] = set()
        self._clients: list[socket.socket] = []
        self._threads = [threading.Thread(target=self._accept, daemon=True)]
        self._threads[0].start()

    def _accept(self) -> None:
        while True:
            try:
                c, _ = self.srv.accept()
            except OSError:
                return
            self._clients.append(c)
            t = threading.Thread(target=self._serve, args=(c,), daemon=True)
            self._threads.append(t)
            t.start()

    @staticmethod
    def _read(c: socket.socket, n: int) -> bytes:
        data = b""
        while len(data) < n:
            chunk = c.recv(n - len(data))
            if not chunk:
                raise OSError("closed")
            data += chunk
        return data

    def _serve(self, c: socket.socket) -> None:
        try:
            while True:
                first = self._read(c, 1)[0]
                mult, length = 1, 0
                while True:
                    d = self._read(c, 1)[0]
                    length += (d & 127) * mult
                    if not d & 128:
                        break
                    mult *= 128
                body = self._read(c, length) if length else b""
                kind = first >> 4
                if kind == 1:  # CONNECT
                    c.sendall(bytes([0x20, 2, 0, 0]))
                elif kind == 8:  # SUBSCRIBE
                    i, granted = 2, b""
                    while i < len(body):
                        tl = int.from_bytes(body[i : i + 2], "big")
                        self.subscribed.add(body[i + 2 : i + 2 + tl].decode())
                        granted += b"\x00"
                        i += 3 + tl
                    c.sendall(bytes([0x90, 2 + len(granted)]) + body[:2] + granted)
                elif kind == 10:  # UNSUBSCRIBE
                    c.sendall(bytes([0xB0, 2]) + body[:2])
                elif kind == 3:  # PUBLISH (QoS 0 from HA for our topics)
                    tl = int.from_bytes(body[:2], "big")
                    self.received.append((body[2 : 2 + tl].decode(), body[2 + tl :].decode()))
                elif kind == 12:
                    c.sendall(bytes([0xD0, 0]))
                elif kind == 14:
                    return
        except OSError:
            return

    def push(self, topic: str, payload: str) -> None:
        for c in self._clients:
            try:
                c.sendall(_publish_packet(topic, payload))
            except OSError:
                pass

    def close(self) -> None:
        try:
            self.srv.shutdown(socket.SHUT_RDWR)  # wakes the blocked accept()
        except OSError:
            pass
        self.srv.close()
        for c in self._clients:
            try:
                c.shutdown(socket.SHUT_RDWR)
                c.close()
            except OSError:
                pass
        for t in list(self._threads):
            t.join(timeout=3)


async def until(cond, timeout: float = 8.0) -> None:
    for _ in range(int(timeout / 0.05)):
        if cond():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("condition not met in time")


def requests(broker: Broker) -> list[str]:
    return [p for t, p in broker.received if t == f"{PREFIX}/profile/set"]


async def test_full_round_trip_over_a_real_mqtt_connection(hass, socket_enabled):
    # The test config dir has no configuration.yaml, which HA's MQTT setup reads.
    with patch("homeassistant.config.async_hass_config_yaml", AsyncMock(return_value={})):
        await _round_trip(hass)


async def _round_trip(hass):
    broker = Broker()
    mqtt_entry = MockConfigEntry(domain="mqtt", data={"broker": "127.0.0.1", "port": broker.port}, version=1, minor_version=2)
    mqtt_entry.add_to_hass(hass)
    try:
        assert await hass.config_entries.async_setup(mqtt_entry.entry_id)
        await hass.async_block_till_done()

        hass.states.async_set(PRESENCE, "on")
        entry = make_entry(away_delay=0)  # 'away' means normal immediately
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        # HA -> NAS: the profile arrives on the command topic, as plain text, not retained.
        await until(lambda: requests(broker) == ["quiet"])
        # ...and the integration subscribed to the three topics the bridge publishes on.
        await until(lambda: {f"{PREFIX}/availability", f"{PREFIX}/profile", f"{PREFIX}/telemetry"} <= broker.subscribed)

        # A presence change is published at once.
        n = len(requests(broker))
        hass.states.async_set(PRESENCE, "off")
        await until(lambda: requests(broker)[n:] == ["normal"])
        hass.states.async_set(PRESENCE, "on")
        await until(lambda: requests(broker)[-1] == "quiet")

        # NAS -> HA: what the real bridge publishes.
        broker.push(f"{PREFIX}/availability", "online")
        broker.push(f"{PREFIX}/profile", "quiet")
        broker.push(f"{PREFIX}/telemetry", (FIXTURES / "bridge_telemetry_ok.json").read_text())
        await until(lambda: hass.states.get(LINK) and hass.states.get(LINK).state == STATE_ON)
        await until(lambda: hass.states.get(ACTIVE).state == "quiet")
        await until(lambda: hass.states.get(CPU) is not None and float(hass.states.get(CPU).state) == 42.25)
        assert hass.states.get(PROBLEM).state == STATE_OFF

        broker.push(f"{PREFIX}/availability", "offline")
        await until(lambda: hass.states.get(LINK).state == STATE_OFF)

        # Unloading stops the heartbeat and unsubscribes cleanly.
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
    finally:
        await hass.config_entries.async_unload(mqtt_entry.entry_id)
        await hass.async_block_till_done()
        broker.close()
