import os
import time
import threading
from dataclasses import dataclass
from typing import Optional, List

import yaml
import requests
import paho.mqtt.client as mqtt

try:
    from aydsko.iracingdata import DataClient
    HAS_DATA = True
except Exception:  # pragma: no cover - library optional
    HAS_DATA = False


# ------------------------- helpers -------------------------

def fmt_laptime(seconds: float) -> str:
    """Format seconds as M:SS.ss"""
    try:
        seconds = float(seconds)
    except Exception:
        return str(seconds)
    m = int(seconds // 60)
    s = seconds % 60
    return f"{m}:{s:05.2f}"


@dataclass
class Driver:
    name: str
    iracing_id: int
    discord_id: Optional[str] = None
    enabled: bool = True


@dataclass
class LiveState:
    series: str = ""
    track: str = ""
    session_type: str = ""
    flag: str = ""
    field_size: Optional[int] = None
    subsession_id: Optional[int] = None
    lap: int = 0
    last_lap_time: float = 0.0
    pos: Optional[int] = None
    prev_pos: Optional[int] = None
    incidents: int = 0
    posted_joined: bool = False
    posted_green: bool = False
    last_posted_lap: int = -1


# ------------------------- configuration -------------------------

def load_config():
    with open("config/settings.yaml", "r") as f:
        settings = yaml.safe_load(f) or {}
    with open("config/drivers.yaml", "r") as f:
        dcfg = yaml.safe_load(f) or {}
    drivers = []
    for d in dcfg.get("drivers", []):
        if not d.get("enabled", True):
            continue
        drivers.append(
            Driver(
                name=str(d.get("name", "Driver")),
                iracing_id=int(d.get("iracing_id", 0)),
                discord_id=str(d.get("discord_id")) if d.get("discord_id") else None,
            )
        )
    settings.setdefault("mqtt", {})
    settings.setdefault("discord", {})
    settings.setdefault("runtime", {})
    settings["ir_email"] = os.getenv("IRACING_EMAIL")
    settings["ir_password"] = os.getenv("IRACING_PASSWORD")
    return settings, drivers


# ------------------------- Discord -------------------------

def post_discord(webhook: str, content: str):
    if not webhook or "REPLACE_ME" in webhook:
        print("[INFO] Discord webhook not configured; message was:\n", content)
        return
    try:
        r = requests.post(webhook, json={"content": content}, timeout=10)
        if r.status_code >= 300:
            print("[WARN] Discord post failed", r.status_code, r.text)
    except Exception as exc:  # pragma: no cover - network errors
        print("[ERR] Discord post error", exc)


# ------------------------- MQTT bridge -------------------------

class Bridge:
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

    def __init__(self, settings, drivers: List[Driver]):
        self.settings = settings
        self.drivers = drivers
        self.state = LiveState()
        self.prefix = settings.get("mqtt", {}).get("prefix", "").rstrip("/")
        self.webhook = settings.get("discord", {}).get("webhook", "")
        client_id = settings.get("mqtt", {}).get("client_id", "ir2discord")
        self.client = mqtt.Client(client_id=client_id)
        user = settings.get("mqtt", {}).get("username")
        pwd = settings.get("mqtt", {}).get("password")
        if user:
            self.client.username_pw_set(user, pwd or None)
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message

    # ---- MQTT callbacks ----
    def on_connect(self, client, userdata, flags, rc):  # pragma: no cover
        for t in self.TOPICS:
            client.subscribe(f"{self.prefix}/{t}")

    def on_message(self, client, userdata, msg):  # pragma: no cover
        key = msg.topic[len(self.prefix) + 1:]
        payload = msg.payload.decode("utf-8", errors="ignore")
        st = self.state

        if key == "session/series_name":
            st.series = payload
        elif key == "session/track_name":
            st.track = payload
        elif key == "session/session_type":
            st.session_type = payload
            if payload.lower() in {"practice", "qualify", "race"} and not st.posted_joined:
                post_discord(self.webhook, f"**Joined {payload}** — {st.series} @ {st.track}")
                st.posted_joined = True
        elif key == "session/flag":
            st.flag = payload
            if payload.lower() == "green" and not st.posted_green:
                post_discord(self.webhook, "🟢 **Green Flag**")
                st.posted_green = True
            if payload.lower() == "checkered":
                pos = st.pos if st.pos is not None else "?"
                field = st.field_size if st.field_size is not None else "?"
                post_discord(
                    self.webhook,
                    f"🏁 Finished P{pos} of {field} with {st.incidents}x",
                )
                if self.settings.get("runtime", {}).get("post_official", True):
                    threading.Thread(target=self.post_official_results, daemon=True).start()
        elif key == "session/field_size":
            try:
                st.field_size = int(float(payload))
            except Exception:
                st.field_size = None
        elif key == "session/subsession_id":
            try:
                st.subsession_id = int(float(payload))
            except Exception:
                st.subsession_id = None
        elif key == "player/lap":
            try:
                l = int(float(payload))
            except Exception:
                return
            st.lap = l
            if l > 0 and l != st.last_posted_lap:
                pos = st.pos or 0
                prev = st.prev_pos or pos
                delta = prev - pos
                lap_str = fmt_laptime(st.last_lap_time)
                post_discord(
                    self.webhook,
                    f"Lap {l} — {lap_str} / Incidents {st.incidents} / Position {pos} ({delta:+})",
                )
                st.last_posted_lap = l
                st.prev_pos = pos
        elif key == "player/last_lap_time":
            try:
                st.last_lap_time = float(payload)
            except Exception:
                pass
        elif key == "player/position":
            try:
                st.pos = int(float(payload))
            except Exception:
                st.pos = None
        elif key == "player/incidents":
            try:
                st.incidents = int(float(payload))
            except Exception:
                pass
        elif key == "qualify/position":
            try:
                qp = int(float(payload))
            except Exception:
                qp = 0
            if qp > 0:
                lap_str = fmt_laptime(st.last_lap_time)
                post_discord(self.webhook, f"Qualified P{qp} with a {lap_str}")
        elif key == "qualify/best_laptime":
            try:
                st.last_lap_time = float(payload)
            except Exception:
                pass

    # ---- official results ----
    def post_official_results(self):  # pragma: no cover - relies on network
        if not HAS_DATA:
            print("[INFO] aydsko-iracingdata not installed; skipping official results")
            return
        email = self.settings.get("ir_email")
        pwd = self.settings.get("ir_password")
        sub = self.state.subsession_id
        if not (email and pwd and sub):
            print("[INFO] missing credentials or subsession_id; skipping official results")
            return
        try:
            with DataClient(logon_email=email, logon_password=pwd) as client:
                data = None
                for _ in range(30):
                    try:
                        r = client.GetSubsessionResultsAsync(int(sub)).result()
                        data = getattr(r, "Data", r)
                        if data:
                            break
                    except Exception:
                        time.sleep(10)
                if not data:
                    print("[WARN] results not ready")
                    return
                simsessions = data.get("simsession_results") or []
                first = simsessions[0] if simsessions else {}
                sof = first.get("strength_of_field")
                field = data.get("num_drivers") or first.get("results_num_drivers") or "?"
                sess_results = data.get("session_results") or []
                race = None
                for s in sess_results:
                    if str(s.get("simsession_type_name", "")).lower().startswith("race"):
                        race = s
                if race is None and sess_results:
                    race = sess_results[-1]
                lines = [f"**{field} Cars — SOF {sof}**"]
                tracked = {d.iracing_id: d for d in self.drivers}
                if race and "results" in race:
                    for m in race["results"]:
                        cid = int(m.get("cust_id", 0) or 0)
                        if cid in tracked:
                            dr = tracked[cid]
                            label = f"<@{dr.discord_id}>" if dr.discord_id else dr.name
                            new_ir = m.get("newi_rating")
                            old_ir = m.get("oldi_rating")
                            ir_delta = (new_ir - old_ir) if None not in (new_ir, old_ir) else 0
                            new_sr = (m.get("new_sub_level") or 0) / 100.0
                            old_sr = (m.get("old_sub_level") or 0) / 100.0
                            sr_delta = new_sr - old_sr
                            pos = m.get("finish_position") or m.get("position") or "?"
                            incidents = m.get("incidents", 0)
                            lines.append(
                                f"**{label}** — P{pos}, {incidents}x — {new_ir} ({ir_delta:+}) iRating — {new_sr:.2f} ({sr_delta:+.2f}) SR"
                            )
                post_discord(self.webhook, "\n".join(lines))
        except Exception as exc:
            print("[ERR] official results failure", exc)

    def run(self):  # pragma: no cover
        host = self.settings.get("mqtt", {}).get("host", "localhost")
        port = int(self.settings.get("mqtt", {}).get("port", 1883))
        self.client.connect(host, port)
        self.client.loop_forever()


def main():  # pragma: no cover
    settings, drivers = load_config()
    bridge = Bridge(settings, drivers)
    bridge.run()


if __name__ == "__main__":  # pragma: no cover
    main()
