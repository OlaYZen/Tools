#!/bin/bash

# Audio devices to record, one track each.
# gpu-screen-recorder binds these at startup and never reconnects, so if the
# GoXLR drops off USB (PipeWire rebuilds the nodes under new IDs) every track
# silently encodes silence. The supervisor loop below watches for that and
# restarts the recorder.
AUDIO_DEVICES=(
  alsa_output.usb-TC-Helicon_GoXLRMini-00.HiFi__Speaker__sink.monitor
  alsa_input.usb-TC-Helicon_GoXLRMini-00.HiFi__Line4__source
  alsa_output.usb-TC-Helicon_GoXLRMini-00.HiFi__Line3__sink.monitor
  alsa_output.usb-TC-Helicon_GoXLRMini-00.HiFi__Headphones__sink.monitor
  alsa_output.usb-TC-Helicon_GoXLRMini-00.HiFi__Line2__sink.monitor
  alsa_output.usb-TC-Helicon_GoXLRMini-00.HiFi__Line1__sink.monitor
)

RECORDER_PID=""

notify() {
  notify-send --icon ~/LOGO.png -a "Nvidia Shadowplay" "$1" "$2"
}

# Prints "device:nodeid" for every device, or fails if any is missing.
# The node ID changes when PipeWire recreates the device, which is the signal
# that the recorder's audio streams are now dead.
audio_fingerprint() {
  local sources dev id
  sources=$(pactl list short sources 2>/dev/null) || return 1
  for dev in "${AUDIO_DEVICES[@]}"; do
    id=$(awk -v d="$dev" '$2 == d { print $1 }' <<<"$sources")
    [ -n "$id" ] || return 1
    printf '%s:%s ' "$dev" "$id"
  done
}

stop_recorder() {
  if [ -n "$RECORDER_PID" ] && kill -0 "$RECORDER_PID" 2>/dev/null; then
    kill "$RECORDER_PID"
    wait "$RECORDER_PID" 2>/dev/null
    echo "gpu-screen-recorder stopped (PID: $RECORDER_PID)"
  else
    echo "No running gpu-screen-recorder process found, killing any existing processes"
    pkill -f "gpu-screen-recorder"
  fi
  RECORDER_PID=""
}

trap 'echo "Stopping gpu-screen-recorder at $(date)"; notify "Recording Stopped" "gpu-screen-recorder stopped at $(date +"%H:%M:%S")"; stop_recorder; exit' SIGTERM SIGINT

# Give Hyprland a moment to fully initialize the desktop
sleep 30

while true; do
  # Wait until every audio device is present, then let PipeWire settle so we
  # fingerprint the final node IDs rather than ones mid-reenumeration.
  until fingerprint=$(audio_fingerprint); do
    sleep 2
  done
  sleep 3
  fingerprint=$(audio_fingerprint) || continue

  audio_args=()
  for dev in "${AUDIO_DEVICES[@]}"; do
    audio_args+=(-a "$dev")
  done

  echo "Starting gpu-screen-recorder at $(date)"
  notify "Recording Started" "gpu-screen-recorder has been started at $(date +"%H:%M:%S")"
  gpu-screen-recorder -w DP-1 -f 120 -r 180 -o ~/Videos/Clips \
    "${audio_args[@]}" \
    -ac flac -fm vfr -c mp4 &

  RECORDER_PID=$!
  echo "gpu-screen-recorder started with PID: $RECORDER_PID"

  # Supervise: restart if the recorder dies, or if any audio device is
  # recreated underneath it (which would leave the tracks silent).
  while kill -0 "$RECORDER_PID" 2>/dev/null; do
    sleep 5
    if ! current=$(audio_fingerprint) || [ "$current" != "$fingerprint" ]; then
      echo "Audio devices changed at $(date), restarting gpu-screen-recorder"
      notify "Audio Devices Changed" "Restarting recorder at $(date +"%H:%M:%S")"
      stop_recorder
      break
    fi
  done

  stop_recorder
  sleep 2
done
