# OUdrivindrivin

Discord bot that posts live iRacing session updates to a channel. Telemetry from
[`ir2mqtt`](https://github.com/search?q=ir2mqtt) is published to MQTT; this bot
subscribes and reports join / green / qualify / lap / checkered events. After the
race it can call the iRacing Data API for official results (SOF, iRating, SR)
for drivers listed in config.

```
iRacing PC ──► ir2mqtt ──► MQTT broker ──► OUdrivindrivin bot ──► Discord channel
                                              │
                                              └─► iRacing Data API (optional official results)
```

## What you need

| Piece | Purpose |
|-------|---------|
| **Discord application + bot token** | The bot that posts messages and responds to slash commands |
| **Discord channel ID** | Target channel for race reports |
| **MQTT broker** | Message bus between `ir2mqtt` and the bot (Mosquitto, HiveMQ, etc.) |
| **`ir2mqtt` on the iRacing PC** | Publishes live telemetry to MQTT using a shared topic prefix |
| **Docker** (recommended) | Runs the bot via `docker compose` |
| **iRacing account** (optional) | Email/password for official post-race results |

### Discord bot permissions

Create an application at [Discord Developer Portal](https://discord.com/developers/applications):

1. **New Application** → **Bot** → reset/copy the token.
2. Under **OAuth2 → URL Generator**, scopes: `bot`, `applications.commands`.
3. Bot permissions: **View Channels**, **Send Messages**, **Embed Links** (optional), **Read Message History** (optional).
4. Open the generated invite URL, add the bot to your server.
5. Enable **Developer Mode** in Discord, right-click the report channel → **Copy Channel ID**.

## Quick start

1. Copy `.env.example` to `.env` and set at least `DISCORD_BOT_TOKEN`.
2. Edit `config/settings.yaml` — set `discord.channel_id`, and point `mqtt.host` / `mqtt.prefix` at your broker and `ir2mqtt` prefix.
3. Edit `config/drivers.yaml` with the drivers you want in official summaries.
4. Start the bot:
   ```bash
   docker compose up -d --build
   ```
5. On the iRacing PC, run `ir2mqtt` with the **same topic prefix** and broker host/port.
6. In Discord, try `/ping` and `/status`.

### Optional local Mosquitto broker

Uncomment the `mqtt` service in `docker-compose.yml` and set `mqtt.host: "mqtt"` in
`config/settings.yaml`. A starter `mosquitto.conf` is included (anonymous access on
port 1883 — tighten this for anything beyond a private LAN).

---

## Config guide

### Environment (`.env`)

| Variable | Required | Description |
|----------|----------|-------------|
| `DISCORD_BOT_TOKEN` | **Yes** | Bot token from the Developer Portal |
| `DISCORD_CHANNEL_ID` | No | Overrides `discord.channel_id` in YAML |
| `IRACING_EMAIL` | For official results | iRacing login email |
| `IRACING_PASSWORD` | For official results | iRacing password (prefer an app password if you use one) |

Do **not** commit `.env`. It is listed in `.gitignore`.

### `config/settings.yaml`

```yaml
discord:
  token: "REPLACE_ME"          # prefer DISCORD_BOT_TOKEN in .env
  channel_id: 1234567890       # report channel
  # guild_id: 1234567890       # optional — faster slash-command sync to one server

mqtt:
  host: "mqtt"                 # broker hostname or IP
  port: 1883
  prefix: "OUdrivindrivin"     # must match ir2mqtt Topic Prefix
  client_id: "ou-race-bot"
  # username: ""
  # password: ""

runtime:
  post_official: true          # fetch official results after checkered
  post_laps: true              # Discord line per completed lap
  post_qualify: true           # one qualify message per session
```

**Notes**

- `mqtt.prefix` is prepended to every topic (e.g. `OUdrivindrivin/session/flag`).
- If `mqtt.host` is another machine on your LAN, use that IP instead of `mqtt`.
- Set `guild_id` while developing so `/status`, `/ping`, and `/drivers` appear immediately; without it, global command sync can take up to ~1 hour.

### `config/drivers.yaml`

```yaml
drivers:
  - name: "Alice Example"
    iracing_id: 100001          # iRacing customer ID (custid)
    discord_id: "111111111111111111"  # optional @mention
    enabled: true
```

- Only `enabled: true` drivers appear in the **official** results post.
- Live lap/flag messages always come from the **local player's** `ir2mqtt` feed (the PC running the sim), not from this list.
- Find `iracing_id` on a member profile URL: `...custid=123456`.

### MQTT topics expected from `ir2mqtt`

| Topic (after prefix) | Used for |
|----------------------|----------|
| `session/series_name` | Join message / session identity |
| `session/track_name` | Join message / session identity |
| `session/session_type` | Join (`Practice` / `Qualify` / `Race`) |
| `session/flag` | Green + checkered posts |
| `session/field_size` | Finish summary |
| `session/subsession_id` | Official results lookup; resets state on change |
| `player/lap` | Lap updates |
| `player/last_lap_time` | Lap time formatting |
| `player/position` | Position + delta |
| `player/incidents` | Incident count |
| `qualify/position` | Qualify result (once) |
| `qualify/best_laptime` | Qualify lap time |

### Slash commands

| Command | Description |
|---------|-------------|
| `/ping` | Confirm the bot is online |
| `/status` | Current series, track, flag, position, lap, subsession |
| `/drivers` | List tracked drivers from `drivers.yaml` |

---

## MQTT smoke test

With the bot running, simulate a race without iRacing:

```bash
BROKER=<host or IP>
PREFIX=OUdrivindrivin

mosquitto_pub -h $BROKER -t $PREFIX/session/series_name -m "FIA F4"
mosquitto_pub -h $BROKER -t $PREFIX/session/track_name -m "COTA"
mosquitto_pub -h $BROKER -t $PREFIX/session/session_type -m "Race"
mosquitto_pub -h $BROKER -t $PREFIX/session/flag -m "green"
mosquitto_pub -h $BROKER -t $PREFIX/player/last_lap_time -m "92.68"
mosquitto_pub -h $BROKER -t $PREFIX/player/position -m "7"
mosquitto_pub -h $BROKER -t $PREFIX/player/incidents -m "0"
mosquitto_pub -h $BROKER -t $PREFIX/player/lap -m "1"
mosquitto_pub -h $BROKER -t $PREFIX/session/field_size -m "12"
mosquitto_pub -h $BROKER -t $PREFIX/session/subsession_id -m "12345678"
mosquitto_pub -h $BROKER -t $PREFIX/session/flag -m "checkered"
```

You should see join → green → lap → finish messages in the configured Discord channel.
Official results only post when iRacing credentials are set and the subsession exists.

## Run without Docker

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then edit
export $(grep -v '^#' .env | xargs)
python src/main.py
```

## Security

- Never commit real Discord tokens, webhooks, or iRacing passwords.
- Keep `.env` private; prefer env vars over putting secrets in YAML.
- If you expose MQTT beyond a trusted network, enable authentication and disable anonymous access in Mosquitto.

## License

[MIT](LICENSE)
