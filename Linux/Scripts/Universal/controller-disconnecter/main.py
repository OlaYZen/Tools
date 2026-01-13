import pygame
import time
import subprocess

def apply_deadzone(value, deadzone):
    if abs(value) < deadzone:
        return 0.0
    sign = 1 if value > 0 else -1
    scaled_value = (abs(value) - deadzone) / (1 - deadzone)
    return sign * scaled_value

def notify_disconnect():
    icon_path = "~/LOGO.png"
    app_name = "Python"
    title = "Roller DCd"
    description = "Controller disconnected due to 15 minutes of inactivity."
    try:
        subprocess.run(
            [
                "notify-send",
                "--icon", icon_path,
                "-a", app_name,
                title,
                description,
            ],
            check=True,
        )
        print("Notification sent.")
    except subprocess.CalledProcessError as e:
        print(f"Failed to send notification: {e}")

def disconnect_controller(mac_address):
    try:
        subprocess.run(["bluetoothctl", "disconnect", mac_address], check=True)
        print(f"Disconnected controller {mac_address} due to inactivity.")
        notify_disconnect()
    except subprocess.CalledProcessError as e:
        print(f"Failed to disconnect controller: {e}")

def main():
    pygame.init()
    pygame.joystick.init()

    deadzone = 0.1
    inactivity_limit = 15 * 60
    last_activity_time = time.time()
    controller_mac = "YOURCONTROLLERMAC"

    joystick = None
    disconnected = False
    running = True

    print("Starting controller inactivity monitor...")

    while running:
        joystick_count = pygame.joystick.get_count()

        if joystick_count > 0 and joystick is None:
            joystick = pygame.joystick.Joystick(0)
            joystick.init()
            print(f"Joystick connected: {joystick.get_name()}")
            disconnected = False
            last_activity_time = time.time()

        if joystick_count == 0 and joystick is not None:
            print("Joystick disconnected.")
            joystick = None
            disconnected = True

        current_time = time.time()

        if not disconnected and (current_time - last_activity_time > inactivity_limit):
            disconnect_controller(controller_mac)
            disconnected = True
            last_activity_time = current_time

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            elif event.type == pygame.JOYDEVICEADDED:
                if joystick is None:
                    joystick = pygame.joystick.Joystick(event.device_index)
                    joystick.init()
                    print(f"Joystick connected (event): {joystick.get_name()}")
                    disconnected = False
                    last_activity_time = time.time()

            elif event.type == pygame.JOYDEVICEREMOVED:
                if joystick is not None and event.instance_id == joystick.get_instance_id():
                    print("Joystick disconnected (event).")
                    joystick = None
                    disconnected = True

            elif event.type == pygame.JOYAXISMOTION:
                value = apply_deadzone(event.value, deadzone)
                if value != 0.0:
                    print(f"Axis {event.axis} moved to {value:.3f}")
                    last_activity_time = current_time
                    disconnected = False

            elif event.type == pygame.JOYBUTTONDOWN:
                print(f"Button {event.button} pressed")
                last_activity_time = current_time
                disconnected = False

            elif event.type == pygame.JOYBUTTONUP:
                print(f"Button {event.button} released")
                last_activity_time = current_time
                disconnected = False

            elif event.type == pygame.JOYHATMOTION:
                print(f"Hat {event.hat} moved to {event.value}")
                last_activity_time = current_time
                disconnected = False

        time.sleep(0.01)

if __name__ == "__main__":
    main()