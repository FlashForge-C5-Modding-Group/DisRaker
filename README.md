# DisRaker

DisRaker is a Python Discord bot for Klipper printers managed by Moonraker.
It posts live Discord status cards with buttons for current print state,
temperatures, motion data, every configured fan, and a
Moonraker-configured camera. It also
notifies a configured status channel when a print starts, pauses, completes,
fails, or is cancelled. Think of it as a cloud app, for Discord.

## Configuration

Copy `usr/data/disraker/config/disraker.json.example` to
`/usr/data/disraker/config/disraker.json`, then set the Discord bot token,
status channel ID, and Moonraker URL. The token may instead be supplied
as `DISRAKER_DISCORD_TOKEN`.

Status is polled every 60 seconds by default. During a print, each poll edits
the current live card. A pause, resume, completion, cancellation, error, or
other state transition creates a new card. Set `notifications.poll_seconds`
to change the interval. Print-state transitions additionally use Moonraker's
WebSocket subscription, so start/pause/finish messages do not wait for a poll.
If a poll cannot reach Moonraker or Klipper, DisRaker posts an offline card.
When the printer responds again, it posts a back-online card containing the
current print state. 
Connectivity monitoring runs when `notifications.enabled` is true.
`show_camera_in_status` controls the dashboard image,
`include_camera_in_events` controls event-message images, and `send_idle`
enables or disables idle transition messages. Camera selection uses
Moonraker's webcam list and the configured `camera_name`; `snapshot_url` can
override it explicitly.

Set each printer's `name` to choose its displayed name. If it is empty,
DisRaker uses the hostname returned by that Moonraker. Print state is saved
beneath
`usr/data/DisRaker/data`, preventing a restart during a print from sending a
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

## Installation on FlashForge printers (Using OpenCreator)

You'll have to move the directories manually, but they should line up almost perfectly to the "Loop Script" method.
```sh
cd /usr/data/disraker
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp /usr/data/disraker/config/disraker.json.example /usr/data/disraker/config/disraker.json 
chmod +x /usr/data/scripts/scripts/disraker_loop.sh
```
When you install requirements on the printer, it may take a long while as it needs to build a library. Wait, you can check status by opening up another ssh window and looking at `top` to see if it is doing anything.
You need to fill out `/usr/data/disraker/config/disraker.json`, usually using SFTP or SCP, alternatively `vi`.
Now you can run it by either running it directly and keeping the window open, `./usr/data/scripts/scripts/disraker_loop.sh` or if loop script is running, you can restart your printer. It is recommended to run it once manually to check if you have any configs wrong.
If you use loop script and want to check if it started, do `cat /usr/data/disraker/logs/disraker.log`

### Windows installations as a server
For Windows testing, run the batch launcher from the repository:
```bat
disraker_loop.bat --check
disraker_loop.bat --once
disraker_loop.bat
```
You'll need a Python install in PATH. Make sure you have it in path by running `python`.
You'll also need pip. 

### Other Linux computers / Printers
For use outside of the intended printer on Linux such as a Qidi, you may have to modify the .sh file and file paths to fit your needs.

## Multiple Moonraker printers

One DisRaker process can connect directly to multiple Moonraker instances.
Each printer has an independent URL, camera, name, status channel, controls,
remembered print state, and notification mentions. Define printers by a short unique ID

You can figure it out by checking out the example config. It may be removed to make it a single printer service.

A printer `status_channel_id` of `0` uses the global Discord status channel.
Users and roles listed under `mention_user_ids` and `mention_role_ids` are
pinged for states in `mention_states`. The defaults cover print start, pause,
completion, cancellation, and errors. Add `resumed` if resumed prints should
also trigger a ping. Use `/printers` to list configured IDs;
`/printer` and `/dashboard` provide printer selection with autocomplete.

The former top-level `moonraker` section remains supported as a single-printer
compatibility mode.

For a server installation, the Discord application needs the `bot` and
`applications.commands` scopes. Recommended channel permissions are View
Channel, Send Messages, Embed Links, Attach Files, and Use Application
Commands. Message Content intent is not required.

## Discord DMs and user installation

DisRaker registers its global commands for both Guild Install and User
Install. Commands may run in a server, a DM with the bot, or another private
channel supported by Discord.

To run without any server channels, configure DM-only mode:

```json
"discord": {
  "token": "YOUR_DISCORD_BOT_TOKEN",
  "dm_only": true,
  "dm_user_id": 123456789012345678,
  "control_user_ids": [123456789012345678]
}
```

In this mode, DisRaker disables guild command contexts and guild installation,
ignores status channel IDs, and sends proactive status notifications directly
to `dm_user_id`. Put that user in `control_user_ids` as shown if they should
also be allowed to start, pause, resume, or cancel prints. The destination user
must install the application for their user account and allow DMs from it.

In the Discord Developer Portal, open the application's Installation page,
enable User Install, and add `applications.commands` to the User Install
default scopes. Use the resulting Discord-provided installation link to add
the application to your user account. Keep the existing Guild Install with
the `bot` and `applications.commands` scopes if status notifications should
still be posted to a server channel.

DMs do not provide server roles. Add the person's Discord account ID to
`discord.control_user_ids` for access to every printer, or to a printer's
`control_user_ids` for access to only that printer. Role-only authorization
will continue to work in servers but cannot authorize a DM command.

Commands are synchronized globally even when `allowed_guild_id` is set, so
user-installed and DM commands remain available. The configured guild also
receives a guild-specific copy for faster command updates.

On first use it creates `usr\data\DisRaker\.venv` and installs the Python
requirements. `--once` keeps errors visible without entering the
restart loop; the default mode restarts after failures and records lifecycle
events in `usr\data\disraker\logs\disraker.log`.

Run `/printer` in Discord for a private status card, or `/dashboard` to publish
a shared status card. The configured `status_channel_id` or DM receives a rolling
live card.

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
allowed user, an allowed role, or Manage Server permission. Public status such as;
camera, refresh are non modifiable so are accessable by the public.
