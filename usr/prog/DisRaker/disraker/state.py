import json
import logging
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


LOG = logging.getLogger("disraker")


@dataclass(frozen=True)
class PrintObservation:
    state: str = "unknown"
    filename: str = ""
    total_duration: float = 0.0

    @classmethod
    def from_status(cls, status: Dict[str, Any]):
        stats = status.get("print_stats", {})
        try:
            duration = float(stats.get("total_duration", 0.0))
        except (TypeError, ValueError):
            duration = 0.0
        return cls(
            state=str(stats.get("state", "unknown")),
            filename=str(stats.get("filename") or ""),
            total_duration=max(0.0, duration),
        )

    def is_new_transition(self, previous: Optional["PrintObservation"]):
        if previous is None:
            return True
        if self.state != previous.state or self.filename != previous.filename:
            return True
        active = self.state in ("printing", "paused")
        return active and self.total_duration + 5.0 < previous.total_duration


class PrintStateStore:
    def __init__(self, path: Path):
        self.path = path

    def _read(self) -> Dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("state data is not an object")
            return data
        except FileNotFoundError:
            return {}
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            LOG.warning("Unable to read persisted print state", exc_info=True)
            return {}

    def _write(self, data: Dict[str, Any]):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(self.path.suffix + ".tmp")
            temporary.write_text(
                json.dumps(data, indent=2) + "\n", encoding="utf-8")
            os.replace(str(temporary), str(self.path))
        except OSError:
            LOG.warning("Unable to persist print state", exc_info=True)

    def load(self) -> Optional[PrintObservation]:
        data = self._read()
        if not data:
            return None
        try:
            return PrintObservation(
                state=str(data.get("state", "unknown")),
                filename=str(data.get("filename", "")),
                total_duration=float(data.get("total_duration", 0.0)),
            )
        except (TypeError, ValueError):
            LOG.warning("Persisted print observation is malformed")
            return None

    def save(self, observation: PrintObservation):
        data = self._read()
        data.update(asdict(observation))
        self._write(data)

    def terminal_message(self) -> Optional[Tuple[str, int]]:
        data = self._read()
        try:
            state = str(data.get("terminal_message_state", ""))
            message_id = int(data.get("terminal_message_id", 0))
        except (TypeError, ValueError):
            return None
        if state not in ("cancelled", "error") or not message_id:
            return None
        return state, message_id

    def save_terminal_message(self, state: str, message_id: int):
        if state not in ("cancelled", "error"):
            raise ValueError("Only cancelled or error messages are terminal")
        data = self._read()
        data["terminal_message_state"] = state
        data["terminal_message_id"] = int(message_id)
        self._write(data)

    def clear_terminal_message(self):
        data = self._read()
        data.pop("terminal_message_state", None)
        data.pop("terminal_message_id", None)
        self._write(data)
