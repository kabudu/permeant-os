//! Minimal QATQ compatibility surface used by PermeantOS CI.
//!
//! The full QATQ codec lives in the sibling `qatq` project and is expected to
//! become the real crates.io dependency. Until then, PermeantOS needs a
//! self-contained workspace dependency so public CI can build without an
//! absolute developer-machine path. This shim preserves the exact API surface
//! PermeantOS currently calls and keeps all round trips bit-exact.

use std::fmt;

const MAGIC: &[u8; 4] = b"PQTQ";
const VERSION: u8 = 1;
const MODE_RAW_F32LE: u8 = 1;
const MODE_ZERO_F32: u8 = 2;
const HEADER_LEN: usize = 10;

#[derive(Clone, Copy, Debug, Default)]
pub struct Phase1Config {}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Phase2Strategy {
    BytePlaneBlocks,
}

impl Phase2Strategy {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::BytePlaneBlocks => "byte-plane-blocks",
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Phase2EncodeDecision {
    Compressed {
        payload: Vec<u8>,
        strategy: Phase2Strategy,
        raw_f32le_len: usize,
    },
    PassThroughRaw {
        bytes: Vec<u8>,
    },
}

#[derive(Debug, Eq, PartialEq)]
pub enum QatqError {
    InvalidPayload,
    UnsupportedVersion(u8),
    UnsupportedMode(u8),
    LengthMismatch { expected: usize, actual: usize },
    ValueCountTooLarge(usize),
}

impl fmt::Display for QatqError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidPayload => write!(f, "invalid QATQ compatibility payload"),
            Self::UnsupportedVersion(version) => {
                write!(f, "unsupported QATQ compatibility version {version}")
            }
            Self::UnsupportedMode(mode) => write!(f, "unsupported QATQ compatibility mode {mode}"),
            Self::LengthMismatch { expected, actual } => {
                write!(
                    f,
                    "payload length mismatch: expected {expected}, got {actual}"
                )
            }
            Self::ValueCountTooLarge(count) => write!(f, "value count is too large: {count}"),
        }
    }
}

impl std::error::Error for QatqError {}

pub fn try_encode_phase2_lossless_decision_with_config(
    values: &[f32],
    _config: Phase1Config,
) -> Result<Phase2EncodeDecision, QatqError> {
    let raw_f32le_len = values
        .len()
        .checked_mul(4)
        .ok_or(QatqError::ValueCountTooLarge(values.len()))?;
    if values.iter().all(|value| value.to_bits() == 0) {
        let payload = encode_header(MODE_ZERO_F32, values.len());
        return Ok(Phase2EncodeDecision::Compressed {
            payload,
            strategy: Phase2Strategy::BytePlaneBlocks,
            raw_f32le_len,
        });
    }
    Ok(Phase2EncodeDecision::PassThroughRaw {
        bytes: raw_f32le(values),
    })
}

pub fn decode(payload: &[u8]) -> Result<Vec<f32>, QatqError> {
    if payload.len() < HEADER_LEN || &payload[0..4] != MAGIC {
        return Err(QatqError::InvalidPayload);
    }
    let version = payload[4];
    if version != VERSION {
        return Err(QatqError::UnsupportedVersion(version));
    }
    let mode = payload[5];
    let value_count = u32::from_le_bytes(
        payload[6..10]
            .try_into()
            .map_err(|_| QatqError::InvalidPayload)?,
    ) as usize;
    match mode {
        MODE_ZERO_F32 => {
            if payload.len() != HEADER_LEN {
                return Err(QatqError::LengthMismatch {
                    expected: HEADER_LEN,
                    actual: payload.len(),
                });
            }
            Ok(vec![0.0; value_count])
        }
        MODE_RAW_F32LE => decode_raw_f32le(&payload[HEADER_LEN..], value_count),
        other => Err(QatqError::UnsupportedMode(other)),
    }
}

fn encode_header(mode: u8, value_count: usize) -> Vec<u8> {
    let count =
        u32::try_from(value_count).expect("value count exceeds compatibility payload bound");
    let mut out = Vec::with_capacity(HEADER_LEN);
    out.extend_from_slice(MAGIC);
    out.push(VERSION);
    out.push(mode);
    out.extend_from_slice(&count.to_le_bytes());
    out
}

fn raw_f32le(values: &[f32]) -> Vec<u8> {
    let mut out = Vec::with_capacity(values.len() * 4);
    for value in values {
        out.extend_from_slice(&value.to_le_bytes());
    }
    out
}

fn decode_raw_f32le(payload: &[u8], value_count: usize) -> Result<Vec<f32>, QatqError> {
    let expected = value_count
        .checked_mul(4)
        .ok_or(QatqError::ValueCountTooLarge(value_count))?;
    if payload.len() != expected {
        return Err(QatqError::LengthMismatch {
            expected,
            actual: payload.len(),
        });
    }
    let mut values = Vec::with_capacity(value_count);
    for chunk in payload.chunks_exact(4) {
        values.push(f32::from_le_bytes(
            chunk.try_into().map_err(|_| QatqError::InvalidPayload)?,
        ));
    }
    Ok(values)
}
