"""Load YAML config and environment overrides."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Tuple

import yaml

from models import Driver


def load_config(
    settings_path: str = "config/settings.yaml",
    drivers_path: str = "config/drivers.yaml",
) -> Tuple[Dict[str, Any], List[Driver]]:
    with open(settings_path, "r", encoding="utf-8") as f:
        settings = yaml.safe_load(f) or {}
    with open(drivers_path, "r", encoding="utf-8") as f:
        dcfg = yaml.safe_load(f) or {}

    drivers: List[Driver] = []
    for d in dcfg.get("drivers", []) or []:
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

    # Secrets and overrides from the environment
    env_token = os.getenv("DISCORD_BOT_TOKEN")
    if env_token:
        settings["discord"]["token"] = env_token

    env_channel = os.getenv("DISCORD_CHANNEL_ID")
    if env_channel:
        settings["discord"]["channel_id"] = int(env_channel)

    settings["ir_email"] = os.getenv("IRACING_EMAIL") or settings.get("iracing", {}).get("email")
    settings["ir_password"] = os.getenv("IRACING_PASSWORD") or settings.get("iracing", {}).get(
        "password"
    )

    return settings, drivers


def require_discord_config(settings: Dict[str, Any]) -> Tuple[str, int]:
    token = (settings.get("discord") or {}).get("token") or ""
    channel_id = (settings.get("discord") or {}).get("channel_id")
    if not token or token == "REPLACE_ME":
        raise SystemExit(
            "Discord bot token missing. Set DISCORD_BOT_TOKEN in .env or discord.token in settings.yaml."
        )
    if not channel_id or str(channel_id) in {"0", "REPLACE_ME"}:
        raise SystemExit(
            "Discord channel_id missing. Set DISCORD_CHANNEL_ID in .env or discord.channel_id in settings.yaml."
        )
    return token, int(channel_id)
