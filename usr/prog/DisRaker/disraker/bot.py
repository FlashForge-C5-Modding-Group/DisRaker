import logging
from io import BytesIO
from typing import Any, Dict, Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

from .config import AppConfig
from .moonraker import MoonrakerClient, MoonrakerError


LOG = logging.getLogger("disraker")


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return "{:02d}:{:02d}:{:02d}".format(hours, minutes, seconds)


def status_embed(status: Dict[str, Any]) -> discord.Embed:
    stats = status.get("print_stats", {})
    state = str(stats.get("state", "unknown"))
    filename = stats.get("filename") or "No active file"
    virtual_sd = status.get("virtual_sdcard", {})
    progress = 100.0 * _number(virtual_sd.get("progress"))
    color = {
        "printing": discord.Color.green(),
        "paused": discord.Color.gold(),
        "error": discord.Color.red(),
        "cancelled": discord.Color.red(),
        "complete": discord.Color.blue(),
    }.get(state, discord.Color.light_grey())
    embed = discord.Embed(
        title="Printer status", description=str(filename), color=color)
    embed.add_field(name="State", value=state.title(), inline=True)
    embed.add_field(name="Progress", value="{:.1f}%".format(progress),
                    inline=True)
    embed.add_field(name="Print time", value=_duration(
        _number(stats.get("print_duration"))), inline=True)

    temperatures = []
    for name, values in status.items():
        if not isinstance(values, dict) or "temperature" not in values:
            continue
        current = _number(values.get("temperature"))
        target = _number(values.get("target"))
        label = name.replace("temperature_sensor ", "").replace(
            "heater_generic ", "").replace("_", " ").title()
        temperatures.append(
            "{}: **{:.1f}°C** / {:.1f}°C".format(label, current, target))
    embed.add_field(name="Temperatures",
                    value="\n".join(temperatures) or "Unavailable",
                    inline=False)
    message = stats.get("message")
    if message:
        embed.add_field(name="Message", value=str(message)[:1024],
                        inline=False)
    return embed


class PrinterView(discord.ui.View):
    def __init__(self, bot: "DisRakerBot"):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Refresh status", style=discord.ButtonStyle.primary,
                       emoji="🔄", custom_id="disraker:status")
    async def refresh(self, interaction: discord.Interaction,
                      button: discord.ui.Button):
        del button
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            status = await self.bot.moonraker.status()
            await interaction.followup.send(
                embed=status_embed(status), ephemeral=True)
        except MoonrakerError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)

    @discord.ui.button(label="Camera", style=discord.ButtonStyle.secondary,
                       emoji="📷", custom_id="disraker:camera")
    async def camera(self, interaction: discord.Interaction,
                     button: discord.ui.Button):
        del button
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            image = await self.bot.moonraker.camera_image()
            await interaction.followup.send(
                file=discord.File(BytesIO(image.data), image.filename),
                ephemeral=True)
        except MoonrakerError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)


class DisRakerBot(commands.Bot):
    def __init__(self, config: AppConfig, moonraker: MoonrakerClient):
        super().__init__(command_prefix=commands.when_mentioned,
                         intents=discord.Intents.none())
        self.config = config
        self.moonraker = moonraker
        self._last_print_state: Optional[str] = None
        self._commands_synced = False

    async def setup_hook(self):
        self.add_view(PrinterView(self))
        self.notification_poll.change_interval(
            seconds=self.config.notifications.poll_seconds)
        if self.config.notifications.enabled:
            self.notification_poll.start()

    async def on_ready(self):
        if not self._commands_synced:
            if self.config.discord.allowed_guild_id:
                guild = discord.Object(
                    id=self.config.discord.allowed_guild_id)
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
            else:
                await self.tree.sync()
            self._commands_synced = True
        LOG.info("Logged in as %s", self.user)

    async def send_status(self, interaction: discord.Interaction,
                          ephemeral: bool):
        await interaction.response.defer(ephemeral=ephemeral, thinking=True)
        try:
            status = await self.moonraker.status()
            await interaction.followup.send(
                embed=status_embed(status), view=PrinterView(self),
                ephemeral=ephemeral)
        except MoonrakerError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)

    @tasks.loop(seconds=10.0)
    async def notification_poll(self):
        channel_id = self.config.discord.notification_channel_id
        if not channel_id:
            return
        try:
            status = await self.moonraker.status()
        except MoonrakerError:
            LOG.exception("Moonraker notification poll failed")
            return
        state = str(status.get("print_stats", {}).get("state", "unknown"))
        previous = self._last_print_state
        self._last_print_state = state
        if previous is None or state == previous:
            return
        if state not in self.config.notifications.states:
            return
        channel = self.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.fetch_channel(channel_id)
            except discord.DiscordException:
                LOG.exception("Cannot access notification channel %s",
                              channel_id)
                return
        kwargs: Dict[str, Any] = {"embed": status_embed(status)}
        if self.config.notifications.include_camera:
            try:
                image = await self.moonraker.camera_image()
                kwargs["file"] = discord.File(
                    BytesIO(image.data), image.filename)
                kwargs["embed"].set_image(
                    url="attachment://{}".format(image.filename))
            except MoonrakerError:
                LOG.warning("Camera unavailable for notification",
                            exc_info=True)
        await channel.send(**kwargs)

    @notification_poll.before_loop
    async def before_notification_poll(self):
        await self.wait_until_ready()


def register_commands(bot: DisRakerBot):
    @bot.tree.command(name="printer",
                      description="Show current printer status and controls")
    async def printer(interaction: discord.Interaction):
        await bot.send_status(
            interaction,
            ephemeral=not bot.config.discord.public_status_responses)

    @bot.tree.command(name="dashboard",
                      description="Publish a shared printer dashboard")
    @app_commands.default_permissions(manage_messages=True)
    async def dashboard(interaction: discord.Interaction):
        await bot.send_status(interaction, ephemeral=False)
