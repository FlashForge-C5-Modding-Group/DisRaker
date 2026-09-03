import asyncio
import logging
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

from .config import AppConfig, PrinterConfig
from .moonraker import MoonrakerClient, MoonrakerError
from .state import PrintObservation, PrintStateStore


LOG = logging.getLogger("disraker")


def user_can_control(config: AppConfig, printer: PrinterConfig,
                     user: Any) -> bool:
    user_id = getattr(user, "id", 0)
    role_ids = {
        getattr(role, "id", 0)
        for role in getattr(user, "roles", [])
    }
    permissions = getattr(user, "guild_permissions", None)
    return bool(
        user_id in config.discord.control_user_ids
        or role_ids.intersection(config.discord.control_role_ids)
        or user_id in printer.control_user_ids
        or role_ids.intersection(printer.control_role_ids)
        or (permissions and permissions.manage_guild)
    )


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


def _size(size: Any) -> str:
    value = max(0.0, _number(size))
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024.0 or unit == "GiB":
            return "{:.1f} {}".format(value, unit)
        value /= 1024.0
    return "0 B"


def _discord_time(timestamp: Any) -> str:
    value = int(_number(timestamp))
    return "<t:{}:R>".format(value) if value > 0 else "Unknown time"


def status_embed(status: Dict[str, Any], printer_name: str) -> discord.Embed:
    printer_name = printer_name[:180]
    stats = status.get("print_stats", {})
    state = str(stats.get("state", "unknown"))
    filename = stats.get("filename") or "No active file"
    virtual_sd = status.get("virtual_sdcard", {})
    display_status = status.get("display_status", {})
    progress_value = display_status.get("progress")
    if progress_value is None:
        progress_value = virtual_sd.get("progress")
    progress = 100.0 * _number(progress_value)
    color = {
        "printing": discord.Color.green(),
        "paused": discord.Color.gold(),
        "error": discord.Color.red(),
        "cancelled": discord.Color.red(),
        "complete": discord.Color.blue(),
    }.get(state, discord.Color.light_grey())
    embed = discord.Embed(
        title="{} - Printer status".format(printer_name),
        description=str(filename)[:4096], color=color)
    embed.add_field(name="State", value=state.title(), inline=True)
    embed.add_field(name="Progress", value="{:.1f}%".format(progress),
                    inline=True)
    embed.add_field(name="Print time", value=_duration(
        _number(stats.get("print_duration"))), inline=True)
    total_duration = _number(stats.get("total_duration"))
    if 0.0 < progress < 100.0:
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
    performance = []
    if gcode_move:
        performance.append("Speed {:.0f}%".format(
            100.0 * _number(gcode_move.get("speed_factor"), 1.0)))
        performance.append("Flow {:.0f}%".format(
            100.0 * _number(gcode_move.get("extrude_factor"), 1.0)))
    fan_prefixes = (
        "fan_generic ", "heater_fan ", "controller_fan ",
        "temperature_fan ",
    )
    for name, values in status.items():
        if name != "fan" and not name.startswith(fan_prefixes):
            continue
        if not isinstance(values, dict) or "speed" not in values:
            continue
        label = "Part cooling" if name == "fan" else name.split(" ", 1)[1]
        label = label.replace("_", " ").title()
        fan_status = "{} {:.0f}%".format(
            label, 100.0 * _number(values.get("speed")))
        rpm = _number(values.get("rpm"))
        if rpm:
            fan_status += " ({:.0f} RPM)".format(rpm)
        performance.append(fan_status)
    if performance:
        embed.add_field(name="Performance",
                        value=" • ".join(performance)[:1024],
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
    embed.add_field(
        name="Temperatures",
        value=("\n".join(temperatures) or "Unavailable")[:1024],
        inline=False,
    )
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
        title="{} - Details".format(printer_name),
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


def current_job_embed(status: Dict[str, Any], metadata: Dict[str, Any],
                      queue: Dict[str, Any],
                      printer_name: str) -> discord.Embed:
    stats = status.get("print_stats", {})
    filename = str(stats.get("filename") or "No active file")
    state = str(stats.get("state", "unknown")).title()
    embed = discord.Embed(
        title="{} - Current job".format(printer_name),
        description="`{}`".format(filename)[:4096],
        color=discord.Color.blurple(),
    )
    embed.add_field(name="State", value=state)
    progress_value = status.get("display_status", {}).get("progress")
    if progress_value is None:
        progress_value = status.get("virtual_sdcard", {}).get("progress")
    embed.add_field(
        name="Progress",
        value="{:.1f}%".format(100.0 * _number(progress_value)))
    embed.add_field(
        name="Elapsed",
        value=_duration(_number(stats.get("print_duration"))))
    layer_info = stats.get("info", {})
    current_layer = layer_info.get("current_layer")
    total_layer = layer_info.get("total_layer")
    if current_layer is not None or total_layer is not None:
        embed.add_field(
            name="Layer",
            value="{} / {}".format(
                current_layer or "?", total_layer or "?"))
    estimated = _number(metadata.get("estimated_time"))
    if estimated:
        remaining = max(
            0.0, estimated - _number(stats.get("print_duration")))
        embed.add_field(name="Slicer estimate", value=_duration(estimated))
        embed.add_field(name="Estimate remaining", value=_duration(remaining))
    material = metadata.get("filament_name") or metadata.get("filament_type")
    if material:
        embed.add_field(name="Material", value=str(material)[:1024])
    slicer = metadata.get("slicer")
    if slicer:
        slicer_version = metadata.get("slicer_version")
        value = str(slicer)
        if slicer_version:
            value += " {}".format(slicer_version)
        embed.add_field(name="Slicer", value=value[:1024])
    dimensions = []
    for label, key, suffix in (
            ("Layer", "layer_height", " mm"),
            ("Height", "object_height", " mm"),
            ("Nozzle", "nozzle_diameter", " mm")):
        if metadata.get(key) is not None:
            dimensions.append("{} {}{}".format(
                label, metadata[key], suffix))
    if dimensions:
        embed.add_field(
            name="Print geometry", value=" • ".join(dimensions),
            inline=False)
    queued = queue.get("queued_jobs", [])
    embed.add_field(
        name="Queue",
        value="{} • {} job(s)".format(
            str(queue.get("queue_state", "unknown")).title(), len(queued)),
        inline=False,
    )
    embed.timestamp = discord.utils.utcnow()
    return embed


def history_embed(history: Dict[str, Any],
                  printer_name: str) -> discord.Embed:
    lines = []
    for job in history.get("jobs", [])[:10]:
        if not isinstance(job, dict):
            continue
        filename = str(job.get("filename") or "Unknown file")
        state = str(job.get("status") or "unknown").title()
        elapsed = _duration(_number(job.get("print_duration")))
        when = _discord_time(job.get("end_time") or job.get("start_time"))
        lines.append("**{}** - {} • {} • {}".format(
            filename[:120], state, elapsed, when))
    embed = discord.Embed(
        title="{} - Recent prints".format(printer_name),
        description=("\n".join(lines) or "No print history available")[:4096],
        color=discord.Color.blurple(),
    )
    embed.set_footer(text="{} total recorded job(s)".format(
        history.get("count", len(lines))))
    embed.timestamp = discord.utils.utcnow()
    return embed


def queue_embed(queue: Dict[str, Any], printer_name: str) -> discord.Embed:
    lines = []
    for index, job in enumerate(queue.get("queued_jobs", [])[:20], 1):
        if not isinstance(job, dict):
            continue
        filename = job.get("filename") or job.get("job_id") or "Unknown file"
        lines.append("{}. `{}`".format(index, str(filename)[:180]))
    embed = discord.Embed(
        title="{} - Print queue".format(printer_name),
        description=("\n".join(lines) or "The print queue is empty")[:4096],
        color=discord.Color.blurple(),
    )
    embed.add_field(
        name="Queue state",
        value=str(queue.get("queue_state", "unknown")).title())
    embed.timestamp = discord.utils.utcnow()
    return embed


def files_embed(files: list, printer_name: str) -> discord.Embed:
    lines = []
    for item in files[:15]:
        path = str(item.get("path") or "Unknown file")
        lines.append("`{}` - {} • {}".format(
            path[:180], _size(item.get("size")),
            _discord_time(item.get("modified"))))
    embed = discord.Embed(
        title="{} - Recent G-code files".format(printer_name),
        description=("\n".join(lines) or "No G-code files found")[:4096],
        color=discord.Color.blurple(),
    )
    embed.set_footer(text="Use /start_print with the exact path to print")
    embed.timestamp = discord.utils.utcnow()
    return embed


def state_event_content(printer_name: str, status: Dict[str, Any],
                        state: str,
                        previous: Optional[PrintObservation] = None) -> str:
    stats = status.get("print_stats", {})
    filename = stats.get("filename") or "the selected job"
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
    if state == "printing" and previous is not None:
        if previous.state == "paused":
            messages["printing"] = "▶️ **{} resumed:** `{}`".format(
                printer_name, filename)
    return messages.get(
        state, "{} changed to **{}**.".format(printer_name, state.title()))


class PrinterButton(discord.ui.Button):
    def __init__(self, bot: "DisRakerBot", printer_id: str, action: str,
                 label_override: Optional[str] = None):
        definitions = {
            "refresh": ("Refresh", "🔄", discord.ButtonStyle.primary),
            "camera": ("Camera", "📷", discord.ButtonStyle.secondary),
            "details": ("Details", "ℹ️", discord.ButtonStyle.secondary),
            "jobs": ("Current job", "📋", discord.ButtonStyle.secondary),
            "pause_resume": (
                "Pause / Resume", "⏯️", discord.ButtonStyle.secondary),
            "cancel": ("Cancel", "🛑", discord.ButtonStyle.danger),
        }
        label, emoji, style = definitions[action]
        label = label_override or label
        super().__init__(
            label=label, emoji=emoji, style=style,
            custom_id="disraker:{}:{}".format(printer_id, action),
        )
        self.bot = bot
        self.printer_id = printer_id
        self.action = action

    async def callback(self, interaction: discord.Interaction):
        await self.bot.handle_button(interaction, self.printer_id, self.action)


class PrinterView(discord.ui.View):
    def __init__(self, bot: "DisRakerBot", printer_id: str,
                 state: Optional[str] = None):
        super().__init__(timeout=None)
        self.bot = bot
        for action in ("refresh", "camera", "details", "jobs"):
            self.add_item(PrinterButton(bot, printer_id, action))
        if state in ("printing", "paused"):
            label = "Pause" if state == "printing" else "Resume"
            self.add_item(PrinterButton(
                bot, printer_id, "pause_resume", label_override=label))
            self.add_item(PrinterButton(bot, printer_id, "cancel"))
        url = bot.printer_config(printer_id).printer_ui_url
        if url:
            self.add_item(discord.ui.Button(
                label="Open printer UI", emoji="🌐",
                style=discord.ButtonStyle.link, url=url))


class CancelConfirmationView(discord.ui.View):
    def __init__(self, bot: "DisRakerBot", printer_id: str):
        super().__init__(timeout=30.0)
        self.bot = bot
        self.printer_id = printer_id

    @discord.ui.button(label="Confirm cancel",
                       style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction,
                      button: discord.ui.Button):
        del button
        if not await self.bot.require_control_access(
                interaction, self.printer_id):
            return
        try:
            status = await self.bot.client(self.printer_id).status()
            state = str(status.get("print_stats", {}).get("state", ""))
            if state not in ("printing", "paused"):
                await interaction.response.edit_message(
                    content="There is no active print to cancel.", view=None)
                return
            await self.bot.client(self.printer_id).cancel_print()
            await interaction.response.edit_message(
                content="Print cancellation requested.", view=None)
        except MoonrakerError as exc:
            await interaction.response.edit_message(
                content=str(exc), view=None)

    @discord.ui.button(label="Keep printing",
                       style=discord.ButtonStyle.secondary)
    async def dismiss(self, interaction: discord.Interaction,
                      button: discord.ui.Button):
        del button
        await interaction.response.edit_message(
            content="Cancellation dismissed.", view=None)


class StartPrintConfirmationView(discord.ui.View):
    def __init__(self, bot: "DisRakerBot", printer_id: str, filename: str):
        super().__init__(timeout=45.0)
        self.bot = bot
        self.printer_id = printer_id
        self.filename = filename

    @discord.ui.button(label="Start print",
                       style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction,
                      button: discord.ui.Button):
        del button
        if not await self.bot.require_control_access(
                interaction, self.printer_id):
            return
        try:
            status = await self.bot.client(self.printer_id).status()
            state = str(status.get("print_stats", {}).get("state", ""))
            if state in ("printing", "paused"):
                await interaction.response.edit_message(
                    content="A print is already {}.".format(state),
                    view=None)
                return
            await self.bot.client(self.printer_id).start_print(self.filename)
            await interaction.response.edit_message(
                content="Print start requested for `{}`.".format(
                    self.filename), view=None)
        except MoonrakerError as exc:
            await interaction.response.edit_message(
                content=str(exc), view=None)

    @discord.ui.button(label="Do not start",
                       style=discord.ButtonStyle.secondary)
    async def dismiss(self, interaction: discord.Interaction,
                      button: discord.ui.Button):
        del button
        await interaction.response.edit_message(
            content="Print start dismissed.", view=None)


class DisRakerBot(commands.Bot):
    def __init__(self, config: AppConfig,
                 moonrakers: Dict[str, MoonrakerClient]):
        super().__init__(command_prefix=commands.when_mentioned,
                         intents=discord.Intents.none())
        self.tree.allowed_contexts = app_commands.AppCommandContext(
            guild=True, dm_channel=True, private_channel=True)
        self.tree.allowed_installs = app_commands.AppInstallationType(
            guild=True, user=True)
        self.config = config
        self.moonrakers = moonrakers
        self._commands_synced = False
        self._startup_cleanup_done = False
        self._names: Dict[str, str] = {}
        self._messages: Dict[str, discord.Message] = {}
        self._observations: Dict[str, Optional[PrintObservation]] = {}
        self._stores: Dict[str, PrintStateStore] = {}
        self._locks: Dict[str, asyncio.Lock] = {}
        self._realtime_tasks = []
        for printer_id in config.printers:
            store = PrintStateStore(self._state_path(printer_id))
            self._stores[printer_id] = store
            self._observations[printer_id] = store.load()
            self._locks[printer_id] = asyncio.Lock()

    def _state_path(self, printer_id: str) -> Path:
        configured = self.config.notifications.state_file
        if configured and len(self.config.printers) == 1:
            return Path(configured)
        if configured:
            base = Path(configured)
            return base.with_name(
                "{}-{}{}".format(base.stem, printer_id, base.suffix))
        root = Path(__file__).resolve().parent.parent / "data"
        return root / "{}.json".format(printer_id)

    def printer_config(self, printer_id: str) -> PrinterConfig:
        return self.config.printers[printer_id]

    def client(self, printer_id: str) -> MoonrakerClient:
        return self.moonrakers[printer_id]

    def default_printer_id(self) -> str:
        return next(iter(self.config.printers))

    async def current_job_data(self, printer_id: str):
        client = self.client(printer_id)
        status = await client.status()
        filename = str(
            status.get("print_stats", {}).get("filename") or "")
        metadata = {}
        if filename:
            try:
                metadata = await client.gcode_metadata(filename)
            except MoonrakerError:
                LOG.info("G-code metadata unavailable for %s", printer_id,
                         exc_info=True)
        try:
            queue = await client.job_queue()
        except MoonrakerError:
            LOG.info("Job queue unavailable for %s", printer_id,
                     exc_info=True)
            queue = {"queue_state": "unavailable", "queued_jobs": []}
        return status, metadata, queue

    async def setup_hook(self):
        for printer_id in self.config.printers:
            self.add_view(PrinterView(self, printer_id, state="printing"))
        self.notification_poll.change_interval(
            seconds=self.config.notifications.poll_seconds)
        if self.config.notifications.enabled:
            self.notification_poll.start()
            for printer_id in self.config.printers:
                task = asyncio.create_task(
                    self.realtime_monitor(printer_id))
                self._realtime_tasks.append(task)

    async def close(self):
        for task in self._realtime_tasks:
            task.cancel()
        await super().close()

    async def on_ready(self):
        if not self._commands_synced:
            await self.tree.sync()
            if self.config.discord.allowed_guild_id:
                guild = discord.Object(
                    id=self.config.discord.allowed_guild_id)
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
            self._commands_synced = True
        if not self._startup_cleanup_done:
            for printer_id in self.config.printers:
                await self.delete_terminal_message(printer_id)
            self._startup_cleanup_done = True
        LOG.info("Logged in as %s with %d printers",
                 self.user, len(self.config.printers))

    async def printer_name(self, printer_id: str) -> str:
        if printer_id in self._names:
            return self._names[printer_id]
        configured = self.printer_config(printer_id).moonraker.printer_name
        if configured:
            self._names[printer_id] = configured
            return configured
        try:
            info = await self.client(printer_id).printer_info()
            name = str(info.get("hostname") or printer_id)
            self._names[printer_id] = name
            return name
        except MoonrakerError:
            return printer_id

    def _is_known_printer(self, printer_id: Optional[str]) -> bool:
        return printer_id is not None and printer_id in self.config.printers

    async def require_control_access(
            self, interaction: discord.Interaction, printer_id: str):
        if not self.config.discord.job_controls_enabled:
            await interaction.response.send_message(
                "Printer controls are disabled.", ephemeral=True)
            return False
        printer = self.printer_config(printer_id)
        if user_can_control(self.config, printer, interaction.user):
            return True
        await interaction.response.send_message(
            "You cannot control this printer.", ephemeral=True)
        return False

    async def handle_button(self, interaction: discord.Interaction,
                            printer_id: str, action: str):
        if not self._is_known_printer(printer_id):
            await interaction.response.send_message(
                "That printer is no longer configured.", ephemeral=True)
            return
        client = self.client(printer_id)
        if action == "camera":
            await interaction.response.defer(ephemeral=True, thinking=True)
            try:
                image = await client.camera_image()
                await interaction.followup.send(
                    file=discord.File(BytesIO(image.data), image.filename),
                    ephemeral=True)
            except MoonrakerError as exc:
                await interaction.followup.send(str(exc), ephemeral=True)
            return
        if action == "details":
            await interaction.response.defer(ephemeral=True, thinking=True)
            try:
                status = await client.status()
                info = await client.printer_info()
                embed = details_embed(
                    status, info, await self.printer_name(printer_id))
                await interaction.edit_original_response(embed=embed)
            except MoonrakerError as exc:
                await interaction.edit_original_response(content=str(exc))
            return
        if action == "jobs":
            if not await self.require_control_access(
                    interaction, printer_id):
                return
            await interaction.response.defer(ephemeral=True, thinking=True)
            try:
                status, metadata, queue = await self.current_job_data(
                    printer_id)
                embed = current_job_embed(
                    status, metadata, queue,
                    await self.printer_name(printer_id))
                await interaction.edit_original_response(embed=embed)
            except MoonrakerError as exc:
                await interaction.edit_original_response(content=str(exc))
            return
        if action == "refresh":
            await interaction.response.defer(thinking=True)
            try:
                status = await client.status()
                kwargs = await self.status_edit_payload(printer_id, status)
                await interaction.edit_original_response(**kwargs)
            except MoonrakerError as exc:
                await interaction.edit_original_response(
                    embed=error_embed(
                        str(exc), await self.printer_name(printer_id)),
                    attachments=[], view=PrinterView(self, printer_id))
            return
        if not await self.require_control_access(interaction, printer_id):
            return
        if action == "cancel":
            await interaction.response.send_message(
                "Cancel the current print? This cannot be undone.",
                view=CancelConfirmationView(self, printer_id),
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            status = await client.status()
            state = str(status.get("print_stats", {}).get("state", ""))
            if state == "printing":
                await client.pause_print()
                result = "Pause requested."
            elif state == "paused":
                await client.resume_print()
                result = "Resume requested."
            else:
                result = "There is no printing or paused job."
            await interaction.edit_original_response(content=result)
        except MoonrakerError as exc:
            await interaction.edit_original_response(content=str(exc))

    async def status_content(self, printer_id: str, status: Dict[str, Any]):
        embed = status_embed(status, await self.printer_name(printer_id))
        image = None
        if self.config.notifications.show_camera_in_status:
            try:
                camera = await self.client(printer_id).camera_image()
                image = discord.File(BytesIO(camera.data), camera.filename)
                embed.set_image(url="attachment://{}".format(camera.filename))
            except MoonrakerError:
                LOG.warning("Camera unavailable for %s", printer_id,
                            exc_info=True)
        return embed, image

    async def status_edit_payload(self, printer_id: str,
                                  status: Dict[str, Any]):
        embed, image = await self.status_content(printer_id, status)
        attachments = [image] if image is not None else []
        return {
            "embed": embed,
            "attachments": attachments,
            "view": PrinterView(
                self, printer_id,
                state=str(status.get("print_stats", {}).get("state", ""))),
        }

    async def status_channel(self, printer_id: str):
        printer = self.printer_config(printer_id)
        channel_id = (
            printer.status_channel_id
            or self.config.discord.status_channel_id)
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

    async def delete_terminal_message(self, printer_id: str, channel=None):
        terminal = self._stores[printer_id].terminal_message()
        if terminal is None:
            return
        _state, message_id = terminal
        message = self._messages.get(printer_id)
        if message is None or message.id != message_id:
            channel = channel or await self.status_channel(printer_id)
            if channel is None:
                return
            try:
                message = await channel.fetch_message(message_id)
            except discord.NotFound:
                self._stores[printer_id].clear_terminal_message()
                return
            except discord.DiscordException:
                LOG.exception(
                    "Unable to fetch old terminal card for %s", printer_id)
                return
        try:
            await message.delete()
        except discord.NotFound:
            pass
        except discord.DiscordException:
            LOG.exception(
                "Unable to delete old terminal card for %s", printer_id)
            return
        if self._messages.get(printer_id) is message:
            self._messages.pop(printer_id, None)
        self._stores[printer_id].clear_terminal_message()

    async def send_status(self, interaction: discord.Interaction,
                          printer_id: str, ephemeral: bool):
        await interaction.response.defer(ephemeral=ephemeral, thinking=True)
        try:
            status = await self.client(printer_id).status()
            embed, image = await self.status_content(printer_id, status)
            kwargs = {
                "embed": embed,
                "view": PrinterView(
                    self, printer_id,
                    state=str(status.get(
                        "print_stats", {}).get("state", ""))),
                "ephemeral": ephemeral,
            }
            if image is not None:
                kwargs["file"] = image
            await interaction.followup.send(**kwargs)
        except MoonrakerError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)

    async def update_dashboard(self, printer_id: str, channel,
                               status: Dict[str, Any], force_new: bool):
        embed, image = await self.status_content(printer_id, status)
        view = PrinterView(
            self, printer_id,
            state=str(status.get("print_stats", {}).get("state", "")))
        kwargs = {"embed": embed, "view": view}
        if image is not None:
            kwargs["file"] = image
        message = self._messages.get(printer_id)
        if force_new or message is None:
            self._messages[printer_id] = await channel.send(**kwargs)
            return
        attachments = [image] if image is not None else []
        try:
            await message.edit(
                embed=embed, attachments=attachments, view=view)
        except discord.NotFound:
            self._messages[printer_id] = await channel.send(**kwargs)

    def mention_text(
            self, printer_id: str, state: str,
            previous: Optional[PrintObservation]) -> str:
        printer = self.printer_config(printer_id)
        mention_state = state
        if (state == "printing" and previous is not None
                and previous.state == "paused"):
            mention_state = "resumed"
        if mention_state not in printer.mention_states:
            return ""
        mentions = ["<@{}>".format(user_id)
                    for user_id in printer.mention_user_ids]
        mentions.extend("<@&{}>".format(role_id)
                        for role_id in printer.mention_role_ids)
        return " ".join(mentions)

    async def send_state_event(
            self, printer_id: str, channel, status: Dict[str, Any],
            state: str, previous: Optional[PrintObservation]):
        printer_name = await self.printer_name(printer_id)
        content = state_event_content(
            printer_name, status, state, previous)
        mentions = self.mention_text(printer_id, state, previous)
        if mentions:
            content = "{}\n{}".format(mentions, content)
        embed = status_embed(status, printer_name)
        kwargs = {
            "content": content,
            "embed": embed,
            "view": PrinterView(self, printer_id, state=state),
            "allowed_mentions": discord.AllowedMentions(
                everyone=False, users=True, roles=True, replied_user=False),
        }
        if self.config.notifications.include_camera_in_events:
            try:
                image = await self.client(printer_id).camera_image()
                kwargs["file"] = discord.File(
                    BytesIO(image.data), image.filename)
                embed.set_image(url="attachment://{}".format(image.filename))
            except MoonrakerError:
                LOG.warning("Camera unavailable for %s event", printer_id,
                            exc_info=True)
        return await channel.send(**kwargs)

    async def process_status(self, printer_id: str,
                             status: Dict[str, Any]):
        async with self._locks[printer_id]:
            observation = PrintObservation.from_status(status)
            previous = self._observations[printer_id]
            changed = observation.is_new_transition(previous)
            self._observations[printer_id] = observation
            self._stores[printer_id].save(observation)
            channel = await self.status_channel(printer_id)
            if channel is None:
                return
            state = observation.state
            if changed and state == "printing":
                await self.delete_terminal_message(printer_id, channel)
            notify = changed and (
                state in self.config.notifications.states
                and (state != "standby"
                     or self.config.notifications.send_idle)
            )
            if notify:
                message = await self.send_state_event(
                    printer_id, channel, status, state, previous)
                self._messages[printer_id] = message
                if state in ("cancelled", "error"):
                    self._stores[printer_id].save_terminal_message(
                        state, message.id)
                return
            if changed or state == "printing":
                await self.update_dashboard(
                    printer_id, channel, status, force_new=changed)
                if changed and state in ("cancelled", "error"):
                    message = self._messages.get(printer_id)
                    if message is not None:
                        self._stores[printer_id].save_terminal_message(
                            state, message.id)

    async def realtime_monitor(self, printer_id: str):
        await self.wait_until_ready()
        client = self.client(printer_id)
        while not self.is_closed():
            try:
                async for update in client.status_updates():
                    print_stats = update.get("print_stats")
                    if not isinstance(print_stats, dict):
                        continue
                    if "state" not in print_stats:
                        continue
                    state = str(print_stats["state"])
                    previous = self._observations[printer_id]
                    if previous is not None and state == previous.state:
                        continue
                    status = await client.status()
                    await self.process_status(printer_id, status)
            except MoonrakerError:
                LOG.warning("Real-time feed unavailable for %s", printer_id,
                            exc_info=True)
            except discord.DiscordException:
                LOG.warning("Discord update failed for %s", printer_id,
                            exc_info=True)
            except asyncio.CancelledError:
                return
            await asyncio.sleep(5.0)

    async def _poll_printer(self, printer_id: str):
        try:
            status = await self.client(printer_id).status()
            await self.process_status(printer_id, status)
        except (MoonrakerError, discord.DiscordException):
            LOG.exception("Moonraker poll failed for %s", printer_id)

    @tasks.loop(seconds=10.0)
    async def notification_poll(self):
        await asyncio.gather(*(
            self._poll_printer(printer_id)
            for printer_id in self.config.printers
        ))

    @notification_poll.before_loop
    async def before_notification_poll(self):
        await self.wait_until_ready()


def register_commands(bot: DisRakerBot):
    async def resolve(interaction: discord.Interaction,
                      printer_id: Optional[str]):
        selected = printer_id or bot.default_printer_id()
        if selected not in bot.config.printers:
            await interaction.response.send_message(
                "Unknown printer ID. Use `/printers` to list printers.",
                ephemeral=True,
            )
            return None
        return selected

    async def autocomplete_printer(
            interaction: discord.Interaction, current: str):
        del interaction
        current = current.lower()
        choices = []
        for printer_id, printer in bot.config.printers.items():
            name = printer.moonraker.printer_name or printer_id
            if current in printer_id.lower() or current in name.lower():
                choices.append(app_commands.Choice(
                    name="{} ({})".format(name, printer_id)[:100],
                    value=printer_id))
        return choices[:25]

    @bot.tree.command(name="printer",
                      description="Show one printer's status and controls")
    @app_commands.describe(printer_id="Configured printer ID")
    async def printer(interaction: discord.Interaction,
                      printer_id: Optional[str] = None):
        selected = await resolve(interaction, printer_id)
        if selected is not None:
            await bot.send_status(
                interaction, selected,
                ephemeral=not bot.config.discord.public_status_responses)

    printer.autocomplete("printer_id")(autocomplete_printer)

    @bot.tree.command(name="dashboard",
                      description="Publish one printer's shared status card")
    @app_commands.describe(printer_id="Configured printer ID")
    @app_commands.default_permissions(manage_messages=True)
    async def dashboard(interaction: discord.Interaction,
                        printer_id: Optional[str] = None):
        selected = await resolve(interaction, printer_id)
        if selected is not None:
            await bot.send_status(interaction, selected, ephemeral=False)

    dashboard.autocomplete("printer_id")(autocomplete_printer)

    @bot.tree.command(name="job",
                      description="Show the active print and queue summary")
    @app_commands.describe(printer_id="Configured printer ID")
    async def job(interaction: discord.Interaction,
                  printer_id: Optional[str] = None):
        selected = await resolve(interaction, printer_id)
        if selected is None:
            return
        if not await bot.require_control_access(interaction, selected):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            status, metadata, queue_data = await bot.current_job_data(
                selected)
            embed = current_job_embed(
                status, metadata, queue_data,
                await bot.printer_name(selected))
            await interaction.edit_original_response(embed=embed)
        except MoonrakerError as exc:
            await interaction.edit_original_response(content=str(exc))

    job.autocomplete("printer_id")(autocomplete_printer)

    @bot.tree.command(name="history",
                      description="Show recent completed and stopped prints")
    @app_commands.describe(printer_id="Configured printer ID")
    async def history(interaction: discord.Interaction,
                      printer_id: Optional[str] = None):
        selected = await resolve(interaction, printer_id)
        if selected is None:
            return
        if not await bot.require_control_access(interaction, selected):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            data = await bot.client(selected).recent_history()
            embed = history_embed(data, await bot.printer_name(selected))
            await interaction.edit_original_response(embed=embed)
        except MoonrakerError as exc:
            await interaction.edit_original_response(content=str(exc))

    history.autocomplete("printer_id")(autocomplete_printer)

    @bot.tree.command(name="queue",
                      description="Show prints waiting in Moonraker's queue")
    @app_commands.describe(printer_id="Configured printer ID")
    async def queue(interaction: discord.Interaction,
                    printer_id: Optional[str] = None):
        selected = await resolve(interaction, printer_id)
        if selected is None:
            return
        if not await bot.require_control_access(interaction, selected):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            data = await bot.client(selected).job_queue()
            embed = queue_embed(data, await bot.printer_name(selected))
            await interaction.edit_original_response(embed=embed)
        except MoonrakerError as exc:
            await interaction.edit_original_response(content=str(exc))

    queue.autocomplete("printer_id")(autocomplete_printer)

    @bot.tree.command(name="files",
                      description="Show recently added printable files")
    @app_commands.describe(printer_id="Configured printer ID")
    async def files(interaction: discord.Interaction,
                    printer_id: Optional[str] = None):
        selected = await resolve(interaction, printer_id)
        if selected is None:
            return
        if not await bot.require_control_access(interaction, selected):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            data = await bot.client(selected).gcode_files()
            embed = files_embed(data, await bot.printer_name(selected))
            await interaction.edit_original_response(embed=embed)
        except MoonrakerError as exc:
            await interaction.edit_original_response(content=str(exc))

    files.autocomplete("printer_id")(autocomplete_printer)

    @bot.tree.command(name="start_print",
                      description="Start a G-code file after confirmation")
    @app_commands.describe(
        filename="Exact path shown by /files",
        printer_id="Configured printer ID",
    )
    async def start_print(interaction: discord.Interaction, filename: str,
                          printer_id: Optional[str] = None):
        selected = await resolve(interaction, printer_id)
        if selected is None:
            return
        if not await bot.require_control_access(interaction, selected):
            return
        filename = filename.strip()
        if not filename:
            await interaction.response.send_message(
                "A G-code filename is required.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            metadata = await bot.client(selected).gcode_metadata(filename)
            expected = str(metadata.get("filename") or filename)
            view = StartPrintConfirmationView(bot, selected, expected)
            await interaction.edit_original_response(
                content="Start `{}` on **{}**?".format(
                    expected, await bot.printer_name(selected)),
                view=view,
            )
        except MoonrakerError as exc:
            await interaction.edit_original_response(content=str(exc))

    start_print.autocomplete("printer_id")(autocomplete_printer)

    @bot.tree.command(name="printers",
                      description="List configured Moonraker printers")
    async def printers(interaction: discord.Interaction):
        lines = []
        for printer_id, printer_config in bot.config.printers.items():
            name = printer_config.moonraker.printer_name or printer_id
            lines.append("• **{}** - `{}`".format(name, printer_id))
        embed = discord.Embed(
            title="Configured printers",
            description="\n".join(lines),
            color=discord.Color.blurple(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
