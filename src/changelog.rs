//! The patch notes, compiled in from `CHANGELOG.md` and parsed for the overlay.
//!
//! The tests below are the format's guard: the build fails when the newest entry is not
//! `Cargo.toml`'s version, an `x.y.0` lacks its title line, a group is unknown, versions
//! are out of order or an em-dash crept in.

pub const SOURCE: &str = include_str!("../CHANGELOG.md");

pub const GROUPS: [&str; 7] =
    ["Added", "Changed", "Security", "Performance", "Stability", "Fixed", "Removed"];

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Release {
    pub version: String,
    pub date: String,
    pub title: Option<String>,
    pub groups: Vec<(String, Vec<String>)>,
}

/// Parses every `## [x.y.z] - date` entry, newest first as written.
pub fn parse(src: &str) -> Vec<Release> {
    let mut out: Vec<Release> = Vec::new();
    for line in src.lines() {
        let line = line.trim_end();
        if let Some(rest) = line.strip_prefix("## [") {
            let Some((version, tail)) = rest.split_once(']') else { continue };
            let date = tail.trim_start_matches(" - ").trim().to_string();
            out.push(Release { version: version.to_string(), date, title: None, groups: Vec::new() });
        } else if let Some(rel) = out.last_mut() {
            if let Some(group) = line.strip_prefix("### ") {
                rel.groups.push((group.trim().to_string(), Vec::new()));
            } else if let Some(item) = line.strip_prefix("- ") {
                if let Some((_, items)) = rel.groups.last_mut() {
                    items.push(item.to_string());
                }
            } else if !line.is_empty() && rel.groups.is_empty() && rel.title.is_none() {
                rel.title = Some(line.to_string());
            }
        }
    }
    out
}

pub fn releases() -> Vec<Release> {
    parse(SOURCE)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn version_key(v: &str) -> Option<(u32, u32, u32)> {
        let mut it = v.split('.').map(|p| p.parse::<u32>().ok());
        Some((it.next()??, it.next()??, it.next()??))
    }

    #[test]
    fn newest_entry_is_the_crate_version() {
        let rel = releases();
        assert_eq!(rel.first().map(|r| r.version.as_str()), Some(env!("CARGO_PKG_VERSION")));
    }

    #[test]
    fn minor_releases_have_a_title() {
        for r in releases() {
            if r.version.ends_with(".0") {
                assert!(r.title.is_some(), "{} has no title line", r.version);
            }
        }
    }

    #[test]
    fn groups_are_known_and_not_empty() {
        for r in releases() {
            assert!(!r.groups.is_empty(), "{} has no groups", r.version);
            let mut last = 0;
            for (g, items) in &r.groups {
                let pos = GROUPS.iter().position(|k| k == g);
                assert!(pos.is_some(), "{}: unknown group {g}", r.version);
                assert!(pos.unwrap() >= last, "{}: group {g} out of order", r.version);
                last = pos.unwrap();
                assert!(!items.is_empty(), "{}: empty group {g}", r.version);
            }
        }
    }

    #[test]
    fn versions_descend_and_dates_are_set() {
        let rel = releases();
        for pair in rel.windows(2) {
            let a = version_key(&pair[0].version).expect("version");
            let b = version_key(&pair[1].version).expect("version");
            assert!(a > b, "{} is not newer than {}", pair[0].version, pair[1].version);
        }
        for r in &rel {
            assert!(r.date.len() >= 10, "{} has no date", r.version);
        }
    }

    #[test]
    fn no_em_dash() {
        assert!(!SOURCE.contains('\u{2014}'), "CHANGELOG.md contains an em-dash");
    }

    #[test]
    fn parses_a_sample() {
        let r = parse("## [1.2.0] - 2026-01-01\n\nTitle\n\n### Added\n- one\n- two\n");
        assert_eq!(r[0].title.as_deref(), Some("Title"));
        assert_eq!(r[0].groups, vec![("Added".to_string(), vec!["one".into(), "two".into()])]);
    }
}
