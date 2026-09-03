# DisRaker

DisRaker is a Python Discord bot for Klipper printers managed by Moonraker.
It posts live Discord status cards with buttons for current print state,
temperatures, progress, motion data, every configured fan, and a
Moonraker-configured camera. It also
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

Status is polled every 60 seconds by default. During a print, each poll edits
the current live card. A pause, resume, completion, cancellation, error, or
other state transition creates a new card. Set `notifications.poll_seconds`
to change the interval. Print-state transitions additionally use Moonraker's
WebSocket subscription, so start/pause/finish messages do not wait for a poll.
Cancellation and error card IDs are remembered. Those old terminal cards are
deleted when DisRaker restarts or when that printer begins a new print.
`show_camera_in_status` controls the dashboard image,
`include_camera_in_events` controls event-message images, and `send_idle`
enables or disables idle transition messages. Camera selection uses
Moonraker's webcam list and the configured `camera_name`; `snapshot_url` can
override it explicitly.

Set each printer's `name` to choose its displayed name. If it is empty,
DisRaker uses the hostname returned by that Moonraker. Print state is saved
beneath
`usr/prog/DisRaker/data`, preventing a restart during a print from sending a
duplicate start notification. `notifications.state_file` can override that
location.

The status controls support pause, resume, confirmed cancellation, and a
detailed current-job view through Moonraker. Set
`discord.job_controls_enabled` to `false` to disable all protected print
management. Add
Discord account IDs to the global `discord.control_user_ids` and/or role IDs
to `discord.control_role_ids` to create central administrators. Each printer
may also define its own `control_user_ids` and `control_role_ids`. Access is
denied when a user is not present in an applicable allowlist. Empty lists do
not grant public control. Members with Manage Server permission are always
central administrators.

## Multiple Moonraker printers

One DisRaker process can connect directly to multiple Moonraker instances.
Each printer has an independent URL, camera, name, status channel, controls,
remembered print state, and notification mentions.

Define printers by a short unique ID:

```json
"printers": {
  "creator5": {
    "name": "Creator 5 Pro",
    "status_channel_id": 123456789012345678,
    "control_user_ids": [111111111111111111],
    "control_role_ids": [],
    "mention_user_ids": [111111111111111111],
    "mention_role_ids": [222222222222222222],
    "mention_states": [
      "printing", "paused", "complete", "cancelled", "error"
    ],
    "moonraker": {
      "url": "http://creator5.local:7125",
      "api_key": "",
      "camera_name": ""
    }
  }
}
```

A printer `status_channel_id` of `0` uses the global Discord status channel.
Users and roles listed under `mention_user_ids` and `mention_role_ids` are
pinged for states in `mention_states`. The defaults cover print start, pause,
completion, cancellation, and errors. Add `resumed` if resumed prints should
also trigger a ping. Use `/printers` to list configured IDs;
`/printer` and `/dashboard` provide printer selection with autocomplete.

The former top-level `moonraker` section remains supported as a single-printer
compatibility mode.

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
a shared status card. The configured `status_channel_id` receives a rolling
live card plus a new card at each state transition. Refresh, Camera, and
Details always fetch fresh information through Moonraker; an optional link
button opens `printer_ui_url`.

Print-management commands are available for each configured printer:

- `/job` shows the active file, state, elapsed time, slicer metadata,
  remaining slicer estimate, and queue summary.
- `/history` shows recent completed, cancelled, and failed jobs.
- `/queue` lists jobs waiting in Moonraker's print queue.
- `/files` lists the most recently added G-code paths.
- `/start_print` validates an exact G-code path and asks for confirmation
  before starting it. It uses the same global and per-printer access rules as
  pause, resume, and cancel.

The Current Job button and all five print-management commands require an
allowed user, an allowed role, or Manage Server permission. Public status,
camera, refresh, and general printer details remain read-only.

DisRaker intentionally does not expose arbitrary G-code, machine power, or
host administration commands.
