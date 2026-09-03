from typing import Optional, TYPE_CHECKING

import discord

from .moonraker import MoonrakerError


if TYPE_CHECKING:
    from .bot import DisRakerBot


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
        super().__init__(
            label=label_override or label,
            emoji=emoji,
            style=style,
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
