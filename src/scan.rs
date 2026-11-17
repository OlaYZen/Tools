//! The scan: a parallel walk of one directory into a size-sorted tree.
//!
//! Each directory is one `rayon` task. The walk returns a nested `Raw` tree with sizes summed
//! on the way back up, which `Tree::build` then flattens into an arena of `Node`s whose
//! children are sorted largest first.

use std::collections::{HashMap, HashSet};
use std::ffi::OsStr;
use std::fs;
use std::os::unix::fs::MetadataExt;
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};

use rayon::prelude::*;

pub const NONE: u32 = u32::MAX;

/// Which size the tree is counted and sorted by.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Measure {
    /// `st_blocks × 512`, what fills the disk.
    Allocated,
    /// `st_size`, the length of the file.
    Apparent,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Kind {
    Dir,
    File,
    Link,
    Other,
}

#[derive(Debug, Clone)]
pub struct Node {
    pub name: Box<str>,
    pub parent: u32,
    pub children: Vec<u32>,
    pub kind: Kind,
    pub allocated: u64,
    pub apparent: u64,
    /// Files (anything not a directory) in this subtree, itself included.
    pub files: u64,
    /// Index into `Tree::exts`, for files; `NONE` otherwise.
    pub ext: u32,
}

impl Node {
    pub fn size(&self, m: Measure) -> u64 {
        match m {
            Measure::Allocated => self.allocated,
            Measure::Apparent => self.apparent,
        }
    }
}

/// One file type, by lower-case extension; `""` is files without one.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Ext {
    pub name: String,
    pub allocated: u64,
    pub apparent: u64,
    pub files: u64,
}

impl Ext {
    pub fn size(&self, m: Measure) -> u64 {
        match m {
            Measure::Allocated => self.allocated,
            Measure::Apparent => self.apparent,
        }
    }
}

/// Counters the screen reads while the scan runs, and the flag that stops it.
#[derive(Default)]
pub struct Progress {
    pub files: AtomicU64,
    pub dirs: AtomicU64,
    pub bytes: AtomicU64,
    pub errors: AtomicU64,
    pub cancel: AtomicBool,
}

#[derive(Debug, Clone, Copy)]
pub struct Options {
    pub cross_filesystems: bool,
}

pub struct Tree {
    pub root_path: PathBuf,
    pub nodes: Vec<Node>,
    pub exts: Vec<Ext>,
    pub errors: u64,
    pub measure: Measure,
}

struct Raw {
    name: Box<str>,
    kind: Kind,
    allocated: u64,
    apparent: u64,
    files: u64,
    ext: Option<Box<str>>,
    children: Vec<Raw>,
}

struct Ctx<'a> {
    opts: Options,
    dev: u64,
    seen: Mutex<HashSet<(u64, u64)>>,
    progress: &'a Progress,
}

fn ext_of(name: &OsStr) -> Box<str> {
    let p = Path::new(name);
    match p.extension() {
        // A dotfile (".bashrc") has no extension: `Path` already says so.
        Some(e) => e.to_string_lossy().to_lowercase().into_boxed_str(),
        None => "".into(),
    }
}

fn name_of(path: &Path) -> Box<str> {
    path.file_name().map(|n| n.to_string_lossy().into_owned())
        .unwrap_or_else(|| path.to_string_lossy().into_owned()).into_boxed_str()
}

fn entry(ctx: &Ctx, path: &Path, md: &fs::Metadata) -> Raw {
    let name = name_of(path);
    let ft = md.file_type();
    if ft.is_dir() {
        if ctx.opts.cross_filesystems || md.dev() == ctx.dev {
            return walk(ctx, path, name, md);
        }
        // Another filesystem: shown, but empty and not entered.
        return Raw { name, kind: Kind::Dir, allocated: 0, apparent: 0, files: 0, ext: None,
            children: Vec::new() };
    }
    ctx.progress.files.fetch_add(1, Ordering::Relaxed);
    let kind = if ft.is_file() { Kind::File } else if ft.is_symlink() { Kind::Link } else { Kind::Other };
    let mut allocated = md.blocks() * 512;
    let mut apparent = md.size();
    // A hard-linked file counts once, at the first path met.
    if kind == Kind::File && md.nlink() > 1 {
        let fresh = ctx.seen.lock().unwrap_or_else(|e| e.into_inner()).insert((md.dev(), md.ino()));
        if !fresh {
            allocated = 0;
            apparent = 0;
        }
    }
    ctx.progress.bytes.fetch_add(allocated, Ordering::Relaxed);
    let ext = (kind == Kind::File).then(|| ext_of(path.file_name().unwrap_or_default()));
    Raw { name, kind, allocated, apparent, files: 1, ext, children: Vec::new() }
}

fn walk(ctx: &Ctx, path: &Path, name: Box<str>, md: &fs::Metadata) -> Raw {
    ctx.progress.dirs.fetch_add(1, Ordering::Relaxed);
    let mut raw = Raw { name, kind: Kind::Dir, allocated: md.blocks() * 512, apparent: md.size(),
        files: 0, ext: None, children: Vec::new() };
    if ctx.progress.cancel.load(Ordering::Relaxed) {
        return raw;
    }
    let paths: Vec<PathBuf> = match fs::read_dir(path) {
        Ok(rd) => rd.filter_map(|e| match e {
            Ok(e) => Some(e.path()),
            Err(_) => {
                ctx.progress.errors.fetch_add(1, Ordering::Relaxed);
                None
            }
        }).collect(),
        Err(_) => {
            ctx.progress.errors.fetch_add(1, Ordering::Relaxed);
            return raw;
        }
    };
    raw.children = paths.par_iter().filter_map(|p| match fs::symlink_metadata(p) {
        Ok(md) => Some(entry(ctx, p, &md)),
        Err(_) => {
            ctx.progress.errors.fetch_add(1, Ordering::Relaxed);
            None
        }
    }).collect();
    for c in &raw.children {
        raw.allocated += c.allocated;
        raw.apparent += c.apparent;
        raw.files += c.files;
    }
    raw
}

/// Scans `root`, following it if it is itself a symbolic link, and nothing below.
pub fn scan(root: &Path, opts: Options, progress: &Progress) -> std::io::Result<Tree> {
    let md = fs::metadata(root)?;
    let ctx = Ctx { opts, dev: md.dev(), seen: Mutex::new(HashSet::new()), progress };
    let raw = if md.is_dir() {
        walk(&ctx, root, root.to_string_lossy().into_owned().into_boxed_str(), &md)
    } else {
        entry(&ctx, root, &md)
    };
    let errors = progress.errors.load(Ordering::Relaxed);
    Ok(Tree::build(root.to_path_buf(), raw, errors))
}

impl Tree {
    fn build(root_path: PathBuf, raw: Raw, errors: u64) -> Tree {
        let mut tree = Tree { root_path, nodes: Vec::new(), exts: Vec::new(), errors,
            measure: Measure::Allocated };
        let mut ext_ids: HashMap<Box<str>, u32> = HashMap::new();
        // Depth first with an explicit stack: a deep tree cannot overflow the call stack.
        let mut stack = vec![(raw, NONE)];
        while let Some((mut r, parent)) = stack.pop() {
            let id = tree.nodes.len() as u32;
            let ext = match r.ext.take() {
                Some(e) => {
                    let next = ext_ids.len() as u32;
                    let i = *ext_ids.entry(e.clone()).or_insert(next);
                    if i as usize == tree.exts.len() {
                        tree.exts.push(Ext { name: e.into(), allocated: 0, apparent: 0, files: 0 });
                    }
                    let x = &mut tree.exts[i as usize];
                    x.allocated += r.allocated;
                    x.apparent += r.apparent;
                    x.files += 1;
                    i
                }
                None => NONE,
            };
            tree.nodes.push(Node { name: r.name, parent, children: Vec::new(), kind: r.kind,
                allocated: r.allocated, apparent: r.apparent, files: r.files, ext });
            if parent != NONE {
                tree.nodes[parent as usize].children.push(id);
            }
            for c in r.children.drain(..) {
                stack.push((c, id));
            }
        }
        tree.sort(Measure::Allocated);
        tree
    }

    /// Re-sorts every folder's children, and the file types, largest first by `m`.
    pub fn sort(&mut self, m: Measure) {
        self.measure = m;
        let mut kids: Vec<Vec<u32>> =
            self.nodes.iter_mut().map(|n| std::mem::take(&mut n.children)).collect();
        for k in &mut kids {
            k.sort_by(|&a, &b| {
                let (a, b) = (&self.nodes[a as usize], &self.nodes[b as usize]);
                b.size(m).cmp(&a.size(m)).then_with(|| a.name.cmp(&b.name))
            });
        }
        for (n, k) in self.nodes.iter_mut().zip(kids) {
            n.children = k;
        }
        self.ext_order_by(m);
    }

    fn ext_order_by(&mut self, m: Measure) {
        // Ext indices are stored on nodes, so the order lives in a separate permutation.
        let mut order: Vec<u32> = (0..self.exts.len() as u32).collect();
        order.sort_by(|&a, &b| {
            let (a, b) = (&self.exts[a as usize], &self.exts[b as usize]);
            b.size(m).cmp(&a.size(m)).then_with(|| a.name.cmp(&b.name))
        });
        let mut remap = vec![0u32; order.len()];
        for (new, &old) in order.iter().enumerate() {
            remap[old as usize] = new as u32;
        }
        let mut exts = std::mem::take(&mut self.exts);
        let mut sorted: Vec<Option<Ext>> = exts.drain(..).map(Some).collect();
        self.exts = order.iter().map(|&o| sorted[o as usize].take().expect("each once")).collect();
        for n in &mut self.nodes {
            if n.ext != NONE {
                n.ext = remap[n.ext as usize];
            }
        }
    }

    pub fn root(&self) -> u32 {
        0
    }

    pub fn node(&self, id: u32) -> &Node {
        &self.nodes[id as usize]
    }

    /// The full path of a node, from the scanned root.
    pub fn path(&self, id: u32) -> PathBuf {
        let mut parts = Vec::new();
        let mut cur = id;
        while cur != self.root() && cur != NONE {
            parts.push(&*self.nodes[cur as usize].name);
            cur = self.nodes[cur as usize].parent;
        }
        let mut p = self.root_path.clone();
        for part in parts.iter().rev() {
            p.push(part);
        }
        p
    }

    /// Ancestors of `id` from the root down, `id` excluded.
    pub fn ancestors(&self, id: u32) -> Vec<u32> {
        let mut out = Vec::new();
        let mut cur = self.nodes[id as usize].parent;
        while cur != NONE {
            out.push(cur);
            cur = self.nodes[cur as usize].parent;
        }
        out.reverse();
        out
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    fn file(dir: &Path, name: &str, len: usize) {
        let mut f = fs::File::create(dir.join(name)).unwrap();
        f.write_all(&vec![7u8; len]).unwrap();
    }

    fn find(t: &Tree, name: &str) -> u32 {
        t.nodes.iter().position(|n| &*n.name == name).expect(name) as u32
    }

    fn sample() -> (tempfile::TempDir, Tree) {
        let d = tempfile::tempdir().unwrap();
        fs::create_dir(d.path().join("big")).unwrap();
        fs::create_dir(d.path().join("small")).unwrap();
        file(&d.path().join("big"), "a.MKV", 300_000);
        file(&d.path().join("big"), "b.mkv", 100_000);
        file(&d.path().join("small"), "notes.txt", 1_000);
        file(&d.path().join("small"), ".hidden", 10);
        fs::hard_link(d.path().join("big/a.MKV"), d.path().join("small/again.mkv")).unwrap();
        std::os::unix::fs::symlink("big", d.path().join("link")).unwrap();
        let t = scan(d.path(), Options { cross_filesystems: false }, &Progress::default()).unwrap();
        (d, t)
    }

    #[test]
    fn sizes_sum_up_and_hard_links_count_once() {
        let (_d, t) = sample();
        let files: u64 = 300_000 + 100_000 + 1_000 + 10;
        let dirs: u64 = [t.root(), find(&t, "big"), find(&t, "small")].iter()
            .map(|&i| fs::symlink_metadata(t.path(i)).unwrap().size()).sum();
        let link = fs::symlink_metadata(t.path(find(&t, "link"))).unwrap().size();
        assert_eq!(t.node(t.root()).apparent, files + dirs + link);
        assert_eq!(t.node(t.root()).files, 6);
        let a = t.node(find(&t, "a.MKV")).apparent;
        let again = t.node(find(&t, "again.mkv")).apparent;
        assert_eq!(a + again, 300_000);
    }

    #[test]
    fn symlinks_are_not_followed() {
        let (_d, t) = sample();
        let l = t.node(find(&t, "link"));
        assert_eq!(l.kind, Kind::Link);
        assert!(l.children.is_empty());
    }

    #[test]
    fn children_sort_largest_first() {
        let (_d, mut t) = sample();
        for m in [Measure::Apparent, Measure::Allocated] {
            t.sort(m);
            for n in &t.nodes {
                let sizes: Vec<u64> = n.children.iter().map(|&c| t.node(c).size(m)).collect();
                assert!(sizes.windows(2).all(|w| w[0] >= w[1]), "{sizes:?}");
            }
        }
        // Which of "big" and "small" leads depends on which path to the hard-linked file the
        // parallel walk met first; that it is a folder and not a loose file does not.
        t.sort(Measure::Apparent);
        assert_eq!(t.node(t.node(t.root()).children[0]).kind, Kind::Dir);
    }

    #[test]
    fn extensions_are_lower_case_and_dotfiles_have_none() {
        let (_d, mut t) = sample();
        t.sort(Measure::Apparent);
        assert_eq!(t.exts[0].name, "mkv");
        assert_eq!(t.exts[0].files, 3);
        assert_eq!(t.exts[0].apparent, 400_000);
        let none = t.exts.iter().find(|e| e.name.is_empty()).unwrap();
        assert_eq!(none.files, 1);
        let n = t.node(find(&t, "notes.txt"));
        assert_eq!(t.exts[n.ext as usize].name, "txt");
    }

    #[test]
    fn paths_and_ancestors_round_trip() {
        let (d, t) = sample();
        let id = find(&t, "notes.txt");
        assert_eq!(t.path(id), d.path().join("small/notes.txt"));
        let anc = t.ancestors(id);
        assert_eq!(anc, vec![t.root(), find(&t, "small")]);
    }

    #[test]
    fn a_cancelled_scan_stops_early() {
        let (d, _) = sample();
        let p = Progress::default();
        p.cancel.store(true, Ordering::Relaxed);
        let t = scan(d.path(), Options { cross_filesystems: false }, &p).unwrap();
        assert!(t.node(t.root()).children.is_empty());
    }
}
