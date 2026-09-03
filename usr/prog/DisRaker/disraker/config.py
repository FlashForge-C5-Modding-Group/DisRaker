import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


DEFAULT_CONFIG = Path("/usr/prog/scripts/config/disraker.json")
DEFAULT_MENTION_STATES = [
    "printing", "paused", "complete", "cancelled", "error",
]


@dataclass(frozen=True)
class MoonrakerConfig:
    url: str = "http://127.0.0.1:7125"
    api_key: str = ""
    timeout_seconds: float = 10.0
    verify_ssl: bool = True
    camera_name: str = ""
    snapshot_url: str = ""
    printer_name: str = ""
    temperature_objects: List[str] = field(default_factory=lambda: [
        "extruder", "heater_bed", "heater_generic chamber_heater",
        "temperature_sensor chamber",
    ])


@dataclass(frozen=True)
class DiscordConfig:
    token: str
    status_channel_id: int = 0
    allowed_guild_id: int = 0
    public_status_responses: bool = False
    printer_ui_url: str = ""
    job_controls_enabled: bool = True
    control_user_ids: List[int] = field(default_factory=list)
    control_role_ids: List[int] = field(default_factory=list)


@dataclass(frozen=True)
class NotificationConfig:
    enabled: bool = True
    poll_seconds: float = 60.0
    show_camera_in_status: bool = True
    include_camera_in_events: bool = True
    send_idle: bool = False
    state_file: str = ""
    states: List[str] = field(default_factory=lambda: [
        "printing", "paused", "complete", "error", "cancelled", "standby",
    ])


@dataclass(frozen=True)
class PrinterConfig:
    moonraker: MoonrakerConfig
    status_channel_id: int = 0
    printer_ui_url: str = ""
    control_user_ids: List[int] = field(default_factory=list)
    control_role_ids: List[int] = field(default_factory=list)
    mention_user_ids: List[int] = field(default_factory=list)
    mention_role_ids: List[int] = field(default_factory=list)
    mention_states: List[str] = field(
        default_factory=lambda: list(DEFAULT_MENTION_STATES))


@dataclass(frozen=True)
class AppConfig:
    discord: DiscordConfig
    notifications: NotificationConfig
    printers: Dict[str, PrinterConfig]

    @property
    def moonraker(self) -> MoonrakerConfig:
        return next(iter(self.printers.values())).moonraker


def _section(data: Dict[str, Any], name: str) -> Dict[str, Any]:
    value = data.get(name, {})
    if not isinstance(value, dict):
        raise ValueError("Configuration section {!r} must be an object".format(
            name))
    return value


def _id_list(data: Dict[str, Any], name: str) -> List[int]:
    value = data.get(name, [])
    if not isinstance(value, list):
        raise ValueError("{} must be an array".format(name))
    return [int(item) for item in value]


def _moonraker(data: Dict[str, Any], default_name: str = ""):
    return MoonrakerConfig(
        url=str(data.get("url", "http://127.0.0.1:7125")).rstrip("/"),
        api_key=str(data.get("api_key", "")),
        timeout_seconds=float(data.get("timeout_seconds", 10.0)),
        verify_ssl=bool(data.get("verify_ssl", True)),
        camera_name=str(data.get("camera_name", "")),
        snapshot_url=str(data.get("snapshot_url", "")),
        printer_name=str(data.get("printer_name", default_name)).strip(),
        temperature_objects=list(data.get(
            "temperature_objects", MoonrakerConfig().temperature_objects)),
    )


def _printer_config(printer_id: str, data: Dict[str, Any],
                    inherited_moonraker: Dict[str, Any]) -> PrinterConfig:
    moonraker_data = data.get("moonraker", {})
    if not isinstance(moonraker_data, dict):
        raise ValueError(
            "printers.{}.moonraker must be an object".format(printer_id))
    merged_moonraker = dict(inherited_moonraker)
    merged_moonraker.update(moonraker_data)
    display_name = str(data.get("name", "")).strip()
    return PrinterConfig(
        moonraker=_moonraker(merged_moonraker, display_name),
        status_channel_id=int(data.get("status_channel_id", 0)),
        printer_ui_url=str(data.get("printer_ui_url", "")),
        control_user_ids=_id_list(data, "control_user_ids"),
        control_role_ids=_id_list(data, "control_role_ids"),
        mention_user_ids=_id_list(data, "mention_user_ids"),
        mention_role_ids=_id_list(data, "mention_role_ids"),
        mention_states=list(data.get(
            "mention_states", DEFAULT_MENTION_STATES)),
    )


def load_config(path: Optional[Path] = None) -> AppConfig:
    config_path = path or Path(os.environ.get(
        "DISRAKER_CONFIG", str(DEFAULT_CONFIG)))
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError("DisRaker configuration not found: {}".format(
            config_path)) from exc
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid JSON in {}: {}".format(
            config_path, exc)) from exc
    if not isinstance(data, dict):
        raise ValueError("DisRaker configuration must be an object")

    discord_data = _section(data, "discord")
    notification_data = _section(data, "notifications")
    token = os.environ.get(
        "DISRAKER_DISCORD_TOKEN", str(discord_data.get("token", ""))).strip()
    if not token:
        raise ValueError(
            "Set discord.token or the DISRAKER_DISCORD_TOKEN "
            "environment variable")

    discord = DiscordConfig(
        token=token,
        status_channel_id=int(discord_data.get(
            "status_channel_id",
            discord_data.get("notification_channel_id", 0))),
        allowed_guild_id=int(discord_data.get("allowed_guild_id", 0)),
        public_status_responses=bool(
            discord_data.get("public_status_responses", False)),
        printer_ui_url=str(discord_data.get("printer_ui_url", "")),
        job_controls_enabled=bool(
            discord_data.get("job_controls_enabled", True)),
        control_user_ids=_id_list(discord_data, "control_user_ids"),
        control_role_ids=_id_list(discord_data, "control_role_ids"),
    )
    notifications = NotificationConfig(
        enabled=bool(notification_data.get("enabled", True)),
        poll_seconds=max(2.0, float(
            notification_data.get("poll_seconds", 60.0))),
        show_camera_in_status=bool(notification_data.get(
            "show_camera_in_status", True)),
        include_camera_in_events=bool(notification_data.get(
            "include_camera_in_events",
            notification_data.get("include_camera", True))),
        send_idle=bool(notification_data.get("send_idle", False)),
        state_file=str(notification_data.get("state_file", "")).strip(),
        states=list(notification_data.get(
            "states", NotificationConfig().states)),
    )

    printers_data = data.get("printers")
    printers: Dict[str, PrinterConfig] = {}
    if printers_data is not None:
        if not isinstance(printers_data, dict) or not printers_data:
            raise ValueError("printers must be a non-empty object")
        inherited_moonraker = _section(data, "moonraker")
        for printer_id, printer_data in printers_data.items():
            if not isinstance(printer_data, dict):
                raise ValueError(
                    "printer {!r} must be an object".format(printer_id))
            printer_id = str(printer_id)
            if not re.fullmatch(r"[A-Za-z0-9_.-]{1,48}", printer_id):
                raise ValueError(
                    "printer IDs may use 1-48 letters, numbers, '.', '-', '_'")
            printers[printer_id] = _printer_config(
                printer_id, printer_data, inherited_moonraker)
    else:
        moonraker_data = _section(data, "moonraker")
        printers["default"] = PrinterConfig(
            moonraker=_moonraker(moonraker_data),
            status_channel_id=discord.status_channel_id,
            printer_ui_url=discord.printer_ui_url,
        )
    return AppConfig(discord, notifications, printers)
