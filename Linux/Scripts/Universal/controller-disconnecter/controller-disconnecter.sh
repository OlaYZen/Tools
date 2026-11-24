#!/usr/bin/env bash
# Disconnect the DualSense over Bluetooth after a period with no joystick input.
# MAC must stay aligned with ~/.local/bin/fix-dualsense
set -euo pipefail
shopt -s nullglob

MAC="48:18:8D:A0:45:7F"
# Substring match against /sys/class/input/jsN/device/name (see fix-dualsense NAME)
NAME_SUB="DualSense"

# Idle time before bluetoothctl disconnect (seconds). For a quick test use e.g. 10.
INACTIVITY_SECS=$((15 * 60))
POLL_DEVICE_SECS=2
# How often we compare wall clock to last real input (lower = snappier after idle).
CHECK_TICK_SECS=1

# jstest prints: Event: type %d, time %d, number %d, value %d
# type 1 = button, 2 = axis; type >= 128 means JS_EVENT_INIT (initial flood) — ignore for idle.
# Axis values are roughly ±32767; ignore motion smaller than this (~pygame 0.1 on -1..1).
AXIS_DEADZONE=3300

ICON_PATH="${HOME}/LOGO.png"
NOTIFY_APP="controller-disconnecter"
NOTIFY_TITLE="Roller DCd"
NOTIFY_BODY="Controller disconnected due to 15 minutes of inactivity."

ACT_FILE="${XDG_RUNTIME_DIR:-/tmp}/controller-disconnecter.last_activity"

red()   { printf '\e[1;31m%s\e[0m\n' "$*"; }
green() { printf '\e[1;32m%s\e[0m\n' "$*"; }
cyan()  { printf '\e[1;36m%s\e[0m\n' "$*"; }

# Reader is a bash subshell reading the FIFO; we never SIGTERM it (ambiguous cmdline).
reader_pid=""
# Only this PID may receive SIGTERM from us — must be the real jstest binary.
jstest_pid=""
EVENT_FIFO=""

is_jstest_exe() {
    local pid=$1 exe
    [[ "$pid" =~ ^[0-9]+$ ]] || return 1
    exe=$(readlink -f "/proc/$pid/exe" 2>/dev/null) || return 1
    [[ "$(basename "$exe")" == jstest ]]
}

cleanup() {
    if [[ -n ${jstest_pid:-} ]] && kill -0 "$jstest_pid" 2>/dev/null; then
        if is_jstest_exe "$jstest_pid"; then
            kill -TERM "$jstest_pid" 2>/dev/null || true
            wait "$jstest_pid" 2>/dev/null || true
        fi
    fi
    jstest_pid=""
    if [[ -n ${reader_pid:-} ]]; then
        wait "$reader_pid" 2>/dev/null || true
    fi
    reader_pid=""
    if [[ -n ${EVENT_FIFO:-} ]]; then
        rm -f "$EVENT_FIFO"
    fi
    EVENT_FIFO=""
}
trap cleanup EXIT INT TERM

js_device_name() {
    local js="$1" sysname
    sysname=$(basename "$js")
    if [[ -r "/sys/class/input/${sysname}/device/name" ]]; then
        tr -d '\0' <"/sys/class/input/${sysname}/device/name"
    else
        echo ""
    fi
}

find_js_dev() {
    local js name
    for js in /dev/input/js[0-9]; do
        [[ -e "$js" ]] || continue
        name=$(js_device_name "$js")
        if [[ -n "$NAME_SUB" ]] && [[ "$name" == *"$NAME_SUB"* ]]; then
            printf '%s' "$js"
            return 0
        fi
    done
    for js in /dev/input/js[0-9]; do
        if [[ -e "$js" ]]; then
            printf '%s' "$js"
            return 0
        fi
    done
    return 1
}

touch_activity() {
    # No trailing newline so reads always match ^[0-9]+$
    printf '%s' "$(date +%s)" >"$ACT_FILE"
}

# jstest --event streams axis noise; only count meaningful input toward idle reset.
handle_jstest_line() {
    local line=$1
    [[ "$line" == Event:* ]] || return 0
    if [[ ! "$line" =~ ^Event:\ type\ ([0-9]+),\ time\ ([0-9]+),\ number\ ([0-9]+),\ value\ (-?[0-9]+)$ ]]; then
        return 0
    fi
    local t=${BASH_REMATCH[1]} val=${BASH_REMATCH[4]}
    # Initial-state events keep the device "busy" forever if treated as activity.
    if ((t >= 128)); then
        return 0
    fi
    if ((t == 1)); then
        touch_activity
        return 0
    fi
    if ((t == 2)); then
        local av=$val
        if ((val < 0)); then av=$((0 - val)); fi
        if ((av > AXIS_DEADZONE)); then
            touch_activity
        fi
        return 0
    fi
    touch_activity
}

notify_disconnect() {
    if ! command -v notify-send >/dev/null 2>&1; then
        return 0
    fi
    local -a args=(-a "$NOTIFY_APP" "$NOTIFY_TITLE" "$NOTIFY_BODY")
    if [[ -f "$ICON_PATH" ]]; then
        args=(--icon "$ICON_PATH" "${args[@]}")
    fi
    if notify-send "${args[@]}" 2>/dev/null; then
        cyan "Notification sent."
    fi
}

disconnect_controller() {
    cyan "Disconnecting $MAC (inactivity)."
    if bluetoothctl disconnect "$MAC" 2>/dev/null; then
        green "Disconnected controller $MAC."
        notify_disconnect
    else
        red "bluetoothctl disconnect failed for $MAC"
    fi
}

start_reader() {
    local dev="$1"
    cleanup
    reader_pid=""
    jstest_pid=""
    EVENT_FIFO="${ACT_FILE}.jstest.fifo"
    rm -f "$EVENT_FIFO"
    if ! mkfifo "$EVENT_FIFO"; then
        red "mkfifo failed for $EVENT_FIFO"
        return 1
    fi

    # jstest opens the FIFO for write (blocks in the kernel until a reader exists).
    jstest --event "$dev" >"$EVENT_FIFO" 2>/dev/null &
    jstest_pid=$!

    (
        exec 3<"$EVENT_FIFO"
        while IFS= read -r -u 3 line || [[ -n "${line:-}" ]]; do
            [[ -z "${line:-}" ]] && continue
            handle_jstest_line "$line"
        done
        exec 3<&-
    ) &
    reader_pid=$!
}

require_cmds() {
    local missing=()
    command -v bluetoothctl >/dev/null 2>&1 || missing+=("bluetoothctl")
    command -v jstest >/dev/null 2>&1 || missing+=("jstest")
    if ((${#missing[@]})); then
        red "Missing: ${missing[*]}"
        echo "Install packages that provide these commands, for example:"
        echo "  Arch / CachyOS: sudo pacman -S joyutils bluez-utils"
        echo "    (jstest → joyutils; bluetoothctl → bluez-utils)"
        echo "  Debian / Ubuntu: sudo apt install joystick bluez"
        exit 1
    fi
}

require_cmds
cyan "Starting controller inactivity monitor (MAC=$MAC, idle=${INACTIVITY_SECS}s)."
touch_activity

disconnected=false

while true; do
    js=""
    if ! js=$(find_js_dev); then
        sleep "$POLL_DEVICE_SECS"
        disconnected=true
        continue
    fi

    cyan "Joystick device: $js ($(js_device_name "$js"))"
    touch_activity
    disconnected=false
    start_reader "$js"

    while kill -0 "$reader_pid" 2>/dev/null; do
        sleep "$CHECK_TICK_SECS"
        now=$(date +%s)
        last_raw=""
        if [[ -r "$ACT_FILE" ]]; then
            last_raw=$(tr -d '\n\r \t' <"$ACT_FILE" || true)
        fi
        # Never default last to 0: (now - 0) would exceed INACTIVITY_SECS immediately.
        if ! [[ "$last_raw" =~ ^[0-9]+$ ]] || ((last_raw > now)); then
            last=$now
        else
            last=$last_raw
        fi
        if [[ "$disconnected" == false ]] && ((now - last >= INACTIVITY_SECS)); then
            disconnect_controller
            disconnected=true
            touch_activity
            break
        fi
    done

    cleanup
    reader_pid=""
    cyan "Joystick reader stopped; waiting for device cycle…"
    # After disconnect, wait until js node goes away (if it does) before hunting again.
    for _ in {1..60}; do
        [[ -e "$js" ]] || break
        sleep 1
    done
    sleep "$POLL_DEVICE_SECS"
done
