import unittest

from disraker.config import MoonrakerConfig
from disraker.moonraker import MoonrakerClient


class FakeMoonrakerClient(MoonrakerClient):
    def __init__(self):
        super().__init__(MoonrakerConfig())
        self.requests = []
        self.responses = {}

    async def _json(self, method, path, **kwargs):
        self.requests.append((method, path, kwargs))
        return self.responses[path]


class MoonrakerPrintManagementTests(unittest.IsolatedAsyncioTestCase):
    async def test_files_are_sorted_newest_first_and_limited(self):
        client = FakeMoonrakerClient()
        client.responses["/server/files/list"] = [
            {"path": "old.gcode", "modified": 10},
            {"path": "new.gcode", "modified": 20},
        ]
        files = await client.gcode_files(limit=1)
        self.assertEqual(files[0]["path"], "new.gcode")
        self.assertEqual(
            client.requests[0][2]["params"], {"root": "gcodes"})

    async def test_history_and_queue_endpoints(self):
        client = FakeMoonrakerClient()
        client.responses["/server/history/list"] = {
            "count": 1, "jobs": [{"filename": "cube.gcode"}],
        }
        client.responses["/server/job_queue/status"] = {
            "queue_state": "ready", "queued_jobs": [],
        }
        history = await client.recent_history(limit=5)
        queue = await client.job_queue()
        self.assertEqual(history["count"], 1)
        self.assertEqual(queue["queue_state"], "ready")
        self.assertEqual(client.requests[0][2]["params"]["order"], "desc")

    async def test_start_print_uses_filename_parameter(self):
        client = FakeMoonrakerClient()
        client.responses["/printer/print/start"] = "ok"
        await client.start_print("parts/cube.gcode")
        self.assertEqual(client.requests[0], (
            "POST",
            "/printer/print/start",
            {"params": {"filename": "parts/cube.gcode"}},
        ))


if __name__ == "__main__":
    unittest.main()
