//! Hyprland IPC: where the glass window is, what is stacked over it, the screen shader it
//! borrows, and the rules that keep Hyprland from decorating it.

use std::io::{BufRead, BufReader, Read, Write};
use std::os::unix::net::UnixStream;
use std::path::{Path, PathBuf};
use std::time::Duration;

use anyhow::{Context, Result, bail};
use serde::Deserialize;
use serde::de::DeserializeOwned;

use crate::config::APP_ID;

/// The namespace of the marker layer.
pub const MARKER_NAMESPACE: &str = "liquid-glass-marker";

/// A rectangle in global logical px.
#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct Rect {
    pub x: f64,
    pub y: f64,
    pub w: f64,
    pub h: f64,
}

impl Rect {
    pub fn intersects(&self, o: &Rect) -> bool {
        self.x < o.x + o.w && o.x < self.x + self.w && self.y < o.y + o.h && o.y < self.y + self.h
    }

    fn overlap_area(&self, o: &Rect) -> f64 {
        let w = (self.x + self.w).min(o.x + o.w) - self.x.max(o.x);
        let h = (self.y + self.h).min(o.y + o.h) - self.y.max(o.y);
        w.max(0.0) * h.max(0.0)
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct MonitorInfo {
    pub id: i64,
    pub name: String,
    /// Logical.
    pub rect: Rect,
    pub scale: f64,
}

/// Where the glass window is and what covers it.
#[derive(Clone, Debug, PartialEq)]
pub struct Placement {
    pub address: u64,
    pub window: Rect,
    pub monitor: MonitorInfo,
    pub floating: bool,
    /// Its workspace is the one shown, and nothing fullscreen or special is over it.
    pub visible: bool,
    /// The focused window: compositor-driven moves (super+drag) are then polled fast.
    pub active: bool,
    /// Windows stacked above it that overlap it, biggest overlap first.
    pub occluders: Vec<Rect>,
}

/// The request socket of the Hyprland instance we run under.
#[derive(Clone, Debug)]
pub struct Hypr {
    dir: PathBuf,
}

impl Hypr {
    pub fn from_env() -> Result<Self> {
        let sig = std::env::var("HYPRLAND_INSTANCE_SIGNATURE").context("not running under Hyprland (HYPRLAND_INSTANCE_SIGNATURE unset)")?;
        let runtime = std::env::var("XDG_RUNTIME_DIR").context("XDG_RUNTIME_DIR unset")?;
        let dir = Path::new(&runtime).join("hypr").join(sig);
        if !dir.join(".socket.sock").exists() {
            bail!("no Hyprland socket in {}", dir.display());
        }
        Ok(Self { dir })
    }

    /// One request per connection, as Hyprland expects; the reply ends at EOF.
    pub fn request(&self, cmd: &str) -> Result<String> {
        let path = self.dir.join(".socket.sock");
        let mut s = UnixStream::connect(&path).with_context(|| format!("connecting to {}", path.display()))?;
        s.set_read_timeout(Some(Duration::from_secs(2)))?;
        s.write_all(cmd.as_bytes())?;
        let mut reply = String::new();
        s.read_to_string(&mut reply)?;
        Ok(reply)
    }

    fn json<T: DeserializeOwned>(&self, what: &str) -> Result<T> {
        let reply = self.request(&format!("j/{what}"))?;
        serde_json::from_str(&reply).with_context(|| format!("parsing `{what}`: {}", reply.chars().take(120).collect::<String>()))
    }

    /// Run Lua in the compositor (a Lua-config Hyprland, 0.55+).
    pub fn eval(&self, lua: &str) -> Result<()> {
        ok(self.request(&format!("/eval {lua}"))?)
    }

    /// A dispatch in the Lua form, falling back to the classic one on a hyprlang Hyprland.
    fn dispatch(&self, lua: &str, classic: &str) -> Result<()> {
        ok(self.request(&format!("dispatch {lua}"))?).or_else(|_| ok(self.request(&format!("dispatch {classic}"))?))
    }

    /// The configured screen shader's path; `""` when none.
    pub fn screen_shader(&self) -> Result<String> {
        let v: serde_json::Value = self.json("getoption decoration:screen_shader")?;
        let s = v.get("str").and_then(|s| s.as_str()).unwrap_or("");
        Ok(if s == "[[EMPTY]]" { String::new() } else { s.to_string() })
    }

    pub fn set_screen_shader(&self, path: &str) -> Result<()> {
        self.eval(&format!("hl.config({{ decoration = {{ screen_shader = {} }} }})", lua_string(path)))
            .or_else(|_| ok(self.request(&format!("keyword decoration:screen_shader {path}"))?))
    }

    /// `debug:damage_tracking`: 0 none, 1 whole monitor, 2 full (the default).
    pub fn damage_tracking(&self) -> Result<i64> {
        let v: serde_json::Value = self.json("getoption debug:damage_tracking")?;
        v.get("int").and_then(|i| i.as_i64()).context("getoption debug:damage_tracking: no int")
    }

    pub fn set_damage_tracking(&self, mode: i64) -> Result<()> {
        self.eval(&format!("hl.config({{ debug = {{ damage_tracking = {mode} }} }})"))
            .or_else(|_| ok(self.request(&format!("keyword debug:damage_tracking {mode}"))?))
    }

    /// Float our window without border, shadow, rounding or Hyprland's own blur behind it (the
    /// shader draws the glass), and let the marker layer appear without a fade, whose
    /// in-between colours would fail its checksum. The rules live until Hyprland reloads.
    pub fn install_rules(&self, width: f64, height: f64) -> Result<()> {
        self.eval(&format!(
            "hl.window_rule({{ name = \"{APP_ID}\", match = {{ class = \"^({APP_ID})$\" }}, float = true, center = true, \
             size = {{ {w}, {h} }}, no_blur = true, no_shadow = true, no_dim = true, border_size = 0, rounding = 0, decorate = false, no_anim = true }})",
            w = width.round(),
            h = height.round(),
        ))?;
        self.eval(&format!("hl.layer_rule({{ name = \"{MARKER_NAMESPACE}\", match = {{ namespace = \"^({MARKER_NAMESPACE})$\" }}, no_anim = true }})"))?;
        // The settings window floats beside the glass instead of retiling the workspace.
        let settings = crate::gui::APP_ID;
        self.eval(&format!("hl.window_rule({{ name = \"{settings}\", match = {{ class = \"^({settings})$\" }}, float = true, size = {{ 360, 720 }} }})"))
    }

    pub fn float(&self, address: u64) -> Result<()> {
        self.dispatch(
            &format!("hl.dsp.window.float({{ action = \"enable\", window = \"address:0x{address:x}\" }})"),
            &format!("setfloating address:0x{address:x}"),
        )
    }

    /// Put window `address` at `(x, y)` (global logical px).
    pub fn move_to(&self, address: u64, x: i64, y: i64) -> Result<()> {
        self.dispatch(
            &format!("hl.dsp.window.move({{ x = {x}, y = {y}, window = \"address:0x{address:x}\" }})"),
            &format!("movewindowpixel exact {x} {y},address:0x{address:x}"),
        )
    }

    pub fn resize_to(&self, address: u64, w: i64, h: i64) -> Result<()> {
        self.dispatch(
            &format!("hl.dsp.window.resize({{ x = {w}, y = {h}, window = \"address:0x{address:x}\" }})"),
            &format!("resizewindowpixel exact {w} {h},address:0x{address:x}"),
        )
    }

    pub fn monitor_scales(&self) -> Result<Vec<(i64, f64)>> {
        Ok(self.json::<Vec<Monitor>>("monitors")?.into_iter().map(|m| (m.id, m.scale)).collect())
    }

    /// Where our window (the one with our pid) is, and what covers it.
    pub fn placement(&self) -> Result<Option<Placement>> {
        let clients: Vec<Client> = self.json("clients")?;
        let monitors: Vec<Monitor> = self.json("monitors")?;
        Ok(place(&clients, &monitors, i64::from(std::process::id())))
    }

    /// Our window's rectangle, if it is the focused one: `activewindow` is the cheapest query
    /// there is (~50 µs), cheap enough to follow a compositor-driven drag at frame rate.
    pub fn active_rect(&self, address: u64) -> Option<Rect> {
        let c: Client = self.json("activewindow").ok()?;
        (parse_address(&c.address) == Some(address)).then_some(c.rect())
    }

    /// Read the event socket on a thread, calling `on_event` for every event that can move,
    /// show, hide or cover the glass, and with `true` after a config reload (which drops the
    /// rules and the screen shader).
    pub fn spawn_events(&self, on_event: impl Fn(bool) + Send + 'static) {
        let path = self.dir.join(".socket2.sock");
        std::thread::Builder::new()
            .name("hypr-events".into())
            .spawn(move || {
                let Ok(stream) = UnixStream::connect(&path) else { return };
                for line in BufReader::new(stream).lines() {
                    let Ok(line) = line else { return };
                    let name = line.split(">>").next().unwrap_or("");
                    if name == "configreloaded" {
                        on_event(true);
                    } else if matters(name) {
                        on_event(false);
                    }
                }
            })
            .expect("spawning the event reader");
    }
}

/// Events after which the glass may have moved, appeared, disappeared or been covered.
fn matters(event: &str) -> bool {
    matches!(
        event,
        "workspace"
            | "workspacev2"
            | "focusedmon"
            | "focusedmonv2"
            | "activewindow"
            | "activewindowv2"
            | "fullscreen"
            | "monitoradded"
            | "monitoraddedv2"
            | "monitorremoved"
            | "monitorremovedv2"
            | "openwindow"
            | "closewindow"
            | "movewindow"
            | "movewindowv2"
            | "changefloatingmode"
            | "activespecial"
            | "activespecialv2"
            | "pin"
    )
}

fn ok(reply: String) -> Result<()> {
    if reply.trim() == "ok" { Ok(()) } else { bail!("Hyprland: {}", reply.trim()) }
}

/// A Lua string literal.
fn lua_string(s: &str) -> String {
    let mut out = String::from("\"");
    for ch in s.chars() {
        match ch {
            '\\' => out.push_str("\\\\"),
            '"' => out.push_str("\\\""),
            '\n' => out.push_str("\\n"),
            c => out.push(c),
        }
    }
    out.push('"');
    out
}

pub fn parse_address(s: &str) -> Option<u64> {
    u64::from_str_radix(s.trim_start_matches("0x"), 16).ok()
}

// --- IPC shapes ---------------------------------------------------------------

fn yes() -> bool {
    true
}

#[derive(Deserialize, Debug, Default, Clone)]
struct WsRef {
    id: i64,
}

#[derive(Deserialize, Debug, Clone)]
#[serde(rename_all = "camelCase")]
struct Client {
    address: String,
    #[serde(default)]
    mapped: bool,
    #[serde(default)]
    hidden: bool,
    #[serde(default = "yes")]
    visible: bool,
    at: [f64; 2],
    size: [f64; 2],
    #[serde(default)]
    workspace: WsRef,
    #[serde(default)]
    floating: bool,
    #[serde(default)]
    monitor: i64,
    #[serde(default)]
    pid: i64,
    #[serde(default)]
    pinned: bool,
    #[serde(default)]
    fullscreen: i64,
    #[serde(default)]
    focus_history_id: i64,
}

impl Client {
    fn rect(&self) -> Rect {
        Rect { x: self.at[0], y: self.at[1], w: self.size[0], h: self.size[1] }
    }
}

#[derive(Deserialize, Debug)]
#[serde(rename_all = "camelCase")]
struct Monitor {
    id: i64,
    name: String,
    x: f64,
    y: f64,
    width: f64,
    height: f64,
    scale: f64,
    #[serde(default)]
    transform: i64,
    #[serde(default)]
    active_workspace: WsRef,
    #[serde(default)]
    special_workspace: WsRef,
}

/// The glass's placement from one poll's replies. Pure, for the tests.
fn place(clients: &[Client], monitors: &[Monitor], pid: i64) -> Option<Placement> {
    let (me_index, me) = clients.iter().enumerate().find(|(_, c)| c.pid == pid && c.mapped)?;
    let mon = monitors.iter().find(|m| m.id == me.monitor)?;
    // A rotated monitor swaps its mode's sides.
    let (pw, ph) = if mon.transform % 2 == 1 { (mon.height, mon.width) } else { (mon.width, mon.height) };
    let monitor = MonitorInfo { id: mon.id, name: mon.name.clone(), rect: Rect { x: mon.x, y: mon.y, w: pw / mon.scale, h: ph / mon.scale }, scale: mon.scale };
    let special = mon.special_workspace.id != 0;
    let on_shown = |c: &Client| c.monitor == mon.id && (c.pinned || c.workspace.id == mon.active_workspace.id || (special && c.workspace.id == mon.special_workspace.id));
    let me_rect = me.rect();
    // A fullscreen window, or an open special workspace we are not on, hides everything below.
    let covered = clients.iter().any(|c| c.pid != pid && c.mapped && !c.hidden && on_shown(c) && c.fullscreen != 0 && !me.pinned)
        || (special && me.workspace.id != mon.special_workspace.id && !me.pinned);
    let visible = me.mapped && !me.hidden && on_shown(me) && !covered;
    // Floating windows are drawn in the order `clients` lists them, pinned ones last: the
    // ones after us that overlap us are on top of us.
    let above = |i: usize, c: &Client| {
        c.pid != pid
            && c.mapped
            && !c.hidden
            && c.visible
            && on_shown(c)
            && (c.floating || c.pinned)
            && (c.pinned && !me.pinned || (c.pinned == me.pinned && i > me_index))
    };
    let mut occluders: Vec<Rect> = clients.iter().enumerate().filter(|(i, c)| above(*i, c)).map(|(_, c)| c.rect()).filter(|r| r.intersects(&me_rect)).collect();
    occluders.sort_by(|a, b| b.overlap_area(&me_rect).total_cmp(&a.overlap_area(&me_rect)));
    Some(Placement {
        address: parse_address(&me.address)?,
        window: me_rect,
        monitor,
        floating: me.floating,
        visible,
        active: me.focus_history_id == 0,
        occluders,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn client(addr: &str, pid: i64, at: [f64; 2], floating: bool, ws: i64) -> Client {
        Client {
            address: addr.into(),
            mapped: true,
            hidden: false,
            visible: true,
            at,
            size: [100.0, 100.0],
            workspace: WsRef { id: ws },
            floating,
            monitor: 0,
            pid,
            pinned: false,
            fullscreen: 0,
            focus_history_id: 1,
        }
    }

    fn monitor() -> Monitor {
        Monitor {
            id: 0,
            name: "DP-1".into(),
            x: 0.0,
            y: 0.0,
            width: 2560.0,
            height: 1440.0,
            scale: 4.0 / 3.0,
            transform: 0,
            active_workspace: WsRef { id: 1 },
            special_workspace: WsRef { id: 0 },
        }
    }

    #[test]
    fn windows_after_us_that_overlap_cover_us_and_ones_before_do_not() {
        let clients = vec![
            client("0xa1", 9, [50.0, 50.0], true, 1),  // floating, before us: below
            client("0xbe", 7, [0.0, 0.0], true, 1),    // us
            client("0xc1", 9, [60.0, 60.0], true, 1),  // floating, after us: above
            client("0xd1", 9, [500.0, 0.0], true, 1),  // above but elsewhere
            client("0xe1", 9, [10.0, 10.0], false, 1), // tiled: always below
        ];
        let p = place(&clients, &[monitor()], 7).unwrap();
        assert_eq!(p.occluders, vec![Rect { x: 60.0, y: 60.0, w: 100.0, h: 100.0 }]);
        assert!(p.visible);
        assert_eq!(p.monitor.rect.w.round(), 1920.0);
    }

    #[test]
    fn another_workspace_or_a_fullscreen_window_hides_the_glass() {
        let clients = vec![client("0xbe", 7, [0.0, 0.0], true, 2)];
        assert!(!place(&clients, &[monitor()], 7).unwrap().visible);
        let mut full = client("0xf1", 9, [0.0, 0.0], false, 1);
        full.fullscreen = 2;
        let clients = vec![client("0xbe", 7, [0.0, 0.0], true, 1), full];
        assert!(!place(&clients, &[monitor()], 7).unwrap().visible);
    }

    #[test]
    fn lua_strings_are_quoted() {
        assert_eq!(lua_string(r#"/a/"b"\c"#), r#""/a/\"b\"\\c""#);
    }
}
