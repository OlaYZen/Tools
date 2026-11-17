//! The program's state and what each key and click does to it.

use std::collections::HashSet;
use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::sync::Arc;
use std::sync::atomic::Ordering;
use std::thread::JoinHandle;
use std::time::{Duration, Instant};

use ratatui::crossterm::event::{self, Event, KeyCode, KeyEvent, KeyEventKind, KeyModifiers, MouseButton,
    MouseEvent, MouseEventKind};
use ratatui::layout::Rect;
use ratatui::widgets::TableState;

use crate::scan::{self, Kind, Measure, NONE, Options, Progress, Tree};
use crate::treemap::Pixmap;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Focus {
    Tree,
    Types,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Overlay {
    Help,
    Notes,
}

pub struct Scanning {
    pub progress: Arc<Progress>,
    pub started: Instant,
    handle: JoinHandle<std::io::Result<Tree>>,
}

/// What the cached treemap was drawn for; any change redraws it.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct MapKey {
    pub w: usize,
    pub h: usize,
    pub zoom: u32,
    pub measure: Measure,
    pub highlight: Option<u32>,
}

pub struct App {
    pub path: PathBuf,
    pub opts: Options,
    pub tree: Option<Tree>,
    pub scanning: Option<Scanning>,
    pub scan_time: Duration,
    pub failure: Option<String>,
    pub expanded: HashSet<u32>,
    /// The visible tree rows: node and depth.
    pub rows: Vec<(u32, u16)>,
    pub tree_state: TableState,
    pub ext_state: TableState,
    pub focus: Focus,
    pub show_map: bool,
    pub zoom: u32,
    pub overlay: Option<Overlay>,
    pub overlay_scroll: u16,
    pub map: Option<(MapKey, Pixmap)>,
    pub message: Option<String>,
    pub quit: bool,
    // Where the last frame put each part, for the mouse.
    pub tree_area: Rect,
    pub ext_area: Rect,
    pub map_area: Rect,
}

impl App {
    pub fn new(path: PathBuf, opts: Options) -> App {
        let mut app = App {
            path, opts, tree: None, scanning: None, scan_time: Duration::ZERO, failure: None,
            expanded: HashSet::new(), rows: Vec::new(), tree_state: TableState::default(),
            ext_state: TableState::default(), focus: Focus::Tree, show_map: true, zoom: 0,
            overlay: None, overlay_scroll: 0, map: None, message: None, quit: false,
            tree_area: Rect::default(), ext_area: Rect::default(), map_area: Rect::default(),
        };
        app.start_scan();
        app
    }

    pub fn start_scan(&mut self) {
        let progress = Arc::new(Progress::default());
        let (p, path, opts) = (progress.clone(), self.path.clone(), self.opts);
        let handle = std::thread::spawn(move || scan::scan(&path, opts, &p));
        self.scanning = Some(Scanning { progress, started: Instant::now(), handle });
        self.tree = None;
        self.failure = None;
        self.map = None;
    }

    /// Takes the finished scan's result, if it has finished.
    pub fn poll_scan(&mut self) {
        let done = self.scanning.as_ref().is_some_and(|s| s.handle.is_finished());
        if !done {
            return;
        }
        let s = self.scanning.take().expect("checked above");
        self.scan_time = s.started.elapsed();
        match s.handle.join() {
            Ok(Ok(tree)) => {
                self.zoom = tree.root();
                self.expanded = HashSet::from([tree.root()]);
                self.tree = Some(tree);
                self.tree_state = TableState::default().with_selected(Some(0));
                self.ext_state = TableState::default().with_selected(Some(0));
                self.rebuild_rows();
            }
            Ok(Err(e)) => self.failure = Some(format!("Cannot scan {}: {e}", self.path.display())),
            Err(_) => self.failure = Some("The scan stopped unexpectedly.".into()),
        }
    }

    pub fn rebuild_rows(&mut self) {
        let Some(tree) = &self.tree else { return };
        let keep = self.selected();
        self.rows.clear();
        let mut stack = vec![(tree.root(), 0u16)];
        while let Some((id, depth)) = stack.pop() {
            self.rows.push((id, depth));
            if self.expanded.contains(&id) {
                for &c in tree.node(id).children.iter().rev() {
                    stack.push((c, depth + 1));
                }
            }
        }
        if let Some(id) = keep {
            self.select_node(id);
        }
    }

    pub fn selected(&self) -> Option<u32> {
        self.tree_state.selected().and_then(|i| self.rows.get(i)).map(|r| r.0)
    }

    fn select_node(&mut self, id: u32) {
        if let Some(i) = self.rows.iter().position(|r| r.0 == id) {
            self.tree_state.select(Some(i));
        }
    }

    /// Opens every folder above `id` and selects it.
    pub fn reveal(&mut self, id: u32) {
        let Some(tree) = &self.tree else { return };
        self.expanded.extend(tree.ancestors(id));
        self.rebuild_rows();
        self.select_node(id);
    }

    pub fn highlight(&self) -> Option<u32> {
        (self.focus == Focus::Types).then(|| self.ext_state.selected().map(|i| i as u32)).flatten()
    }

    fn move_in(state: &mut TableState, len: usize, delta: isize) {
        if len == 0 {
            return;
        }
        let cur = state.selected().unwrap_or(0) as isize;
        state.select(Some((cur + delta).clamp(0, len as isize - 1) as usize));
    }

    fn page(&self) -> isize {
        let area = if self.focus == Focus::Tree { self.tree_area } else { self.ext_area };
        (area.height.saturating_sub(3)).max(1) as isize
    }

    pub fn wait_event(&mut self) -> std::io::Result<()> {
        let timeout = if self.scanning.is_some() { 100 } else { 500 };
        if event::poll(Duration::from_millis(timeout))? {
            match event::read()? {
                Event::Key(k) if k.kind != KeyEventKind::Release => self.key(k),
                Event::Mouse(m) => self.mouse(m),
                _ => {}
            }
        }
        self.poll_scan();
        Ok(())
    }

    fn key(&mut self, k: KeyEvent) {
        self.message = None;
        if k.code == KeyCode::Char('c') && k.modifiers.contains(KeyModifiers::CONTROL) {
            self.quit = true;
            return;
        }
        if let Some(o) = self.overlay {
            match k.code {
                KeyCode::Esc | KeyCode::Char('q') => self.overlay = None,
                KeyCode::Char('?') if o == Overlay::Help => self.overlay = None,
                KeyCode::Char('c') if o == Overlay::Notes => self.overlay = None,
                KeyCode::Down | KeyCode::Char('j') => self.overlay_scroll = self.overlay_scroll.saturating_add(1),
                KeyCode::Up | KeyCode::Char('k') => self.overlay_scroll = self.overlay_scroll.saturating_sub(1),
                KeyCode::PageDown => self.overlay_scroll = self.overlay_scroll.saturating_add(10),
                KeyCode::PageUp => self.overlay_scroll = self.overlay_scroll.saturating_sub(10),
                KeyCode::Home => self.overlay_scroll = 0,
                _ => {}
            }
            return;
        }
        match k.code {
            KeyCode::Char('q') | KeyCode::Esc => self.quit = true,
            KeyCode::Char('?') => self.open_overlay(Overlay::Help),
            KeyCode::Char('c') => self.open_overlay(Overlay::Notes),
            _ if self.scanning.is_some() || self.tree.is_none() => {
                if k.code == KeyCode::Char('r') && self.scanning.is_none() {
                    self.start_scan();
                }
            }
            KeyCode::Tab | KeyCode::BackTab => {
                self.focus = if self.focus == Focus::Tree { Focus::Types } else { Focus::Tree };
            }
            KeyCode::Char('t') => self.show_map = !self.show_map,
            KeyCode::Char('a') => self.toggle_measure(),
            KeyCode::Char('r') => self.start_scan(),
            KeyCode::Char('o') => self.open_selected(),
            KeyCode::Char('z') => self.zoom_selected(),
            KeyCode::Char('Z') => self.zoom = 0,
            code => match self.focus {
                Focus::Tree => self.tree_key(code),
                Focus::Types => self.types_key(code),
            },
        }
    }

    fn open_overlay(&mut self, o: Overlay) {
        self.overlay = Some(o);
        self.overlay_scroll = 0;
    }

    fn list_motion(&self, code: KeyCode, len: usize) -> Option<isize> {
        Some(match code {
            KeyCode::Up | KeyCode::Char('k') => -1,
            KeyCode::Down | KeyCode::Char('j') => 1,
            KeyCode::PageUp => -self.page(),
            KeyCode::PageDown => self.page(),
            KeyCode::Home | KeyCode::Char('g') => -(len as isize),
            KeyCode::End | KeyCode::Char('G') => len as isize,
            _ => return None,
        })
    }

    fn tree_key(&mut self, code: KeyCode) {
        if let Some(d) = self.list_motion(code, self.rows.len()) {
            Self::move_in(&mut self.tree_state, self.rows.len(), d);
            return;
        }
        let (Some(tree), Some(id)) = (&self.tree, self.selected()) else { return };
        let n = tree.node(id);
        let openable = n.kind == Kind::Dir && !n.children.is_empty();
        match code {
            KeyCode::Right | KeyCode::Enter | KeyCode::Char('l') => {
                if openable && !self.expanded.contains(&id) {
                    self.expanded.insert(id);
                    self.rebuild_rows();
                } else if openable {
                    Self::move_in(&mut self.tree_state, self.rows.len(), 1);
                }
            }
            KeyCode::Left | KeyCode::Char('h') => {
                if self.expanded.contains(&id) && id != tree.root() {
                    self.expanded.remove(&id);
                    self.rebuild_rows();
                } else if n.parent != NONE {
                    let p = n.parent;
                    self.select_node(p);
                }
            }
            _ => {}
        }
    }

    fn types_key(&mut self, code: KeyCode) {
        let len = self.tree.as_ref().map_or(0, |t| t.exts.len());
        if let Some(d) = self.list_motion(code, len) {
            Self::move_in(&mut self.ext_state, len, d);
        }
    }

    fn toggle_measure(&mut self) {
        let Some(tree) = &mut self.tree else { return };
        let ext = self.ext_state.selected().map(|i| tree.exts[i].name.clone());
        let m = if tree.measure == Measure::Allocated { Measure::Apparent } else { Measure::Allocated };
        tree.sort(m);
        if let Some(name) = ext {
            let i = tree.exts.iter().position(|e| e.name == name);
            self.ext_state.select(i);
        }
        self.rebuild_rows();
    }

    fn zoom_selected(&mut self) {
        let (Some(tree), Some(id)) = (&self.tree, self.selected()) else { return };
        let n = tree.node(id);
        self.zoom = if n.kind == Kind::Dir { id } else if n.parent != NONE { n.parent } else { id };
    }

    fn open_selected(&mut self) {
        let (Some(tree), Some(id)) = (&self.tree, self.selected()) else { return };
        let n = tree.node(id);
        let dir = if n.kind == Kind::Dir { id } else { n.parent };
        let path = tree.path(if dir == NONE { id } else { dir });
        let spawned = Command::new("xdg-open").arg(&path)
            .stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null()).spawn();
        self.message = Some(match spawned {
            Ok(mut child) => {
                // Reap it, so it does not linger as a zombie until diskmap exits.
                std::thread::spawn(move || child.wait());
                format!("Opened {}", path.display())
            }
            Err(e) => format!("Cannot run xdg-open: {e}"),
        });
    }

    fn mouse(&mut self, m: MouseEvent) {
        if self.overlay.is_some() || self.tree.is_none() {
            return;
        }
        let inside = |r: Rect| m.column >= r.x && m.column < r.x + r.width && m.row >= r.y && m.row < r.y + r.height;
        match m.kind {
            MouseEventKind::Down(MouseButton::Left) => {
                if self.show_map && inside(self.map_area) {
                    let (x, y) = ((m.column - self.map_area.x) as usize, (m.row - self.map_area.y) as usize * 2);
                    let hit = self.map.as_ref().map_or(NONE, |(_, p)| p.owner_at(x, y));
                    if hit != NONE {
                        self.focus = Focus::Tree;
                        self.reveal(hit);
                    }
                } else if inside(self.tree_area) {
                    self.focus = Focus::Tree;
                    if let Some(i) = Self::row_at(&self.tree_state, self.tree_area, m.row)
                        && i < self.rows.len()
                    {
                        // A click on the selected row opens or closes it.
                        if self.tree_state.selected() == Some(i) {
                            let open = self.expanded.contains(&self.rows[i].0);
                            self.tree_key(if open { KeyCode::Left } else { KeyCode::Right });
                        } else {
                            self.tree_state.select(Some(i));
                        }
                    }
                } else if inside(self.ext_area) {
                    self.focus = Focus::Types;
                    let len = self.tree.as_ref().map_or(0, |t| t.exts.len());
                    if let Some(i) = Self::row_at(&self.ext_state, self.ext_area, m.row).filter(|&i| i < len) {
                        self.ext_state.select(Some(i));
                    }
                }
            }
            MouseEventKind::ScrollDown | MouseEventKind::ScrollUp => {
                let d = if m.kind == MouseEventKind::ScrollDown { 3 } else { -3 };
                if inside(self.tree_area) {
                    Self::move_in(&mut self.tree_state, self.rows.len(), d);
                } else if inside(self.ext_area) {
                    let len = self.tree.as_ref().map_or(0, |t| t.exts.len());
                    Self::move_in(&mut self.ext_state, len, d);
                }
            }
            _ => {}
        }
    }

    /// The list row under screen row `y`: past the top border and the header.
    fn row_at(state: &TableState, area: Rect, y: u16) -> Option<usize> {
        let first = area.y + 2;
        (y >= first && y < area.y + area.height.saturating_sub(1)).then(|| state.offset() + (y - first) as usize)
    }

    pub fn cancel_scan(&mut self) {
        if let Some(s) = self.scanning.take() {
            s.progress.cancel.store(true, Ordering::Relaxed);
            let _ = s.handle.join();
        }
    }
}
