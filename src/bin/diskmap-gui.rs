//! diskmap's window: the same scan and treemap as the terminal program, laid out like
//! WinDirStat with the tree on the left, the file types on the right and the treemap below.

use std::collections::HashSet;
use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::sync::Arc;
use std::sync::atomic::Ordering;
use std::thread::JoinHandle;
use std::time::{Duration, Instant};

use eframe::egui::{self, Align, Color32, CornerRadius, Key, Pos2, Rect, RichText, Sense, Stroke, StrokeKind,
    TextureHandle, TextureOptions, Vec2};
use egui_extras::{Column, TableBuilder};

use diskmap::changelog;
use diskmap::disks::{self, Disk};
use diskmap::fmt::{count, size};
use diskmap::scan::{self, Kind, Measure, NONE, Options, Progress, Tree};
use diskmap::treemap::{self, Pixmap};

const ACCENT: Color32 = Color32::from_rgb(110, 170, 255);
const ROW: f32 = 20.0;

const USAGE: &str = "\
Usage: diskmap-gui [OPTIONS] [PATH]

Opens diskmap's window. With PATH it scans that folder at once; without, it
offers the disks to choose from.

Options:
  -x, --cross-filesystems  Also scan other filesystems mounted below PATH
  -h, --help               Print this help
  -V, --version            Print the version";

fn main() -> std::process::ExitCode {
    let mut path = None;
    let mut opts = Options { cross_filesystems: false };
    for arg in std::env::args_os().skip(1) {
        match arg.to_str() {
            Some("-h" | "--help") => {
                println!("{USAGE}");
                return std::process::ExitCode::SUCCESS;
            }
            Some("-V" | "--version") => {
                println!("diskmap-gui {}", env!("CARGO_PKG_VERSION"));
                return std::process::ExitCode::SUCCESS;
            }
            Some("-x" | "--cross-filesystems") => opts.cross_filesystems = true,
            Some(s) if s.starts_with('-') && s.len() > 1 => {
                eprintln!("diskmap-gui: unknown option {s}\n\n{USAGE}");
                return std::process::ExitCode::from(2);
            }
            _ => path = Some(PathBuf::from(arg)),
        }
    }
    let native = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default().with_title("diskmap").with_app_id("diskmap")
            .with_inner_size([1280.0, 820.0]).with_min_inner_size([640.0, 420.0]),
        ..Default::default()
    };
    let result = eframe::run_native("diskmap", native, Box::new(move |_cc| {
        let mut gui = Gui::new(opts);
        if let Some(p) = path {
            gui.start_scan(p);
        }
        Ok(Box::new(gui))
    }));
    match result {
        Ok(()) => std::process::ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("diskmap-gui: {e}");
            std::process::ExitCode::FAILURE
        }
    }
}

struct Scanning {
    path: PathBuf,
    progress: Arc<Progress>,
    started: Instant,
    handle: JoinHandle<std::io::Result<Tree>>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct MapKey {
    w: usize,
    h: usize,
    zoom: u32,
    measure: Measure,
    highlight: Option<u32>,
}

struct Gui {
    opts: Options,
    path_input: String,
    disks: Vec<Disk>,
    tree: Option<Tree>,
    scanning: Option<Scanning>,
    scan_time: Duration,
    failure: Option<String>,
    expanded: HashSet<u32>,
    rows: Vec<(u32, u16)>,
    selected: Option<u32>,
    scroll_to: Option<usize>,
    zoom: u32,
    highlight: Option<u32>,
    show_map: bool,
    map: Option<(MapKey, Pixmap, TextureHandle)>,
    show_notes: bool,
    message: Option<String>,
}

impl Gui {
    fn new(opts: Options) -> Gui {
        let home = std::env::var_os("HOME").map(PathBuf::from).unwrap_or_else(|| PathBuf::from("/"));
        Gui {
            opts, path_input: home.display().to_string(), disks: disks::list(), tree: None, scanning: None,
            scan_time: Duration::ZERO, failure: None, expanded: HashSet::new(), rows: Vec::new(), selected: None,
            scroll_to: None, zoom: 0, highlight: None, show_map: true, map: None, show_notes: false, message: None,
        }
    }

    fn start_scan(&mut self, path: PathBuf) {
        let path = match std::fs::canonicalize(&path) {
            Ok(p) => p,
            Err(e) => {
                self.failure = Some(format!("Cannot scan {}: {e}", path.display()));
                return;
            }
        };
        self.cancel_scan();
        let progress = Arc::new(Progress::default());
        let (p, at, opts) = (progress.clone(), path.clone(), self.opts);
        let handle = std::thread::spawn(move || scan::scan(&at, opts, &p));
        self.path_input = path.display().to_string();
        self.scanning = Some(Scanning { path, progress, started: Instant::now(), handle });
        self.tree = None;
        self.failure = None;
        self.map = None;
        self.message = None;
    }

    fn cancel_scan(&mut self) {
        if let Some(s) = self.scanning.take() {
            s.progress.cancel.store(true, Ordering::Relaxed);
            let _ = s.handle.join();
        }
    }

    fn poll_scan(&mut self) {
        if !self.scanning.as_ref().is_some_and(|s| s.handle.is_finished()) {
            return;
        }
        let s = self.scanning.take().expect("checked above");
        self.scan_time = s.started.elapsed();
        match s.handle.join() {
            Ok(Ok(tree)) => {
                self.zoom = tree.root();
                self.expanded = HashSet::from([tree.root()]);
                self.selected = Some(tree.root());
                self.highlight = None;
                self.tree = Some(tree);
                self.rebuild_rows();
            }
            Ok(Err(e)) => self.failure = Some(format!("Cannot scan {}: {e}", s.path.display())),
            Err(_) => self.failure = Some("The scan stopped unexpectedly.".into()),
        }
    }

    fn rebuild_rows(&mut self) {
        let Some(tree) = &self.tree else { return };
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
    }

    fn row_of(&self, id: u32) -> Option<usize> {
        self.rows.iter().position(|r| r.0 == id)
    }

    /// Opens every folder above `id`, selects it and scrolls the tree to it.
    fn reveal(&mut self, id: u32) {
        let Some(tree) = &self.tree else { return };
        self.expanded.extend(tree.ancestors(id));
        self.rebuild_rows();
        self.selected = Some(id);
        self.scroll_to = self.row_of(id);
    }

    fn toggle(&mut self, id: u32) {
        if !self.expanded.remove(&id) {
            self.expanded.insert(id);
        }
        self.rebuild_rows();
    }

    fn set_measure(&mut self, m: Measure) {
        let Some(tree) = &mut self.tree else { return };
        if tree.measure == m {
            return;
        }
        let ext = self.highlight.map(|i| tree.exts[i as usize].name.clone());
        tree.sort(m);
        self.highlight = ext.and_then(|n| tree.exts.iter().position(|e| e.name == n)).map(|i| i as u32);
        self.rebuild_rows();
    }

    fn folder_of(&self, id: u32) -> Option<PathBuf> {
        let tree = self.tree.as_ref()?;
        let n = tree.node(id);
        let dir = if n.kind == Kind::Dir || n.parent == NONE { id } else { n.parent };
        Some(tree.path(dir))
    }

    fn open_in_file_manager(&mut self, id: u32) {
        let Some(path) = self.folder_of(id) else { return };
        let spawned = Command::new("xdg-open").arg(&path)
            .stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null()).spawn();
        self.message = Some(match spawned {
            Ok(mut child) => {
                std::thread::spawn(move || child.wait());
                format!("Opened {}", path.display())
            }
            Err(e) => format!("Cannot run xdg-open: {e}"),
        });
    }

    fn keys(&mut self, ctx: &egui::Context) {
        if ctx.egui_wants_keyboard_input() || self.tree.is_none() {
            return;
        }
        let (up, down, left, right, enter) = ctx.input(|i| (i.key_pressed(Key::ArrowUp), i.key_pressed(Key::ArrowDown),
            i.key_pressed(Key::ArrowLeft), i.key_pressed(Key::ArrowRight), i.key_pressed(Key::Enter)));
        let Some(cur) = self.selected.and_then(|s| self.row_of(s)) else { return };
        let tree = self.tree.as_ref().expect("checked above");
        let id = self.rows[cur].0;
        let n = tree.node(id);
        let openable = n.kind == Kind::Dir && !n.children.is_empty();
        if up && cur > 0 {
            self.selected = Some(self.rows[cur - 1].0);
            self.scroll_to = Some(cur - 1);
        } else if down && cur + 1 < self.rows.len() {
            self.selected = Some(self.rows[cur + 1].0);
            self.scroll_to = Some(cur + 1);
        } else if ((right || enter) && openable && !self.expanded.contains(&id))
            || (left && self.expanded.contains(&id) && id != tree.root())
        {
            self.toggle(id);
        } else if left && n.parent != NONE {
            let p = n.parent;
            self.selected = Some(p);
            self.scroll_to = self.row_of(p);
        }
    }

    // ---- screens ------------------------------------------------------------------------

    fn start_screen(&mut self, ui: &mut egui::Ui) {
        ui.add_space(24.0);
        ui.vertical_centered(|ui| {
            ui.heading(RichText::new("What should diskmap look at?").size(22.0));
            ui.add_space(4.0);
            ui.label(RichText::new("It only reads: nothing on the disk is changed.").weak());
        });
        ui.add_space(20.0);
        if let Some(f) = &self.failure {
            ui.colored_label(Color32::LIGHT_RED, f);
            ui.add_space(8.0);
        }
        let mut go = None;
        egui::Frame::group(ui.style()).show(ui, |ui| {
            ui.label(RichText::new("Disks").strong());
            ui.add_space(4.0);
            for d in &self.disks {
                let used = d.total.saturating_sub(d.free);
                let frac = used as f32 / d.total as f32;
                ui.horizontal(|ui| {
                    if ui.button("Scan").clicked() {
                        go = Some(d.mount.clone());
                    }
                    ui.add_sized([220.0, ROW], egui::Label::new(RichText::new(d.mount.display().to_string()).strong())
                        .truncate());
                    let colour = if frac > 0.9 { Color32::from_rgb(220, 80, 70) } else { ACCENT };
                    ui.add(egui::ProgressBar::new(frac).desired_width(220.0).fill(colour)
                        .text(format!("{} of {} used", size(used), size(d.total))));
                    ui.label(RichText::new(format!("{} free", size(d.free))).weak());
                    ui.label(RichText::new(format!("{}  {}", d.fstype, d.source)).weak().small());
                });
            }
        });
        ui.add_space(12.0);
        egui::Frame::group(ui.style()).show(ui, |ui| {
            ui.label(RichText::new("A folder").strong());
            ui.add_space(4.0);
            ui.horizontal(|ui| {
                let edit = ui.add(egui::TextEdit::singleline(&mut self.path_input).desired_width(480.0));
                let enter = edit.lost_focus() && ui.input(|i| i.key_pressed(Key::Enter));
                if ui.button("Scan").clicked() || enter {
                    go = Some(PathBuf::from(self.path_input.trim()));
                }
                if let Some(home) = std::env::var_os("HOME")
                    && ui.button("Home").clicked()
                {
                    go = Some(PathBuf::from(home));
                }
            });
            ui.checkbox(&mut self.opts.cross_filesystems, "Also scan other filesystems mounted inside it");
        });
        if let Some(p) = go {
            self.start_scan(p);
        }
    }

    fn scanning_screen(&mut self, ui: &mut egui::Ui) {
        let s = self.scanning.as_ref().expect("only while scanning");
        let p = &s.progress;
        let mut stop = false;
        ui.vertical_centered(|ui| {
            ui.add_space(ui.available_height() / 3.0);
            ui.add(egui::Spinner::new().size(32.0));
            ui.add_space(8.0);
            ui.heading(format!("Scanning {}", s.path.display()));
            ui.label(format!("{} files in {} folders, {}", count(p.files.load(Ordering::Relaxed)),
                count(p.dirs.load(Ordering::Relaxed)), size(p.bytes.load(Ordering::Relaxed))));
            ui.label(RichText::new(format!("{:.1} s", s.started.elapsed().as_secs_f64())).weak());
            ui.add_space(8.0);
            stop = ui.button("Stop").clicked();
        });
        if stop {
            self.cancel_scan();
        }
        ui.ctx().request_repaint_after(Duration::from_millis(100));
    }

    fn toolbar(&mut self, ui: &mut egui::Ui) {
        let Some(tree) = &self.tree else { return };
        let (measure, root, zoom) = (tree.measure, tree.root(), self.zoom);
        let root_path = tree.root_path.clone();
        ui.horizontal(|ui| {
            if ui.button("⏏ New scan").on_hover_text("Choose another disk or folder").clicked() {
                self.tree = None;
                self.map = None;
                self.disks = disks::list();
                return;
            }
            if ui.button("⟳ Rescan").clicked() {
                self.start_scan(root_path.clone());
                return;
            }
            ui.separator();
            let mut m = measure;
            ui.selectable_value(&mut m, Measure::Allocated, "Allocated")
                .on_hover_text("Space taken on the disk, as du counts it");
            ui.selectable_value(&mut m, Measure::Apparent, "Apparent").on_hover_text("The files' own lengths");
            self.set_measure(m);
            ui.separator();
            ui.checkbox(&mut self.show_map, "Treemap");
            if zoom != root && ui.button("⤢ Whole treemap").clicked() {
                self.zoom = root;
            }
            ui.with_layout(egui::Layout::right_to_left(Align::Center), |ui| {
                if ui.button("Patch notes").clicked() {
                    self.show_notes = true;
                }
                ui.label(RichText::new(format!("diskmap {}", env!("CARGO_PKG_VERSION"))).weak());
            });
        });
    }

    fn status(&self, ui: &mut egui::Ui) {
        ui.horizontal(|ui| {
            if let Some(msg) = &self.message {
                ui.label(msg);
                return;
            }
            let (Some(tree), Some(id)) = (&self.tree, self.selected) else { return };
            let n = tree.node(id);
            ui.label(tree.path(id).display().to_string());
            ui.label(RichText::new("·").weak());
            ui.label(size(n.size(tree.measure)));
            if n.kind == Kind::Dir {
                ui.label(RichText::new("·").weak());
                ui.label(format!("{} files", count(n.files)));
            }
            if tree.errors > 0 {
                ui.label(RichText::new("·").weak());
                ui.colored_label(Color32::YELLOW, format!("{} unreadable", count(tree.errors)))
                    .on_hover_text("Folders or files this user may not read; run as root to count them");
            }
            ui.with_layout(egui::Layout::right_to_left(Align::Center), |ui| {
                let root = tree.node(tree.root());
                ui.label(RichText::new(format!("{} in {} files, scanned in {:.1} s", size(root.size(tree.measure)),
                    count(root.files), self.scan_time.as_secs_f64())).weak());
            });
        });
    }

    fn tree_table(&mut self, ui: &mut egui::Ui) {
        let Some(tree) = &self.tree else { return };
        let m = tree.measure;
        let mut clicked = None;
        let mut toggled = None;
        let mut menu: Option<(u32, MenuAction)> = None;
        let mut table = TableBuilder::new(ui).id_salt("tree").striped(true).sense(Sense::click())
            .column(Column::remainder().at_least(200.0).clip(true))
            .column(Column::exact(110.0))
            .column(Column::exact(64.0))
            .column(Column::exact(80.0))
            .column(Column::exact(84.0));
        if let Some(r) = self.scroll_to.take() {
            table = table.scroll_to_row(r, None);
        }
        table.header(ROW, |mut h| {
            for (i, t) in ["Name", "Subtree", "%", "Size", "Files"].iter().enumerate() {
                h.col(|ui| {
                    if i == 0 {
                        ui.strong(*t);
                    } else {
                        ui.with_layout(egui::Layout::right_to_left(Align::Center), |ui| ui.strong(*t));
                    }
                });
            }
        }).body(|body| {
            body.rows(ROW, self.rows.len(), |mut row| {
                let (id, depth) = self.rows[row.index()];
                let n = tree.node(id);
                let parent = if n.parent == NONE { n.size(m) } else { tree.node(n.parent).size(m) };
                let share = if parent == 0 { 0.0 } else { n.size(m) as f32 / parent as f32 };
                row.set_selected(self.selected == Some(id));
                row.col(|ui| {
                    ui.horizontal(|ui| {
                    ui.spacing_mut().item_spacing.x = 4.0;
                    ui.add_space(depth as f32 * 14.0);
                    let openable = n.kind == Kind::Dir && !n.children.is_empty();
                    if openable {
                        let arrow = if self.expanded.contains(&id) { "▼" } else { "▶" };
                        if ui.add(egui::Button::new(arrow).frame(false).small()).clicked() {
                            toggled = Some(id);
                        }
                    } else {
                        ui.add_space(16.0);
                    }
                    if n.kind == Kind::File {
                        let c = treemap::ext_color(n.ext);
                        ui.label(RichText::new("■").color(Color32::from_rgb(c[0], c[1], c[2])));
                    }
                    let text = match n.kind {
                        Kind::Dir => RichText::new(&*n.name).strong(),
                        Kind::File => RichText::new(&*n.name),
                        Kind::Link => RichText::new(format!("{} →", n.name)).weak(),
                        Kind::Other => RichText::new(&*n.name).weak(),
                    };
                    ui.add(egui::Label::new(text).selectable(false).truncate());
                    });
                });
                row.col(|ui| {
                    let (rect, _) = ui.allocate_exact_size(Vec2::new(100.0, 10.0), Sense::hover());
                    ui.painter().rect_filled(rect, CornerRadius::same(2), ui.visuals().extreme_bg_color);
                    let mut fill = rect;
                    fill.set_width(rect.width() * share.clamp(0.0, 1.0));
                    ui.painter().rect_filled(fill, CornerRadius::same(2), ACCENT);
                });
                for text in [format!("{:.1} %", share * 100.0), size(n.size(m)),
                    if n.kind == Kind::Dir { count(n.files) } else { String::new() }]
                {
                    row.col(|ui| {
                        ui.with_layout(egui::Layout::right_to_left(Align::Center), |ui| {
                            ui.add(egui::Label::new(text).selectable(false));
                        });
                    });
                }
                let resp = row.response();
                if resp.clicked() {
                    clicked = Some(id);
                }
                if resp.double_clicked() && n.kind == Kind::Dir && !n.children.is_empty() {
                    toggled = Some(id);
                }
                resp.context_menu(|ui| {
                    if let Some(a) = context_menu(ui) {
                        menu = Some((id, a));
                    }
                });
            });
        });
        if let Some(id) = clicked {
            self.selected = Some(id);
        }
        if let Some(id) = toggled {
            self.toggle(id);
        }
        if let Some((id, a)) = menu {
            self.menu_action(ui.ctx(), id, a);
        }
    }

    fn types_table(&mut self, ui: &mut egui::Ui) {
        let Some(tree) = &self.tree else { return };
        let m = tree.measure;
        let total: u64 = tree.exts.iter().map(|e| e.size(m)).sum();
        let mut clicked = None;
        ui.horizontal(|ui| {
            ui.strong("File types");
            if self.highlight.is_some() && ui.small_button("Show all").clicked() {
                self.highlight = None;
            }
        });
        TableBuilder::new(ui).id_salt("types").striped(true).sense(Sense::click())
            .column(Column::exact(16.0))
            .column(Column::remainder().at_least(60.0).clip(true))
            .column(Column::exact(72.0))
            .column(Column::exact(56.0))
            .column(Column::exact(64.0))
            .header(ROW, |mut h| {
                for t in ["", "Type", "Size", "%", "Files"] {
                    h.col(|ui| {
                        ui.strong(t);
                    });
                }
            })
            .body(|body| {
                body.rows(ROW, tree.exts.len(), |mut row| {
                    let i = row.index();
                    let e = &tree.exts[i];
                    row.set_selected(self.highlight == Some(i as u32));
                    row.col(|ui| {
                        let c = treemap::ext_color(i as u32);
                        ui.label(RichText::new("■").color(Color32::from_rgb(c[0], c[1], c[2])));
                    });
                    row.col(|ui| {
                        let name = if e.name.is_empty() { "(none)".to_string() } else { format!(".{}", e.name) };
                        ui.add(egui::Label::new(name).selectable(false).truncate());
                    });
                    let share = if total == 0 { 0.0 } else { e.size(m) as f64 / total as f64 * 100.0 };
                    for text in [size(e.size(m)), format!("{share:.1} %"), count(e.files)] {
                        row.col(|ui| {
                            ui.with_layout(egui::Layout::right_to_left(Align::Center), |ui| {
                                ui.add(egui::Label::new(text).selectable(false));
                            });
                        });
                    }
                    if row.response().clicked() {
                        clicked = Some(i as u32);
                    }
                });
            });
        if let Some(i) = clicked {
            // A second click on the lit type shows every type again.
            self.highlight = if self.highlight == Some(i) { None } else { Some(i) };
        }
    }

    fn treemap_view(&mut self, ui: &mut egui::Ui) {
        let Some(tree) = &self.tree else { return };
        let (rect, resp) = ui.allocate_exact_size(ui.available_size(), Sense::click());
        let ppp = ui.ctx().pixels_per_point();
        let key = MapKey { w: (rect.width() * ppp).round().max(1.0) as usize, h: (rect.height() * ppp).round().max(1.0) as usize,
            zoom: self.zoom, measure: tree.measure, highlight: self.highlight };
        if self.map.as_ref().is_none_or(|(k, _, _)| *k != key) {
            let pix = treemap::render(tree, self.zoom, key.w, key.h, key.highlight);
            let bytes: Vec<u8> = pix.px.iter().flat_map(|p| *p).collect();
            let image = egui::ColorImage::from_rgb([pix.w, pix.h], &bytes);
            match &mut self.map {
                Some((k, p, tex)) => {
                    tex.set(image, TextureOptions::NEAREST);
                    *k = key;
                    *p = pix;
                }
                None => {
                    let tex = ui.ctx().load_texture("treemap", image, TextureOptions::NEAREST);
                    self.map = Some((key, pix, tex));
                }
            }
        }
        let (_, pix, tex) = self.map.as_ref().expect("drawn above");
        let painter = ui.painter_at(rect);
        painter.image(tex.id(), rect, Rect::from_min_max(Pos2::ZERO, Pos2::new(1.0, 1.0)), Color32::WHITE);
        let to_screen = |(x0, y0, x1, y1): (usize, usize, usize, usize)| Rect::from_min_max(
            rect.min + Vec2::new(x0 as f32, y0 as f32) / ppp, rect.min + Vec2::new(x1 as f32, y1 as f32) / ppp);
        if let Some(sel) = self.selected {
            let mut cur = sel;
            while cur != NONE && !pix.rects.contains_key(&cur) {
                cur = tree.node(cur).parent;
            }
            if let Some(&r) = pix.rects.get(&cur) {
                painter.rect_stroke(to_screen(r), 0.0, Stroke::new(2.0, Color32::WHITE), StrokeKind::Inside);
            }
        }
        let hit = resp.hover_pos().map_or(NONE, |p| {
            let v = (p - rect.min) * ppp;
            pix.owner_at(v.x as usize, v.y as usize)
        });
        let mut action = None;
        if hit != NONE {
            if let Some(&r) = pix.rects.get(&hit) {
                painter.rect_stroke(to_screen(r), 0.0, Stroke::new(1.0, Color32::from_white_alpha(160)), StrokeKind::Inside);
            }
            let n = tree.node(hit);
            let path = tree.path(hit);
            let resp = resp.clone().on_hover_ui_at_pointer(|ui| {
                ui.strong(path.display().to_string());
                ui.label(size(n.size(tree.measure)));
            });
            if resp.clicked() {
                action = Some((hit, MenuAction::Select));
            }
            if resp.double_clicked() {
                action = Some((hit, MenuAction::Zoom));
            }
            resp.context_menu(|ui| {
                if let Some(a) = context_menu(ui) {
                    action = Some((hit, a));
                }
            });
        }
        if let Some((id, a)) = action {
            self.menu_action(ui.ctx(), id, a);
        }
    }

    fn menu_action(&mut self, ctx: &egui::Context, id: u32, a: MenuAction) {
        let Some(tree) = &self.tree else { return };
        match a {
            MenuAction::Select => self.reveal(id),
            MenuAction::Zoom => {
                let n = tree.node(id);
                self.zoom = if n.kind == Kind::Dir { id } else if n.parent != NONE { n.parent } else { id };
                self.reveal(id);
            }
            MenuAction::Open => self.open_in_file_manager(id),
            MenuAction::Copy => {
                let p = tree.path(id).display().to_string();
                ctx.copy_text(p.clone());
                self.message = Some(format!("Copied {p}"));
            }
        }
    }

    fn notes_window(&mut self, ctx: &egui::Context) {
        let mut open = self.show_notes;
        egui::Window::new("Patch notes").open(&mut open).default_size([520.0, 420.0]).show(ctx, |ui| {
            egui::ScrollArea::vertical().show(ui, |ui| {
                for r in changelog::releases() {
                    ui.horizontal(|ui| {
                        ui.label(RichText::new(&r.version).strong().color(ACCENT));
                        ui.label(RichText::new(&r.date).weak());
                        if let Some(t) = &r.title {
                            ui.strong(t);
                        }
                    });
                    for (g, items) in &r.groups {
                        ui.label(RichText::new(g).weak());
                        for i in items {
                            ui.label(format!("  •  {}", i.replace('`', "")));
                        }
                    }
                    ui.add_space(10.0);
                }
            });
        });
        self.show_notes = open;
    }
}

#[derive(Debug, Clone, Copy)]
enum MenuAction {
    Select,
    Zoom,
    Open,
    Copy,
}

fn context_menu(ui: &mut egui::Ui) -> Option<MenuAction> {
    let mut a = None;
    if ui.button("Zoom the treemap here").clicked() {
        a = Some(MenuAction::Zoom);
    }
    if ui.button("Open in the file manager").clicked() {
        a = Some(MenuAction::Open);
    }
    if ui.button("Copy the path").clicked() {
        a = Some(MenuAction::Copy);
    }
    if a.is_some() {
        ui.close();
    }
    a
}

impl eframe::App for Gui {
    fn ui(&mut self, ui: &mut egui::Ui, _frame: &mut eframe::Frame) {
        let ctx = ui.ctx().clone();
        self.poll_scan();
        self.keys(&ctx);
        if self.scanning.is_some() {
            egui::CentralPanel::default_margins().show(ui, |ui| self.scanning_screen(ui));
            return;
        }
        if self.tree.is_none() {
            egui::CentralPanel::default_margins().show(ui, |ui| {
                egui::ScrollArea::vertical().show(ui, |ui| self.start_screen(ui));
            });
            return;
        }
        egui::Panel::top("toolbar").show(ui, |ui| {
            ui.add_space(4.0);
            self.toolbar(ui);
            ui.add_space(2.0);
        });
        if self.tree.is_none() || self.scanning.is_some() {
            return;
        }
        egui::Panel::bottom("status").show(ui, |ui| self.status(ui));
        if self.show_map {
            let h = ui.available_height();
            egui::Panel::bottom("treemap").resizable(true).default_size(h * 0.5).size_range(80.0..=h - 120.0)
                .frame(egui::Frame::NONE).show(ui, |ui| self.treemap_view(ui));
        }
        egui::Panel::right("types").resizable(true).default_size(320.0).show(ui, |ui| self.types_table(ui));
        egui::CentralPanel::default_margins().show(ui, |ui| self.tree_table(ui));
        self.notes_window(&ctx);
    }

    fn on_exit(&mut self) {
        self.cancel_scan();
    }
}
