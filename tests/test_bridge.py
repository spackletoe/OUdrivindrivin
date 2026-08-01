"""Lightweight tests for session state and MQTT event mapping."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from models import LiveState
from mqtt_bridge import MqttBridge
from util import fmt_laptime


class FakeMsg:
    def __init__(self, topic: str, payload: str):
        self.topic = topic
        self.payload = payload.encode("utf-8")


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        settings = {
            "mqtt": {"prefix": "uRacing", "client_id": "test"},
            "runtime": {"post_official": True, "post_laps": True, "post_qualify": True},
        }
        self.bridge = MqttBridge(settings, [], on_event=self.events.append)

    def pub(self, key: str, payload: str):
        self.bridge.on_message(None, None, FakeMsg(f"uRacing/{key}", payload))

    def test_fmt_laptime(self):
        self.assertEqual(fmt_laptime(92.68), "1:32.68")

    def test_join_green_lap_checkered(self):
        self.pub("session/series_name", "FIA F4")
        self.pub("session/track_name", "COTA")
        self.pub("session/session_type", "Race")
        self.pub("session/flag", "green")
        self.pub("player/last_lap_time", "92.68")
        self.pub("player/position", "7")
        self.pub("player/incidents", "0")
        self.pub("player/lap", "1")
        self.pub("session/field_size", "12")
        self.pub("session/subsession_id", "99")
        self.pub("session/flag", "checkered")
        # duplicate checkered should not re-post
        self.pub("session/flag", "checkered")

        contents = [e["content"] for e in self.events]
        self.assertTrue(any("Joined Race" in c for c in contents))
        self.assertTrue(any("Green Flag" in c for c in contents))
        self.assertTrue(any(c.startswith("Lap 1") for c in contents))
        checkered = [e for e in self.events if "Finished" in e["content"]]
        self.assertEqual(len(checkered), 1)
        self.assertTrue(checkered[0]["request_official"])

    def test_subsession_resets_flags(self):
        self.pub("session/session_type", "Race")
        self.assertTrue(self.bridge.state.posted_joined)
        self.pub("session/subsession_id", "1")
        self.pub("session/subsession_id", "2")
        self.assertFalse(self.bridge.state.posted_joined)
        self.assertEqual(self.bridge.state.subsession_id, 2)

    def test_qualify_once(self):
        self.pub("qualify/best_laptime", "91.5")
        self.pub("qualify/position", "3")
        self.pub("qualify/position", "3")
        qualify = [e for e in self.events if e["content"].startswith("Qualified")]
        self.assertEqual(len(qualify), 1)

    def test_begin_new_session(self):
        st = LiveState(series="A", track="B", posted_green=True, lap=4)
        st.begin_new_session(series="A", track="B", subsession_id=5)
        self.assertFalse(st.posted_green)
        self.assertEqual(st.lap, 0)
        self.assertEqual(st.subsession_id, 5)


if __name__ == "__main__":
    unittest.main()
