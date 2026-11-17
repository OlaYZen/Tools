//! diskmap: a disk usage analyzer for the terminal.

mod changelog;
mod scan;

const USAGE: &str = "\
Usage: diskmap [OPTIONS] [PATH]

Scans PATH (default: the current directory) and shows where the space went.

Options:
  -h, --help       Print this help
  -V, --version    Print the version";

fn main() {
    for arg in std::env::args().skip(1) {
        match arg.as_str() {
            "-h" | "--help" => {
                println!("{USAGE}");
                return;
            }
            "-V" | "--version" => {
                println!("diskmap {}", env!("CARGO_PKG_VERSION"));
                return;
            }
            _ => {}
        }
    }
    let notes = changelog::releases();
    let title = notes.first().and_then(|r| r.title.as_deref()).unwrap_or("");
    println!("diskmap {}: {title}", env!("CARGO_PKG_VERSION"));
}
