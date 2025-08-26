import os, time, threading, queue
import yaml, requests
from dataclasses import dataclass, field
from typing import Optional, Dict, List

import paho.mqtt.client as mqtt

try:
    from aydsko.iracingdata import DataClient
    HAS_DATA_CLIENT = True
except Exception:
    HAS_DATA_CLIENT = False

def fmt_laptime(seconds: float) -> str:
    try:
        seconds = float(seconds)
    except Exception:
        return str(seconds)
    m = int(seconds // 60)
    s = seconds % 60
    return f"{m}:{s:05.2f}"

def ordinal(n: int) -> str:
    try:
        n = int(n)
    except Exception:
        return str(n)
    return "%d%s" % (n, "tsnrhtdd"[(n//10%10!=1)*(n%10<4)*n%10::4])

@dataclass
class LiveState:
    series: str = ""
    track: str = ""
    session_type: str = ""
    flag: str = ""
    field_size: Optional[int] = None
    lap: int = 0
    last_lap_time: float = 0.0
    pos: Optional[int] = None
    prev_pos: Optional[int] = None
    incidents: int = 0
    subsession_id: Optional[int] = None
    posted_joined: bool = False
    posted_green: bool = False
    last_posted_lap: int = -1

@dataclass
class DriverCfg:
    name: str
    display_label: str
    iracing_id: Optional[int]
    discord_id: Optional[str]
    topic_prefix: str
    webhook: Optional[str]
    enabled: bool = True

@dataclass
class Config:
    mqtt_host: str
    mqtt_port: int
    mqtt_user: str
    mqtt_pass: str
    default_webhook: str
    drivers: List[DriverCfg]
    ir_email: Optional[str] = None
    ir_password: Optional[str] = None

def load_config() -> Config:
    with open("config/settings.yaml", "r") as f:
        s = yaml.safe_load(f) or {}
    with open("config/drivers.yaml", "r") as f:
        d = yaml.safe_load(f) or {}

    drivers = []
    for x in d.get("drivers", []):
        drivers.append(DriverCfg(
            name=x.get("name", "Driver"),
            display_label=x.get("display_label", x.get("name", "Driver")),
            iracing_id=(int(x.get("iracing_id")) if x.get("iracing_id") else None),
            discord_id=(str(x.get("discord_id")) if x.get("discord_id") else None),
            topic_prefix=str(x.get("topic_prefix", "")).strip().rstrip('/'),
            webhook=(str(x.get("webhook")) if x.get("webhook") else None),
            enabled=bool(x.get("enabled", True)),
        ))

    return Config(
        mqtt_host=str(s.get("mqtt", {}).get("host", "localhost")),
        mqtt_port=int(s.get("mqtt", {}).get("port", 1883)),
        mqtt_user=str(s.get("mqtt", {}).get("username", "")),
        mqtt_pass=str(s.get("mqtt", {}).get("password", "")),
        default_webhook=str(s.get("discord", {}).get("default_webhook", "")),
        drivers=[dr for dr in drivers if dr.enabled and dr.topic_prefix],
        ir_email=os.getenv("IRACING_EMAIL"),
        ir_password=os.getenv("IRACING_PASSWORD"),
    )

def post_discord(webhook: str, content: str):
    if not webhook or webhook.endswith("/REPLACE_ME"):
        print("[WARN] Discord webhook not set; would post:\n", content)
        return
    try:
        r = requests.post(webhook, json={"content": content}, timeout=10)
        if r.status_code >= 300:
            print("[ERR] Discord post failed:", r.status_code, r.text)
    except Exception as e:
        print("[ERR] Discord post error:", e)

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

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.client = mqtt.Client(clean_session=True)
        if self.cfg.mqtt_user:
            self.client.username_pw_set(self.cfg.mqtt_user, self.cfg.mqtt_pass)
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.on_disconnect = self.on_disconnect

        self.msg_q: "queue.Queue[tuple[str, str]]" = queue.Queue()
        self.states: Dict[str, LiveState] = {}     # key: topic_prefix
        self.drivers_by_prefix: Dict[str, DriverCfg] = {}

        for d in self.cfg.drivers:
            self.states[d.topic_prefix] = LiveState()
            self.drivers_by_prefix[d.topic_prefix] = d

    def on_connect(self, client, userdata, flags, rc):
        print("[MQTT] Connected rc=", rc)
        for prefix in self.drivers_by_prefix.keys():
            for t in self.TOPICS:
                topic = f"{prefix}/{t}"
                client.subscribe(topic, qos=0)
                print("[MQTT] Subscribed:", topic)

    def on_disconnect(self, client, userdata, rc):
        print("[MQTT] Disconnected rc=", rc)

    def on_message(self, client, userdata, msg):
        try:
            payload = msg.payload.decode("utf-8")
        except Exception:
            payload = str(msg.payload)
        self.msg_q.put((msg.topic, payload))

    def run(self):
        threading.Thread(target=self.process_loop, daemon=True).start()
        while True:
            try:
                self.client.connect(self.cfg.mqtt_host, self.cfg.mqtt_port, keepalive=60)
                self.client.loop_forever(retry_first_connection=True)
            except Exception as e:
                print("[MQTT] Connect error:", e)
                time.sleep(5)

    def process_loop(self):
        while True:
            topic, payload = self.msg_q.get()
            self.handle(topic, payload)

    def find_prefix_and_key(self, topic: str):
        # topic is like "joe/session/flag"; split first element as prefix
        parts = topic.split('/', 1)
        if len(parts) == 2 and parts[0] in self.drivers_by_prefix:
            return parts[0], parts[1]
        # fallback: longest matching prefix
        for p in sorted(self.drivers_by_prefix.keys(), key=len, reverse=True):
            if topic.startswith(p + "/"):
                return p, topic[len(p)+1:]
        return None, topic

    def label_for(self, d: DriverCfg) -> str:
        # You can @mention with <@ID>; for now show label; uncomment next to ping users
        # if d.discord_id: return f"<@{d.discord_id}>"
        return d.display_label or d.name

    def webhook_for(self, d: DriverCfg) -> str:
        return d.webhook or self.cfg.default_webhook

    def handle(self, topic: str, payload: str):
        prefix, key = self.find_prefix_and_key(topic)
        if prefix is None:
            return
        d = self.drivers_by_prefix[prefix]
        st = self.states[prefix]
        p = payload.strip()

        def say(msg: str):
            post_discord(self.webhook_for(d), f"**[{self.label_for(d)}]** {msg}")

        if key == "session/series_name":
            st.series = p
        elif key == "session/track_name":
            st.track = p
        elif key == "session/session_type":
            prev = st.session_type
            st.session_type = p
            if p in ("Practice","Qualify","Race") and prev not in ("Practice","Qualify","Race") and not st.posted_joined:
                say(f"has joined a {p} session on iRacing!\n{st.series} — {st.track}")
                st.posted_joined = True
        elif key == "session/flag":
            st.flag = p
            if p.lower() == "green" and not st.posted_green:
                say(f"🇨🇨 **Green Flag!** {st.series} @ {st.track}")
                st.posted_green = True
            if p.lower() == "checkered":
                pos = st.pos if st.pos is not None else "?"
                field = st.field_size if st.field_size is not None else "?"
                say(f"🏁 **Finished P{pos}** — {st.series} @ {st.track}\nField: {field} • Incidents: {st.incidents}")
                threading.Thread(target=self.post_official_results, args=(prefix,), daemon=True).start()
        elif key == "session/field_size":
            try: st.field_size = int(float(p))
            except Exception: st.field_size = None
        elif key == "session/subsession_id":
            try: st.subsession_id = int(float(p))
            except Exception: st.subsession_id = None
        elif key == "player/lap":
            try: l = int(float(p))
            except Exception: l = st.lap
            st.lap = l
            if l > 0 and l != st.last_posted_lap:
                pos = st.pos if st.pos is not None else 0
                prev = st.prev_pos if st.prev_pos is not None else 0
                delta = (prev - pos) if prev else 0
                delta_str = f"+{delta}" if delta>0 else (str(delta) if delta<0 else "+0")
                lap_str = fmt_laptime(st.last_lap_time)
                say(f"Lap {l} — {lap_str}  /  {st.incidents}x  /  {pos}  {delta_str}")
                st.last_posted_lap = l
                st.prev_pos = pos
        elif key == "player/last_lap_time":
            try: st.last_lap_time = float(p)
            except Exception: pass
        elif key == "player/position":
            try: st.pos = int(float(p))
            except Exception: st.pos = None
        elif key == "player/incidents":
            try: st.incidents = int(float(p))
            except Exception: pass
        elif key == "qualify/position":
            try: qp = int(float(p))
            except Exception: qp = 0
            if qp > 0:
                lap_str = fmt_laptime(st.last_lap_time)
                say(f"**Qualified {ordinal(qp)}** with a {lap_str}")
        elif key == "qualify/best_laptime":
            try: st.last_lap_time = float(p)
            except Exception: pass

    def post_official_results(self, prefix: str):
        if not HAS_DATA_CLIENT:
            print("[INFO] aydsko-iracingdata not installed; skipping official results.")
            return
        if not (self.cfg.ir_email and self.cfg.ir_password):
            print("[INFO] IRACING_EMAIL/IRACING_PASSWORD not set; skipping official results.")
            return
        d = self.drivers_by_prefix[prefix]
        st = self.states[prefix]
        sub = st.subsession_id
        if not sub:
            print(f"[INFO] No subsession_id for {prefix}; cannot fetch official results.")
            return
        try:
            with DataClient(logon_email=self.cfg.ir_email, logon_password=self.cfg.ir_password) as client:
                data = None
                for _ in range(30):
                    try:
                        r = client.GetSubsessionResultsAsync(int(sub)).result()
                        data = getattr(r, "Data", r)
                        if data: break
                    except Exception: time.sleep(10)
                if not data:
                    print("[WARN] Results not ready.")
                    return

                simsessions = data.get("simsession_results") or []
                first_session = simsessions[0] if simsessions else {}
                sof = first_session.get("strength_of_field")
                field = data.get("num_drivers") or first_session.get("results_num_drivers") or "?"
                sess_results = data.get("session_results") or []
                race_res = None
                for s in sess_results:
                    if str(s.get("simsession_type_name", "")).lower().startswith("race"):
                        race_res = s
                if race_res is None and sess_results:
                    race_res = sess_results[-1]

                # Build a map of tracked drivers by iRacing ID
                tracked = {dr.iracing_id: dr for dr in self.cfg.drivers if dr.iracing_id}
                lines = [f"**[{self.label_for(d)}] Official Results**", f"**{field} Cars — SOF {sof}**"]
                if race_res and "results" in race_res:
                    for m in race_res["results"]:
                        cid = int(m.get("cust_id", 0) or 0)
                        if cid in tracked:
                            dr = tracked[cid]
                            old_ir = m.get("oldi_rating"); new_ir = m.get("newi_rating")
                            ir_delta = (new_ir - old_ir) if (new_ir is not None and old_ir is not None) else 0
                            old_sub = m.get("old_sub_level"); new_sub = m.get("new_sub_level")
                            sr_after = (new_sub or 0) / 100.0
                            sr_delta = ((new_sub or 0) - (old_sub or 0)) / 100.0
                            pos = m.get("finish_position") or m.get("position") or "?"
                            incidents = m.get("incidents", 0)
                            lines.append(
                                f"**{dr.display_label or dr.name}** — P{pos} • {incidents}x • {new_ir} ({ir_delta:+}) iRating • {sr_after:.2f} ({sr_delta:+.2f}) SR"
                            )
                post_discord(self.webhook_for(d), "\n".join(lines))
        except Exception as e:
            print("[ERR] Official results failure:", e)

    def label_for(self, d: DriverCfg) -> str:
        return d.display_label or d.name

    def webhook_for(self, d: DriverCfg) -> str:
        return d.webhook or self.cfg.default_webhook

def main():
    cfg = load_config()
    if not cfg.drivers:
        print("No enabled drivers configured. Exiting.")
        return
    b = Bridge(cfg)
    b.run()

if __name__ == "__main__":
    main()
