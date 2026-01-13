#!/bin/bash

# Wait 15 seconds before checking
sleep 15

# Check if shadowplay.sh is running
if ! ps aux | grep shadowplay.sh | grep -v grep > /dev/null; then
  notify-send --icon ~/LOGO.png -a "Nvidia" "Shadowplay" "shadowplay.sh is not running"
fi