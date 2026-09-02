import asyncio
import logging
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

from .config import AppConfig
from .moonraker import MoonrakerClient, MoonrakerError
from .state import PrintObservation, PrintStateStore


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


def status_embed(status: Dict[str, Any], printer_name: str) -> discord.Embed:
    stats = status.get("print_stats", {})
    state = str(stats.get("state", "unknown"))
    filename = stats.get("filename") or "No active file"
    virtual_sd = status.get("virtual_sdcard", {})
    display_status = status.get("display_status", {})
    progress = 100.0 * _number(
        display_status.get("progress", virtual_sd.get("progress")))
    color = {
        "printing": discord.Color.green(),
        "paused": discord.Color.gold(),
        "error": discord.Color.red(),
        "cancelled": discord.Color.red(),
        "complete": discord.Color.blue(),
    }.get(state, discord.Color.light_grey())
    embed = discord.Embed(
        title="{} — Printer status".format(printer_name),
        description=str(filename), color=color)
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

    info = stats.get("info", {})
    current_layer = info.get("current_layer")
    total_layer = info.get("total_layer")
    if current_layer is not None or total_layer is not None:
        embed.add_field(
            name="Layer",
            value="{} / {}".format(current_layer or "?", total_layer or "?"),
            inline=True,
        )

    motion = status.get("motion_report", {})
    toolhead = status.get("toolhead", {})
    position = motion.get("live_position") or toolhead.get("position")
    if isinstance(position, list) and len(position) >= 3:
        embed.add_field(
            name="Position",
            value="X {:.1f}  Y {:.1f}  Z {:.1f}".format(
                _number(position[0]), _number(position[1]),
                _number(position[2])),
            inline=False,
        )

    gcode_move = status.get("gcode_move", {})
    fan = status.get("fan", {})
    performance = []
    if gcode_move:
        performance.append("Speed {:.0f}%".format(
            100.0 * _number(gcode_move.get("speed_factor"), 1.0)))
        performance.append("Flow {:.0f}%".format(
            100.0 * _number(gcode_move.get("extrude_factor"), 1.0)))
    if fan:
        performance.append("Fan {:.0f}%".format(
            100.0 * _number(fan.get("speed"))))
    if performance:
        embed.add_field(name="Performance", value=" • ".join(performance),
                        inline=False)

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
    message = stats.get("message") or display_status.get("message")
    if message:
        embed.add_field(name="Message", value=str(message)[:1024],
                        inline=False)
    klippy_state = str(
        status.get("webhooks", {}).get("state", "ready")).title()
    embed.set_footer(text="DisRaker • {} • Klipper {}".format(
        printer_name, klippy_state))
    embed.timestamp = discord.utils.utcnow()
    return embed


def error_embed(message: str, printer_name: str = "Printer") -> discord.Embed:
    embed = discord.Embed(
        title="{} unavailable".format(printer_name),
        description=message, color=discord.Color.red())
    embed.set_footer(text="DisRaker live status")
    embed.timestamp = discord.utils.utcnow()
    return embed


def details_embed(status: Dict[str, Any], info: Dict[str, Any],
                  printer_name: str) -> discord.Embed:
    embed = discord.Embed(
        title="{} — Details".format(printer_name),
        color=discord.Color.blurple(),
    )
    embed.add_field(name="Klipper state",
                    value=str(info.get("state", "unknown")).title())
    embed.add_field(name="Klipper version",
                    value=str(info.get("software_version", "unknown")))
    toolhead = status.get("toolhead", {})
    embed.add_field(name="Homed axes",
                    value=str(toolhead.get("homed_axes") or "None").upper())
    embed.add_field(
        name="Motion limits",
        value="{:.0f} mm/s • {:.0f} mm/s²".format(
            _number(toolhead.get("max_velocity")),
            _number(toolhead.get("max_accel"))),
        inline=False,
    )
    system = status.get("system_stats", {})
    system_parts = []
    if "sysload" in system:
        system_parts.append("Load {:.2f}".format(_number(system["sysload"])))
    if "memavail" in system:
        system_parts.append("Free memory {:.0f} MiB".format(
            _number(system["memavail"]) / 1024.0))
    if system_parts:
        embed.add_field(name="Host", value=" • ".join(system_parts),
                        inline=False)
    cpu_info = info.get("cpu_info")
    if cpu_info:
        embed.add_field(name="MCU / CPU", value=str(cpu_info)[:1024],
                        inline=False)
    state_message = info.get("state_message")
    if state_message:
        embed.add_field(name="State message", value=str(state_message)[:1024],
                        inline=False)
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

    @discord.ui.button(
        label="Refresh status", style=discord.ButtonStyle.primary,
        emoji="🔄", custom_id="disraker:status",
    )
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

    @discord.ui.button(label="Details", style=discord.ButtonStyle.secondary,
                       emoji="ℹ️", custom_id="disraker:details")
    async def details(self, interaction: discord.Interaction,
                      button: discord.ui.Button):
        del button
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            status = await self.bot.moonraker.status()
            info = await self.bot.moonraker.printer_info()
            embed = details_embed(
                status, info, await self.bot.printer_name())
            await interaction.edit_original_response(embed=embed)
        except MoonrakerError as exc:
            await interaction.edit_original_response(content=str(exc))

    @discord.ui.button(
        label="Pause / Resume", style=discord.ButtonStyle.secondary,
        emoji="⏯️", custom_id="disraker:pause_resume",
    )
    async def pause_resume(self, interaction: discord.Interaction,
                           button: discord.ui.Button):
        del button
        if not await self.bot.require_control_access(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            status = await self.bot.moonraker.status()
            state = str(status.get("print_stats", {}).get("state", ""))
            if state == "printing":
                await self.bot.moonraker.pause_print()
                result = "Pause requested."
            elif state == "paused":
                await self.bot.moonraker.resume_print()
                result = "Resume requested."
            else:
                result = "There is no printing or paused job."
            await interaction.edit_original_response(content=result)
        except MoonrakerError as exc:
            await interaction.edit_original_response(content=str(exc))

    @discord.ui.button(
        label="Cancel", style=discord.ButtonStyle.danger,
        emoji="🛑", custom_id="disraker:cancel",
    )
    async def cancel(self, interaction: discord.Interaction,
                     button: discord.ui.Button):
        del button
        if not await self.bot.require_control_access(interaction):
            return
        await interaction.response.send_message(
            "Cancel the current print? This cannot be undone.",
            view=CancelConfirmationView(self.bot), ephemeral=True,
        )


class CancelConfirmationView(discord.ui.View):
    def __init__(self, bot: "DisRakerBot"):
        super().__init__(timeout=30.0)
        self.bot = bot

    @discord.ui.button(label="Confirm cancel",
                       style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction,
                      button: discord.ui.Button):
        del button
        if not await self.bot.require_control_access(interaction):
            return
        try:
            await self.bot.moonraker.cancel_print()
            await interaction.response.edit_message(
                content="Print cancellation requested.", view=None)
        except MoonrakerError as exc:
            await interaction.response.edit_message(
                content=str(exc), view=None)

    @discord.ui.button(label="Keep printing",
                       style=discord.ButtonStyle.secondary)
    async def keep_printing(self, interaction: discord.Interaction,
                            button: discord.ui.Button):
        del button
        await interaction.response.edit_message(
            content="Cancellation dismissed.", view=None)


class DisRakerBot(commands.Bot):
    def __init__(self, config: AppConfig, moonraker: MoonrakerClient):
        super().__init__(command_prefix=commands.when_mentioned,
                         intents=discord.Intents.none())
        self.config = config
        self.moonraker = moonraker
        state_path = config.notifications.state_file
        if state_path:
            path = Path(state_path)
        else:
            path = (Path(__file__).resolve().parent.parent
                    / "data" / "state.json")
        self._state_store = PrintStateStore(path)
        self._last_observation = self._state_store.load()
        configured_name = config.moonraker.printer_name
        self._printer_name: Optional[str] = configured_name or None
        self._commands_synced = False
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

    async def printer_name(self) -> str:
        if self._printer_name:
            return self._printer_name
        try:
            info = await self.moonraker.printer_info()
            self._printer_name = str(info.get("hostname") or "Klipper Printer")
        except MoonrakerError:
            return "Klipper Printer"
        return self._printer_name

    async def require_control_access(self, interaction: discord.Interaction):
        discord_config = self.config.discord
        if not discord_config.job_controls_enabled:
            await interaction.response.send_message(
                "Printer controls are disabled in DisRaker configuration.",
                ephemeral=True,
            )
            return False

        allowed_users = set(discord_config.control_user_ids)
        allowed_roles = set(discord_config.control_role_ids)
        if not allowed_users and not allowed_roles:
            return True
        if interaction.user.id in allowed_users:
            return True
        roles = getattr(interaction.user, "roles", [])
        if any(getattr(role, "id", 0) in allowed_roles for role in roles):
            return True
        permissions = getattr(interaction.user, "guild_permissions", None)
        if permissions and permissions.manage_guild:
            return True
        await interaction.response.send_message(
            "You do not have permission to control this printer.",
            ephemeral=True,
        )
        return False

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
        embed = status_embed(status, await self.printer_name())
        image = None
        if self.config.notifications.show_camera_in_status:
            try:
                camera = await self.moonraker.camera_image()
                image = discord.File(BytesIO(camera.data), camera.filename)
                embed.set_image(url="attachment://{}".format(camera.filename))
            except MoonrakerError:
                LOG.warning("Camera unavailable for status", exc_info=True)
        return embed, image

    async def status_edit_payload(
            self, status: Optional[Dict[str, Any]] = None):
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

    async def update_dashboard(self, channel, status: Dict[str, Any]):
        embed, image = await self.status_content(status)
        view = PrinterView(self)
        kwargs = {"embed": embed, "view": view}
        if image is not None:
            kwargs["file"] = image
        await channel.send(**kwargs)

    async def send_state_event(self, channel, status: Dict[str, Any],
                               state: str):
        stats = status.get("print_stats", {})
        filename = stats.get("filename") or "the selected job"
        printer_name = await self.printer_name()
        messages = {
            "printing": "🖨️ **{} is starting:** `{}`".format(
                printer_name, filename),
            "paused": "⏸️ **{} paused:** `{}`".format(
                printer_name, filename),
            "complete": "✅ **{} completed:** `{}`".format(
                printer_name, filename),
            "error": "❌ **{} print error:** `{}`".format(
                printer_name, filename),
            "cancelled": "🛑 **{} cancelled:** `{}`".format(
                printer_name, filename),
            "standby": "💤 **{} is idle.**".format(printer_name),
        }
        content = messages.get(state, "Printer state changed to **{}**.".format(
            state.title()))
        embed = status_embed(status, printer_name)
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
        async with self._state_lock:
            observation = PrintObservation.from_status(status)
            changed = observation.is_new_transition(self._last_observation)
            self._last_observation = observation
            self._state_store.save(observation)
            channel = await self.status_channel()
            if channel is None:
                return
            if update_dashboard:
                await self.update_dashboard(channel, status)
            if not changed:
                return
            state = observation.state
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
                    if (self._last_observation is not None and
                            state == self._last_observation.state):
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
