#!/usr/bin/env python3
import asyncio
import logging
import os
from contextlib import AsyncExitStack
from pathlib import Path

from disraker.bot import DisRakerBot, register_commands
from disraker.config import load_config
from disraker.moonraker import MoonrakerClient


async def main():
    logging.basicConfig(
        level=os.environ.get("DISRAKER_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config_path = os.environ.get("DISRAKER_CONFIG")
    config = load_config(Path(config_path) if config_path else None)
    async with AsyncExitStack() as stack:
        moonrakers = {}
        for printer_id, printer in config.printers.items():
            moonrakers[printer_id] = await stack.enter_async_context(
                MoonrakerClient(printer.moonraker))
        bot = DisRakerBot(config, moonrakers)
        register_commands(bot)
        await bot.start(config.discord.token)


if __name__ == "__main__":
    asyncio.run(main())
