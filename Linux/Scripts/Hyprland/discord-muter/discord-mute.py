import subprocess
import time
import json
import threading
import os
import glob
import fcntl
from flask import Flask, jsonify

app = Flask(__name__)

# Cache for Discord window address
discord_window_address_cache = None
discord_cache_timestamp = 0
DISCORD_CACHE_TTL = 10  # seconds

# Cache for mouse devices
mouse_devices_cache = None
mouse_cache_timestamp = 0
MOUSE_CACHE_TTL = 30  # seconds


def get_mouse_devices():
    """Find only Logitech mouse/pointer devices on the system"""
    global mouse_devices_cache, mouse_cache_timestamp
    now = time.time()
    
    if mouse_devices_cache is None or now - mouse_cache_timestamp > MOUSE_CACHE_TTL:
        devices = []
        print("[DEBUG] Detecting Logitech mouse devices...")
        
        try:
            # Use libinput to find pointer devices
            result = subprocess.run(
                ["libinput", "list-devices"], 
                capture_output=True, 
                text=True, 
                check=True
            )
            
            current_device = None
            current_kernel = None
            has_pointer = False
            is_logitech = False
            
            for line in result.stdout.split('\n'):
                if line.startswith('Device:'):
                    # Save previous device if it was a Logitech pointer
                    if current_device and current_kernel and has_pointer and is_logitech:
                        devices.append(current_kernel)
                        print(f"[INFO] Found Logitech device: {current_device} -> {current_kernel}")
                    
                    # Start new device
                    current_device = line.split('Device:')[1].strip()
                    current_kernel = None
                    has_pointer = False
                    is_logitech = 'logitech' in current_device.lower()
                    
                elif line.startswith('Kernel:'):
                    current_kernel = line.split('Kernel:')[1].strip()
                    
                elif line.startswith('Capabilities:'):
                    caps = line.split('Capabilities:')[1].strip()
                    if 'pointer' in caps:
                        has_pointer = True
            
            # Don't forget the last device
            if current_device and current_kernel and has_pointer and is_logitech:
                devices.append(current_kernel)
                print(f"[INFO] Found Logitech device: {current_device} -> {current_kernel}")
                
        except (subprocess.CalledProcessError, FileNotFoundError):
            print("[WARN] libinput not available, using fallback detection...")
            # Fallback method - only look for Logitech devices
            for event_file in glob.glob('/dev/input/event*'):
                device_name = os.path.basename(event_file)
                name_path = f'/sys/class/input/{device_name}/device/name'
                if os.path.exists(name_path):
                    try:
                        with open(name_path, 'r') as f:
                            name = f.read().strip().lower()
                            if 'logitech' in name:
                                devices.append(event_file)
                                print(f"[INFO] Found Logitech device: {name} -> {event_file}")
                    except (IOError, OSError):
                        continue
        
        print(f"[INFO] Total Logitech devices found: {len(devices)}")
        mouse_devices_cache = devices
        mouse_cache_timestamp = now
    else:
        print(f"[DEBUG] Using cached Logitech devices: {len(mouse_devices_cache)} devices")
    
    return mouse_devices_cache


def disable_mouse_input():
    """Disable only Logitech mouse/pointer devices using evtest"""
    devices = get_mouse_devices()
    disabled_devices = []
    print(f"[DEBUG] Attempting to disable {len(devices)} Logitech devices...")
    
    for device in devices:
        try:
            print(f"[DEBUG] Grabbing Logitech device: {device}")
            # Use evtest to grab device exclusively
            proc = subprocess.Popen(
                ["timeout", "30", "evtest", "--grab", device],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL
            )
            time.sleep(0.01)  # Give it time to grab
            if proc.poll() is None:  # Still running = successfully grabbed
                disabled_devices.append(("evtest", device, proc))
                print(f"[INFO] Successfully grabbed: {device}")
            else:
                proc.terminate()
                print(f"[ERROR] Failed to grab: {device}")
        except Exception as e:
            print(f"[ERROR] Error grabbing {device}: {e}")
            # Silent fail - don't let mouse disabling break Discord functionality
            pass
    
    print(f"[INFO] Successfully disabled {len(disabled_devices)} Logitech devices")
    return disabled_devices


def enable_mouse_input(disabled_devices):
    """Re-enable previously disabled mouse/pointer devices"""
    print(f"[DEBUG] Re-enabling {len(disabled_devices)} Logitech devices...")
    
    for device_info in disabled_devices:
        try:
            method, device, handle = device_info
            if method == "evtest":
                handle.terminate()
                handle.wait(timeout=2)
                print(f"[INFO] Released: {device}")
        except Exception as e:
            print(f"[ERROR] Error releasing {device}: {e}")
            # Silent fail - ensure we don't break the main functionality
            pass
    
    print("[INFO] Logitech mouse input re-enabled")


def get_focused_window():
    print("[DEBUG] Getting currently focused window...")
    try:
        result = subprocess.run(
            ["hyprctl", "activewindow", "-j"],
            capture_output=True,
            text=True,
            check=True,
        )
        active_window_info = json.loads(result.stdout)
        window_address = active_window_info.get("address")
        print(f"[DEBUG] Current focused window: {window_address}")
        return window_address
    except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
        print(f"[ERROR] Error getting focused window in Hyprland: {e}")
        return None


def get_discord_window():
    print("[DEBUG] Searching for Discord window...")
    try:
        result = subprocess.run(
            ["hyprctl", "clients", "-j"],
            capture_output=True,
            text=True,
            check=True,
        )
        clients = json.loads(result.stdout)

        for client in clients:
            if client.get("class") == "vesktop":
                discord_address = client.get("address")
                print(f"[DEBUG] Found Discord window (Vesktop): {discord_address}")
                return discord_address
        
        # If vesktop not found, check for regular discord
        for client in clients:
            if client.get("class") == "discord":
                discord_address = client.get("address")
                print(f"[DEBUG] Found Discord window (Discord): {discord_address}")
                return discord_address
        
        print("[ERROR] Discord window not found (neither Vesktop nor Discord)")
        return None
    except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
        print(f"[ERROR] Error getting Discord window in Hyprland: {e}")
        return None


def get_discord_window_cached():
    global discord_window_address_cache, discord_cache_timestamp
    now = time.time()
    if (
        discord_window_address_cache is None
        or now - discord_cache_timestamp > DISCORD_CACHE_TTL
    ):
        print("[DEBUG] Discord cache expired, refreshing...")
        discord_window_address_cache = get_discord_window()
        discord_cache_timestamp = now
    else:
        print(f"[DEBUG] Using cached Discord window: {discord_window_address_cache}")
    return discord_window_address_cache


def focus_window(window_address):
    if window_address:
        print(f"[DEBUG] Focusing window: {window_address}")
        try:
            subprocess.run(
                ["hyprctl", "dispatch", "focuswindow", f"address:{window_address}"],
                check=True,
            )
            print(f"[INFO] Successfully focused window: {window_address}")
        except subprocess.CalledProcessError as e:
            print(f"[ERROR] Error focusing window {window_address} in Hyprland: {e}")
    else:
        print("[ERROR] No window address provided to focus.")


def send_key_combination(key_letter):
    """
    Send Ctrl+Shift+<key> using ydotool.
    key_letter: str, e.g. 'm' for M, 'd' for D
    """
    print(f"[DEBUG] Sending key combination: Ctrl+Shift+{key_letter.upper()}")
    
    # Key codes for letters (scancode format)
    key_codes = {
        "m": 50,  # M key
        "d": 32,  # D key
    }

    keycode = key_codes.get(key_letter.lower())
    if keycode is None:
        print(f"[ERROR] Unknown key: {key_letter}")
        return

    try:
        subprocess.run(
            [
                "ydotool",
                "key",
                "29:1",  # Ctrl down
                "42:1",  # Shift down
                f"{keycode}:1",  # Key down
                f"{keycode}:0",  # Key up
                "42:0",  # Shift up
                "29:0",  # Ctrl up
            ],
            check=True,
        )
        print(f"[INFO] Successfully sent: Ctrl+Shift+{key_letter.upper()}")
    except FileNotFoundError:
        print("[ERROR] Error: ydotool command not found. Please ensure ydotool is installed.")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Error sending key with ydotool: {e}")
        print("Please ensure ydotoold daemon is running and your user has necessary permissions.")
    except Exception as e:
        print(f"[ERROR] An unexpected error occurred with ydotool: {e}")


def toggle_discord(key_letter):
    print(f"\n[INFO] === STARTING DISCORD TOGGLE FOR KEY: {key_letter.upper()} ===")
    
    # Disable mouse input before starting
    disabled_devices = disable_mouse_input()
    
    try:
        original_window_address = get_focused_window()
        discord_window_address = get_discord_window_cached()

        if discord_window_address is None:
            print("[ERROR] Discord window not found.")
            return False

        focus_window(discord_window_address)
        print("[DEBUG] Waiting for focus to settle...")
        time.sleep(0.0001)  # small delay to ensure focus
        send_key_combination(key_letter)

        if original_window_address and original_window_address != discord_window_address:
            print("[DEBUG] Restoring focus to original window...")
            focus_window(original_window_address)
        else:
            print("[INFO] No need to restore focus (same window or no original window)")

        print("[INFO] Discord toggle completed successfully")
        return True
    except Exception as e:
        print(f"[ERROR] Error during Discord toggle: {e}")
        return False
    finally:
        # Always re-enable mouse input, even if an error occurs
        enable_mouse_input(disabled_devices)
        print("[INFO] === DISCORD TOGGLE COMPLETE ===\n")


def toggle_discord_async(key_letter):
    def worker():
        toggle_discord(key_letter)

    threading.Thread(target=worker, daemon=True).start()


@app.route("/mute", methods=["POST"])
def mute():
    toggle_discord_async("m")  # Ctrl+Shift+M
    return jsonify({"status": "success", "action": "mute toggled"})


@app.route("/deafen", methods=["POST"])
def deafen():
    toggle_discord_async("d")  # Ctrl+Shift+D
    return jsonify({"status": "success", "action": "deafen toggled"})



if __name__ == "__main__":
    app.run(port=8784)
