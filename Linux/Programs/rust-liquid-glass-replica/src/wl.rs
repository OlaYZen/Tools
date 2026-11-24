//! The Wayland side: the glass's own window — fully transparent, there to float, take the
//! pointer and keyboard and be dragged — and the marker layer the screen shader reads.
//!
//! Nothing here draws the glass; Hyprland's screen shader does. Both surfaces use shm buffers
//! written by the CPU, so the app itself never touches the GPU.

use std::os::fd::{AsFd, BorrowedFd, OwnedFd};
use std::time::Duration;

use anyhow::{Context, Result, anyhow};
use rustix::event::{PollFd, PollFlags, Timespec};
use wayland_client::globals::{GlobalListContents, registry_queue_init};
use wayland_client::protocol::wl_buffer::{self, WlBuffer};
use wayland_client::protocol::wl_callback::{self, WlCallback};
use wayland_client::protocol::wl_compositor::WlCompositor;
use wayland_client::protocol::wl_keyboard::{self, WlKeyboard};
use wayland_client::protocol::wl_output::{self, WlOutput};
use wayland_client::protocol::wl_pointer::{self, WlPointer};
use wayland_client::protocol::wl_region::WlRegion;
use wayland_client::protocol::wl_registry::WlRegistry;
use wayland_client::protocol::wl_seat::{self, WlSeat};
use wayland_client::protocol::wl_shm::{self, WlShm};
use wayland_client::protocol::wl_shm_pool::WlShmPool;
use wayland_client::protocol::wl_surface::WlSurface;
use wayland_client::{Connection, Dispatch, EventQueue, Proxy as _, QueueHandle, WEnum, delegate_noop};
use wayland_protocols::wp::cursor_shape::v1::client::wp_cursor_shape_device_v1::{Shape, WpCursorShapeDeviceV1};
use wayland_protocols::wp::cursor_shape::v1::client::wp_cursor_shape_manager_v1::WpCursorShapeManagerV1;
use wayland_protocols::xdg::shell::client::xdg_surface::{self, XdgSurface};
use wayland_protocols::xdg::shell::client::xdg_toplevel::{self, XdgToplevel};
use wayland_protocols::xdg::shell::client::xdg_wm_base::{self, XdgWmBase};
use wayland_protocols_wlr::layer_shell::v1::client::zwlr_layer_shell_v1::{Layer, ZwlrLayerShellV1};
use wayland_protocols_wlr::layer_shell::v1::client::zwlr_layer_surface_v1::{self, Anchor, KeyboardInteractivity, ZwlrLayerSurfaceV1};

use crate::hypr::MARKER_NAMESPACE;
use crate::marker::{BLOCK, BLOCKS};

const BTN_LEFT: u32 = 0x110;
const BTN_RIGHT: u32 = 0x111;

/// What happened to the window, in surface-local logical px.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Input {
    Enter { x: f64, y: f64 },
    Motion { x: f64, y: f64 },
    Leave,
    Press { x: f64, y: f64 },
    Release,
    /// The right button, pressed.
    Menu,
    /// An evdev key code, pressed.
    Key(u32),
    /// The window's new size.
    Configure { w: u32, h: u32 },
    Close,
}

/// An shm buffer, mapped for as long as it lives.
struct ShmBuffer {
    _fd: OwnedFd,
    pool: WlShmPool,
    buffer: WlBuffer,
    width: u32,
    height: u32,
    map: std::ptr::NonNull<u8>,
    len: usize,
    /// Attached and not yet released by the compositor.
    busy: bool,
}

#[derive(Clone, Copy, Debug)]
enum BufferId {
    Window,
    Marker(usize),
}

impl ShmBuffer {
    fn new(shm: &WlShm, qh: &QueueHandle<State>, width: u32, height: u32, id: BufferId) -> Result<Self> {
        let stride = width * 4;
        let len = (stride * height) as usize;
        let fd = rustix::fs::memfd_create("liquid-glass", rustix::fs::MemfdFlags::CLOEXEC).context("memfd_create")?;
        rustix::fs::ftruncate(&fd, len as u64).context("ftruncate")?;
        // SAFETY: a new shared mapping of the memfd we just sized to `len`; unmapped on drop.
        let ptr = unsafe {
            rustix::mm::mmap(std::ptr::null_mut(), len, rustix::mm::ProtFlags::READ | rustix::mm::ProtFlags::WRITE, rustix::mm::MapFlags::SHARED, &fd, 0)
        }
        .context("mmap")?;
        let map = std::ptr::NonNull::new(ptr.cast::<u8>()).ok_or_else(|| anyhow!("mmap returned null"))?;
        let pool = shm.create_pool(fd.as_fd(), len as i32, qh, ());
        let buffer = pool.create_buffer(0, width as i32, height as i32, stride as i32, wl_shm::Format::Argb8888, qh, id);
        // memfd pages start zeroed: transparent until written.
        Ok(Self { _fd: fd, pool, buffer, width, height, map, len, busy: false })
    }

    fn write(&mut self, pixels: &[u8]) {
        // SAFETY: `map` holds `len` writable bytes; the compositor reads the buffer only while
        // it is attached (`busy`), and callers write only free buffers.
        let dst = unsafe { std::slice::from_raw_parts_mut(self.map.as_ptr(), self.len) };
        let n = dst.len().min(pixels.len());
        dst[..n].copy_from_slice(&pixels[..n]);
    }
}

impl Drop for ShmBuffer {
    fn drop(&mut self) {
        self.buffer.destroy();
        self.pool.destroy();
        // SAFETY: the mapping made in `new`, unmapped once.
        let _ = unsafe { rustix::mm::munmap(self.map.as_ptr().cast(), self.len) };
    }
}

/// The marker strip's layer surface on one output.
struct Marker {
    surface: WlSurface,
    layer: ZwlrLayerSurfaceV1,
    output: String,
    configured: bool,
    buffers: [Option<ShmBuffer>; 2],
    /// A frame callback is out: the next commit waits for it, so the strip changes at most once
    /// per compositor frame, whatever the input rate.
    frame_pending: bool,
    pending: Option<Vec<u8>>,
    shown: Option<Vec<u8>>,
}

impl Drop for Marker {
    fn drop(&mut self) {
        self.buffers = [None, None];
        self.layer.destroy();
        self.surface.destroy();
    }
}

pub struct State {
    compositor: WlCompositor,
    shm: WlShm,
    layer_shell: ZwlrLayerShellV1,
    cursor_shape: Option<WpCursorShapeManagerV1>,
    outputs: Vec<(WlOutput, Option<String>)>,
    surface: WlSurface,
    _xdg_surface: XdgSurface,
    _toplevel: XdgToplevel,
    size: (u32, u32),
    pending_size: Option<(u32, u32)>,
    window_buffer: Option<ShmBuffer>,
    pointer: Option<WlPointer>,
    cursor_device: Option<WpCursorShapeDeviceV1>,
    enter_serial: u32,
    /// The pointer's last surface-local position: a button event carries none.
    pointer_pos: (f64, f64),
    keyboard: Option<WlKeyboard>,
    marker: Option<Marker>,
    events: Vec<Input>,
}

pub struct Wl {
    conn: Connection,
    queue: EventQueue<State>,
    state: State,
}

impl Wl {
    pub fn connect(app_id: &str, title: &str, size: (u32, u32), min: (u32, u32)) -> Result<Self> {
        let conn = Connection::connect_to_env().context("connecting to Wayland")?;
        let (globals, mut queue) = registry_queue_init::<State>(&conn).context("listing globals")?;
        let qh = queue.handle();
        let missing = |what: &'static str| move |e| anyhow!("compositor lacks {what}: {e}");
        let compositor: WlCompositor = globals.bind(&qh, 4..=6, ()).map_err(missing("wl_compositor"))?;
        let shm: WlShm = globals.bind(&qh, 1..=1, ()).map_err(missing("wl_shm"))?;
        let wm: XdgWmBase = globals.bind(&qh, 1..=6, ()).map_err(missing("xdg_wm_base"))?;
        let layer_shell: ZwlrLayerShellV1 = globals.bind(&qh, 1..=4, ()).map_err(missing("zwlr_layer_shell_v1"))?;
        let cursor_shape: Option<WpCursorShapeManagerV1> = globals.bind(&qh, 1..=1, ()).ok();
        let _seat: WlSeat = globals.bind(&qh, 1..=7, ()).map_err(missing("wl_seat"))?;
        let mut outputs = Vec::new();
        globals.contents().with_list(|list| {
            for g in list.iter().filter(|g| g.interface == WlOutput::interface().name) {
                let output: WlOutput = globals.registry().bind(g.name, g.version.min(4), &qh, outputs.len());
                outputs.push((output, None));
            }
        });

        let surface = compositor.create_surface(&qh, ());
        let xdg_surface = wm.get_xdg_surface(&surface, &qh, ());
        let toplevel = xdg_surface.get_toplevel(&qh, ());
        toplevel.set_app_id(app_id.into());
        toplevel.set_title(title.into());
        toplevel.set_min_size(min.0 as i32, min.1 as i32);
        surface.commit();

        let mut state = State {
            compositor,
            shm,
            layer_shell,
            cursor_shape,
            outputs,
            surface,
            _xdg_surface: xdg_surface,
            _toplevel: toplevel,
            size,
            pending_size: None,
            window_buffer: None,
            pointer: None,
            cursor_device: None,
            enter_serial: 0,
            pointer_pos: (0.0, 0.0),
            keyboard: None,
            marker: None,
            events: Vec::new(),
        };
        // Output names, the seat's devices and the first configure.
        queue.roundtrip(&mut state).context("Wayland roundtrip")?;
        queue.roundtrip(&mut state).context("Wayland roundtrip")?;
        Ok(Self { conn, queue, state })
    }

    /// Wait for Wayland events, or `wake` becoming readable, or `timeout`.
    pub fn dispatch(&mut self, timeout: Duration, wake: BorrowedFd<'_>) -> Result<()> {
        self.queue.dispatch_pending(&mut self.state).context("dispatching")?;
        self.conn.flush().context("flushing")?;
        if self.state.events.is_empty()
            && let Some(guard) = self.queue.prepare_read()
        {
            let timeout = Timespec::try_from(timeout).map_err(|e| anyhow!("{e}"))?;
            let mut fds = [PollFd::from_borrowed_fd(guard.connection_fd(), PollFlags::IN), PollFd::from_borrowed_fd(wake, PollFlags::IN)];
            match rustix::event::poll(&mut fds, Some(&timeout)) {
                Ok(_) | Err(rustix::io::Errno::INTR) => {}
                Err(e) => return Err(anyhow!("poll: {e}")),
            }
            if fds[0].revents().contains(PollFlags::IN) {
                match guard.read() {
                    Ok(_) => {}
                    Err(wayland_client::backend::WaylandError::Io(e)) if e.kind() == std::io::ErrorKind::WouldBlock => {}
                    Err(e) => return Err(anyhow!("reading Wayland events: {e}")),
                }
            }
        }
        self.queue.dispatch_pending(&mut self.state).context("dispatching")?;
        let qh = self.queue.handle();
        self.state.commit_marker(&qh);
        self.conn.flush().context("flushing")?;
        Ok(())
    }

    pub fn take_events(&mut self) -> Vec<Input> {
        std::mem::take(&mut self.state.events)
    }

    /// Logical size of the window.
    pub fn size(&self) -> (u32, u32) {
        self.state.size
    }

    pub fn set_cursor(&self, shape: Shape) {
        if let Some(device) = &self.state.cursor_device {
            device.set_shape(self.state.enter_serial, shape);
        }
    }

    /// Show `pixels` (from [`crate::marker::Marker::pixels`]) as the strip on output `output`.
    pub fn set_marker(&mut self, output: &str, pixels: Vec<u8>) {
        let qh = self.queue.handle();
        if self.state.marker.as_ref().is_some_and(|m| m.output != output) {
            self.state.marker = None;
        }
        if self.state.marker.is_none() {
            let Some((wl_output, _)) = self.state.outputs.iter().find(|(_, n)| n.as_deref() == Some(output)) else { return };
            let surface = self.state.compositor.create_surface(&qh, ());
            // Clicks go through the strip.
            let region: WlRegion = self.state.compositor.create_region(&qh, ());
            surface.set_input_region(Some(&region));
            region.destroy();
            let layer = self.state.layer_shell.get_layer_surface(&surface, Some(wl_output), Layer::Overlay, MARKER_NAMESPACE.into(), &qh, ());
            layer.set_size(BLOCKS as u32 * BLOCK, BLOCK);
            layer.set_anchor(Anchor::Top | Anchor::Left);
            // At the very corner, whatever bars reserve.
            layer.set_exclusive_zone(-1);
            layer.set_keyboard_interactivity(KeyboardInteractivity::None);
            surface.commit();
            self.state.marker = Some(Marker {
                surface,
                layer,
                output: output.to_string(),
                configured: false,
                buffers: [None, None],
                frame_pending: false,
                pending: None,
                shown: None,
            });
        }
        if let Some(m) = &mut self.state.marker {
            m.pending = Some(pixels);
        }
        self.state.commit_marker(&qh);
        let _ = self.conn.flush();
    }

    /// Take the strip away: the shader then leaves every pixel as it is.
    pub fn hide_marker(&mut self) {
        if self.state.marker.take().is_some() {
            let _ = self.conn.flush();
        }
    }
}

impl State {
    /// Commit the pending strip, unless the last one has not been shown yet.
    fn commit_marker(&mut self, qh: &QueueHandle<State>) {
        let Some(m) = &mut self.marker else { return };
        if !m.configured || m.frame_pending || m.pending.is_none() || m.pending == m.shown {
            return;
        }
        let (w, h) = (BLOCKS as u32 * BLOCK, BLOCK);
        let Some(slot) = (0..2).find(|&i| m.buffers[i].as_ref().is_none_or(|b| !b.busy)) else { return };
        if m.buffers[slot].is_none() {
            match ShmBuffer::new(&self.shm, qh, w, h, BufferId::Marker(slot)) {
                Ok(b) => m.buffers[slot] = Some(b),
                Err(e) => {
                    eprintln!("liquid-glass: marker buffer: {e:#}");
                    return;
                }
            }
        }
        let Some(buffer) = &mut m.buffers[slot] else { return };
        let Some(pixels) = m.pending.take() else { return };
        buffer.write(&pixels);
        buffer.busy = true;
        m.surface.attach(Some(&buffer.buffer), 0, 0);
        m.surface.damage_buffer(0, 0, w as i32, h as i32);
        m.surface.frame(qh, ());
        m.frame_pending = true;
        m.surface.commit();
        m.shown = Some(pixels);
    }

    /// (Re)attach a transparent buffer the window's size.
    fn present_window(&mut self, qh: &QueueHandle<State>) {
        let (w, h) = self.size;
        if self.window_buffer.as_ref().is_none_or(|b| (b.width, b.height) != (w, h)) {
            match ShmBuffer::new(&self.shm, qh, w.max(1), h.max(1), BufferId::Window) {
                Ok(b) => self.window_buffer = Some(b),
                Err(e) => {
                    eprintln!("liquid-glass: window buffer: {e:#}");
                    return;
                }
            }
        }
        let Some(b) = &mut self.window_buffer else { return };
        self.surface.attach(Some(&b.buffer), 0, 0);
        self.surface.damage_buffer(0, 0, w as i32, h as i32);
        b.busy = true;
        self.surface.commit();
    }
}

// --- events ------------------------------------------------------------------

impl Dispatch<WlRegistry, GlobalListContents> for State {
    fn event(_: &mut Self, _: &WlRegistry, _: wayland_client::protocol::wl_registry::Event, _: &GlobalListContents, _: &Connection, _: &QueueHandle<Self>) {}
}

impl Dispatch<WlOutput, usize> for State {
    fn event(state: &mut Self, _: &WlOutput, event: wl_output::Event, index: &usize, _: &Connection, _: &QueueHandle<Self>) {
        if let wl_output::Event::Name { name } = event
            && let Some(o) = state.outputs.get_mut(*index)
        {
            o.1 = Some(name);
        }
    }
}

impl Dispatch<WlBuffer, BufferId> for State {
    fn event(state: &mut Self, _: &WlBuffer, event: wl_buffer::Event, id: &BufferId, _: &Connection, _: &QueueHandle<Self>) {
        if let wl_buffer::Event::Release = event {
            let buffer = match id {
                BufferId::Window => state.window_buffer.as_mut(),
                BufferId::Marker(i) => state.marker.as_mut().and_then(|m| m.buffers[*i].as_mut()),
            };
            if let Some(b) = buffer {
                b.busy = false;
            }
        }
    }
}

impl Dispatch<WlCallback, ()> for State {
    fn event(state: &mut Self, _: &WlCallback, event: wl_callback::Event, _: &(), _: &Connection, qh: &QueueHandle<Self>) {
        if let wl_callback::Event::Done { .. } = event
            && let Some(m) = &mut state.marker
        {
            m.frame_pending = false;
            state.commit_marker(qh);
        }
    }
}

impl Dispatch<XdgWmBase, ()> for State {
    fn event(_: &mut Self, wm: &XdgWmBase, event: xdg_wm_base::Event, _: &(), _: &Connection, _: &QueueHandle<Self>) {
        if let xdg_wm_base::Event::Ping { serial } = event {
            wm.pong(serial);
        }
    }
}

impl Dispatch<XdgSurface, ()> for State {
    fn event(state: &mut Self, xdg: &XdgSurface, event: xdg_surface::Event, _: &(), _: &Connection, qh: &QueueHandle<Self>) {
        if let xdg_surface::Event::Configure { serial } = event {
            xdg.ack_configure(serial);
            if let Some(size) = state.pending_size.take() {
                state.size = size;
            }
            state.events.push(Input::Configure { w: state.size.0, h: state.size.1 });
            state.present_window(qh);
        }
    }
}

impl Dispatch<XdgToplevel, ()> for State {
    fn event(state: &mut Self, _: &XdgToplevel, event: xdg_toplevel::Event, _: &(), _: &Connection, _: &QueueHandle<Self>) {
        match event {
            xdg_toplevel::Event::Configure { width, height, .. } if width > 0 && height > 0 => {
                state.pending_size = Some((width as u32, height as u32));
            }
            xdg_toplevel::Event::Close => state.events.push(Input::Close),
            _ => {}
        }
    }
}

impl Dispatch<ZwlrLayerSurfaceV1, ()> for State {
    fn event(state: &mut Self, layer: &ZwlrLayerSurfaceV1, event: zwlr_layer_surface_v1::Event, _: &(), _: &Connection, qh: &QueueHandle<Self>) {
        match event {
            zwlr_layer_surface_v1::Event::Configure { serial, .. } => {
                layer.ack_configure(serial);
                if let Some(m) = &mut state.marker {
                    m.configured = true;
                }
                state.commit_marker(qh);
            }
            zwlr_layer_surface_v1::Event::Closed => state.marker = None,
            _ => {}
        }
    }
}

impl Dispatch<WlSeat, ()> for State {
    fn event(state: &mut Self, seat: &WlSeat, event: wl_seat::Event, _: &(), _: &Connection, qh: &QueueHandle<Self>) {
        if let wl_seat::Event::Capabilities { capabilities: WEnum::Value(caps) } = event {
            if caps.contains(wl_seat::Capability::Pointer) && state.pointer.is_none() {
                let pointer = seat.get_pointer(qh, ());
                state.cursor_device = state.cursor_shape.as_ref().map(|m| m.get_pointer(&pointer, qh, ()));
                state.pointer = Some(pointer);
            }
            if caps.contains(wl_seat::Capability::Keyboard) && state.keyboard.is_none() {
                state.keyboard = Some(seat.get_keyboard(qh, ()));
            }
        }
    }
}

impl Dispatch<WlPointer, ()> for State {
    fn event(state: &mut Self, _: &WlPointer, event: wl_pointer::Event, _: &(), _: &Connection, _: &QueueHandle<Self>) {
        match event {
            wl_pointer::Event::Enter { serial, surface, surface_x, surface_y } if surface == state.surface => {
                state.enter_serial = serial;
                state.pointer_pos = (surface_x, surface_y);
                state.events.push(Input::Enter { x: surface_x, y: surface_y });
            }
            wl_pointer::Event::Leave { surface, .. } if surface == state.surface => state.events.push(Input::Leave),
            wl_pointer::Event::Motion { surface_x, surface_y, .. } => {
                state.pointer_pos = (surface_x, surface_y);
                state.events.push(Input::Motion { x: surface_x, y: surface_y });
            }
            wl_pointer::Event::Button { button: BTN_RIGHT, state: WEnum::Value(wl_pointer::ButtonState::Pressed), .. } => state.events.push(Input::Menu),
            wl_pointer::Event::Button { button: BTN_LEFT, state: WEnum::Value(s), .. } => {
                let (x, y) = state.pointer_pos;
                state.events.push(if s == wl_pointer::ButtonState::Pressed { Input::Press { x, y } } else { Input::Release });
            }
            _ => {}
        }
    }
}

impl Dispatch<WlKeyboard, ()> for State {
    fn event(state: &mut Self, _: &WlKeyboard, event: wl_keyboard::Event, _: &(), _: &Connection, _: &QueueHandle<Self>) {
        if let wl_keyboard::Event::Key { key, state: WEnum::Value(wl_keyboard::KeyState::Pressed), .. } = event {
            state.events.push(Input::Key(key));
        }
    }
}

delegate_noop!(State: WlCompositor);
delegate_noop!(State: ignore WlShm);
delegate_noop!(State: WlShmPool);
delegate_noop!(State: WlRegion);
delegate_noop!(State: ignore WlSurface);
delegate_noop!(State: ZwlrLayerShellV1);
delegate_noop!(State: WpCursorShapeManagerV1);
delegate_noop!(State: WpCursorShapeDeviceV1);
