#!/bin/sh

APP_DIR=/usr/prog/DisRaker
CONFIG=/usr/prog/scripts/config/disraker.json
LOG_DIR=/usr/data/logs
LOG_FILE=$LOG_DIR/disraker.log
RESTART_DELAY=${DISRAKER_RESTART_DELAY:-5}

mkdir -p "$LOG_DIR"
export DISRAKER_CONFIG=${DISRAKER_CONFIG:-$CONFIG}
export PYTHONPATH="$APP_DIR${PYTHONPATH:+:$PYTHONPATH}"

if [ -x "$APP_DIR/.venv/bin/python" ]; then
    PYTHON="$APP_DIR/.venv/bin/python"
else
    PYTHON=${PYTHON:-python3}
fi

while true; do
    echo "$(date '+%Y-%m-%d %H:%M:%S') starting DisRaker" >> "$LOG_FILE"
    "$PYTHON" "$APP_DIR/main.py" >> "$LOG_FILE" 2>&1
    status=$?
    echo "$(date '+%Y-%m-%d %H:%M:%S') DisRaker exited ($status); restarting in ${RESTART_DELAY}s" >> "$LOG_FILE"
    sleep "$RESTART_DELAY"
done

