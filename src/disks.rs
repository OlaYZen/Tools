//! The disks worth offering to scan: one entry per real filesystem, with its size and free
//! space, read from `/proc/self/mountinfo` and `statvfs`.

use std::collections::HashMap;
use std::ffi::CString;
use std::os::unix::ffi::OsStrExt;
use std::path::{Path, PathBuf};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Disk {
    pub mount: PathBuf,
    pub fstype: String,
    pub source: String,
    pub total: u64,
    pub free: u64,
}

/// Filesystems that hold no files of anyone's: kernel views, memory and container layers.
const PSEUDO: [&str; 24] = [
    "proc", "sysfs", "devtmpfs", "devpts", "tmpfs", "ramfs", "securityfs", "cgroup", "cgroup2",
    "pstore", "bpf", "debugfs", "tracefs", "configfs", "fusectl", "mqueue", "hugetlbfs", "autofs",
    "overlay", "squashfs", "efivarfs", "binfmt_misc", "nsfs", "rpc_pipefs",
];

fn unescape(s: &str) -> String {
    s.replace("\\040", " ").replace("\\011", "\t").replace("\\012", "\n").replace("\\134", "\\")
}

/// `(mount point, filesystem id, type, source)` for every mount of a real filesystem.
fn parse(text: &str) -> Vec<(PathBuf, String, String, String)> {
    text.lines().filter_map(|l| {
        let (left, right) = l.split_once(" - ")?;
        let mut f = left.split(' ');
        let id = f.nth(2)?.to_string();
        let point = PathBuf::from(unescape(f.nth(1)?));
        let mut r = right.split(' ');
        let fstype = r.next()?.to_string();
        let source = unescape(r.next().unwrap_or(""));
        let pseudo = PSEUDO.contains(&fstype.as_str()) || fstype.starts_with("fuse.portal")
            || point.starts_with("/proc") || point.starts_with("/sys") || point.starts_with("/run")
            || point.starts_with("/dev") || point.starts_with("/var/lib/docker")
            || point.starts_with("/snap");
        (!pseudo).then_some((point, id, fstype, source))
    }).collect()
}

/// Size and free space of the filesystem holding `path`, in bytes.
pub fn usage(path: &Path) -> Option<(u64, u64)> {
    let c = CString::new(path.as_os_str().as_bytes()).ok()?;
    let mut st: libc::statvfs = unsafe { std::mem::zeroed() };
    // SAFETY: `c` is a valid NUL-terminated path and `st` a properly sized out-parameter.
    if unsafe { libc::statvfs(c.as_ptr(), &mut st) } != 0 {
        return None;
    }
    let frag = st.f_frsize as u64;
    Some((st.f_blocks as u64 * frag, st.f_bavail as u64 * frag))
}

/// One entry per filesystem, at its shortest mount point (so a btrfs root is `/`, not each
/// of its subvolumes), root first and then by mount point.
pub fn list() -> Vec<Disk> {
    let text = std::fs::read_to_string("/proc/self/mountinfo").unwrap_or_default();
    let mut best: HashMap<String, (PathBuf, String, String)> = HashMap::new();
    for (point, id, fstype, source) in parse(&text) {
        let keep = best.get(&id).is_none_or(|(p, _, _)| point.as_os_str().len() < p.as_os_str().len());
        if keep {
            best.insert(id, (point, fstype, source));
        }
    }
    let mut out: Vec<Disk> = best.into_values().filter_map(|(mount, fstype, source)| {
        let (total, free) = usage(&mount)?;
        (total > 0).then_some(Disk { mount, fstype, source, total, free })
    }).collect();
    out.sort_by(|a, b| (a.mount != Path::new("/")).cmp(&(b.mount != Path::new("/"))).then(a.mount.cmp(&b.mount)));
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    const MOUNTINFO: &str = "\
22 1 0:37 /@ / rw - btrfs /dev/nvme0n1p2 rw
23 22 0:37 /@home /home rw - btrfs /dev/nvme0n1p2 rw
24 22 0:59 / /tmp rw - tmpfs tmpfs rw
25 22 0:22 / /proc rw - proc proc rw
26 22 8:17 / /mnt/2tb rw - fuseblk /dev/sdb1 rw
27 22 0:202 / /mnt/Mother\\040load rw - nfs4 192.168.1.3:/storage rw
28 22 0:84 / /var/lib/docker/rootfs/overlayfs/abc rw - overlay overlay rw
";

    #[test]
    fn only_real_filesystems_are_offered() {
        let points: Vec<PathBuf> = parse(MOUNTINFO).into_iter().map(|m| m.0).collect();
        assert_eq!(points, ["/", "/home", "/mnt/2tb", "/mnt/Mother load"].map(PathBuf::from));
    }

    #[test]
    fn the_root_reports_its_size() {
        let (total, free) = usage(Path::new("/")).unwrap();
        assert!(total > 0 && free <= total);
    }
}
