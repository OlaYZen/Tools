#!/usr/bin/env bash
#
# fix-scale.sh
#
# Workaround for a Hyprland bug where DP-1 comes up at the wrong zoom/scale on
# login. DP-1 only has 1x and 1.33x as valid scales, so momentarily "breaking"
# the scale to 1.3 and then setting it back to 1.33 forces Hyprland to recompute
# and apply the correct scale.
#
# The values are written back to monitor.conf so they persist, and we reload
# Hyprland explicitly after each change so the toggle is deterministic.

set -euo pipefail

CONF="$HOME/.config/hypr/conf/monitor.conf"

# Let Hyprland finish coming up and apply its (buggy) initial scale.
sleep 0.5

# Break the scale on DP-1: 1.33 -> 1.3  (HDMI's "scale = 2" is left untouched)
sed -i 's/^\(\s*scale = \)1\.33$/\11.3/' "$CONF"
hyprctl reload >/dev/null 2>&1 || true

sleep 0.5

# Restore the correct scale on DP-1: 1.3 -> 1.33
sed -i 's/^\(\s*scale = \)1\.3$/\11.33/' "$CONF"
hyprctl reload >/dev/null 2>&1 || true
