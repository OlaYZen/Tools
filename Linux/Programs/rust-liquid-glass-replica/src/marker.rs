//! The marker: how the glass tells Hyprland's screen shader where it is.
//!
//! A screen shader takes no inputs of ours, and recompiling it on every move would stall the
//! compositor. So the app draws a strip of coloured blocks in a layer surface at the monitor's
//! top-left corner, and the shader reads them back out of the frame it is shading: the glass's
//! rectangle, its press and hover state, and the windows stacked above it. The shader then
//! paints the strip over with what lies beneath it.
//!
//! Each block is [`BLOCK`] × [`BLOCK`] logical px of one colour, so the compositor's scaling
//! (1.33× here) never blends a block's centre with its neighbours. Numbers are 24-bit, one per
//! block (R, G, B = high to low byte), offset by 2²³ so they can be negative. A magic block
//! leads and a checksum block ends the strip: whatever else is in that corner (nothing of ours
//! after a crash, a notification on top) never passes for a glass.

/// Block side, logical px.
pub const BLOCK: u32 = 4;
/// Windows above the glass the strip can carry.
pub const MAX_OCCLUDERS: usize = 4;
/// Magic, x/y/w/h, state, occluders, checksum.
pub const BLOCKS: usize = 1 + 4 + 1 + 4 * MAX_OCCLUDERS + 1;
pub const MAGIC: [u8; 3] = [0x4c, 0x47, 0x21]; // "LG!"
const CHECK_TAG: u8 = 0xa5;
const OFFSET: i32 = 1 << 23;

/// Everything the shader needs, in physical px relative to the monitor's top-left.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Marker {
    /// The glass window, shadow padding included: x, y, w, h.
    pub window: [i32; 4],
    /// 0–255.
    pub press: u8,
    pub hover: u8,
    pub visible: bool,
    /// Windows stacked above the glass: it is not drawn where they are.
    pub occluders: Vec<[i32; 4]>,
}

fn number(v: i32) -> [u8; 3] {
    let v = (v.clamp(-OFFSET, OFFSET - 1) + OFFSET) as u32;
    [(v >> 16) as u8, (v >> 8) as u8, v as u8]
}

impl Marker {
    /// The strip's blocks, left to right.
    pub fn encode(&self) -> [[u8; 3]; BLOCKS] {
        let mut blocks = [[0u8; 3]; BLOCKS];
        blocks[0] = MAGIC;
        for (i, v) in self.window.iter().enumerate() {
            blocks[1 + i] = number(*v);
        }
        blocks[5] = [self.press, self.hover, u8::from(self.visible)];
        for i in 0..MAX_OCCLUDERS {
            // An empty slot is a rectangle of no size, which covers nothing.
            let r = self.occluders.get(i).copied().unwrap_or([0; 4]);
            for (j, v) in r.iter().enumerate() {
                blocks[6 + 4 * i + j] = number(*v);
            }
        }
        let body = &blocks[1..BLOCKS - 1];
        let sum = body.iter().flatten().fold(0u8, |a, b| a.wrapping_add(*b));
        let xor = body.iter().flatten().fold(0u8, |a, b| a ^ b);
        blocks[BLOCKS - 1] = [sum, xor, CHECK_TAG];
        blocks
    }

    /// The strip as an ARGB8888 buffer (`BLOCKS·BLOCK` × `BLOCK` px), opaque.
    pub fn pixels(&self) -> Vec<u8> {
        let blocks = self.encode();
        let width = BLOCKS * BLOCK as usize;
        let mut out = Vec::with_capacity(width * BLOCK as usize * 4);
        for _ in 0..BLOCK {
            for x in 0..width {
                let [r, g, b] = blocks[x / BLOCK as usize];
                out.extend_from_slice(&[b, g, r, 0xff]);
            }
        }
        out
    }
}

/// What the shader reads back (the Rust twin of `decode` in the GLSL, for the tests).
#[cfg(test)]
fn decode(blocks: &[[u8; 3]; BLOCKS]) -> Option<Marker> {
    if blocks[0] != MAGIC {
        return None;
    }
    let body = &blocks[1..BLOCKS - 1];
    let sum = body.iter().flatten().fold(0u8, |a, b| a.wrapping_add(*b));
    let xor = body.iter().flatten().fold(0u8, |a, b| a ^ b);
    if blocks[BLOCKS - 1] != [sum, xor, CHECK_TAG] {
        return None;
    }
    let n = |i: usize| ((i32::from(blocks[i][0]) << 16) | (i32::from(blocks[i][1]) << 8) | i32::from(blocks[i][2])) - OFFSET;
    let occluders = (0..MAX_OCCLUDERS).map(|i| [n(6 + 4 * i), n(7 + 4 * i), n(8 + 4 * i), n(9 + 4 * i)]).filter(|r| r[2] > 0 && r[3] > 0).collect();
    Some(Marker {
        window: [n(1), n(2), n(3), n(4)],
        press: blocks[5][0],
        hover: blocks[5][1],
        visible: blocks[5][2] & 1 == 1,
        occluders,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_marker_round_trips_including_negative_positions() {
        let m = Marker { window: [-40, 12, 613, 347], press: 200, hover: 9, visible: true, occluders: vec![[100, -5, 50, 60]] };
        assert_eq!(decode(&m.encode()), Some(m));
    }

    #[test]
    fn a_damaged_strip_is_rejected() {
        let mut blocks = Marker { window: [1, 2, 3, 4], visible: true, ..Marker::default() }.encode();
        blocks[2][1] ^= 1;
        assert_eq!(decode(&blocks), None, "a flipped bit must not move the glass");
        let mut blocks = Marker::default().encode();
        blocks[0] = [0, 0, 0];
        assert_eq!(decode(&blocks), None, "no magic, no glass");
    }

    #[test]
    fn pixels_are_whole_blocks_of_bgra() {
        let m = Marker { window: [0, 0, 10, 10], visible: true, ..Marker::default() };
        let px = m.pixels();
        let width = BLOCKS * BLOCK as usize;
        assert_eq!(px.len(), width * BLOCK as usize * 4);
        // The magic block, little-endian ARGB: B, G, R, A.
        assert_eq!(&px[..4], &[MAGIC[2], MAGIC[1], MAGIC[0], 0xff]);
        // Last row, last pixel: the checksum block's tag in B.
        assert_eq!(px[px.len() - 4], CHECK_TAG);
    }
}
