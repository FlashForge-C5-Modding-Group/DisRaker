import unittest

from disraker.bot import (
    current_job_embed,
    files_embed,
    history_embed,
    queue_embed,
    status_embed,
)


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

    def test_current_job_includes_metadata_and_queue(self):
        embed = current_job_embed(
            {
                "print_stats": {
                    "state": "printing",
                    "filename": "parts/test.gcode",
                    "print_duration": 120,
                },
            },
            {
                "estimated_time": 600,
                "filament_type": "PLA",
                "slicer": "OrcaSlicer",
                "layer_height": 0.2,
            },
            {"queue_state": "ready", "queued_jobs": [{"job_id": "1"}]},
            "Test Printer",
        )
        fields = {field.name: field.value for field in embed.fields}
        self.assertEqual(fields["State"], "Printing")
        self.assertEqual(fields["Estimate remaining"], "00:08:00")
        self.assertIn("1 job(s)", fields["Queue"])

    def test_print_management_lists(self):
        history = history_embed({
            "count": 1,
            "jobs": [{
                "filename": "cube.gcode",
                "status": "completed",
                "print_duration": 90,
                "end_time": 1000,
            }],
        }, "Test Printer")
        queue = queue_embed({
            "queue_state": "paused",
            "queued_jobs": [{"filename": "next.gcode"}],
        }, "Test Printer")
        files = files_embed([{
            "path": "new.gcode", "size": 2048, "modified": 1000,
        }], "Test Printer")
        self.assertIn("cube.gcode", history.description)
        self.assertIn("next.gcode", queue.description)
        self.assertIn("new.gcode", files.description)
