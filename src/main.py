"""uRacing? — iRacing race reporting Discord bot."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Allow `python src/main.py` without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from bot import RaceBot
from config import load_config, require_discord_config


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )
    settings, drivers = load_config()
    token, channel_id = require_discord_config(settings)
    settings.setdefault("discord", {})["channel_id"] = channel_id
    bot = RaceBot(settings, drivers)
    bot.run(token, log_handler=None)


if __name__ == "__main__":
    main()
