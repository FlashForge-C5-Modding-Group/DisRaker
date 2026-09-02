# DisRaker

DisRaker is a Python Discord bot for a Klipper printer managed by Moonraker.
It posts live Discord status cards with buttons for current print state,
temperatures, progress, motion data, and a Moonraker-configured camera. It also
notifies a configured status channel when a print starts, pauses, completes,
fails, or is cancelled.

The repository mirrors the requested printer installation layout:

```text
usr/prog/DisRaker/                 Python application
usr/prog/scripts/config/           Runtime configuration
usr/prog/scripts/scripts/          Restart loop script
```

## Configuration

Copy `usr/prog/scripts/config/disraker.json.example` to
`/usr/prog/scripts/config/disraker.json`, then set the Discord bot token,
status channel ID, and Moonraker URL. The token may instead be supplied
as `DISRAKER_DISCORD_TOKEN`.

Status is polled every 60 seconds by default. Each poll sends a fresh status
card; set `notifications.poll_seconds` to change the interval. Print-state
transitions additionally use Moonraker's WebSocket subscription, so
start/pause/finish messages do not wait for the next poll.
`show_camera_in_status` controls the dashboard image,
`include_camera_in_events` controls event-message images, and `send_idle`
enables or disables idle transition messages. Camera selection uses
Moonraker's webcam list and the configured `camera_name`; `snapshot_url` can
override it explicitly.

Set `moonraker.printer_name` to choose the displayed name. If it is empty,
DisRaker uses the hostname returned by Moonraker. Print state is saved beneath
`usr/prog/DisRaker/data`, preventing a restart during a print from sending a
duplicate start notification. `notifications.state_file` can override that
location.

The status controls support pause, resume, and confirmed cancellation through
Moonraker. Set `discord.job_controls_enabled` to `false` to disable them. Add
Discord account IDs to `control_user_ids` and/or role IDs to
`control_role_ids` to restrict control access. If both lists are empty, anyone
who can see the status card may use the controls. Members with Manage Server
permission are always allowed when an allowlist is active.

The Discord application needs the `bot` and `applications.commands` scopes.
Recommended channel permissions are View Channel, Send Messages, Embed Links,
Attach Files, and Use Application Commands. Message Content intent is not
required.

## Installation on the printer

```sh
cd /usr/prog/DisRaker
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp /path/to/disraker.json /usr/prog/scripts/config/disraker.json
chmod +x /usr/prog/scripts/scripts/disraker_loop.sh
/usr/prog/scripts/scripts/disraker_loop.sh
```

For Windows testing, run the batch launcher from the repository:

```bat
usr\prog\scripts\scripts\disraker_loop.bat --check
usr\prog\scripts\scripts\disraker_loop.bat --once
usr\prog\scripts\scripts\disraker_loop.bat
```

On first use it creates `usr\prog\DisRaker\.venv` and installs the Python
requirements. If the JSON configuration does not exist, it copies the example
to `usr\prog\scripts\config\disraker.json` and asks you to fill in the Discord
token and status channel. `--once` keeps errors visible without entering the
restart loop; the default mode restarts after failures and records lifecycle
events in `usr\prog\DisRaker\logs\disraker.log`.

Run `/printer` in Discord for a private status card, or `/dashboard` to publish
a shared status card. The configured `status_channel_id` receives a new card
on every poll. Refresh, Camera, and Details always fetch fresh information
through Moonraker; an optional link button opens `printer_ui_url`.
