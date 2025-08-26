# OUdrivindrivin

Posts iRacing live events to a Discord channel.  Telemetry from `ir2mqtt` is
forwarded through MQTT and this bridge posts join/green/lap/checkered messages.
After the race it can call the iRacing Data API for official results including
SOF and iRating/SR deltas.

## Quick start
1. Copy `.env.example` to `.env` and fill in `IRACING_EMAIL` and
   `IRACING_PASSWORD` if you want official results.
2. Edit `config/settings.yaml`:
   - `mqtt.host` and `mqtt.port` point to your broker.
   - `mqtt.prefix` must match the **Topic Prefix** configured in `ir2mqtt`
     (default `OUdrivindrivin`).
   - `discord.webhook` is the channel webhook URL where messages will post.
3. Edit `config/drivers.yaml` to list drivers you care about for official
   result summaries.  Set `enabled: false` to skip any driver.
4. Run the bridge:
   ```bash
   docker compose up -d --build
   ```
5. Run `ir2mqtt` on the iRacing PC using the same topic prefix and point it at
   the MQTT broker.

## Optional Mosquitto broker
If you do not already have a broker you can run one alongside the bridge:

```yaml
services:
  mqtt:
    image: eclipse-mosquitto:2
    volumes:
      - ./mosquitto.conf:/mosquitto/config/mosquitto.conf
    ports:
      - "1883:1883"
```

Example `mosquitto.conf`:

```
listener 1883
allow_anonymous true
```

## MQTT smoke test
With the bridge running you can simulate a race without iRacing:

```bash
BROKER=<host or IP>
mosquitto_pub -h $BROKER -t OUdrivindrivin/session/series_name -m "FIA F4"
mosquitto_pub -h $BROKER -t OUdrivindrivin/session/track_name -m "COTA"
mosquitto_pub -h $BROKER -t OUdrivindrivin/session/session_type -m "Race"
mosquitto_pub -h $BROKER -t OUdrivindrivin/session/flag -m "green"
mosquitto_pub -h $BROKER -t OUdrivindrivin/player/last_lap_time -m "92.68"
mosquitto_pub -h $BROKER -t OUdrivindrivin/player/position -m "7"
mosquitto_pub -h $BROKER -t OUdrivindrivin/player/incidents -m "0"
mosquitto_pub -h $BROKER -t OUdrivindrivin/player/lap -m "1"
mosquitto_pub -h $BROKER -t OUdrivindrivin/session/flag -m "checkered"
```

## Security
Do **not** commit real Discord webhooks or iRacing credentials.  Keep `.env`
private and use `.gitignore` to avoid committing it.

## License
[MIT](LICENSE)
