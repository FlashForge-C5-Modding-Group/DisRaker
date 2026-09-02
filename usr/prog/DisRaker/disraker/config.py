import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


DEFAULT_CONFIG = Path("/usr/prog/scripts/config/disraker.json")


@dataclass(frozen=True)
class MoonrakerConfig:
    url: str = "http://127.0.0.1:7125"
    api_key: str = ""
    timeout_seconds: float = 10.0
    verify_ssl: bool = True
    camera_name: str = ""
    snapshot_url: str = ""
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


@dataclass(frozen=True)
class NotificationConfig:
    enabled: bool = True
    poll_seconds: float = 300.0
    show_camera_in_status: bool = True
    include_camera_in_events: bool = True
    send_idle: bool = False
    states: List[str] = field(default_factory=lambda: [
        "printing", "paused", "complete", "error", "cancelled", "standby",
    ])


@dataclass(frozen=True)
class AppConfig:
    discord: DiscordConfig
    moonraker: MoonrakerConfig
    notifications: NotificationConfig


def _section(data: Dict[str, Any], name: str) -> Dict[str, Any]:
    value = data.get(name, {})
    if not isinstance(value, dict):
        raise ValueError("Configuration section {!r} must be an object".format(
            name))
    return value


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

    discord_data = _section(data, "discord")
    moonraker_data = _section(data, "moonraker")
    notification_data = _section(data, "notifications")
    token = os.environ.get(
        "DISRAKER_DISCORD_TOKEN", str(discord_data.get("token", ""))).strip()
    if not token:
        raise ValueError(
            "Set discord.token or the DISRAKER_DISCORD_TOKEN environment variable")

    discord = DiscordConfig(
        token=token,
        status_channel_id=int(discord_data.get(
            "status_channel_id",
            discord_data.get("notification_channel_id", 0))),
        allowed_guild_id=int(discord_data.get("allowed_guild_id", 0)),
        public_status_responses=bool(
            discord_data.get("public_status_responses", False)),
        printer_ui_url=str(discord_data.get("printer_ui_url", "")),
    )
    moonraker = MoonrakerConfig(
        url=str(moonraker_data.get("url", "http://127.0.0.1:7125"))
        .rstrip("/"),
        api_key=str(moonraker_data.get("api_key", "")),
        timeout_seconds=float(moonraker_data.get("timeout_seconds", 10.0)),
        verify_ssl=bool(moonraker_data.get("verify_ssl", True)),
        camera_name=str(moonraker_data.get("camera_name", "")),
        snapshot_url=str(moonraker_data.get("snapshot_url", "")),
        temperature_objects=list(moonraker_data.get(
            "temperature_objects", MoonrakerConfig().temperature_objects)),
    )
    notifications = NotificationConfig(
        enabled=bool(notification_data.get("enabled", True)),
        poll_seconds=max(2.0, float(
            notification_data.get("poll_seconds", 300.0))),
        show_camera_in_status=bool(notification_data.get(
            "show_camera_in_status", True)),
        include_camera_in_events=bool(notification_data.get(
            "include_camera_in_events",
            notification_data.get("include_camera", True))),
        send_idle=bool(notification_data.get("send_idle", False)),
        states=list(notification_data.get(
            "states", NotificationConfig().states)),
    )
    return AppConfig(discord, moonraker, notifications)
