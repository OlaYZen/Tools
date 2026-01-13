#!/bin/bash

# Give Hyprland a moment to fully initialize the desktop
sleep 30

# Trap to handle script termination
trap 'echo "Stopping gpu-screen-recorder at $(date)"; notify-send --icon ~/LOGO.png -a "Nvidia Shadowplay" "Recording Stopped" "gpu-screen-recorder stopped at $(date +"%H:%M:%S")"; if [ ! -z "$RECORDER_PID" ] && kill -0 $RECORDER_PID 2>/dev/null; then kill $RECORDER_PID; wait $RECORDER_PID 2>/dev/null; echo "gpu-screen-recorder stopped (PID: $RECORDER_PID)"; else echo "No running gpu-screen-recorder process found, killing any existing processes"; pkill -f "gpu-screen-recorder"; fi; exit' SIGTERM SIGINT

# Start gpu-screen-recorder
echo "Starting gpu-screen-recorder at $(date)"
notify-send --icon ~/LOGO.png -a "Nvidia Shadowplay" "Recording Started" "gpu-screen-recorder has been started at $(date +"%H:%M:%S")"
gpu-screen-recorder -w DP-1 -f 120 -r 180 -o ~/Videos/Clips \
  -a alsa_output.usb-TC-Helicon_GoXLRMini-00.HiFi__Speaker__sink.monitor \
  -a alsa_input.usb-TC-Helicon_GoXLRMini-00.HiFi__Line4__source \
  -a alsa_output.usb-TC-Helicon_GoXLRMini-00.HiFi__Line3__sink.monitor \
  -a alsa_output.usb-TC-Helicon_GoXLRMini-00.HiFi__Headphones__sink.monitor \
  -a alsa_output.usb-TC-Helicon_GoXLRMini-00.HiFi__Line2__sink.monitor \
  -a alsa_output.usb-TC-Helicon_GoXLRMini-00.HiFi__Line1__sink.monitor \
  -ac flac -fm vfr -c mp4 &

# Store the PID of the background process
RECORDER_PID=$!
echo "gpu-screen-recorder started with PID: $RECORDER_PID"

# Keep the script running indefinitely
wait $RECORDER_PID