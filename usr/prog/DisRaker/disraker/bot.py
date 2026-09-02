import asyncio
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
    total_duration = _number(stats.get("total_duration"))
    if progress > 0.0 and progress < 100.0:
        estimate = total_duration / (progress / 100.0)
        remaining = max(0.0, estimate - total_duration)
        embed.add_field(name="Estimated remaining",
                        value=_duration(remaining), inline=True)
    filament = _number(stats.get("filament_used"))
    if filament:
        embed.add_field(name="Filament used",
                        value="{:.1f} mm".format(filament), inline=True)

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
    embed.set_footer(text="DisRaker live status")
    embed.timestamp = discord.utils.utcnow()
    return embed


def error_embed(message: str) -> discord.Embed:
    embed = discord.Embed(title="Printer unavailable", description=message,
                          color=discord.Color.red())
    embed.set_footer(text="DisRaker live status")
    embed.timestamp = discord.utils.utcnow()
    return embed


class PrinterView(discord.ui.View):
    def __init__(self, bot: "DisRakerBot"):
        super().__init__(timeout=None)
        self.bot = bot
        if bot.config.discord.printer_ui_url:
            self.add_item(discord.ui.Button(
                label="Open printer UI", emoji="🌐",
                style=discord.ButtonStyle.link,
                url=bot.config.discord.printer_ui_url))

    @discord.ui.button(label="Refresh status", style=discord.ButtonStyle.primary,
                       emoji="🔄", custom_id="disraker:status")
    async def refresh(self, interaction: discord.Interaction,
                      button: discord.ui.Button):
        del button
        await interaction.response.defer(thinking=True)
        try:
            kwargs = await self.bot.status_edit_payload()
            await interaction.edit_original_response(**kwargs)
        except MoonrakerError as exc:
            await interaction.edit_original_response(
                embed=error_embed(str(exc)), attachments=[], view=self)

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
        self._dashboard_message: Optional[discord.Message] = None
        self._state_lock = asyncio.Lock()
        self._realtime_task = None

    async def setup_hook(self):
        self.add_view(PrinterView(self))
        self.notification_poll.change_interval(
            seconds=self.config.notifications.poll_seconds)
        if self.config.notifications.enabled:
            self.notification_poll.start()
            self._realtime_task = asyncio.create_task(self.realtime_monitor())

    async def close(self):
        if self._realtime_task is not None:
            self._realtime_task.cancel()
        await super().close()

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
            embed, image = await self.status_content(status)
            kwargs = {"embed": embed, "view": PrinterView(self),
                      "ephemeral": ephemeral}
            if image is not None:
                kwargs["file"] = image
            await interaction.followup.send(**kwargs)
        except MoonrakerError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)

    async def status_content(self, status: Dict[str, Any]):
        embed = status_embed(status)
        image = None
        if self.config.notifications.show_camera_in_status:
            try:
                camera = await self.moonraker.camera_image()
                image = discord.File(BytesIO(camera.data), camera.filename)
                embed.set_image(url="attachment://{}".format(camera.filename))
            except MoonrakerError:
                LOG.warning("Camera unavailable for status", exc_info=True)
        return embed, image

    async def status_edit_payload(self, status: Optional[Dict[str, Any]] = None):
        status = status or await self.moonraker.status()
        embed, image = await self.status_content(status)
        attachments = [image] if image is not None else []
        return {"embed": embed, "attachments": attachments,
                "view": PrinterView(self)}

    async def status_channel(self):
        channel_id = self.config.discord.status_channel_id
        if not channel_id:
            return None
        channel = self.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.fetch_channel(channel_id)
            except discord.DiscordException:
                LOG.exception("Cannot access status channel %s", channel_id)
                return None
        return channel

    async def find_dashboard(self, channel):
        if self._dashboard_message is not None:
            return self._dashboard_message
        try:
            async for message in channel.history(limit=50):
                if message.author.id != self.user.id or not message.embeds:
                    continue
                if message.embeds[0].footer.text == "DisRaker live status":
                    self._dashboard_message = message
                    return message
        except (discord.Forbidden, discord.HTTPException):
            LOG.warning("Unable to search for existing dashboard", exc_info=True)
        return None

    async def update_dashboard(self, channel, status: Dict[str, Any]):
        message = await self.find_dashboard(channel)
        embed, image = await self.status_content(status)
        view = PrinterView(self)
        if message is None:
            kwargs = {"embed": embed, "view": view}
            if image is not None:
                kwargs["file"] = image
            self._dashboard_message = await channel.send(**kwargs)
            return
        attachments = [image] if image is not None else []
        try:
            await message.edit(embed=embed, attachments=attachments, view=view)
        except discord.NotFound:
            self._dashboard_message = None
            await self.update_dashboard(channel, status)

    async def send_state_event(self, channel, status: Dict[str, Any],
                               state: str):
        stats = status.get("print_stats", {})
        filename = stats.get("filename") or "the selected job"
        messages = {
            "printing": "🖨️ **A print is starting:** `{}`".format(filename),
            "paused": "⏸️ **Print paused:** `{}`".format(filename),
            "complete": "✅ **Print completed:** `{}`".format(filename),
            "error": "❌ **Print error:** `{}`".format(filename),
            "cancelled": "🛑 **Print cancelled:** `{}`".format(filename),
            "standby": "💤 **Printer is idle.**",
        }
        content = messages.get(state, "Printer state changed to **{}**.".format(
            state.title()))
        embed = status_embed(status)
        kwargs = {"content": content, "embed": embed}
        if self.config.notifications.include_camera_in_events:
            try:
                image = await self.moonraker.camera_image()
                kwargs["file"] = discord.File(
                    BytesIO(image.data), image.filename)
                embed.set_image(url="attachment://{}".format(image.filename))
            except MoonrakerError:
                LOG.warning("Camera unavailable for event", exc_info=True)
        await channel.send(**kwargs)

    async def process_status(self, status: Dict[str, Any],
                             update_dashboard: bool):
        channel = await self.status_channel()
        if channel is None:
            return
        async with self._state_lock:
            state = str(status.get(
                "print_stats", {}).get("state", "unknown"))
            previous = self._last_print_state
            self._last_print_state = state
            if update_dashboard:
                await self.update_dashboard(channel, status)
            if state == previous:
                return
            if state not in self.config.notifications.states:
                return
            if state == "standby" and not self.config.notifications.send_idle:
                return
            await self.send_state_event(channel, status, state)

    async def realtime_monitor(self):
        await self.wait_until_ready()
        while not self.is_closed():
            try:
                async for update in self.moonraker.status_updates():
                    print_stats = update.get("print_stats")
                    if not isinstance(print_stats, dict) or \
                            "state" not in print_stats:
                        continue
                    state = str(print_stats["state"])
                    if state == self._last_print_state:
                        continue
                    status = await self.moonraker.status()
                    await self.process_status(status, update_dashboard=True)
            except MoonrakerError:
                LOG.warning("Moonraker real-time feed unavailable; retrying",
                            exc_info=True)
            except asyncio.CancelledError:
                return
            await asyncio.sleep(5.0)

    @tasks.loop(seconds=10.0)
    async def notification_poll(self):
        try:
            status = await self.moonraker.status()
        except MoonrakerError:
            LOG.exception("Moonraker notification poll failed")
            return
        await self.process_status(status, update_dashboard=True)

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
