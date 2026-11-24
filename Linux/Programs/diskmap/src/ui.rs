//! Drawing: the tree, the file types, the treemap, the status bar and the overlays.

use std::sync::atomic::Ordering;

use ratatui::Frame;
use ratatui::layout::{Alignment, Constraint, Layout, Rect};
use ratatui::style::{Color, Modifier, Style};
use ratatui::text::{Line, Span};
use ratatui::widgets::{Block, Cell, Clear, Paragraph, Row, Table, Wrap};

use crate::app::{App, Focus, MapKey, Overlay};
use diskmap::changelog;
use diskmap::fmt::{count, size};
use diskmap::scan::{Kind, Measure, NONE, Tree};
use diskmap::treemap::{self, Rgb};

const ACCENT: Color = Color::Rgb(110, 170, 255);
const DIM: Color = Color::Rgb(130, 130, 130);

/// A bar `width` cells long, filled to `frac` in eighths.
fn bar(frac: f64, width: usize) -> String {
    const PARTS: [char; 8] = [' ', '▏', '▎', '▍', '▌', '▋', '▊', '▉'];
    let eighths = (frac.clamp(0.0, 1.0) * (width * 8) as f64).round() as usize;
    let mut s = "█".repeat(eighths / 8);
    if !eighths.is_multiple_of(8) {
        s.push(PARTS[eighths % 8]);
    }
    while s.chars().count() < width {
        s.push(' ');
    }
    s
}

fn rgb(c: Rgb) -> Color {
    Color::Rgb(c[0], c[1], c[2])
}

fn pct(part: u64, whole: u64) -> f64 {
    if whole == 0 { 0.0 } else { part as f64 / whole as f64 }
}

fn ext_label(name: &str) -> String {
    if name.is_empty() { "(none)".into() } else { format!(".{name}") }
}

fn block(title: String, focused: bool) -> Block<'static> {
    let style = if focused { Style::new().fg(ACCENT) } else { Style::new().fg(DIM) };
    Block::bordered().border_style(style).title(Span::styled(title, Style::new().add_modifier(Modifier::BOLD)))
}

pub fn draw(f: &mut Frame, app: &mut App) {
    let area = f.area();
    let [main, status] = Layout::vertical([Constraint::Min(3), Constraint::Length(1)]).areas(area);
    if app.tree.is_none() {
        draw_waiting(f, app, main);
    } else if app.show_map {
        let [top, map] = Layout::vertical([Constraint::Percentage(45), Constraint::Percentage(55)]).areas(main);
        draw_lists(f, app, top);
        draw_map(f, app, map);
    } else {
        draw_lists(f, app, main);
        app.map_area = Rect::default();
    }
    draw_status(f, app, status);
    match app.overlay {
        Some(Overlay::Help) => draw_overlay(f, app, "Keys", help_text()),
        Some(Overlay::Notes) => draw_overlay(f, app, "Patch notes", notes_text()),
        None => {}
    }
}

fn draw_waiting(f: &mut Frame, app: &App, area: Rect) {
    let lines = if let Some(s) = &app.scanning {
        let p = &s.progress;
        let spin = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'][(s.started.elapsed().as_millis() / 100 % 10) as usize];
        vec![
            Line::from(Span::styled(format!("{spin} Scanning {}", app.path.display()), Style::new().fg(ACCENT))),
            Line::from(""),
            Line::from(format!("{} files in {} folders, {}", count(p.files.load(Ordering::Relaxed)),
                count(p.dirs.load(Ordering::Relaxed)), size(p.bytes.load(Ordering::Relaxed)))),
            Line::from(format!("{:.1} s", s.started.elapsed().as_secs_f64())),
            Line::from(""),
            Line::from(Span::styled("q to stop", Style::new().fg(DIM))),
        ]
    } else {
        vec![
            Line::from(Span::styled(app.failure.clone().unwrap_or_default(), Style::new().fg(Color::Red))),
            Line::from(""),
            Line::from(Span::styled("r to try again, q to quit", Style::new().fg(DIM))),
        ]
    };
    let h = lines.len() as u16;
    let y = area.y + area.height.saturating_sub(h) / 2;
    let r = Rect { x: area.x, y, width: area.width, height: h.min(area.height) };
    f.render_widget(Paragraph::new(lines).alignment(Alignment::Center), r);
}

fn draw_lists(f: &mut Frame, app: &mut App, area: Rect) {
    let types_w = if area.width >= 90 { 38 } else if area.width >= 60 { 28 } else { 0 };
    let [left, right] = Layout::horizontal([Constraint::Min(20), Constraint::Length(types_w)]).areas(area);
    draw_tree(f, app, left);
    if types_w > 0 {
        draw_types(f, app, right);
    } else {
        app.ext_area = Rect::default();
    }
}

fn draw_tree(f: &mut Frame, app: &mut App, area: Rect) {
    app.tree_area = area;
    let tree = app.tree.as_ref().expect("drawn with a tree");
    let m = tree.measure;
    let wide = area.width >= 70;
    let rows: Vec<Row> = app.rows.iter().map(|&(id, depth)| {
        let n = tree.node(id);
        let parent = if n.parent == NONE { n.size(m) } else { tree.node(n.parent).size(m) };
        let share = pct(n.size(m), parent);
        let marker = match n.kind {
            Kind::Dir if n.children.is_empty() => "  ",
            Kind::Dir if app.expanded.contains(&id) => "▾ ",
            Kind::Dir => "▸ ",
            _ => "  ",
        };
        let name_style = match n.kind {
            Kind::Dir => Style::new().add_modifier(Modifier::BOLD),
            Kind::File => Style::new(),
            _ => Style::new().fg(DIM),
        };
        let swatch = if n.kind == Kind::File { rgb(treemap::ext_color(n.ext)) } else { Color::Reset };
        let name = Line::from(vec![
            Span::raw("  ".repeat(depth as usize)),
            Span::raw(marker),
            Span::styled(if n.kind == Kind::File { "■ " } else { "" }, Style::new().fg(swatch)),
            Span::styled(n.name.to_string(), name_style),
            Span::styled(if n.kind == Kind::Link { " →" } else { "" }, Style::new().fg(DIM)),
        ]);
        let mut cells = vec![Cell::from(name)];
        if wide {
            cells.push(Cell::from(Span::styled(bar(share, 10), Style::new().fg(ACCENT))));
        }
        cells.push(Cell::from(Line::from(format!("{:.1} %", share * 100.0)).alignment(Alignment::Right)));
        cells.push(Cell::from(Line::from(size(n.size(m))).alignment(Alignment::Right)));
        if wide {
            let files = if n.kind == Kind::Dir { count(n.files) } else { String::new() };
            cells.push(Cell::from(Line::from(files).alignment(Alignment::Right)));
        }
        Row::new(cells)
    }).collect();
    let mut widths = vec![Constraint::Min(16)];
    let mut header = vec!["Name"];
    if wide {
        widths.push(Constraint::Length(10));
        header.push("Subtree");
    }
    widths.extend([Constraint::Length(7), Constraint::Length(9)]);
    header.extend(["%", "Size"]);
    if wide {
        widths.push(Constraint::Length(10));
        header.push("Files");
    }
    let header = Row::new(header.into_iter().enumerate().map(|(i, h)| {
        let l = Line::from(h);
        Cell::from(if i == 0 { l } else { l.alignment(Alignment::Right) })
    })).style(Style::new().fg(DIM));
    let focused = app.focus == Focus::Tree;
    let table = Table::new(rows, widths).header(header)
        .block(block(format!(" {} ", tree.root_path.display()), focused))
        .row_highlight_style(Style::new().bg(if focused { Color::Rgb(40, 60, 100) } else { Color::Rgb(50, 50, 50) }));
    f.render_stateful_widget(table, area, &mut app.tree_state);
}

fn draw_types(f: &mut Frame, app: &mut App, area: Rect) {
    app.ext_area = area;
    let tree = app.tree.as_ref().expect("drawn with a tree");
    let m = tree.measure;
    let total: u64 = tree.exts.iter().map(|e| e.size(m)).sum();
    let rows: Vec<Row> = tree.exts.iter().enumerate().map(|(i, e)| {
        Row::new(vec![
            Cell::from(Span::styled("■■", Style::new().fg(rgb(treemap::ext_color(i as u32))))),
            Cell::from(ext_label(&e.name)),
            Cell::from(Line::from(size(e.size(m))).alignment(Alignment::Right)),
            Cell::from(Line::from(format!("{:.1} %", pct(e.size(m), total) * 100.0)).alignment(Alignment::Right)),
        ])
    }).collect();
    let header = Row::new(vec![Cell::from(""), Cell::from("Type"), Cell::from(Line::from("Size").alignment(Alignment::Right)),
        Cell::from(Line::from("%").alignment(Alignment::Right))]).style(Style::new().fg(DIM));
    let focused = app.focus == Focus::Types;
    let table = Table::new(rows, [Constraint::Length(2), Constraint::Min(6), Constraint::Length(9), Constraint::Length(7)])
        .header(header).block(block(" Types ".into(), focused))
        .row_highlight_style(Style::new().bg(if focused { Color::Rgb(40, 60, 100) } else { Color::Rgb(50, 50, 50) }));
    f.render_stateful_widget(table, area, &mut app.ext_state);
}

fn draw_map(f: &mut Frame, app: &mut App, area: Rect) {
    let tree = app.tree.as_ref().expect("drawn with a tree");
    let title = if app.zoom == tree.root() {
        " Treemap ".to_string()
    } else {
        format!(" Treemap: {}  (Z for all) ", tree.path(app.zoom).display())
    };
    let b = block(title, false);
    let inner = b.inner(area);
    f.render_widget(b, area);
    app.map_area = inner;
    let key = MapKey { w: inner.width as usize, h: inner.height as usize * 2, zoom: app.zoom, measure: tree.measure,
        highlight: app.highlight() };
    if app.map.as_ref().is_none_or(|(k, _)| *k != key) {
        app.map = Some((key, treemap::render(tree, app.zoom, key.w, key.h, key.highlight)));
    }
    let (_, cached) = app.map.as_ref().expect("drawn above");
    // The outline is drawn on a copy, so moving the selection does not redraw the cushions.
    let mut pix = treemap::Pixmap { w: cached.w, h: cached.h, px: cached.px.clone(), owner: Vec::new(),
        rects: Default::default() };
    if let Some(sel) = app.selected()
        && let Some(r) = outline_rect(tree, cached, sel)
    {
        pix.rects.insert(sel, r);
        pix.outline(tree, sel);
    }
    let buf = f.buffer_mut();
    for cy in 0..inner.height as usize {
        for cx in 0..inner.width as usize {
            let top = pix.at(cx, cy * 2);
            let bottom = if cy * 2 + 1 < pix.h { pix.at(cx, cy * 2 + 1) } else { top };
            if let Some(cell) = buf.cell_mut((inner.x + cx as u16, inner.y + cy as u16)) {
                cell.set_char('▀').set_fg(rgb(top)).set_bg(rgb(bottom));
            }
        }
    }
}

/// The rectangle to outline for `id`: its own, or its nearest ancestor's that was laid out.
fn outline_rect(tree: &Tree, map: &treemap::Pixmap, id: u32) -> Option<(usize, usize, usize, usize)> {
    let mut cur = id;
    while cur != NONE {
        if let Some(&r) = map.rects.get(&cur) {
            return Some(r);
        }
        cur = tree.node(cur).parent;
    }
    None
}

fn draw_status(f: &mut Frame, app: &App, area: Rect) {
    let mut spans = Vec::new();
    if let Some(msg) = &app.message {
        spans.push(Span::raw(format!(" {msg}")));
    } else if let (Some(tree), Some(id)) = (&app.tree, app.selected()) {
        let n = tree.node(id);
        spans.push(Span::raw(format!(" {}", tree.path(id).display())));
        spans.push(Span::styled("  ·  ", Style::new().fg(DIM)));
        spans.push(Span::raw(size(n.size(tree.measure))));
        if n.kind == Kind::Dir {
            spans.push(Span::styled("  ·  ", Style::new().fg(DIM)));
            spans.push(Span::raw(format!("{} files", count(n.files))));
        }
        spans.push(Span::styled("  ·  ", Style::new().fg(DIM)));
        spans.push(Span::raw(if tree.measure == Measure::Allocated { "allocated" } else { "apparent" }));
        if tree.errors > 0 {
            spans.push(Span::styled("  ·  ", Style::new().fg(DIM)));
            spans.push(Span::styled(format!("{} unreadable", count(tree.errors)), Style::new().fg(Color::Yellow)));
        }
        spans.push(Span::styled(format!("  ·  scanned in {:.1} s", app.scan_time.as_secs_f64()), Style::new().fg(DIM)));
    }
    let left = Paragraph::new(Line::from(spans));
    let right = Paragraph::new(Line::from(Span::styled(
        format!("? help  c notes  diskmap {} ", env!("CARGO_PKG_VERSION")), Style::new().fg(DIM))))
        .alignment(Alignment::Right);
    f.render_widget(left, area);
    let rw = 34.min(area.width);
    f.render_widget(right, Rect { x: area.x + area.width - rw, y: area.y, width: rw, height: 1 });
}

fn help_text() -> Vec<Line<'static>> {
    let keys = [
        ("↑ ↓  PgUp PgDn  Home End", "move in the focused list"),
        ("→  Enter", "open a folder"),
        ("←", "close a folder, or go to its parent"),
        ("Tab", "switch between the tree and the types"),
        ("t", "show or hide the treemap"),
        ("z  /  Z", "zoom the treemap to the selection / back out"),
        ("a", "allocated or apparent size"),
        ("o", "open the folder in the file manager"),
        ("r", "scan again"),
        ("c", "patch notes"),
        ("q  Esc", "quit, or close this"),
        ("", ""),
        ("click", "select; a treemap click finds the file"),
        ("wheel", "scroll the list under the pointer"),
    ];
    let mut lines = vec![Line::from(Span::styled("diskmap only reads: it never changes the disk.", Style::new().fg(DIM))),
        Line::from("")];
    lines.extend(keys.iter().map(|(k, v)| Line::from(vec![
        Span::styled(format!("{k:<26}"), Style::new().fg(ACCENT)), Span::raw(*v)])));
    lines
}

fn notes_text() -> Vec<Line<'static>> {
    let mut lines = Vec::new();
    for r in changelog::releases() {
        let mut head = vec![Span::styled(r.version.clone(), Style::new().fg(ACCENT).add_modifier(Modifier::BOLD)),
            Span::styled(format!("  {}", r.date), Style::new().fg(DIM))];
        if let Some(t) = &r.title {
            head.push(Span::styled(format!("  {t}"), Style::new().add_modifier(Modifier::BOLD)));
        }
        lines.push(Line::from(head));
        for (g, items) in &r.groups {
            lines.push(Line::from(Span::styled(format!("  {g}"), Style::new().fg(DIM))));
            for i in items {
                lines.push(Line::from(format!("    • {}", i.replace('`', ""))));
            }
        }
        lines.push(Line::from(""));
    }
    lines
}

fn draw_overlay(f: &mut Frame, app: &App, title: &str, text: Vec<Line<'static>>) {
    let area = f.area();
    let w = area.width.saturating_sub(4).min(84);
    let h = area.height.saturating_sub(4).min(text.len() as u16 + 2).max(5).min(area.height);
    let r = Rect { x: area.x + (area.width - w) / 2, y: area.y + (area.height - h) / 2, width: w, height: h };
    f.render_widget(Clear, r);
    let p = Paragraph::new(text).wrap(Wrap { trim: false }).scroll((app.overlay_scroll, 0))
        .block(block(format!(" {title} "), true).title_bottom(Line::from(" Esc to close ").alignment(Alignment::Right)));
    f.render_widget(p, r);
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bars_fill_in_eighths() {
        assert_eq!(bar(0.0, 4), "    ");
        assert_eq!(bar(1.0, 4), "████");
        assert_eq!(bar(0.5, 4), "██  ");
        assert_eq!(bar(1.0 / 32.0, 4), "▏   ");
    }
}
