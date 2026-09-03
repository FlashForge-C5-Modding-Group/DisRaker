import unittest
from types import SimpleNamespace

from disraker.bot import (
    current_job_embed,
    files_embed,
    history_embed,
    PrinterView,
    queue_embed,
    status_embed,
    user_can_control,
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


class PermissionTests(unittest.TestCase):
    def _config(self, users=None, roles=None):
        return SimpleNamespace(discord=SimpleNamespace(
            control_user_ids=users or [],
            control_role_ids=roles or [],
        ))

    def _printer(self, users=None, roles=None):
        return SimpleNamespace(
            control_user_ids=users or [],
            control_role_ids=roles or [],
        )

    def _user(self, user_id, roles=None, manage_guild=False):
        return SimpleNamespace(
            id=user_id,
            roles=[SimpleNamespace(id=role_id) for role_id in roles or []],
            guild_permissions=SimpleNamespace(
                manage_guild=manage_guild),
        )

    def test_empty_allowlists_fail_closed(self):
        allowed = user_can_control(
            self._config(), self._printer(), self._user(10))
        self.assertFalse(allowed)

    def test_global_and_printer_permissions_are_accepted(self):
        self.assertTrue(user_can_control(
            self._config(users=[10]), self._printer(), self._user(10)))
        self.assertTrue(user_can_control(
            self._config(), self._printer(roles=[20]),
            self._user(10, roles=[20])))

    def test_manage_server_is_accepted(self):
        self.assertTrue(user_can_control(
            self._config(), self._printer(),
            self._user(10, manage_guild=True)))


class PrinterViewTests(unittest.TestCase):
    def _view(self, state):
        printer = SimpleNamespace(printer_ui_url="")
        bot = SimpleNamespace(printer_config=lambda printer_id: printer)
        return PrinterView(bot, "test", state=state)

    def _actions(self, view):
        return {
            item.custom_id.rsplit(":", 1)[-1]: item.label
            for item in view.children if item.custom_id
        }

    def test_active_print_has_pause_and_cancel(self):
        actions = self._actions(self._view("printing"))
        self.assertEqual(actions["pause_resume"], "Pause")
        self.assertIn("cancel", actions)

    def test_paused_print_has_resume_and_cancel(self):
        actions = self._actions(self._view("paused"))
        self.assertEqual(actions["pause_resume"], "Resume")
        self.assertIn("cancel", actions)

    def test_terminal_states_have_no_job_controls(self):
        for state in ("standby", "complete", "cancelled", "error", None):
            actions = self._actions(self._view(state))
            self.assertNotIn("pause_resume", actions)
            self.assertNotIn("cancel", actions)
