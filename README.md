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

Status is polled every 60 seconds by default. During a print, each poll edits
the current live card. A pause, resume, completion, cancellation, error, or
other state transition creates a new card. Set `notifications.poll_seconds`
to change the interval. Print-state transitions additionally use Moonraker's
WebSocket subscription, so start/pause/finish messages do not wait for a poll.
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

## Multi-printer relay

DisRaker can securely forward a printer's Moonraker status to a central
DisRaker Discord bot. Moonraker itself does not need to be exposed. Every
publisher has a unique relay ID and HMAC secret, allowing one hub to collect
status from multiple people's printers.

On a printer-side instance, configure:

```json
"relay": {
  "publish_url": "https://discord-bot.example/disraker/v1/status",
  "relay_id": "alice-creator5",
  "secret": "GENERATE_A_LONG_RANDOM_SECRET",
  "include_camera": false
}
```

The printer-side `status_channel_id` may be `0` if only the central bot should
post status. The publisher still needs a Discord bot token because DisRaker is
run as a Discord bot process.

On the central instance, disable local polling if it has no local printer and
configure the listener and authorized sources:

```json
"notifications": {
  "enabled": false
},
"relay": {
  "listen_host": "0.0.0.0",
  "listen_port": 7131,
  "sources": {
    "alice-creator5": {
      "secret": "GENERATE_A_LONG_RANDOM_SECRET",
      "display_name": "Alice's Creator 5",
      "channel_id": 0
    },
    "bob-voron": {
      "secret": "A_DIFFERENT_LONG_RANDOM_SECRET",
      "display_name": "Bob's Voron",
      "channel_id": 123456789012345678
    }
  }
}
```

A source `channel_id` of `0` uses the hub's normal `status_channel_id`.
Requests are signed with HMAC-SHA256 and expire after five minutes. Keep each
secret private and different. Put the listener behind HTTPS, a VPN, or a TLS
reverse proxy when it crosses the public internet. Set `include_camera` to
`true` only when camera forwarding is wanted; image data increases bandwidth.
The relay forwards status and optional camera images, not remote printer-control
commands.

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
