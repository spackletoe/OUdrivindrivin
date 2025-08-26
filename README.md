# iRacing → Discord Bridge (Multi‑prefix)
**Watch multiple drivers at once.** Each driver runs **ir2mqtt** on their own PC with a **unique topic prefix** (e.g., `joe`, `mike`, `tom`). This service subscribes to all those prefixes and posts to Discord in realtime. After the checkered flag, it pulls **official results (SOF/iRating/SR)** from the iRacing Data API and posts a combined summary for any tracked drivers in that subsession.

## Quick start
1. Edit `config/settings.yaml`:
   - `mqtt.host`/`port`/`username`/`password` → your MQTT broker (HA’s Mosquitto or a sidecar container).
   - `discord.default_webhook` → your Discord channel webhook.
2. Edit `config/drivers.yaml`:
   - Set **topic_prefix** for each driver (this must match the ir2mqtt **Topic Prefix** on that driver’s PC).
   - Optionally set a per‑driver `webhook` (otherwise `default_webhook` is used).
   - `display_label` shows in messages (e.g., a nickname like `#Crispy Cargo`).
3. (Optional) enable official results:
   ```bash
   export IRACING_EMAIL="you@example.com"
   export IRACING_PASSWORD="your_readonly_or_app_password"
   ```
4. Run:
   ```bash
   docker compose up -d --build
   ```
5. On each driver’s PC, run **ir2mqtt** pointing to your broker, and set **Topic Prefix** to the one you configured (e.g., `joe`, `mike`, `tom`).

## What it posts per driver
- **Joined** banner (Practice/Qualify/Race)
- **Qualifying** position + lap time (mm:ss.xx)
- **Green flag** banner
- **Per‑lap**: `Lap N — mm:ss.xx / Incidents x / Position Δ`
- **Finish**: position, field size, incidents
- **Official**: `SOF`, field size, and per‑tracked‑driver `iRating (Δ)` and `SR (Δ)` for that subsession

## Smoke test (no iRacing)
Assuming driver `joe`:
```bash
mosquitto_pub -h <BROKER> -t joe/session/series_name -m "FIA F4"
mosquitto_pub -h <BROKER> -t joe/session/track_name -m "COTA"
mosquitto_pub -h <BROKER> -t joe/session/session_type -m "Race"
mosquitto_pub -h <BROKER> -t joe/session/flag -m "green"
mosquitto_pub -h <BROKER> -t joe/player/last_lap_time -m "92.68"
mosquitto_pub -h <BROKER> -t joe/player/position -m "7"
mosquitto_pub -h <BROKER> -t joe/player/incidents -m "0"
mosquitto_pub -h <BROKER> -t joe/player/lap -m "1"
mosquitto_pub -h <BROKER> -t joe/session/flag -m "checkered"
```
Messages should appear in Discord prefixed with `[Joe’s display_label]`.

## Notes
- Use one broker for all three; MQTT is very lightweight. Just give each **ir2mqtt** a unique `topic_prefix`.
- If you want to @mention the driver, set `display_label` to `<@DISCORD_ID>` (or update `label_for()` in `src/main.py` to return that by default).
- Security: don’t commit real webhooks or credentials. Use env vars and keep your repo private if needed.

MIT License.
