import json
import tempfile
import unittest
from pathlib import Path

from disraker.config import load_config


class ConfigTests(unittest.TestCase):
    def _load(self, data):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "disraker.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            return load_config(path)

    def test_multiple_printers_and_permissions(self):
        data = {
            "discord": {
                "token": "test-token",
                "control_user_ids": [100],
            },
            "printers": {
                "creator5": {
                    "name": "Creator 5",
                    "control_user_ids": [200],
                    "control_role_ids": [300],
                    "mention_user_ids": [400],
                    "mention_role_ids": [500],
                    "mention_states": ["printing", "complete"],
                    "moonraker": {"url": "http://c5:7125"},
                },
                "voron": {
                    "name": "Voron",
                    "moonraker": {"url": "http://voron:7125"},
                },
            },
        }
        config = self._load(data)
        self.assertEqual(list(config.printers), ["creator5", "voron"])
        creator = config.printers["creator5"]
        self.assertEqual(creator.moonraker.printer_name, "Creator 5")
        self.assertEqual(creator.control_user_ids, [200])
        self.assertEqual(creator.control_role_ids, [300])
        self.assertEqual(creator.mention_user_ids, [400])
        self.assertEqual(creator.mention_role_ids, [500])
        self.assertEqual(creator.mention_states, ["printing", "complete"])
        self.assertEqual(config.notifications.poll_seconds, 60.0)

    def test_legacy_single_moonraker_config_still_loads(self):
        config = self._load({
            "discord": {"token": "test-token"},
            "moonraker": {
                "url": "http://127.0.0.1:7125",
                "printer_name": "Legacy Printer",
            },
        })
        self.assertEqual(list(config.printers), ["default"])
        self.assertEqual(config.moonraker.printer_name, "Legacy Printer")

    def test_printer_id_rejects_path_characters(self):
        with self.assertRaisesRegex(ValueError, "printer IDs"):
            self._load({
                "discord": {"token": "test-token"},
                "printers": {
                    "../bad": {"moonraker": {}},
                },
            })


if __name__ == "__main__":
    unittest.main()
