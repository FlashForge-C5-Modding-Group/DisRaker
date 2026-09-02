# DisRaker

DisRaker is a Python Discord bot for a Klipper printer managed by Moonraker.
It publishes a Discord dashboard with buttons for current print state,
temperatures, progress, and a Moonraker-configured camera snapshot. It can also
notify a Discord channel when a print starts, pauses, completes, or fails.

The repository mirrors the requested printer installation layout:

```text
usr/prog/DisRaker/                 Python application
usr/prog/scripts/config/           Runtime configuration
usr/prog/scripts/scripts/          Restart loop script
```

## Configuration

Copy `usr/prog/scripts/config/disraker.json.example` to
`/usr/prog/scripts/config/disraker.json`, then set the Discord bot token,
notification channel ID, and Moonraker URL. The token may instead be supplied
as `DISRAKER_DISCORD_TOKEN`.

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

Run `/printer` in Discord for a private status card, or `/dashboard` to publish
a persistent shared dashboard. The Refresh and Camera buttons always fetch
fresh information through Moonraker.

