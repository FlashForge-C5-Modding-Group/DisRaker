import json
import tempfile
import unittest
from pathlib import Path

from disraker.config import load_config


class ConfigTests(unittest.TestCase):
    def test_control_allowlists_and_new_poll_default(self):
        data = {
            "discord": {
                "token": "test-token",
                "control_user_ids": [123],
                "control_role_ids": [456],
            },
            "moonraker": {"printer_name": "Creator 5"},
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "disraker.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            config = load_config(path)
        self.assertEqual(config.discord.control_user_ids, [123])
        self.assertEqual(config.discord.control_role_ids, [456])
        self.assertEqual(config.moonraker.printer_name, "Creator 5")
        self.assertEqual(config.notifications.poll_seconds, 60.0)


if __name__ == "__main__":
    unittest.main()
