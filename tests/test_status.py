import unittest

from disraker.bot import status_embed


class StatusEmbedTests(unittest.TestCase):
    def test_all_fans_are_displayed(self):
        status = {
            "print_stats": {"state": "printing", "filename": "test.gcode"},
            "virtual_sdcard": {"progress": 0.5},
            "fan": {"speed": 0.25},
            "heater_fan hotend": {"speed": 1.0, "rpm": 5100},
            "controller_fan electronics": {"speed": 0.6},
        }
        embed = status_embed(status, "Test Printer")
        performance = next(
            field.value for field in embed.fields
            if field.name == "Performance")
        self.assertIn("Part Cooling 25%", performance)
        self.assertIn("Hotend 100% (5100 RPM)", performance)
        self.assertIn("Electronics 60%", performance)
