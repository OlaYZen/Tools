//! The squarified cushion treemap, drawn into a pixel buffer.
//!
//! Layout: Bruls, Huizing and van Wijk, "Squarified Treemaps" (2000). Shading: van Wijk and
//! van de Wetering, "Cushion Treemaps" (1999), with WinDirStat's default constants. Every
//! pixel records which node painted it, which is how a click finds its file.

use std::collections::HashMap;

use crate::scan::{Kind, Measure, NONE, Tree};

pub type Rgb = [u8; 3];

/// Cushion height, and the factor it shrinks by per level.
const HEIGHT: f64 = 0.38;
const SCALE: f64 = 0.91;
/// Ambient light, and the light source direction (from the top left).
const AMBIENT: f64 = 0.13;
const LIGHT: [f64; 3] = [-1.0, -1.0, 10.0];
/// Overall brightness: colours are scaled so a flat, lit surface shows them as given.
const BRIGHTNESS: f64 = 0.88;

/// The colours handed to the extensions taking the most space, in order.
pub const PALETTE: [Rgb; 12] = [
    [0, 0, 255], [255, 0, 0], [0, 255, 0], [0, 255, 255], [255, 0, 255], [255, 255, 0],
    [150, 150, 255], [255, 150, 150], [150, 255, 150], [150, 255, 255], [255, 150, 255],
    [255, 255, 150],
];
pub const OTHER: Rgb = [140, 140, 140];
const EMPTY: Rgb = [60, 60, 60];

pub fn ext_color(ext: u32) -> Rgb {
    if ext == NONE { OTHER } else { PALETTE.get(ext as usize).copied().unwrap_or(OTHER) }
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Rect {
    pub x: f64,
    pub y: f64,
    pub w: f64,
    pub h: f64,
}

/// Lays `sizes` (largest first, all positive) out in `r`, one rectangle each, in order.
pub fn squarify(sizes: &[f64], r: Rect) -> Vec<Rect> {
    let mut out = Vec::with_capacity(sizes.len());
    let mut r = r;
    let mut i = 0;
    let mut remaining: f64 = sizes.iter().sum();
    while i < sizes.len() {
        if remaining <= 0.0 || r.w <= 0.0 || r.h <= 0.0 {
            out.extend(std::iter::repeat_n(Rect { x: r.x, y: r.y, w: 0.0, h: 0.0 }, sizes.len() - i));
            break;
        }
        let scale = r.w * r.h / remaining;
        let short = r.w.min(r.h);
        // Grow the row while its worst aspect ratio improves.
        let worst = |sum: f64, max: f64, min: f64| {
            let s2 = (sum * scale) * (sum * scale);
            let l2 = short * short;
            ((l2 * max * scale) / s2).max(s2 / (l2 * min * scale))
        };
        let (mut j, mut sum) = (i + 1, sizes[i]);
        let mut best = worst(sum, sizes[i], sizes[i]);
        while j < sizes.len() {
            let next = worst(sum + sizes[j], sizes[i], sizes[j]);
            if next > best {
                break;
            }
            best = next;
            sum += sizes[j];
            j += 1;
        }
        // The row runs along the short side; its thickness takes the row's share of the area.
        let thick = sum * scale / short;
        let mut pos = 0.0;
        for &s in &sizes[i..j] {
            let len = if sum > 0.0 { s / sum * short } else { 0.0 };
            out.push(if r.w >= r.h {
                Rect { x: r.x, y: r.y + pos, w: thick, h: len }
            } else {
                Rect { x: r.x + pos, y: r.y, w: len, h: thick }
            });
            pos += len;
        }
        if r.w >= r.h {
            r = Rect { x: r.x + thick, y: r.y, w: r.w - thick, h: r.h };
        } else {
            r = Rect { x: r.x, y: r.y + thick, w: r.w, h: r.h - thick };
        }
        remaining -= sum;
        i = j;
    }
    out
}

/// A drawn treemap: colours, and which node owns each pixel.
pub struct Pixmap {
    pub w: usize,
    pub h: usize,
    pub px: Vec<Rgb>,
    pub owner: Vec<u32>,
    /// The pixel bounds `(x0, y0, x1, y1)` of every node big enough to be laid out.
    pub rects: HashMap<u32, (usize, usize, usize, usize)>,
}

impl Pixmap {
    pub fn at(&self, x: usize, y: usize) -> Rgb {
        self.px[y * self.w + x]
    }

    pub fn owner_at(&self, x: usize, y: usize) -> u32 {
        if x < self.w && y < self.h { self.owner[y * self.w + x] } else { NONE }
    }

    /// Draws a white outline round `id`, or round its nearest ancestor that was laid out.
    pub fn outline(&mut self, tree: &Tree, id: u32) {
        let mut cur = id;
        while cur != NONE && !self.rects.contains_key(&cur) {
            cur = tree.node(cur).parent;
        }
        let Some(&(x0, y0, x1, y1)) = self.rects.get(&cur) else { return };
        if x1 <= x0 || y1 <= y0 {
            return;
        }
        let white = [255, 255, 255];
        for x in x0..x1 {
            self.px[y0 * self.w + x] = white;
            self.px[(y1 - 1) * self.w + x] = white;
        }
        for y in y0..y1 {
            self.px[y * self.w + x0] = white;
            self.px[y * self.w + x1 - 1] = white;
        }
    }
}

struct Painter<'a> {
    tree: &'a Tree,
    m: Measure,
    highlight: Option<u32>,
    map: Pixmap,
}

/// Snaps an edge to the pixel grid. Shared edges snap identically, so siblings tile exactly.
fn snap(v: f64, max: usize) -> usize {
    (v.round().max(0.0) as usize).min(max)
}

impl Painter<'_> {
    fn node(&mut self, id: u32, r: Rect, mut surface: [f64; 4], h: f64) {
        let (x0, x1) = (snap(r.x, self.map.w), snap(r.x + r.w, self.map.w));
        let (y0, y1) = (snap(r.y, self.map.h), snap(r.y + r.h, self.map.h));
        if x1 <= x0 || y1 <= y0 {
            return;
        }
        self.map.rects.insert(id, (x0, y0, x1, y1));
        ridge(&mut surface, r, h);
        let n = self.tree.node(id);
        let kids: Vec<u32> = n.children.iter().copied()
            .filter(|&c| self.tree.node(c).size(self.m) > 0).collect();
        if n.kind == Kind::Dir && !kids.is_empty() {
            let sizes: Vec<f64> = kids.iter().map(|&c| self.tree.node(c).size(self.m) as f64).collect();
            for (&c, cr) in kids.iter().zip(squarify(&sizes, r)) {
                self.node(c, cr, surface, h * SCALE);
            }
        } else {
            let base = if n.kind == Kind::Dir { EMPTY } else if n.kind == Kind::File { ext_color(n.ext) } else { OTHER };
            let dim = self.highlight.is_some_and(|e| n.ext != e);
            self.fill(id, (x0, y0, x1, y1), &surface, base, dim);
        }
    }

    fn fill(&mut self, id: u32, (x0, y0, x1, y1): (usize, usize, usize, usize), s: &[f64; 4], base: Rgb,
        dim: bool) {
        let len = (LIGHT[0] * LIGHT[0] + LIGHT[1] * LIGHT[1] + LIGHT[2] * LIGHT[2]).sqrt();
        let diffuse = 1.0 - AMBIENT;
        for y in y0..y1 {
            for x in x0..x1 {
                let (fx, fy) = (x as f64 + 0.5, y as f64 + 0.5);
                let nx = -(2.0 * s[0] * fx + s[2]);
                let ny = -(2.0 * s[1] * fy + s[3]);
                let cos = (nx * LIGHT[0] + ny * LIGHT[1] + LIGHT[2]) / ((nx * nx + ny * ny + 1.0).sqrt() * len);
                let i = (AMBIENT + diffuse * cos.max(0.0)) / BRIGHTNESS;
                let c = if dim {
                    let g = (base[0] as f64 + base[1] as f64 + base[2] as f64) / 3.0 * 0.3;
                    [g; 3]
                } else {
                    base.map(f64::from)
                };
                let k = y * self.map.w + x;
                self.map.px[k] = c.map(|v| (v * i).clamp(0.0, 255.0) as u8);
                self.map.owner[k] = id;
            }
        }
    }
}

/// Adds a cushion ridge over `r` of height `h` to the surface `[x², y², x, y]`.
fn ridge(s: &mut [f64; 4], r: Rect, h: f64) {
    if r.w > 0.0 {
        let (a, b) = (r.x, r.x + r.w);
        s[2] += 4.0 * h * (b + a) / (b - a);
        s[0] -= 4.0 * h / (b - a);
    }
    if r.h > 0.0 {
        let (a, b) = (r.y, r.y + r.h);
        s[3] += 4.0 * h * (b + a) / (b - a);
        s[1] -= 4.0 * h / (b - a);
    }
}

/// Draws the subtree under `root` into a `w × h` pixel treemap. With `highlight`, only files
/// of that extension keep their colour.
pub fn render(tree: &Tree, root: u32, w: usize, h: usize, highlight: Option<u32>) -> Pixmap {
    let map = Pixmap { w, h, px: vec![[0, 0, 0]; w * h], owner: vec![NONE; w * h], rects: HashMap::new() };
    let mut p = Painter { tree, m: tree.measure, highlight, map };
    if w > 0 && h > 0 {
        p.node(root, Rect { x: 0.0, y: 0.0, w: w as f64, h: h as f64 }, [0.0; 4], HEIGHT);
    }
    p.map
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::scan::{Options, Progress, scan};
    use std::io::Write;

    #[test]
    fn squarify_conserves_area_and_stays_inside() {
        let sizes = [6.0, 6.0, 4.0, 3.0, 2.0, 2.0, 1.0];
        let r = Rect { x: 0.0, y: 0.0, w: 6.0, h: 4.0 };
        let out = squarify(&sizes, r);
        assert_eq!(out.len(), sizes.len());
        let total: f64 = sizes.iter().sum();
        for (s, q) in sizes.iter().zip(&out) {
            assert!((q.w * q.h - s / total * 24.0).abs() < 1e-9, "{q:?}");
            assert!(q.x >= -1e-9 && q.y >= -1e-9 && q.x + q.w <= 6.0 + 1e-9 && q.y + q.h <= 4.0 + 1e-9);
        }
    }

    #[test]
    fn squarify_keeps_ratios_sane() {
        let sizes: Vec<f64> = (1..=50).rev().map(f64::from).collect();
        for q in squarify(&sizes, Rect { x: 0.0, y: 0.0, w: 300.0, h: 100.0 }) {
            let ratio = (q.w / q.h).max(q.h / q.w);
            assert!(ratio < 6.0, "{q:?}");
        }
    }

    #[test]
    fn every_pixel_is_painted_and_sizes_show_in_proportion() {
        let d = tempfile::tempdir().unwrap();
        for (name, len) in [("a.bin", 600_000), ("b.txt", 300_000), ("c.log", 100_000)] {
            std::fs::File::create(d.path().join(name)).unwrap().write_all(&vec![1u8; len]).unwrap();
        }
        let mut t = scan(d.path(), Options { cross_filesystems: false }, &Progress::default()).unwrap();
        t.sort(Measure::Apparent);
        let map = render(&t, t.root(), 100, 50, None);
        assert!(map.owner.iter().all(|&o| o != NONE));
        let a = t.nodes.iter().position(|n| &*n.name == "a.bin").unwrap() as u32;
        let share = map.owner.iter().filter(|&&o| o == a).count() as f64 / 5000.0;
        let want = 600_000.0 / t.node(t.root()).children.iter().map(|&c| t.node(c).apparent as f64).sum::<f64>();
        assert!((share - want).abs() < 0.03, "{share} vs {want}");
    }

    #[test]
    fn the_largest_type_gets_the_first_colour() {
        assert_eq!(ext_color(0), PALETTE[0]);
        assert_eq!(ext_color(99), OTHER);
        assert_eq!(ext_color(NONE), OTHER);
    }
}
