//! diskmap: a disk usage analyzer for the terminal.

mod app;
mod ui;

use std::path::PathBuf;
use std::process::ExitCode;

use ratatui::crossterm::event::{DisableMouseCapture, EnableMouseCapture};
use ratatui::crossterm::execute;

use crate::app::App;
use diskmap::scan::Options;

const USAGE: &str = "\
Usage: diskmap [OPTIONS] [PATH]

Scans PATH (default: the current directory) and shows where the space went:
the folders sorted by size, the file types and a treemap. It only reads.

Options:
  -x, --cross-filesystems  Also scan other filesystems mounted below PATH
  -h, --help               Print this help
  -V, --version            Print the version

Inside, press ? for the keys.";

fn main() -> ExitCode {
    let mut path = None;
    let mut opts = Options { cross_filesystems: false };
    for arg in std::env::args_os().skip(1) {
        match arg.to_str() {
            Some("-h" | "--help") => {
                println!("{USAGE}");
                return ExitCode::SUCCESS;
            }
            Some("-V" | "--version") => {
                println!("diskmap {}", env!("CARGO_PKG_VERSION"));
                return ExitCode::SUCCESS;
            }
            Some("-x" | "--cross-filesystems") => opts.cross_filesystems = true,
            Some(s) if s.starts_with('-') && s.len() > 1 => {
                eprintln!("diskmap: unknown option {s}\n\n{USAGE}");
                return ExitCode::from(2);
            }
            _ if path.is_none() => path = Some(PathBuf::from(arg)),
            _ => {
                eprintln!("diskmap: one path at a time\n\n{USAGE}");
                return ExitCode::from(2);
            }
        }
    }
    let path = path.unwrap_or_else(|| PathBuf::from("."));
    let path = match std::fs::canonicalize(&path) {
        Ok(p) => p,
        Err(e) => {
            eprintln!("diskmap: {}: {e}", path.display());
            return ExitCode::FAILURE;
        }
    };
    match run(path, opts) {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("diskmap: {e}");
            ExitCode::FAILURE
        }
    }
}

fn run(path: PathBuf, opts: Options) -> std::io::Result<()> {
    let mut terminal = ratatui::init();
    execute!(std::io::stdout(), EnableMouseCapture)?;
    let mut app = App::new(path, opts);
    let result = (|| {
        while !app.quit {
            terminal.draw(|f| ui::draw(f, &mut app))?;
            app.wait_event()?;
        }
        Ok(())
    })();
    app.cancel_scan();
    let _ = execute!(std::io::stdout(), DisableMouseCapture);
    ratatui::restore();
    result
}
