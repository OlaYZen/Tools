# PadLab: Controller Tester

A local web app that tests Xbox, PlayStation and Nintendo controllers: buttons, sticks, analog trigger travel, gyro and accelerometer, and rumble, including an **unlimited rumble mode**. An animated controller mirrors everything you do on the pad.

## Run it

```bash
./start.sh            # serves http://localhost:8737 and opens it
PORT=9000 ./start.sh  # use a different port
```

Use **Chrome, Edge or another Chromium-based browser**. Firefox can show buttons and sticks, but it has no WebHID, so you won't get gyro, and its rumble support is very limited.

Plug in or pair the controller, then **press any button**. Browsers only expose a gamepad after its first input.

## 3D controller view

PlayStation controllers (DualSense, DualSense Edge) are shown as a real 3D model. Every part moves on its own: face buttons and the D-pad press in, the sticks tilt, the triggers pull, the bumpers press, and the touchpad clicks. The model also tilts with the gyro and shakes with the rumble. On a DualSense Edge you also see the Fn buttons and the rear paddles (drawn see-through). Drag to rotate the model, double-click to reset it, and use the **3D / 2D** toggle to switch views. Other controllers use the 2D drawing until a model is added for them.

The 3D view needs WebGL. In Brave or Chrome, turn on **Settings → System → Use graphics acceleration when available**, then relaunch the browser. Without it, the page falls back to the 2D drawing.

Model: ["Playstation 5 Dualsense"](https://sketchfab.com/3d-models/playstation-5-dualsense-878c1f882808477ab81c2fe86d5a3936) by AHarmlessPotato, licensed CC BY 4.0. Its textures were downscaled to 2K with `tools/prepare_model.py`. three.js r186 (MIT) is vendored in `vendor/three`.

### Adding a model
1. Download a `.glb` and shrink its textures: `python3 tools/prepare_model.py in.glb models/name.glb --size 2048`.
2. Add a profile in `js/model3d.js` (`PROFILES`) that maps the model's geometry islands to buttons, then map the brand to it in `MODEL_FOR` in `js/main.js`.

## What it tests

| Feature | Xbox | PlayStation (DS4 / DualSense) | Nintendo (Pro / Joy-Con) |
|---|---|---|---|
| Buttons, D-pad, press counter, "all tested" checklist | ✓ | ✓ | ✓ |
| Sticks: position, trail, circularity error, max reach | ✓ | ✓ | ✓ |
| Trigger travel: live %, peak, first-register point, full-travel check, graph | ✓ | ✓ | digital ZL/ZR |
| Rumble: strong and weak motors, patterns, timed, **unlimited** | ✓ | ✓ | ✓ |
| Impulse-trigger rumble | ✓ only where the browser exposes `trigger-rumble` (Chrome/Edge on Windows) | – | – |
| Gyro and accelerometer, 3D tilt of the controller model | – (no gyro) | ✓ WebHID | ✓ WebHID |
| Battery, connection type, report rate | – | ✓ WebHID | ✓ WebHID |
| Touchpad, lightbar colour, mute button | – | ✓ WebHID | – |
| DualSense Edge back paddles + Fn buttons | – | ✓ WebHID (the Gamepad API doesn't expose them) | – |
| Adaptive trigger resistance | – | ✓ DualSense, WebHID | – |

### Unlimited rumble
A single Gamepad API vibration lasts at most 5 seconds. Unlimited mode keeps re-sending the effect before it runs out, and over WebHID it re-sends the motor report. The rumble keeps going until you stop it. You can stop it with the button, **Esc**, or **Select + Start** on the controller. Chrome pauses gamepad vibration while the tab is hidden, and it starts again when you come back to the tab.

### Gyro (WebHID)
Click **Connect WebHID · gyro & extras** and pick the controller. The gyro is calibrated automatically after connecting, so leave the controller still for about a second. **Recenter** sets the current pose as neutral. If an axis on the 3D model turns the wrong way for your controller, flip it with the *Invert* checkboxes.

On Linux, the browser needs read/write access to `/dev/hidraw*`. Steam's udev rules already cover the DS4, DualSense and Switch Pro Controller. For Joy-Cons, or if connecting fails, install the included rule:

```bash
sudo cp 70-padlab-controllers.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
```

## Files

- `index.html`, `css/style.css`: layout and styling
- `js/main.js`: UI, render loop and animations
- `js/model3d.js`: 3D controller view (splits the model into parts and animates them)
- `js/controllers.js`: 2D SVG controller drawings (Xbox / PlayStation / Nintendo)
- `models/`: 3D models; `vendor/three/`: three.js; `tools/prepare_model.py`: texture downscaler
- `js/gamepad.js`: brand detection and button naming
- `js/rumble.js`: rumble engine (patterns, unlimited mode, backends)
- `js/hid.js`: WebHID drivers for DS4, DualSense and Switch controllers
- `js/motion.js`: gyro/accel orientation filter
- `js/charts.js`: graphs and stick canvases
