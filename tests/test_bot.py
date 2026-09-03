import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from disraker.bot import DisRakerBot, register_commands
from disraker.config import (
    AppConfig,
    DiscordConfig,
    MoonrakerConfig,
    NotificationConfig,
    PrinterConfig,
)
from disraker.moonraker import MoonrakerError


class BotCommandContextTests(unittest.TestCase):
    def test_commands_support_user_install_and_dm_contexts(self):
        with tempfile.TemporaryDirectory() as directory:
            config = AppConfig(
                discord=DiscordConfig(token="test"),
                notifications=NotificationConfig(
                    enabled=False,
                    state_file=str(Path(directory) / "state.json"),
                ),
                printers={
                    "test": PrinterConfig(moonraker=MoonrakerConfig()),
                },
            )
            bot = DisRakerBot(config, {"test": object()})
            register_commands(bot)
            command = bot.tree.get_command("printer")
            payload = command.to_dict(bot.tree)
            self.assertEqual(payload["contexts"], [0, 1, 2])
            self.assertEqual(payload["integration_types"], [0, 1])
            self.assertTrue(payload["dm_permission"])


class BotConnectivityTests(unittest.IsolatedAsyncioTestCase):
    def _bot(self, directory, client):
        config = AppConfig(
            discord=DiscordConfig(token="test"),
            notifications=NotificationConfig(
                enabled=False,
                state_file=str(Path(directory) / "state.json"),
            ),
            printers={
                "test": PrinterConfig(moonraker=MoonrakerConfig()),
            },
        )
        return DisRakerBot(config, {"test": client})

    async def test_offline_notification_is_sent_once(self):
        with tempfile.TemporaryDirectory() as directory:
            bot = self._bot(directory, object())
            channel = SimpleNamespace(send=AsyncMock(
                return_value=SimpleNamespace(id=123)))
            bot.status_channel = AsyncMock(return_value=channel)
            bot.printer_name = AsyncMock(return_value="Test Printer")
            error = MoonrakerError("connection refused")
            await bot.mark_offline("test", error)
            await bot.mark_offline("test", error)
            channel.send.assert_awaited_once()
            self.assertFalse(bot._stores["test"].connectivity())

    async def test_success_after_offline_is_marked_as_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            status = {"print_stats": {"state": "standby"}}
            client = SimpleNamespace(status=AsyncMock(return_value=status))
            bot = self._bot(directory, client)
            bot._online["test"] = False
            bot.process_status = AsyncMock()
            await bot._poll_printer("test")
            bot.process_status.assert_awaited_once_with(
                "test", status, recovered=True)
            self.assertTrue(bot._stores["test"].connectivity())


if __name__ == "__main__":
    unittest.main()
