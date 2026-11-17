//! File and folder icons from the desktop's icon theme, chosen the way Dolphin chooses them.
//!
//! An extension is turned into a MIME type with shared-mime-info's `globs2`, the MIME type
//! into icon names (`application-pdf`, then its `generic-icons` entry, then
//! `application-x-generic`), and the first name the theme has wins. The theme is the one KDE
//! is set to (`kdeglobals`, `[Icons] Theme`), else GTK's, else breeze, Dolphin's default. On
//! a dark interface its `-dark` variant is used when there is one, as Plasma does, and
//! `Inherits=` is followed down to `hicolor`.

use std::collections::{HashMap, HashSet};
use std::fs;
use std::path::{Path, PathBuf};

/// Icon sizes, most wanted first. The 32 px Breeze set is the coloured one (blue folders,
/// red PDFs); 16 and 22 are line art meant for a recoloured toolbar.
const SIZES: [&str; 8] = ["32", "48", "64", "24", "22", "scalable", "96", "16"];

pub struct Icons {
    pub theme: String,
    mime: HashMap<String, String>,
    generic: HashMap<String, String>,
    files: HashMap<String, PathBuf>,
}

fn read(path: impl AsRef<Path>) -> String {
    fs::read_to_string(path).unwrap_or_default()
}

fn home() -> Option<PathBuf> {
    std::env::var_os("HOME").map(PathBuf::from).filter(|p| p.is_absolute())
}

fn config_home() -> Option<PathBuf> {
    std::env::var_os("XDG_CONFIG_HOME").map(PathBuf::from).filter(|p| p.is_absolute())
        .or_else(|| home().map(|h| h.join(".config")))
}

fn data_dirs() -> Vec<PathBuf> {
    let mut out = Vec::new();
    if let Some(h) = std::env::var_os("XDG_DATA_HOME").map(PathBuf::from).filter(|p| p.is_absolute())
        .or_else(|| home().map(|h| h.join(".local/share")))
    {
        out.push(h);
    }
    let dirs = std::env::var("XDG_DATA_DIRS").ok().filter(|s| !s.is_empty())
        .unwrap_or_else(|| "/usr/local/share:/usr/share".into());
    out.extend(dirs.split(':').filter(|d| d.starts_with('/')).map(PathBuf::from));
    out
}

/// The value of `key` in `[section]` of an ini-style file.
fn ini_value(text: &str, section: &str, key: &str) -> Option<String> {
    let mut inside = false;
    for line in text.lines().map(str::trim) {
        if line.starts_with('[') {
            inside = line == format!("[{section}]");
        } else if inside && let Some((k, v)) = line.split_once('=')
            && k.trim() == key
        {
            return Some(v.trim().to_string()).filter(|v| !v.is_empty());
        }
    }
    None
}

/// The icon theme the desktop is set to.
pub fn theme_name() -> String {
    let cfg = config_home();
    let kde = cfg.as_ref().and_then(|c| ini_value(&read(c.join("kdeglobals")), "Icons", "Theme"));
    let gtk = || cfg.as_ref().and_then(|c| ini_value(&read(c.join("gtk-3.0/settings.ini")), "Settings",
        "gtk-icon-theme-name"));
    kde.or_else(|| theme_dirs("breeze").first().map(|_| "breeze".to_string())).or_else(gtk)
        .unwrap_or_else(|| "hicolor".into())
}

/// Every installed directory of the theme `name`, user ones first.
fn theme_dirs(name: &str) -> Vec<PathBuf> {
    let mut out: Vec<PathBuf> = Vec::new();
    if let Some(h) = home() {
        out.push(h.join(".icons").join(name));
    }
    out.extend(data_dirs().into_iter().map(|d| d.join("icons").join(name)));
    out.retain(|d| d.join("index.theme").is_file() || d.is_dir() && name == "hicolor");
    out
}

/// `extension -> MIME type` from `globs2`, which lists the strongest match first.
fn parse_globs(text: &str) -> HashMap<String, String> {
    let mut out = HashMap::new();
    for line in text.lines().filter(|l| !l.starts_with('#')) {
        let mut f = line.split(':');
        let (Some(_), Some(mime), Some(pattern)) = (f.next(), f.next(), f.next()) else { continue };
        let Some(ext) = pattern.strip_prefix("*.") else { continue };
        if ext.is_empty() || ext.contains(['*', '?', '[', '.']) {
            continue;
        }
        out.entry(ext.to_lowercase()).or_insert_with(|| mime.to_string());
    }
    out
}

fn parse_pairs(text: &str) -> HashMap<String, String> {
    text.lines().filter_map(|l| l.split_once(':')).map(|(a, b)| (a.to_string(), b.to_string())).collect()
}

/// Ranks a theme subdirectory by the size it holds; `None` for one not worth reading.
fn size_rank(sub: &str) -> Option<usize> {
    if sub.contains('@') {
        return None;
    }
    sub.split('/').find_map(|part| {
        let size = part.split('x').next().unwrap_or(part);
        SIZES.iter().position(|s| *s == size)
    })
}

impl Icons {
    pub fn load(dark: bool) -> Icons {
        let mut theme = theme_name();
        if dark && !theme.ends_with("-dark") && !theme_dirs(&format!("{theme}-dark")).is_empty() {
            theme = format!("{theme}-dark");
        }
        let mut mime = HashMap::new();
        let mut generic = HashMap::new();
        for d in data_dirs().iter().rev() {
            // Later (system) dirs first, so the user's own definitions override them.
            for (k, v) in parse_globs(&read(d.join("mime/globs2"))) {
                mime.insert(k, v);
            }
            generic.extend(parse_pairs(&read(d.join("mime/generic-icons"))));
        }
        let mut icons = Icons { theme: theme.clone(), mime, generic, files: HashMap::new() };
        icons.index(&theme);
        icons
    }

    /// Reads `name` and the themes it inherits, nearest first; a name already found in a
    /// nearer theme is kept.
    fn index(&mut self, name: &str) {
        let mut queue = vec![name.to_string()];
        let mut done = HashSet::new();
        while let Some(t) = queue.first().cloned() {
            queue.remove(0);
            if !done.insert(t.clone()) {
                continue;
            }
            let mut found: HashMap<String, (usize, PathBuf)> = HashMap::new();
            for dir in theme_dirs(&t) {
                let index = read(dir.join("index.theme"));
                let subs: Vec<String> = ini_value(&index, "Icon Theme", "Directories")
                    .map(|d| d.split(',').map(|s| s.trim().to_string()).collect())
                    .unwrap_or_else(|| ["32x32/apps", "32x32/mimetypes", "32x32/places", "scalable/apps",
                        "scalable/mimetypes", "scalable/places"].map(String::from).to_vec());
                for sub in subs {
                    let Some(rank) = size_rank(&sub) else { continue };
                    let Ok(entries) = fs::read_dir(dir.join(&sub)) else { continue };
                    for e in entries.flatten() {
                        let p = e.path();
                        let Some(ext) = p.extension().and_then(|e| e.to_str()) else { continue };
                        if ext != "svg" && ext != "png" {
                            continue;
                        }
                        let Some(stem) = p.file_stem().and_then(|s| s.to_str()) else { continue };
                        let better = found.get(stem).is_none_or(|(r, _)| rank < *r);
                        if better {
                            found.insert(stem.to_string(), (rank, p));
                        }
                    }
                }
                if let Some(parents) = ini_value(&index, "Icon Theme", "Inherits") {
                    queue.extend(parents.split(',').map(|s| s.trim().to_string()));
                }
            }
            for (k, (_, p)) in found {
                self.files.entry(k).or_insert(p);
            }
            if queue.is_empty() && !done.contains("hicolor") {
                queue.push("hicolor".into());
            }
        }
    }

    pub fn named(&self, name: &str) -> Option<&Path> {
        self.files.get(name).map(PathBuf::as_path)
    }

    fn first(&self, names: &[String]) -> Option<&Path> {
        names.iter().find_map(|n| self.named(n))
    }

    /// The MIME type for a lower-case extension, as Dolphin would guess it from the name.
    pub fn mime(&self, ext: &str) -> Option<&str> {
        self.mime.get(ext).map(String::as_str)
    }

    /// The icon for a file with this extension (`""` for none).
    pub fn file(&self, ext: &str) -> Option<&Path> {
        let mut names = Vec::new();
        if let Some(m) = self.mime(ext) {
            names.push(m.replace('/', "-"));
            if let Some(g) = self.generic.get(m) {
                names.push(g.clone());
            }
            if let Some((media, _)) = m.split_once('/') {
                names.push(format!("{media}-x-generic"));
            }
        }
        names.extend(["unknown", "text-x-generic", "application-octet-stream"].map(String::from));
        self.first(&names)
    }

    /// The icon for a folder at `path`: the special ones (home, Downloads, Music) as Dolphin
    /// shows them, and `folder` for the rest.
    pub fn folder(&self, path: &Path) -> Option<&Path> {
        let special = special_folder(path);
        let names: Vec<String> = special.into_iter().map(String::from).chain(["folder".to_string()]).collect();
        self.first(&names)
    }

    pub fn link(&self) -> Option<&Path> {
        self.first(&["inode-symlink".into(), "emblem-symbolic-link".into(), "unknown".into()])
    }

    pub fn other(&self) -> Option<&Path> {
        self.first(&["unknown".into(), "application-octet-stream".into()])
    }
}

/// The icon name Dolphin gives a well-known folder, if `path` is one.
fn special_folder(path: &Path) -> Option<&'static str> {
    let home = home()?;
    if path == home {
        return Some("user-home");
    }
    if path == Path::new("/") {
        return Some("folder-root");
    }
    let dirs = read(config_home()?.join("user-dirs.dirs"));
    let names = [
        ("XDG_DESKTOP_DIR", "user-desktop"), ("XDG_DOWNLOAD_DIR", "folder-download"),
        ("XDG_TEMPLATES_DIR", "folder-templates"), ("XDG_PUBLICSHARE_DIR", "folder-public"),
        ("XDG_DOCUMENTS_DIR", "folder-documents"), ("XDG_MUSIC_DIR", "folder-music"),
        ("XDG_PICTURES_DIR", "folder-pictures"), ("XDG_VIDEOS_DIR", "folder-videos"),
        ("XDG_PROJECTS_DIR", "folder-development"),
    ];
    for line in dirs.lines() {
        let Some((key, value)) = line.split_once('=') else { continue };
        let value = value.trim().trim_matches('"');
        let dir = match value.strip_prefix("$HOME") {
            Some(rest) => home.join(rest.trim_start_matches('/')),
            None => PathBuf::from(value),
        };
        if dir == path && dir != home {
            return names.iter().find(|(k, _)| *k == key.trim()).map(|(_, n)| *n);
        }
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn globs_take_the_strongest_simple_pattern() {
        let g = parse_globs("# comment\n50:application/pdf:*.pdf\n50:video/mp4:*.MP4\n10:text/x-foo:*.pdf\n\
            50:application/x-compressed-tar:*.tar.gz\n50:text/x-readme:README*\n");
        assert_eq!(g.get("pdf").map(String::as_str), Some("application/pdf"));
        assert_eq!(g.get("mp4").map(String::as_str), Some("video/mp4"));
        assert!(!g.contains_key("tar.gz") && !g.contains_key("gz"));
        assert_eq!(g.len(), 2);
    }

    #[test]
    fn coloured_sizes_rank_first_and_hidpi_copies_are_skipped() {
        assert!(size_rank("places/32").unwrap() < size_rank("places/16").unwrap());
        assert!(size_rank("32x32/apps").unwrap() < size_rank("scalable/apps").unwrap());
        assert_eq!(size_rank("places/32@2x"), None);
        assert_eq!(size_rank("places/128"), None);
    }

    #[test]
    fn ini_values_are_read_from_their_section() {
        let t = "[General]\nTheme=nope\n[Icons]\nTheme=breeze-dark\n";
        assert_eq!(ini_value(t, "Icons", "Theme").as_deref(), Some("breeze-dark"));
        assert_eq!(ini_value(t, "General", "Missing"), None);
    }

    #[test]
    fn the_installed_theme_answers_common_types() {
        // Only meaningful where an icon theme is installed, as on any desktop.
        let icons = Icons::load(true);
        if icons.named("folder").is_none() {
            return;
        }
        assert!(icons.file("pdf").is_some());
        assert!(icons.file("").is_some());
        assert!(icons.folder(Path::new("/tmp")).is_some());
    }
}
