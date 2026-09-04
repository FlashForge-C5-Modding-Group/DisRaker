from typing import Optional

import discord
from discord import app_commands

from .bot import (
    DisRakerBot,
    current_job_embed,
    files_embed,
    history_embed,
    queue_embed,
)
from .moonraker import MoonrakerError
from .views import StartPrintConfirmationView


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
