import tempfile
import unittest
from pathlib import Path

from disraker.state import PrintObservation, PrintStateStore


class PrintObservationTests(unittest.TestCase):
    def test_same_active_print_after_restart_is_not_a_transition(self):
        previous = PrintObservation("printing", "part.gcode", 120.0)
        current = PrintObservation("printing", "part.gcode", 125.0)
        self.assertFalse(current.is_new_transition(previous))

    def test_duration_reset_detects_repeated_filename(self):
        previous = PrintObservation("printing", "part.gcode", 120.0)
        current = PrintObservation("printing", "part.gcode", 2.0)
        self.assertTrue(current.is_new_transition(previous))

    def test_state_store_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            store = PrintStateStore(Path(directory) / "state.json")
            expected = PrintObservation("paused", "part.gcode", 20.0)
            store.save(expected)
            self.assertEqual(store.load(), expected)

    def test_terminal_message_survives_observation_updates(self):
        with tempfile.TemporaryDirectory() as directory:
            store = PrintStateStore(Path(directory) / "state.json")
            store.save(PrintObservation("cancelled", "part.gcode", 30.0))
            store.save_terminal_message("cancelled", 12345)
            store.save(PrintObservation("standby", "part.gcode", 30.0))
            self.assertEqual(
                store.terminal_message(), ("cancelled", 12345))
            store.clear_terminal_message()
            self.assertIsNone(store.terminal_message())
            self.assertEqual(store.load().state, "standby")


if __name__ == "__main__":
    unittest.main()
