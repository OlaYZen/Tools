//! liquid-glass: a transparent, floating pane of iOS 26-style liquid glass for Hyprland.
//!
//! The glass is drawn by Hyprland itself, as its screen shader ([`shader`]): the shader samples
//! the frame the compositor has just composited, so what the glass bends is never older than the
//! frame it is shown in, and nothing extra runs on the GPU when nothing changes. This program
//! keeps the floating window the glass belongs to (transparent: it only takes the pointer), and
//! tells the shader where the glass is through the [`marker`] strip.
//!
//! The look is ybouane/liquidglass's FS_GLASS, with its parameters and defaults ([`config`]).

mod config;
mod control;
mod gui;
mod hypr;
mod marker;
mod shader;
mod wl;

use std::io::{Read, Write};
use std::os::fd::AsFd;
use std::os::unix::net::UnixStream;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::{Duration, Instant};

use anyhow::{Context, Result, bail};
use wayland_protocols::wp::cursor_shape::v1::client::wp_cursor_shape_device_v1::Shape;

use crate::config::{APP_ID, GlassConfig, Options, SHADOW_PAD};
use crate::hypr::{Hypr, Placement, Rect};
use crate::marker::Marker;
use crate::wl::{Input, Wl};

const KEY_ESC: u32 = 1;
const KEY_Q: u32 = 16;
/// Fastest a new look is applied while a slider moves: each is a shader for Hyprland to compile.
const RESTYLE_INTERVAL: Duration = Duration::from_millis(40);

fn main() {
    if let Err(e) = run() {
        eprintln!("liquid-glass: {e:#}");
        std::process::exit(1);
    }
}

fn run() -> Result<()> {
    let Some(mut opts) = config::parse(std::env::args().skip(1), config::load_saved().unwrap_or_default())? else {
        print!("{}", config::USAGE);
        return Ok(());
    };
    let runtime = std::env::var("XDG_RUNTIME_DIR").context("XDG_RUNTIME_DIR unset")?;
    let dir = Path::new(&runtime).join("liquid-glass");
    if opts.settings {
        return gui::run(&dir);
    }
    let hypr = Hypr::from_env()?;
    if opts.print_shader {
        print!("{}", shader::glsl(&opts.glass, &hypr.monitor_scales()?));
        return Ok(());
    }
    std::fs::create_dir_all(&dir).with_context(|| format!("creating {}", dir.display()))?;
    // One glass at a time: the screen shader and the marker corner are shared.
    let _lock = lock(&dir)?;

    let pad = f64::from(SHADOW_PAD);
    let size = (f64::from(opts.width) + 2.0 * pad, f64::from(opts.height) + 2.0 * pad);
    if !opts.no_rule
        && let Err(e) = hypr.install_rules(size.0, size.1)
    {
        eprintln!("liquid-glass: could not install the window rules ({e:#}); see README");
    }
    // Borrow the screen shader; it is given back on every way out, a crash included (next run).
    let mut shader = ScreenShader::take(hypr.clone(), dir.clone())?;
    shader.install(&opts.glass)?;

    // Wakes the loop: Hyprland events and termination signals.
    let (wake_rx, wake_tx) = UnixStream::pair().context("wake socket")?;
    wake_rx.set_nonblocking(true)?;
    let quit = Arc::new(AtomicBool::new(false));
    for sig in [signal_hook::consts::SIGINT, signal_hook::consts::SIGTERM, signal_hook::consts::SIGHUP] {
        signal_hook::flag::register(sig, quit.clone())?;
        signal_hook::low_level::pipe::register(sig, wake_tx.try_clone()?)?;
    }
    let dirty = Arc::new(AtomicBool::new(true));
    let reloaded = Arc::new(AtomicBool::new(false));
    {
        let (dirty, reloaded, tx) = (dirty.clone(), reloaded.clone(), wake_tx.try_clone()?);
        hypr.spawn_events(move |reload| {
            if reload {
                reloaded.store(true, Ordering::Relaxed);
            }
            dirty.store(true, Ordering::Relaxed);
            let _ = (&tx).write(&[1]);
        });
    }

    // The settings window's requests.
    let control: control::SharedControl = Arc::new(Mutex::new(control::Control {
        glass: opts.glass.clone(),
        panel: (opts.width, opts.height),
        new_glass: None,
        resize: None,
    }));
    control::serve(&dir, control.clone(), wake_tx.try_clone()?)?;
    let mut restyle: Option<GlassConfig> = None;
    let mut restyled = Instant::now();

    let min = (2 * SHADOW_PAD as u32 + 32, 2 * SHADOW_PAD as u32 + 32);
    let mut wl = Wl::connect(APP_ID, "Liquid Glass", (size.0 as u32, size.1 as u32), min)?;
    let mut app = App::new(hypr.clone(), opts.clone(), dirty);
    while !quit.load(Ordering::Relaxed) && !app.quit {
        let mut timeout = app.timeout();
        if restyle.is_some() {
            timeout = timeout.min(RESTYLE_INTERVAL.saturating_sub(restyled.elapsed()));
        }
        wl.dispatch(timeout, wake_rx.as_fd())?;
        let mut sink = [0u8; 64];
        while matches!((&wake_rx).read(&mut sink), Ok(n) if n > 0) {}
        if reloaded.swap(false, Ordering::Relaxed) {
            // A config reload drops runtime rules and resets the screen shader.
            if !opts.no_rule {
                let _ = hypr.install_rules(size.0, size.1);
            }
            shader.reloaded();
            shader.install(&opts.glass)?;
        }
        for input in wl.take_events() {
            app.input(input, &wl);
        }
        if let Ok(mut c) = control.lock() {
            let (w, h) = wl.size();
            c.panel = (w.saturating_sub(2 * SHADOW_PAD as u32), h.saturating_sub(2 * SHADOW_PAD as u32));
            if let Some(g) = c.new_glass.take() {
                restyle = Some(g);
            }
            if let Some((w, h)) = c.resize.take() {
                app.resize_panel(w, h);
            }
        }
        if restyle.is_some() && restyled.elapsed() >= RESTYLE_INTERVAL
            && let Some(g) = restyle.take()
        {
            restyled = Instant::now();
            shader.install(&g)?;
            app.opts.glass = g.clone();
            opts.glass = g.clone();
            if let Ok(mut c) = control.lock() {
                c.glass = g;
            }
        }
        app.tick(&mut wl, &mut shader)?;
    }
    app.close_settings();
    wl.hide_marker();
    Ok(())
}

/// Hold `dir/lock` for as long as the returned fd lives.
fn lock(dir: &Path) -> Result<std::os::fd::OwnedFd> {
    use rustix::fs::{FlockOperation, Mode, OFlags};
    let fd = rustix::fs::open(dir.join("lock"), OFlags::CREATE | OFlags::RDWR | OFlags::CLOEXEC, Mode::from_raw_mode(0o600))?;
    if rustix::fs::flock(&fd, FlockOperation::NonBlockingLockExclusive).is_err() {
        bail!("liquid-glass is already running");
    }
    Ok(fd)
}

/// What the glass borrows from Hyprland: its screen shader, and its damage tracking while the
/// glass is on screen. The previous values are remembered (in files, so a crash can't lose them)
/// and put back when this is dropped — or, after a crash, by the next run.
///
/// Why damage tracking: Hyprland runs the screen shader only over the pixels damaged that
/// frame, and keeps the rest of each swapchain buffer from earlier frames. The glass is not
/// local — every pixel bends in content from up to ~100 px away — so when a video plays near
/// it, glass pixels just outside the video's damage stay stale, at a different age in each of
/// the 2–3 buffers the monitor flips between: flicker. With damage tracking on "monitor", every
/// frame Hyprland draws covers the whole monitor, so every frame has whole, current glass.
/// Hyprland still draws no frame when nothing changed, so a still desktop stays free.
struct ScreenShader {
    hypr: Hypr,
    dir: PathBuf,
    previous: String,
    previous_damage: i64,
    /// Damage tracking is currently ours (whole-monitor frames).
    full_frames: bool,
    current: Option<PathBuf>,
    generation: u32,
    scales: Vec<(i64, f64)>,
}

impl ScreenShader {
    fn take(hypr: Hypr, dir: PathBuf) -> Result<Self> {
        let state = dir.join("previous-shader");
        let damage_state = dir.join("previous-damage-tracking");
        let current = hypr.screen_shader()?;
        let current_damage = hypr.damage_tracking().unwrap_or(2);
        let (previous, previous_damage) = if Path::new(&current).starts_with(&dir) {
            // Ours, left by a run that died: what it borrowed is in the state files.
            let damage = std::fs::read_to_string(&damage_state).ok().and_then(|s| s.trim().parse().ok()).unwrap_or(current_damage);
            (std::fs::read_to_string(&state).unwrap_or_default(), damage)
        } else {
            std::fs::write(&state, &current).with_context(|| format!("writing {}", state.display()))?;
            std::fs::write(&damage_state, current_damage.to_string()).with_context(|| format!("writing {}", damage_state.display()))?;
            (current.clone(), current_damage)
        };
        // Shaders a killed run left behind (the one Hyprland still points at goes on install).
        for entry in std::fs::read_dir(&dir).into_iter().flatten().flatten() {
            let name = entry.file_name();
            if name.to_string_lossy().starts_with("glass-") && entry.path() != Path::new(&current) {
                let _ = std::fs::remove_file(entry.path());
            }
        }
        let current = Path::new(&current).starts_with(&dir).then(|| PathBuf::from(&current));
        Ok(Self { hypr, dir, previous, previous_damage, full_frames: false, current, generation: 0, scales: Vec::new() })
    }

    /// Whole-monitor frames while the glass is on screen; the user's damage tracking otherwise.
    fn full_frames(&mut self, on: bool) {
        if on == self.full_frames {
            return;
        }
        // "None" (0) and "monitor" (1) already redraw whole frames.
        let mode = if on { self.previous_damage.min(1) } else { self.previous_damage };
        match self.hypr.set_damage_tracking(mode) {
            Ok(()) => self.full_frames = on,
            Err(e) => eprintln!("liquid-glass: could not set damage tracking: {e:#}"),
        }
    }

    /// After a config reload Hyprland has its own values back: apply ours again on next use.
    fn reloaded(&mut self) {
        self.full_frames = false;
    }

    /// Write the shader for `glass` and the current monitors, and make it Hyprland's.
    fn install(&mut self, glass: &GlassConfig) -> Result<()> {
        self.scales = self.hypr.monitor_scales()?;
        self.generation += 1;
        // A new name each time: Hyprland may not recompile a path it already has.
        let path = self.dir.join(format!("glass-{}-{}.frag", std::process::id(), self.generation));
        std::fs::write(&path, shader::glsl(glass, &self.scales)).with_context(|| format!("writing {}", path.display()))?;
        self.hypr.set_screen_shader(&path.to_string_lossy())?;
        if let Some(old) = self.current.replace(path) {
            let _ = std::fs::remove_file(old);
        }
        Ok(())
    }
}

impl Drop for ScreenShader {
    fn drop(&mut self) {
        if self.full_frames {
            self.full_frames(false);
        }
        if let Err(e) = self.hypr.set_screen_shader(&self.previous) {
            eprintln!("liquid-glass: could not restore the screen shader `{}`: {e:#}", self.previous);
            return;
        }
        if let Some(path) = self.current.take() {
            let _ = std::fs::remove_file(path);
        }
        let _ = std::fs::remove_file(self.dir.join("previous-shader"));
        let _ = std::fs::remove_file(self.dir.join("previous-damage-tracking"));
    }
}

/// A drag the app runs itself, with the pointer grab every press gives: the glass follows each
/// motion event, so it stays locked to the cursor. The window catches up on release.
#[derive(Clone, Copy, Debug, PartialEq)]
enum Gesture {
    None,
    Move { base: Rect, from: (f64, f64), to: (f64, f64) },
    Resize { base: Rect, edges: Edges, from: (f64, f64), to: (f64, f64) },
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
struct Edges {
    left: bool,
    right: bool,
    top: bool,
    bottom: bool,
}

impl Edges {
    fn any(&self) -> bool {
        self.left || self.right || self.top || self.bottom
    }

    fn cursor(&self) -> Shape {
        match (self.left, self.right, self.top, self.bottom) {
            (true, _, true, _) => Shape::NwResize,
            (_, true, true, _) => Shape::NeResize,
            (true, _, _, true) => Shape::SwResize,
            (_, true, _, true) => Shape::SeResize,
            (true, ..) => Shape::WResize,
            (_, true, ..) => Shape::EResize,
            (_, _, true, _) => Shape::NResize,
            (_, _, _, true) => Shape::SResize,
            _ => Shape::Default,
        }
    }
}

impl Gesture {
    /// The glass's rectangle while this runs.
    fn apply(&self, min: f64) -> Option<Rect> {
        match *self {
            Gesture::None => None,
            Gesture::Move { base, from, to } => Some(Rect { x: base.x + to.0 - from.0, y: base.y + to.1 - from.1, ..base }),
            Gesture::Resize { base, edges, from, to } => {
                let (dx, dy) = (to.0 - from.0, to.1 - from.1);
                let mut r = base;
                if edges.right {
                    r.w = (base.w + dx).max(min);
                }
                if edges.bottom {
                    r.h = (base.h + dy).max(min);
                }
                if edges.left {
                    r.w = (base.w - dx).max(min);
                    r.x = base.x + base.w - r.w;
                }
                if edges.top {
                    r.h = (base.h - dy).max(min);
                    r.y = base.y + base.h - r.h;
                }
                Some(r)
            }
        }
    }
}

struct App {
    hypr: Hypr,
    opts: Options,
    placement: Option<Placement>,
    floated: bool,
    gesture: Gesture,
    /// Where the window was sent on release, until Hyprland reports it there.
    settling: Option<(Rect, Instant)>,
    pointer: Option<(f64, f64)>,
    cursor: Shape,
    hover: f32,
    press: f32,
    last_tick: Instant,
    /// Set by Hyprland events: poll everything now.
    dirty: Arc<AtomicBool>,
    next_full: Instant,
    next_fast: Instant,
    /// Until when the window counts as moving under the compositor (super+drag): it is then
    /// followed every few ms.
    moving_until: Instant,
    quit: bool,
    /// The settings window, while it is open.
    settings: Option<std::process::Child>,
    /// `LIQUID_GLASS_DEBUG`: log every new marker.
    debug: bool,
    last_debug: Option<Marker>,
}

impl App {
    fn new(hypr: Hypr, opts: Options, dirty: Arc<AtomicBool>) -> Self {
        let now = Instant::now();
        Self {
            hypr,
            opts,
            placement: None,
            floated: false,
            gesture: Gesture::None,
            settling: None,
            pointer: None,
            cursor: Shape::Default,
            hover: 0.0,
            press: 0.0,
            last_tick: now,
            dirty,
            next_full: now,
            next_fast: now,
            moving_until: now,
            quit: false,
            settings: None,
            debug: std::env::var_os("LIQUID_GLASS_DEBUG").is_some(),
            last_debug: None,
        }
    }

    fn pad(&self) -> f64 {
        f64::from(SHADOW_PAD)
    }

    /// The resize edges under surface-local `(x, y)`: none on the glass, some on its shadow.
    fn edges_at(&self, (x, y): (f64, f64), wl: &Wl) -> Edges {
        let (w, h) = wl.size();
        let pad = self.pad();
        Edges { left: x < pad, right: x > f64::from(w) - pad, top: y < pad, bottom: y > f64::from(h) - pad }
    }

    fn set_cursor(&mut self, shape: Shape, wl: &Wl) {
        if self.cursor != shape {
            self.cursor = shape;
            wl.set_cursor(shape);
        }
    }

    fn input(&mut self, input: Input, wl: &Wl) {
        match input {
            Input::Enter { x, y } => {
                self.pointer = Some((x, y));
                self.cursor = Shape::Default;
                let shape = self.edges_at((x, y), wl).cursor();
                wl.set_cursor(shape);
                self.cursor = shape;
            }
            Input::Motion { x, y } => {
                self.pointer = Some((x, y));
                match &mut self.gesture {
                    Gesture::Move { to, .. } | Gesture::Resize { to, .. } => *to = (x, y),
                    Gesture::None => self.set_cursor(self.edges_at((x, y), wl).cursor(), wl),
                }
            }
            Input::Leave => {
                if self.gesture == Gesture::None {
                    self.pointer = None;
                }
            }
            Input::Press { x, y } => {
                let Some(base) = self.placement.as_ref().map(|p| p.window) else { return };
                let edges = self.edges_at((x, y), wl);
                self.gesture = if edges.any() {
                    Gesture::Resize { base, edges, from: (x, y), to: (x, y) }
                } else {
                    self.set_cursor(Shape::Grabbing, wl);
                    Gesture::Move { base, from: (x, y), to: (x, y) }
                };
            }
            Input::Release => self.finish_gesture(wl),
            Input::Menu => self.open_settings(),
            Input::Key(KEY_ESC | KEY_Q) | Input::Close => self.quit = true,
            Input::Key(_) | Input::Configure { .. } => {}
        }
    }

    /// Open the settings window, unless it is open already.
    fn open_settings(&mut self) {
        if self.settings.as_mut().is_some_and(|c| matches!(c.try_wait(), Ok(None))) {
            return;
        }
        match std::env::current_exe().and_then(|exe| std::process::Command::new(exe).arg("--settings").spawn()) {
            Ok(child) => self.settings = Some(child),
            Err(e) => eprintln!("liquid-glass: could not open the settings: {e}"),
        }
    }

    /// The settings window closes itself when the glass goes; reap it if it already did.
    fn close_settings(&mut self) {
        if let Some(mut child) = self.settings.take() {
            let _ = child.try_wait();
        }
    }

    /// Resize the window so the panel is `w`×`h` logical px, keeping it centred.
    fn resize_panel(&mut self, w: u32, h: u32) {
        let Some(p) = &self.placement else { return };
        let pad = 2.0 * self.pad();
        let (nw, nh) = (f64::from(w) + pad, f64::from(h) + pad);
        let x = (p.window.x + (p.window.w - nw) / 2.0).round();
        let y = (p.window.y + (p.window.h - nh) / 2.0).round();
        let r = Rect { x, y, w: nw, h: nh };
        if let Err(e) = self.hypr.resize_to(p.address, nw as i64, nh as i64).and_then(|()| self.hypr.move_to(p.address, x as i64, y as i64)) {
            eprintln!("liquid-glass: resize: {e:#}");
        }
        // Show the new size at once; Hyprland's report catches up.
        self.settling = Some((r, Instant::now() + Duration::from_millis(500)));
        self.dirty.store(true, Ordering::Relaxed);
    }

    /// Send the window where the glass was dragged to.
    fn finish_gesture(&mut self, wl: &Wl) {
        let min = 2.0 * self.pad() + 32.0;
        let (gesture, Some(p)) = (std::mem::replace(&mut self.gesture, Gesture::None), &self.placement) else { return };
        let Some(r) = gesture.apply(min) else { return };
        let r = Rect { x: r.x.round(), y: r.y.round(), w: r.w.round(), h: r.h.round() };
        let address = p.address;
        if let Gesture::Resize { .. } = gesture
            && let Err(e) = self.hypr.resize_to(address, r.w as i64, r.h as i64)
        {
            eprintln!("liquid-glass: resize: {e:#}");
        }
        if let Err(e) = self.hypr.move_to(address, r.x as i64, r.y as i64) {
            eprintln!("liquid-glass: move: {e:#}");
        }
        self.settling = Some((r, Instant::now() + Duration::from_millis(500)));
        self.dirty.store(true, Ordering::Relaxed);
        let shape = self.pointer.map_or(Shape::Default, |p| self.edges_at(p, wl).cursor());
        self.set_cursor(shape, wl);
    }

    fn animating(&self) -> bool {
        let (hover, press) = self.targets();
        self.opts.glass.button && ((self.hover - hover).abs() > 0.004 || (self.press - press).abs() > 0.004)
    }

    fn targets(&self) -> (f32, f32) {
        let pressed = matches!(self.gesture, Gesture::Move { .. });
        let hovering = self.pointer.is_some() && self.gesture == Gesture::None;
        (f32::from(u8::from(hovering)), f32::from(u8::from(pressed)))
    }

    /// How long the loop may sleep: input and Hyprland events wake it earlier.
    fn timeout(&self) -> Duration {
        let now = Instant::now();
        if self.animating() {
            return Duration::from_millis(2);
        }
        let mut until = self.next_full;
        if self.gesture == Gesture::None && self.placement.as_ref().is_some_and(|p| p.active) {
            until = until.min(self.next_fast);
        }
        until.saturating_duration_since(now).clamp(Duration::from_micros(500), Duration::from_millis(250))
    }

    fn tick(&mut self, wl: &mut Wl, shader: &mut ScreenShader) -> Result<()> {
        let now = Instant::now();
        if self.dirty.swap(false, Ordering::Relaxed) || now >= self.next_full {
            self.next_full = now + Duration::from_millis(250);
            match self.hypr.placement() {
                Ok(p) => {
                    if p.as_ref().zip(self.placement.as_ref()).is_some_and(|(new, old)| new.window != old.window) {
                        self.moving_until = now + Duration::from_millis(300);
                    }
                    self.placement = p;
                }
                Err(e) => eprintln!("liquid-glass: {e:#}"),
            }
            // A monitor came or went, or changed scale: the shader's scale table is stale.
            if let Ok(scales) = self.hypr.monitor_scales()
                && scales != shader.scales
            {
                shader.install(&self.opts.glass)?;
            }
        } else if self.gesture == Gesture::None
            && now >= self.next_fast
            && let Some(p) = &mut self.placement
            && p.active
        {
            // Hyprland moves windows (super+drag, keybinds) without telling anyone: while ours
            // is focused, follow it closely, very closely while it is moving.
            let moving = now < self.moving_until;
            self.next_fast = now + if moving { Duration::from_millis(2) } else { Duration::from_millis(16) };
            if let Some(r) = self.hypr.active_rect(p.address)
                && r != p.window
            {
                p.window = r;
                self.moving_until = now + Duration::from_millis(300);
            }
        }

        let Some(p) = self.placement.clone() else { return Ok(()) };
        if !self.floated {
            self.floated = true;
            if !p.floating
                && let Err(e) = self.hypr.float(p.address)
            {
                eprintln!("liquid-glass: could not float the window: {e:#}");
            }
        }
        if let Some((target, until)) = self.settling {
            let there = (p.window.x - target.x).abs() < 1.0 && (p.window.y - target.y).abs() < 1.0;
            if there || now >= until {
                self.settling = None;
            }
        }

        let dt = now.duration_since(self.last_tick).as_secs_f32().min(0.1);
        self.last_tick = now;
        let (hover_to, press_to) = self.targets();
        let ease = |v: &mut f32, to: f32, rate: f32| *v += (to - *v) * (1.0 - (-rate * dt).exp());
        ease(&mut self.hover, hover_to, 14.0);
        ease(&mut self.press, press_to, 22.0);

        shader.full_frames(p.visible);
        if !p.visible {
            wl.hide_marker();
            return Ok(());
        }
        let min = 2.0 * self.pad() + 32.0;
        let glass = self.gesture.apply(min).or(self.settling.map(|(r, _)| r)).unwrap_or(p.window);
        let s = p.monitor.scale;
        let m = &p.monitor.rect;
        // Logical → the monitor's physical pixels, rounded as Hyprland places surfaces.
        let phys = |r: &Rect| {
            let x0 = ((r.x - m.x) * s).round();
            let y0 = ((r.y - m.y) * s).round();
            [x0 as i32, y0 as i32, ((r.x + r.w - m.x) * s).round() as i32 - x0 as i32, ((r.y + r.h - m.y) * s).round() as i32 - y0 as i32]
        };
        // While the glass is being dragged it is no longer under the windows its old place
        // was under: only what covers the window where it is now counts.
        let occluders = if self.gesture == Gesture::None { p.occluders.iter().take(marker::MAX_OCCLUDERS).map(phys).collect() } else { Vec::new() };
        let marker = Marker {
            window: phys(&glass),
            press: (self.press.clamp(0.0, 1.0) * 255.0).round() as u8,
            hover: (self.hover.clamp(0.0, 1.0) * 255.0).round() as u8,
            visible: true,
            occluders,
        };
        if self.debug && self.last_debug.as_ref() != Some(&marker) {
            eprintln!("marker: {} {:?} glass {:?} occluders {:?}", p.monitor.name, marker.window, glass, marker.occluders);
            self.last_debug = Some(marker.clone());
        }
        wl.set_marker(&p.monitor.name, marker.pixels());
        Ok(())
    }
}
