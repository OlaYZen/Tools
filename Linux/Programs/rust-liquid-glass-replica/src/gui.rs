//! The settings window: sliders for every parameter of the look, applied to the running glass
//! as they move. Opened by right-clicking the glass, or `liquid-glass --settings`.

use std::io::{BufRead, BufReader};
use std::os::unix::net::UnixStream;
use std::path::Path;
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};

use anyhow::{Context, Result, anyhow, bail};
use eframe::egui;

use crate::config::{self, Bevel, GlassConfig};
use crate::control::{self, Message};

pub const APP_ID: &str = "liquid-glass-settings";

pub fn run(dir: &Path) -> Result<()> {
    let stream = UnixStream::connect(control::socket_path(dir)).context("liquid-glass isn't running; start it first")?;
    let mut reader = BufReader::new(stream.try_clone()?);
    let mut line = String::new();
    reader.read_line(&mut line)?;
    let Message::Hello { glass, width, height } = serde_json::from_str(&line)? else { bail!("unexpected first message: {line}") };
    let gone = Arc::new(AtomicBool::new(false));
    let options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default().with_app_id(APP_ID).with_title("Liquid Glass").with_inner_size([360.0, 720.0]),
        ..Default::default()
    };
    let size = (width, height);
    let app = Settings {
        sent: glass.clone(),
        settled: glass.clone(),
        glass,
        size,
        sent_size: size,
        settled_size: size,
        history: Vec::new(),
        stream: Some(stream.try_clone()?),
        gone: gone.clone(),
        status: String::new(),
    };
    eframe::run_native(
        "Liquid Glass",
        options,
        Box::new(move |cc| {
            // The glass closing the socket (it quit) closes the window: wake it to notice.
            let ctx = cc.egui_ctx.clone();
            std::thread::spawn(move || {
                let mut sink = String::new();
                while matches!(reader.read_line(&mut sink), Ok(n) if n > 0) {
                    sink.clear();
                }
                gone.store(true, Ordering::Relaxed);
                ctx.request_repaint();
            });
            Ok(Box::new(app))
        }),
    )
    .map_err(|e| anyhow!("{e}"))
}

struct Settings {
    glass: GlassConfig,
    /// What the glass has: only differences are sent.
    sent: GlassConfig,
    size: (u32, u32),
    sent_size: (u32, u32),
    /// The look and size when nothing was being dragged: a drag becomes one undo step.
    settled: GlassConfig,
    settled_size: (u32, u32),
    /// What Undo goes back through, newest last.
    history: Vec<Step>,
    stream: Option<UnixStream>,
    gone: Arc<AtomicBool>,
    status: String,
}

/// One undoable change: what was there before it.
#[derive(Debug)]
enum Step {
    Look(GlassConfig),
    Size((u32, u32)),
    /// "Save as default": the saved file before (`None`: there was none).
    Save(Option<String>),
}

/// Undo steps kept.
const HISTORY: usize = 200;

impl Settings {
    fn push(&mut self, step: Step) {
        self.history.push(step);
        if self.history.len() > HISTORY {
            self.history.remove(0);
        }
    }

    /// Record a finished change (a drag counts once, when it ends).
    fn settle(&mut self, dragging: bool) {
        if dragging {
            return;
        }
        if self.glass != self.settled {
            let before = std::mem::replace(&mut self.settled, self.glass.clone());
            self.push(Step::Look(before));
        }
        if self.size != self.settled_size {
            let before = std::mem::replace(&mut self.settled_size, self.size);
            self.push(Step::Size(before));
        }
    }

    fn undo(&mut self) {
        // A change still being made is undone first.
        if self.glass != self.settled || self.size != self.settled_size {
            self.glass = self.settled.clone();
            self.size = self.settled_size;
            return;
        }
        match self.history.pop() {
            Some(Step::Look(g)) => {
                self.glass = g.clone();
                self.settled = g;
                self.status.clear();
            }
            Some(Step::Size(s)) => {
                self.size = s;
                self.settled_size = s;
            }
            Some(Step::Save(before)) => {
                self.status = match config::restore_saved(before.as_deref()) {
                    Ok(()) if before.is_some() => "Save undone: the previous default is back.".into(),
                    Ok(()) => "Save undone: new glasses start from the built-in defaults again.".into(),
                    Err(e) => format!("Could not undo the save: {e:#}"),
                };
            }
            None => {}
        }
    }

    fn save(&mut self) {
        let before = config::saved_raw();
        self.status = match config::save(&self.glass) {
            Ok(path) => {
                self.push(Step::Save(before));
                format!("Saved to {} (Undo reverts it)", path.display())
            }
            Err(e) => format!("Could not save: {e:#}"),
        };
    }

    fn send(&mut self, message: &Message) {
        let failed = self.stream.as_mut().is_some_and(|s| control::send(s, message).is_err());
        if failed {
            self.stream = None;
            self.gone.store(true, Ordering::Relaxed);
        }
    }
}

fn slider(ui: &mut egui::Ui, value: &mut f32, range: std::ops::RangeInclusive<f32>, label: &str, hint: &str) {
    ui.add(egui::Slider::new(value, range).text(label)).on_hover_text(hint);
}

impl eframe::App for Settings {
    fn ui(&mut self, ui: &mut egui::Ui, _frame: &mut eframe::Frame) {
        if self.gone.load(Ordering::Relaxed) {
            ui.ctx().send_viewport_cmd(egui::ViewportCommand::Close);
            return;
        }
        let dragging = ui.input(|i| i.pointer.any_down());
        let ctrl_z = ui.input_mut(|i| i.consume_key(egui::Modifiers::COMMAND, egui::Key::Z));
        if ctrl_z && !dragging {
            self.undo();
        }
        egui::CentralPanel::default_margins().show(ui, |ui| egui::ScrollArea::vertical().show(ui, |ui| {
            ui.heading("Liquid Glass");
            ui.horizontal(|ui| {
                let can_undo = !self.history.is_empty() || self.glass != self.settled || self.size != self.settled_size;
                if ui.add_enabled(can_undo, egui::Button::new("⟲ Undo")).on_hover_text("undo the last change, or the last save (Ctrl+Z)").clicked() {
                    self.undo();
                }
                ui.separator();
                let button = self.glass.button;
                if ui.button("Defaults").on_hover_text("ybouane/liquidglass's defaults (Undo brings your look back)").clicked() {
                    self.glass = GlassConfig { button, ..GlassConfig::default() };
                }
                if ui.button("iOS").on_hover_text("rim lit, a touch more vibrant").clicked() {
                    self.glass = GlassConfig { button, ..GlassConfig::ios() };
                }
                if ui.button("Saved").on_hover_text("the look saved as default").clicked() {
                    self.glass = config::load_saved().unwrap_or_default();
                }
            });

            let g = &mut self.glass;
            ui.add_space(6.0);
            ui.label(egui::RichText::new("Lens").strong());
            slider(ui, &mut g.refraction, 0.0..=2.0, "Refraction", "how strongly the bevel bends what is behind");
            slider(ui, &mut g.z_radius, 2.0..=120.0, "Bevel depth", "how far in from the edge the surface curves (px)");
            slider(ui, &mut g.corner_radius, 0.0..=300.0, "Corner radius", "px; large values make a capsule");
            egui::ComboBox::from_label("Bevel")
                .selected_text(match g.bevel {
                    Bevel::Pill => "Pill (biconvex)",
                    Bevel::Dome => "Dome (magnifier)",
                })
                .show_ui(ui, |ui| {
                    ui.selectable_value(&mut g.bevel, Bevel::Pill, "Pill (biconvex)");
                    ui.selectable_value(&mut g.bevel, Bevel::Dome, "Dome (magnifier)");
                });

            ui.add_space(6.0);
            ui.label(egui::RichText::new("Light").strong());
            slider(ui, &mut g.chrom_aberration, 0.0..=0.5, "Dispersion", "colour fringing along the rim");
            slider(ui, &mut g.edge_highlight, 0.0..=1.0, "Rim light", "inner glow and edge stroke");
            slider(ui, &mut g.specular, 0.0..=1.0, "Specular", "highlights from the lights above");
            slider(ui, &mut g.fresnel, 0.0..=2.0, "Fresnel", "reflection where the surface tilts away");

            ui.add_space(6.0);
            ui.label(egui::RichText::new("Colour").strong());
            slider(ui, &mut g.saturation, -1.0..=1.0, "Saturation", "-1 grey, 1 vivid");
            slider(ui, &mut g.brightness, -0.5..=0.5, "Brightness", "");
            slider(ui, &mut g.tint_strength, 0.0..=1.0, "Cool tint", "");
            slider(ui, &mut g.opacity, 0.0..=1.0, "Opacity", "");
            slider(ui, &mut g.blur_amount, 0.0..=1.0, "Frost", "background blur; liquid glass is clear (0) — costs GPU");
            slider(ui, &mut g.distortion, 0.0..=1.0, "Distortion", "micro-distortion noise");

            ui.add_space(6.0);
            ui.label(egui::RichText::new("Shadow").strong());
            slider(ui, &mut g.shadow_opacity, 0.0..=1.0, "Opacity", "");
            slider(ui, &mut g.shadow_spread, 0.0..=60.0, "Spread", "px");
            slider(ui, &mut g.shadow_offset_y, -20.0..=20.0, "Offset", "px, downwards");

            ui.add_space(6.0);
            ui.label(egui::RichText::new("Behaviour").strong());
            ui.checkbox(&mut g.button, "Button").on_hover_text("hover brightens, a press flattens the bevel");

            ui.add_space(6.0);
            ui.label(egui::RichText::new("Size").strong());
            ui.add(egui::Slider::new(&mut self.size.0, 32..=1600).text("Width"));
            ui.add(egui::Slider::new(&mut self.size.1, 32..=1000).text("Height"));

            ui.add_space(10.0);
            ui.horizontal(|ui| {
                if ui.button("Save as default").on_hover_text("new glasses start with this look (Undo reverts it)").clicked() {
                    self.save();
                }
                if ui.button("Close").clicked() {
                    ui.ctx().send_viewport_cmd(egui::ViewportCommand::Close);
                }
            });
            if !self.status.is_empty() {
                ui.small(&self.status);
            }
        }));

        self.settle(dragging);
        if self.glass != self.sent {
            self.sent = self.glass.clone();
            let message = Message::Glass { glass: self.glass.clone() };
            self.send(&message);
        }
        if self.size != self.sent_size {
            self.sent_size = self.size;
            let message = Message::Resize { width: self.size.0, height: self.size.1 };
            self.send(&message);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn settings() -> Settings {
        let g = GlassConfig::default();
        Settings {
            sent: g.clone(),
            settled: g.clone(),
            glass: g,
            size: (420, 220),
            sent_size: (420, 220),
            settled_size: (420, 220),
            history: Vec::new(),
            stream: None,
            gone: Arc::new(AtomicBool::new(false)),
            status: String::new(),
        }
    }

    #[test]
    fn a_whole_drag_is_one_undo_step() {
        let mut s = settings();
        for v in [0.8, 0.9, 1.4] {
            s.glass.refraction = v;
            s.settle(true);
        }
        s.settle(false);
        assert_eq!(s.history.len(), 1);
        s.undo();
        assert_eq!(s.glass.refraction, 0.69);
        assert!(s.history.is_empty());
    }

    #[test]
    fn presets_and_sizes_undo_in_order() {
        let mut s = settings();
        s.glass = GlassConfig::ios();
        s.settle(false);
        s.size = (300, 90);
        s.settle(false);
        s.undo();
        assert_eq!(s.size, (420, 220));
        assert_eq!(s.glass, GlassConfig::ios());
        s.undo();
        assert_eq!(s.glass, GlassConfig::default());
    }

    #[test]
    fn undo_mid_drag_first_reverts_the_drag() {
        let mut s = settings();
        s.glass.specular = 0.5;
        s.settle(false);
        s.glass.specular = 0.9;
        s.settle(true);
        s.undo();
        assert_eq!(s.glass.specular, 0.5, "the unfinished change goes first");
        s.undo();
        assert_eq!(s.glass.specular, 0.0);
    }
}
