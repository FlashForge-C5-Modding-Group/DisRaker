import json
import logging
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Optional


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

    def load(self) -> Optional[PrintObservation]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return PrintObservation(
                state=str(data.get("state", "unknown")),
                filename=str(data.get("filename", "")),
                total_duration=float(data.get("total_duration", 0.0)),
            )
        except FileNotFoundError:
            return None
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            LOG.warning("Unable to read persisted print state", exc_info=True)
            return None

    def save(self, observation: PrintObservation):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(self.path.suffix + ".tmp")
            temporary.write_text(
                json.dumps(asdict(observation), indent=2) + "\n",
                encoding="utf-8",
            )
            os.replace(str(temporary), str(self.path))
        except OSError:
            LOG.warning("Unable to persist print state", exc_info=True)
