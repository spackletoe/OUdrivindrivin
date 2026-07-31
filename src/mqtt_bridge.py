"""MQTT subscription layer that turns ir2mqtt topics into race events."""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Dict, List, Optional

import paho.mqtt.client as mqtt

from models import Driver, LiveState
from util import fmt_laptime

log = logging.getLogger("oudrivin.mqtt")

# Events are plain dicts: {"type": "...", "content": "...", "request_official": bool}
EventCallback = Callable[[Dict[str, Any]], None]


class MqttBridge:
    TOPICS = [
        "session/series_name",
        "session/track_name",
        "session/session_type",
        "session/flag",
        "session/field_size",
        "session/subsession_id",
        "player/lap",
        "player/last_lap_time",
        "player/position",
        "player/incidents",
        "qualify/position",
        "qualify/best_laptime",
    ]

    def __init__(
        self,
        settings: Dict[str, Any],
        drivers: List[Driver],
        on_event: EventCallback,
    ):
        self.settings = settings
        self.drivers = drivers
        self.on_event = on_event
        self.state = LiveState()
        self.prefix = settings.get("mqtt", {}).get("prefix", "").rstrip("/")
        client_id = settings.get("mqtt", {}).get("client_id", "ou-race-bot")
        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
        )
        user = settings.get("mqtt", {}).get("username")
        pwd = settings.get("mqtt", {}).get("password")
        if user:
            self.client.username_pw_set(user, pwd or None)
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = self.on_message
        self._thread: Optional[threading.Thread] = None

    def emit(self, content: str, *, request_official: bool = False) -> None:
        self.on_event(
            {
                "type": "message",
                "content": content,
                "request_official": request_official,
                "subsession_id": self.state.subsession_id,
            }
        )

    def on_connect(self, client, userdata, flags, reason_code, properties=None):  # pragma: no cover
        failed = getattr(reason_code, "is_failure", None)
        if failed is True or (isinstance(reason_code, int) and reason_code != 0):
            log.error("MQTT connect failed reason=%s", reason_code)
            return
        log.info("MQTT connected; subscribing under %s/", self.prefix)
        for t in self.TOPICS:
            client.subscribe(f"{self.prefix}/{t}")

    def on_disconnect(self, client, userdata, flags, reason_code, properties=None):  # pragma: no cover
        log.warning("MQTT disconnected reason=%s", reason_code)

    def _maybe_new_subsession(self, new_id: int) -> None:
        if self.state.subsession_id and self.state.subsession_id != new_id:
            log.info("new subsession_id %s (was %s); resetting session state", new_id, self.state.subsession_id)
            self.state.begin_new_session(subsession_id=new_id)
        else:
            self.state.subsession_id = new_id

    def on_message(self, client, userdata, msg):  # pragma: no cover
        key = msg.topic[len(self.prefix) + 1 :]
        payload = msg.payload.decode("utf-8", errors="ignore").strip()
        st = self.state
        runtime = self.settings.get("runtime", {}) or {}

        if key == "session/series_name":
            if st.series and payload and payload != st.series and st.posted_joined:
                st.begin_new_session(series=payload, track=st.track)
            else:
                st.series = payload
        elif key == "session/track_name":
            if st.track and payload and payload != st.track and st.posted_joined:
                st.begin_new_session(series=st.series, track=payload)
            else:
                st.track = payload
        elif key == "session/session_type":
            st.session_type = payload
            if payload.lower() in {"practice", "qualify", "race"} and not st.posted_joined:
                self.emit(f"**Joined {payload}** — {st.series} @ {st.track}")
                st.posted_joined = True
        elif key == "session/flag":
            st.flag = payload
            flag = payload.lower()
            if flag == "green" and not st.posted_green:
                self.emit("🟢 **Green Flag**")
                st.posted_green = True
            elif flag == "checkered" and not st.posted_checkered:
                pos = st.pos if st.pos is not None else "?"
                field = st.field_size if st.field_size is not None else "?"
                want_official = bool(runtime.get("post_official", True))
                self.emit(
                    f"🏁 Finished P{pos} of {field} with {st.incidents}x",
                    request_official=want_official,
                )
                st.posted_checkered = True
        elif key == "session/field_size":
            try:
                st.field_size = int(float(payload))
            except (TypeError, ValueError):
                st.field_size = None
        elif key == "session/subsession_id":
            try:
                self._maybe_new_subsession(int(float(payload)))
            except (TypeError, ValueError):
                pass
        elif key == "player/lap":
            if not runtime.get("post_laps", True):
                return
            try:
                lap = int(float(payload))
            except (TypeError, ValueError):
                return
            st.lap = lap
            if lap > 0 and lap != st.last_posted_lap:
                pos = st.pos or 0
                prev = st.prev_pos or pos
                delta = prev - pos
                lap_str = fmt_laptime(st.last_lap_time)
                self.emit(
                    f"Lap {lap} — {lap_str} / Incidents {st.incidents} / Position {pos} ({delta:+})"
                )
                st.last_posted_lap = lap
                st.prev_pos = pos
        elif key == "player/last_lap_time":
            try:
                st.last_lap_time = float(payload)
            except (TypeError, ValueError):
                pass
        elif key == "player/position":
            try:
                st.pos = int(float(payload))
            except (TypeError, ValueError):
                st.pos = None
        elif key == "player/incidents":
            try:
                st.incidents = int(float(payload))
            except (TypeError, ValueError):
                pass
        elif key == "qualify/best_laptime":
            try:
                st.qualify_best = float(payload)
                st.last_lap_time = st.qualify_best
            except (TypeError, ValueError):
                pass
        elif key == "qualify/position":
            if not runtime.get("post_qualify", True):
                return
            if st.posted_qualify:
                return
            try:
                qp = int(float(payload))
            except (TypeError, ValueError):
                qp = 0
            if qp > 0:
                best = st.qualify_best or st.last_lap_time
                self.emit(f"Qualified P{qp} with a {fmt_laptime(best)}")
                st.posted_qualify = True

    def start_background(self) -> None:
        host = self.settings.get("mqtt", {}).get("host", "localhost")
        port = int(self.settings.get("mqtt", {}).get("port", 1883))
        log.info("connecting MQTT %s:%s", host, port)
        self.client.connect(host, port)
        self._thread = threading.Thread(target=self.client.loop_forever, name="mqtt", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        try:
            self.client.disconnect()
        except Exception:
            pass
