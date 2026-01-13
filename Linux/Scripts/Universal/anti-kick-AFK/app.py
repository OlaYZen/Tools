import time
import subprocess
import threading

# === USER SETTING ===
TURN_INTENSITY = 1.5  # 👈 Increase for faster/tighter turning (e.g. 1.0, 1.5, 2.0, 3.0)
START_DELAY = 3        # seconds before starting

# === AUTO-CALCULATED VALUES ===
W_KEYCODE = 17
TURN_SPEED = int(5 * TURN_INTENSITY)          # how far the mouse moves per step
TURN_INTERVAL = max(0.001, 0.01 / TURN_INTENSITY)  # how often it moves

print(f"[CONFIG] TURN_INTENSITY={TURN_INTENSITY} -> SPEED={TURN_SPEED}, INTERVAL={TURN_INTERVAL:.4f}s")

def hold_w():
    try:
        subprocess.run(["ydotool", "key", f"{W_KEYCODE}:1"], check=True)
        print("[INFO] W key held down")
    except Exception as e:
        print(f"[ERROR] Holding W key failed: {e}")

def release_w():
    try:
        subprocess.run(["ydotool", "key", f"{W_KEYCODE}:0"], check=True)
        print("[INFO] W key released")
    except Exception as e:
        print(f"[ERROR] Releasing W key failed: {e}")

def move_mouse_forever():
    print("[INFO] Starting mouse movement using ydotool...")
    try:
        while True:
            subprocess.run(["ydotool", "mousemove", "--", str(TURN_SPEED), "0"], check=True)
            time.sleep(TURN_INTERVAL)
    except Exception as e:
        print(f"[ERROR] Mouse move failed: {e}")

def main():
    print(f"[INFO] Starting in {START_DELAY} seconds...")
    time.sleep(START_DELAY)

    try:
        hold_w()
        thread = threading.Thread(target=move_mouse_forever, daemon=True)
        thread.start()
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[INFO] Stopping...")
        release_w()

if __name__ == "__main__":
    main()
