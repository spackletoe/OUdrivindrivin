"""Discord race reporting bot."""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any, Dict, List, Optional

import discord
from discord import app_commands
from discord.ext import commands

from models import Driver, LiveState
from mqtt_bridge import MqttBridge
from results import fetch_official_summary

log = logging.getLogger("oudrivin.bot")


class RaceBot(commands.Bot):
    def __init__(self, settings: Dict[str, Any], drivers: List[Driver]):
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)
        self.settings = settings
        self.drivers = drivers
        self.channel_id = int(settings["discord"]["channel_id"])
        self._report_channel: Optional[discord.abc.Messageable] = None
        self.mqtt: Optional[MqttBridge] = None
        self._event_queue: asyncio.Queue = asyncio.Queue()
        self._official_lock = threading.Lock()

    async def setup_hook(self) -> None:
        self.tree.add_command(status_cmd)
        self.tree.add_command(ping_cmd)
        self.tree.add_command(drivers_cmd)
        guild_id = (self.settings.get("discord") or {}).get("guild_id")
        if guild_id:
            guild = discord.Object(id=int(guild_id))
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info("synced %s guild commands to %s", len(synced), guild_id)
        else:
            synced = await self.tree.sync()
            log.info("synced %s global commands", len(synced))
        self.loop.create_task(self._event_worker())

    async def on_ready(self) -> None:
        channel = self.get_channel(self.channel_id)
        if channel is None:
            try:
                channel = await self.fetch_channel(self.channel_id)
            except Exception as exc:
                log.error("cannot resolve channel_id %s: %s", self.channel_id, exc)
                return
        self._report_channel = channel
        log.info("logged in as %s; reporting to #%s", self.user, getattr(channel, "name", self.channel_id))
        if self.mqtt is None:
            self.mqtt = MqttBridge(self.settings, self.drivers, on_event=self._enqueue_event)
            self.mqtt.start_background()

    def _enqueue_event(self, event: Dict[str, Any]) -> None:
        self.loop.call_soon_threadsafe(self._event_queue.put_nowait, event)

    async def _event_worker(self) -> None:
        while True:
            event = await self._event_queue.get()
            try:
                await self._handle_event(event)
            except Exception:
                log.exception("failed handling event %s", event)
            finally:
                self._event_queue.task_done()

    async def _handle_event(self, event: Dict[str, Any]) -> None:
        content = event.get("content") or ""
        if content:
            await self.post(content)
        if event.get("request_official"):
            sub_id = event.get("subsession_id")
            asyncio.create_task(self._post_official(sub_id))

    async def post(self, content: str) -> None:
        if not self._report_channel:
            log.warning("no report channel yet; dropping: %s", content)
            return
        # Discord hard limit is 2000 characters
        chunk = content[:1900]
        await self._report_channel.send(chunk)

    async def _post_official(self, subsession_id: Optional[int]) -> None:
        if not subsession_id:
            log.info("no subsession_id for official results")
            return
        email = self.settings.get("ir_email")
        password = self.settings.get("ir_password")
        if not (email and password):
            log.info("iRacing credentials not set; skipping official results")
            return

        def _fetch() -> Optional[str]:
            with self._official_lock:
                return fetch_official_summary(
                    email=email,
                    password=password,
                    subsession_id=int(subsession_id),
                    drivers=self.drivers,
                )

        summary = await asyncio.to_thread(_fetch)
        if summary:
            await self.post(summary)

    def live_state(self) -> LiveState:
        if self.mqtt:
            return self.mqtt.state
        return LiveState()


# Slash commands need a bot reference; resolve via interaction.client
@app_commands.command(name="status", description="Show the current live race session state")
async def status_cmd(interaction: discord.Interaction) -> None:
    bot: RaceBot = interaction.client  # type: ignore[assignment]
    st = bot.live_state()
    lines = [
        f"**Series:** {st.series or '—'}",
        f"**Track:** {st.track or '—'}",
        f"**Session:** {st.session_type or '—'}",
        f"**Flag:** {st.flag or '—'}",
        f"**Position:** {st.pos if st.pos is not None else '—'}"
        f" / Field {st.field_size if st.field_size is not None else '—'}",
        f"**Lap:** {st.lap} · **Incidents:** {st.incidents}",
        f"**Subsession:** {st.subsession_id or '—'}",
    ]
    await interaction.response.send_message("\n".join(lines), ephemeral=True)


@app_commands.command(name="ping", description="Check that the race bot is online")
async def ping_cmd(interaction: discord.Interaction) -> None:
    await interaction.response.send_message("Pong — race bot is online.", ephemeral=True)


@app_commands.command(name="drivers", description="List tracked drivers for official results")
async def drivers_cmd(interaction: discord.Interaction) -> None:
    bot: RaceBot = interaction.client  # type: ignore[assignment]
    if not bot.drivers:
        await interaction.response.send_message("No drivers configured in `config/drivers.yaml`.", ephemeral=True)
        return
    lines = []
    for d in bot.drivers:
        mention = f" → <@{d.discord_id}>" if d.discord_id else ""
        lines.append(f"• **{d.name}** (`{d.iracing_id}`){mention}")
    await interaction.response.send_message("\n".join(lines), ephemeral=True)
