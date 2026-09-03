import tempfile
import unittest
from pathlib import Path

from disraker.bot import DisRakerBot, register_commands
from disraker.config import (
    AppConfig,
    DiscordConfig,
    MoonrakerConfig,
    NotificationConfig,
    PrinterConfig,
)


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


if __name__ == "__main__":
    unittest.main()
