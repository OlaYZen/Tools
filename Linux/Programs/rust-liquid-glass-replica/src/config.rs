//! Glass parameters and command-line parsing.
//!
//! [`GlassConfig`] mirrors `GlassConfig` in ybouane/liquidglass (`src/defaults.ts`) field for
//! field, with the same defaults, so a look tuned on the web demo carries over unchanged.

use std::path::PathBuf;

use anyhow::{Context, Result, bail};
use serde::{Deserialize, Serialize};

/// How the bevel bends light. Both share one half-circle height profile.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Bevel {
    /// Biconvex pill: refraction at the top and bottom surface.
    Pill,
    /// Plano-convex dome: a magnifier, flat underneath.
    Dome,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct GlassConfig {
    /// Background blur, 0 (sharp) to 1. Liquid glass is clear: 0 by default.
    pub blur_amount: f32,
    /// How strongly the bevel bends what is behind the glass.
    pub refraction: f32,
    /// Colour fringing along the rim.
    pub chrom_aberration: f32,
    /// Inner glow and rim lighting.
    pub edge_highlight: f32,
    /// Blinn-Phong highlights.
    pub specular: f32,
    /// Reflection at grazing angles.
    pub fresnel: f32,
    /// Micro-distortion noise.
    pub distortion: f32,
    /// Corner radius, logical px.
    pub corner_radius: f32,
    /// Bevel depth, logical px: how far in from the edge the surface keeps curving.
    pub z_radius: f32,
    pub opacity: f32,
    /// -1 (grey) to 1 (vivid).
    pub saturation: f32,
    /// Cool blue tint.
    pub tint_strength: f32,
    /// -0.5 to 0.5.
    pub brightness: f32,
    pub shadow_opacity: f32,
    /// Logical px.
    pub shadow_spread: f32,
    /// Logical px.
    pub shadow_offset_y: f32,
    /// Hover brightens, press flattens the bevel.
    pub button: bool,
    pub bevel: Bevel,
}

impl Default for GlassConfig {
    fn default() -> Self {
        Self {
            blur_amount: 0.0,
            refraction: 0.69,
            chrom_aberration: 0.05,
            edge_highlight: 0.05,
            specular: 0.0,
            fresnel: 1.0,
            distortion: 0.0,
            corner_radius: 65.0,
            z_radius: 40.0,
            opacity: 1.0,
            saturation: 0.0,
            tint_strength: 0.0,
            brightness: 0.0,
            shadow_opacity: 0.30,
            shadow_spread: 10.0,
            shadow_offset_y: 1.0,
            button: false,
            bevel: Bevel::Pill,
        }
    }
}

impl GlassConfig {
    /// Closer to iOS 26: the same lens with its rim lit and a touch more vibrancy.
    pub fn ios() -> Self {
        Self { edge_highlight: 0.35, specular: 0.35, saturation: 0.15, brightness: 0.03, ..Self::default() }
    }
}

/// Extra room around the panel for its drop shadow, logical px (`SHADOW_PAD` upstream).
pub const SHADOW_PAD: f32 = 20.0;

/// The Wayland app id, and the class Hyprland matches the window rule on.
pub const APP_ID: &str = "liquid-glass";

#[derive(Clone, Debug)]
pub struct Options {
    pub glass: GlassConfig,
    /// Panel size, logical px (the window adds [`SHADOW_PAD`] on each side).
    pub width: u32,
    pub height: u32,
    /// Skip installing the Hyprland window rule.
    pub no_rule: bool,
    /// Print the generated screen shader and exit.
    pub print_shader: bool,
    /// Open the settings window (for the running glass) instead of a glass.
    pub settings: bool,
}

/// Where "Save as default" keeps the look: `$XDG_CONFIG_HOME/liquid-glass/settings.json`.
pub fn settings_path() -> Option<PathBuf> {
    let base = std::env::var_os("XDG_CONFIG_HOME").map(PathBuf::from).or_else(|| std::env::var_os("HOME").map(|h| PathBuf::from(h).join(".config")))?;
    Some(base.join("liquid-glass").join("settings.json"))
}

/// The saved look, if there is one (unknown or missing fields take the defaults).
pub fn load_saved() -> Option<GlassConfig> {
    let text = std::fs::read_to_string(settings_path()?).ok()?;
    match serde_json::from_str(&text) {
        Ok(g) => Some(g),
        Err(e) => {
            eprintln!("liquid-glass: ignoring saved settings: {e}");
            None
        }
    }
}

/// The saved file as it is now (`None`: nothing saved), to put back with [`restore_saved`].
pub fn saved_raw() -> Option<String> {
    std::fs::read_to_string(settings_path()?).ok()
}

/// Put back what [`saved_raw`] returned: the old file, or no file at all.
pub fn restore_saved(raw: Option<&str>) -> Result<()> {
    restore_at(&settings_path().context("no $HOME")?, raw)
}

fn restore_at(path: &std::path::Path, raw: Option<&str>) -> Result<()> {
    match raw {
        Some(text) => std::fs::write(path, text)?,
        None => match std::fs::remove_file(path) {
            Err(e) if e.kind() != std::io::ErrorKind::NotFound => return Err(e.into()),
            _ => {}
        },
    }
    Ok(())
}

pub fn save(glass: &GlassConfig) -> Result<PathBuf> {
    let path = settings_path().context("no $HOME")?;
    if let Some(dir) = path.parent() {
        std::fs::create_dir_all(dir)?;
    }
    std::fs::write(&path, serde_json::to_string_pretty(glass)?)?;
    Ok(path)
}

impl Default for Options {
    fn default() -> Self {
        Self { glass: GlassConfig::default(), width: 420, height: 220, no_rule: false, print_shader: false, settings: false }
    }
}

pub const USAGE: &str = "\
liquid-glass — a floating pane of liquid glass for Hyprland

USAGE: liquid-glass [OPTIONS]

Window
  --width <px>            panel width, logical px            [420]
  --height <px>           panel height, logical px           [220]
  --no-rule               don't install the Hyprland window rule
  --print-shader          print the generated screen shader and exit
  --settings              open the settings window for the running glass

Glass (names and defaults of ybouane/liquidglass)
  --preset <reference|ios>
  --blur <0..1>           background blur (costs GPU)        [0]
  --refraction <f>        bend strength                      [0.69]
  --chroma <f>            chromatic aberration               [0.05]
  --edge-highlight <f>    rim light / inner glow             [0.05]
  --specular <f>          specular highlights                [0]
  --fresnel <f>           grazing-angle reflection           [1]
  --distortion <f>        micro-distortion noise             [0]
  --radius <px>           corner radius                      [65]
  --z-radius <px>         bevel depth                        [40]
  --opacity <0..1>                                           [1]
  --saturation <-1..1>                                       [0]
  --tint <0..1>           cool glass tint                    [0]
  --brightness <-.5..0.5>                                    [0]
  --shadow-opacity <0..1>                                    [0.3]
  --shadow-spread <px>                                       [10]
  --shadow-offset-y <px>                                     [1]
  --bevel <pill|dome>     dome = magnifier                   [pill]
  --button                hover brightens, press flattens

Drag the glass to move it, drag its shadow to resize, right-click it for settings, Esc or q to
quit. The look starts from the one saved in the settings window, then these flags.
";

/// `None` when `--help` was asked for. Flags apply on top of `base` (the saved look).
pub fn parse(args: impl IntoIterator<Item = String>, base: GlassConfig) -> Result<Option<Options>> {
    let mut o = Options { glass: base, ..Options::default() };
    let mut args = args.into_iter();
    while let Some(flag) = args.next() {
        let mut value = || args.next().with_context(|| format!("{flag} needs a value"));
        let g = &mut o.glass;
        match flag.as_str() {
            "-h" | "--help" => return Ok(None),
            "--button" => g.button = true,
            "--no-rule" => o.no_rule = true,
            "--print-shader" => o.print_shader = true,
            "--settings" => o.settings = true,
            "--preset" => {
                let keep_button = g.button;
                *g = match value()?.as_str() {
                    "reference" => GlassConfig::default(),
                    "ios" => GlassConfig::ios(),
                    other => bail!("unknown preset `{other}` (reference, ios)"),
                };
                g.button = keep_button;
            }
            "--bevel" => {
                g.bevel = match value()?.as_str() {
                    "pill" => Bevel::Pill,
                    "dome" => Bevel::Dome,
                    other => bail!("unknown bevel `{other}` (pill, dome)"),
                }
            }
            "--width" => o.width = number(&flag, &value()?)?,
            "--height" => o.height = number(&flag, &value()?)?,
            _ => {
                let field = match flag.as_str() {
                    "--blur" => &mut g.blur_amount,
                    "--refraction" => &mut g.refraction,
                    "--chroma" => &mut g.chrom_aberration,
                    "--edge-highlight" => &mut g.edge_highlight,
                    "--specular" => &mut g.specular,
                    "--fresnel" => &mut g.fresnel,
                    "--distortion" => &mut g.distortion,
                    "--radius" => &mut g.corner_radius,
                    "--z-radius" => &mut g.z_radius,
                    "--opacity" => &mut g.opacity,
                    "--saturation" => &mut g.saturation,
                    "--tint" => &mut g.tint_strength,
                    "--brightness" => &mut g.brightness,
                    "--shadow-opacity" => &mut g.shadow_opacity,
                    "--shadow-spread" => &mut g.shadow_spread,
                    "--shadow-offset-y" => &mut g.shadow_offset_y,
                    _ => bail!("unknown option `{flag}` (see --help)"),
                };
                *field = number(&flag, &value()?)?;
            }
        }
    }
    if o.width < 16 || o.height < 16 {
        bail!("the panel must be at least 16 × 16");
    }
    Ok(Some(o))
}

fn number<T: std::str::FromStr>(flag: &str, v: &str) -> Result<T> {
    v.parse().ok().with_context(|| format!("{flag}: `{v}` is not a number"))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn args(s: &str) -> Vec<String> {
        s.split_whitespace().map(String::from).collect()
    }

    #[test]
    fn defaults_match_the_reference() {
        let o = parse(args(""), GlassConfig::default()).unwrap().unwrap();
        assert_eq!(o.glass.refraction, 0.69);
        assert_eq!(o.glass.corner_radius, 65.0);
        assert_eq!(o.glass.blur_amount, 0.0);
        assert_eq!(o.glass.bevel, Bevel::Pill);
    }

    #[test]
    fn flags_set_their_field_and_a_preset_keeps_button() {
        let o = parse(args("--button --preset ios --refraction 1.2 --bevel dome --width 300"), GlassConfig::default()).unwrap().unwrap();
        assert!(o.glass.button);
        assert_eq!(o.glass.specular, 0.35);
        assert_eq!(o.glass.refraction, 1.2);
        assert_eq!(o.glass.bevel, Bevel::Dome);
        assert_eq!(o.width, 300);
    }

    #[test]
    fn bad_input_is_refused() {
        let d = GlassConfig::default;
        assert!(parse(args("--refraction"), d()).is_err());
        assert!(parse(args("--refraction x"), d()).is_err());
        assert!(parse(args("--nope 1"), d()).is_err());
        assert!(parse(args("--help"), d()).unwrap().is_none());
    }

    #[test]
    fn undoing_a_save_puts_back_the_old_file_or_none() {
        let path = std::env::temp_dir().join(format!("liquid-glass-test-{}.json", std::process::id()));
        std::fs::write(&path, "new").unwrap();
        restore_at(&path, Some("old")).unwrap();
        assert_eq!(std::fs::read_to_string(&path).unwrap(), "old");
        restore_at(&path, None).unwrap();
        assert!(!path.exists(), "no default before the save: none after undoing it");
        restore_at(&path, None).unwrap();
    }

    #[test]
    fn a_saved_look_round_trips_and_flags_still_win() {
        let saved = GlassConfig { refraction: 1.1, bevel: Bevel::Dome, ..GlassConfig::default() };
        let back: GlassConfig = serde_json::from_str(&serde_json::to_string(&saved).unwrap()).unwrap();
        assert_eq!(back, saved);
        // A file from an older version, missing fields, takes the defaults for them.
        let partial: GlassConfig = serde_json::from_str(r#"{"refraction": 0.5}"#).unwrap();
        assert_eq!(partial, GlassConfig { refraction: 0.5, ..GlassConfig::default() });
        let o = parse(args("--chroma 0.2"), saved).unwrap().unwrap();
        assert_eq!((o.glass.refraction, o.glass.chrom_aberration), (1.1, 0.2));
    }
}
