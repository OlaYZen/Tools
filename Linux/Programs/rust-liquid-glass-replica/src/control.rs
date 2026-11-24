//! How the settings window talks to the running glass: JSON lines over a Unix socket in the
//! runtime directory. On connect the glass sends its current look and panel size; the window
//! then sends every change, and the glass applies the latest one (throttled: a new look is a new
//! shader for Hyprland to compile).

use std::io::{BufRead, BufReader, Write};
use std::os::unix::net::{UnixListener, UnixStream};
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};

use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};

use crate::config::GlassConfig;

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum Message {
    /// Glass → window, on connect.
    Hello { glass: GlassConfig, width: u32, height: u32 },
    /// Window → glass: the whole look.
    Glass { glass: GlassConfig },
    /// Window → glass: the panel's size, logical px (the shadow padding comes on top).
    Resize { width: u32, height: u32 },
}

/// What the window asked for, waiting for the glass's loop to take it.
#[derive(Debug)]
pub struct Control {
    /// The current look (what a newly opened window starts from).
    pub glass: GlassConfig,
    /// The current panel size.
    pub panel: (u32, u32),
    /// A look not applied yet.
    pub new_glass: Option<GlassConfig>,
    pub resize: Option<(u32, u32)>,
}

pub type SharedControl = Arc<Mutex<Control>>;

pub fn socket_path(dir: &Path) -> PathBuf {
    dir.join("control.sock")
}

/// Listen for settings windows on a thread; `wake` gets a byte for every request.
pub fn serve(dir: &Path, control: SharedControl, wake: UnixStream) -> Result<()> {
    let path = socket_path(dir);
    // Only one glass runs (the lock): a socket file here is a dead run's.
    let _ = std::fs::remove_file(&path);
    let listener = UnixListener::bind(&path).with_context(|| format!("binding {}", path.display()))?;
    std::thread::Builder::new().name("control".into()).spawn(move || {
        for stream in listener.incoming().flatten() {
            let (control, wake) = (control.clone(), wake.try_clone());
            let Ok(wake) = wake else { continue };
            std::thread::spawn(move || client(stream, &control, wake));
        }
    })?;
    Ok(())
}

fn client(mut stream: UnixStream, control: &SharedControl, mut wake: UnixStream) {
    let hello = {
        let Ok(c) = control.lock() else { return };
        Message::Hello { glass: c.glass.clone(), width: c.panel.0, height: c.panel.1 }
    };
    if send(&mut stream, &hello).is_err() {
        return;
    }
    let Ok(read) = stream.try_clone() else { return };
    for line in BufReader::new(read).lines() {
        let Ok(line) = line else { return };
        let Ok(message) = serde_json::from_str::<Message>(&line) else { continue };
        if let Ok(mut c) = control.lock() {
            match message {
                Message::Glass { glass } => c.new_glass = Some(glass),
                Message::Resize { width, height } => c.resize = Some((width, height)),
                Message::Hello { .. } => continue,
            }
        }
        let _ = wake.write(&[1]);
    }
}

pub fn send(stream: &mut UnixStream, message: &Message) -> Result<()> {
    let mut line = serde_json::to_string(message)?;
    line.push('\n');
    stream.write_all(line.as_bytes())?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn messages_are_tagged_json_lines() {
        let m = Message::Resize { width: 300, height: 80 };
        let text = serde_json::to_string(&m).unwrap();
        assert_eq!(text, r#"{"type":"resize","width":300,"height":80}"#);
        assert_eq!(serde_json::from_str::<Message>(&text).unwrap(), m);
    }
}
