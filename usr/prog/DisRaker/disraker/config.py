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
class RelaySourceConfig:
    secret: str
    display_name: str = ""
    channel_id: int = 0
    allow_controls: bool = False
    control_user_ids: List[int] = field(default_factory=list)
    control_role_ids: List[int] = field(default_factory=list)


@dataclass(frozen=True)
class RelayConfig:
    publish_url: str = ""
    relay_id: str = ""
    secret: str = ""
    include_camera: bool = False
    accept_remote_controls: bool = False
    poll_seconds: float = 5.0
    listen_host: str = ""
    listen_port: int = 7131
    admin_user_ids: List[int] = field(default_factory=list)
    admin_role_ids: List[int] = field(default_factory=list)
    sources: Dict[str, RelaySourceConfig] = field(default_factory=dict)


@dataclass(frozen=True)
class AppConfig:
    discord: DiscordConfig
    moonraker: MoonrakerConfig
    notifications: NotificationConfig
    relay: RelayConfig


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
    relay_data = _section(data, "relay")
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
        control_user_ids=[int(user_id) for user_id in
                          discord_data.get("control_user_ids", [])],
        control_role_ids=[int(role_id) for role_id in
                          discord_data.get("control_role_ids", [])],
    )
    moonraker = MoonrakerConfig(
        url=str(moonraker_data.get("url", "http://127.0.0.1:7125"))
        .rstrip("/"),
        api_key=str(moonraker_data.get("api_key", "")),
        timeout_seconds=float(moonraker_data.get("timeout_seconds", 10.0)),
        verify_ssl=bool(moonraker_data.get("verify_ssl", True)),
        camera_name=str(moonraker_data.get("camera_name", "")),
        snapshot_url=str(moonraker_data.get("snapshot_url", "")),
        printer_name=str(moonraker_data.get("printer_name", "")).strip(),
        temperature_objects=list(moonraker_data.get(
            "temperature_objects", MoonrakerConfig().temperature_objects)),
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
    source_data = relay_data.get("sources", {})
    if not isinstance(source_data, dict):
        raise ValueError("relay.sources must be an object")
    sources = {}
    for relay_id, source in source_data.items():
        if not isinstance(source, dict):
            raise ValueError("relay source {!r} must be an object".format(
                relay_id))
        sources[str(relay_id)] = RelaySourceConfig(
            secret=str(source.get("secret", "")),
            display_name=str(source.get("display_name", "")).strip(),
            channel_id=int(source.get("channel_id", 0)),
            allow_controls=bool(source.get("allow_controls", False)),
            control_user_ids=[int(user_id) for user_id in
                              source.get("control_user_ids", [])],
            control_role_ids=[int(role_id) for role_id in
                              source.get("control_role_ids", [])],
        )
    relay = RelayConfig(
        publish_url=str(relay_data.get("publish_url", "")).strip(),
        relay_id=str(relay_data.get("relay_id", "")).strip(),
        secret=str(relay_data.get("secret", "")),
        include_camera=bool(relay_data.get("include_camera", False)),
        accept_remote_controls=bool(
            relay_data.get("accept_remote_controls", False)),
        poll_seconds=max(2.0, float(
            relay_data.get("poll_seconds", 5.0))),
        listen_host=str(relay_data.get("listen_host", "")).strip(),
        listen_port=int(relay_data.get("listen_port", 7131)),
        admin_user_ids=[int(user_id) for user_id in
                        relay_data.get("admin_user_ids", [])],
        admin_role_ids=[int(role_id) for role_id in
                        relay_data.get("admin_role_ids", [])],
        sources=sources,
    )
    if relay.publish_url and (not relay.relay_id or not relay.secret):
        raise ValueError(
            "relay publishing requires relay_id and secret")
    relay_ids = list(sources)
    if relay.relay_id:
        relay_ids.append(relay.relay_id)
    if any(len(relay_id) > 48 for relay_id in relay_ids):
        raise ValueError("relay IDs must be 48 characters or fewer")
    if relay.listen_host:
        missing = [name for name, source in sources.items()
                   if not source.secret]
        if missing:
            raise ValueError("relay sources require a secret: {}".format(
                ", ".join(missing)))
    return AppConfig(discord, moonraker, notifications, relay)
