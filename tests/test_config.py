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
            "relay": {
                "listen_host": "127.0.0.1",
                "sources": {
                    "remote-c5": {
                        "secret": "test-secret",
                        "display_name": "Remote C5",
                        "channel_id": 99,
                    }
                },
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "disraker.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            config = load_config(path)
        self.assertEqual(config.discord.control_user_ids, [123])
        self.assertEqual(config.discord.control_role_ids, [456])
        self.assertEqual(config.moonraker.printer_name, "Creator 5")
        self.assertEqual(config.notifications.poll_seconds, 60.0)
        source = config.relay.sources["remote-c5"]
        self.assertEqual(source.display_name, "Remote C5")
        self.assertEqual(source.channel_id, 99)

    def test_publisher_requires_identity_and_secret(self):
        data = {
            "discord": {"token": "test-token"},
            "relay": {"publish_url": "http://relay.invalid/status"},
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "disraker.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "relay_id and secret"):
                load_config(path)


if __name__ == "__main__":
    unittest.main()
