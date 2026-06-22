//! FP8 (E4M3 and E5M2) quantization & dequantization utilities.
use anyhow::{bail, Result};

pub const QATQ_PHASE2_STORAGE: &str = "qatq-phase2";
pub const QATQ_EXACT_F32LE_STORAGE: &str = "qatq-exact-f32le";
pub const RAW_F32LE_PASS_THROUGH_STORAGE: &str = "raw-f32le-pass-through";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct QatqPhase2Transfer {
    pub storage: QatqTransferStorage,
    pub payload: Vec<u8>,
    pub raw_f32le_len: usize,
}

impl QatqPhase2Transfer {
    pub fn storage_name(&self) -> &'static str {
        self.storage.name()
    }

    pub fn strategy_name(&self) -> Option<&'static str> {
        self.storage.strategy_name()
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum QatqTransferStorage {
    QatqPhase2 { strategy: &'static str },
    QatqExactF32Le,
    RawF32LePassThrough,
}

impl QatqTransferStorage {
    pub fn name(&self) -> &'static str {
        match self {
            Self::QatqPhase2 { .. } => QATQ_PHASE2_STORAGE,
            Self::QatqExactF32Le => QATQ_EXACT_F32LE_STORAGE,
            Self::RawF32LePassThrough => RAW_F32LE_PASS_THROUGH_STORAGE,
        }
    }

    pub fn strategy_name(&self) -> Option<&'static str> {
        match self {
            Self::QatqPhase2 { strategy } => Some(strategy),
            Self::QatqExactF32Le => Some("qatq-exact"),
            Self::RawF32LePassThrough => None,
        }
    }
}

/// Convert f32 to FP8 E4M3 (1 sign, 4 exponent, 3 mantissa, bias = 7)
pub fn f32_to_e4m3(val: f32) -> u8 {
    if val == 0.0 {
        return 0;
    }
    if val.is_nan() {
        return 0x7f;
    }

    let sign = if val.is_sign_negative() { 0x80 } else { 0x00 };
    let abs_val = val.abs();

    // Max representable value in E4M3 is 448.0
    if abs_val >= 448.0 {
        return sign | 0x7e; // clamp to max positive/negative
    }

    let mut exp = (abs_val.log2().floor() as i32) + 7;
    if exp < 0 {
        // Subnormal range: value is (-1)^s * 2^-6 * (mantissa / 8)
        let mantissa = (abs_val * 512.0).round() as i32;
        let mantissa = mantissa.clamp(0, 7) as u8;
        return sign | mantissa;
    }

    if exp > 15 {
        exp = 15;
    }

    let scale_factor = 2.0f32.powi(exp - 7);
    let mant_val = ((abs_val / scale_factor) - 1.0) * 8.0;
    let mut mantissa = mant_val.round() as i32;

    if mantissa < 0 {
        mantissa = 0;
    }

    if mantissa > 7 {
        if exp == 15 {
            mantissa = 6; // max value
        } else {
            // Re-run with exponent incremented
            return f32_to_e4m3(val.signum() * 2.0f32.powi(exp - 6));
        }
    }

    sign | ((exp as u8) << 3) | (mantissa as u8)
}

/// Convert FP8 E4M3 back to f32
pub fn e4m3_to_f32(byte: u8) -> f32 {
    let sign = if (byte & 0x80) != 0 { -1.0 } else { 1.0 };
    let exp = (byte & 0x78) >> 3;
    let mant = byte & 0x07;

    if exp == 0 {
        // Subnormal: (-1)^s * 2^-6 * (m / 8)
        sign * 2.0f32.powi(-6) * (mant as f32 / 8.0)
    } else if exp == 15 && mant == 7 {
        f32::NAN
    } else {
        // Normal: (-1)^s * 2^(exp - 7) * (1 + m/8)
        sign * 2.0f32.powi(exp as i32 - 7) * (1.0 + mant as f32 / 8.0)
    }
}

/// Convert f32 to FP8 E5M2 (1 sign, 5 exponent, 2 mantissa, bias = 15)
pub fn f32_to_e5m2(val: f32) -> u8 {
    if val == 0.0 {
        return 0;
    }
    if val.is_nan() {
        return 0x7f; // NaN: exp = 31, mant = 3
    }
    let sign = if val.is_sign_negative() { 0x80 } else { 0x00 };
    let abs_val = val.abs();

    if abs_val.is_infinite() {
        return sign | 0x7c; // Inf: exp = 31, mant = 0
    }

    // Max representable value is 57344.0
    if abs_val >= 57344.0 {
        return sign | 0x7c; // Clamp to max/Inf
    }

    let mut exp = (abs_val.log2().floor() as i32) + 15;
    if exp < 0 {
        // Subnormal: (-1)^s * 2^-14 * (m / 4)
        let mantissa = (abs_val * 65536.0).round() as i32;
        let mantissa = mantissa.clamp(0, 3) as u8;
        return sign | mantissa;
    }

    if exp > 30 {
        exp = 30;
    }

    let scale_factor = 2.0f32.powi(exp - 15);
    let mant_val = ((abs_val / scale_factor) - 1.0) * 4.0;
    let mut mantissa = mant_val.round() as i32;

    if mantissa < 0 {
        mantissa = 0;
    }

    if mantissa > 3 {
        if exp == 30 {
            mantissa = 3;
        } else {
            return f32_to_e5m2(val.signum() * 2.0f32.powi(exp - 14));
        }
    }

    sign | ((exp as u8) << 2) | (mantissa as u8)
}

/// Convert FP8 E5M2 back to f32
pub fn e5m2_to_f32(byte: u8) -> f32 {
    let sign = if (byte & 0x80) != 0 { -1.0 } else { 1.0 };
    let exp = (byte & 0x7c) >> 2;
    let mant = byte & 0x03;

    if exp == 0 {
        // Subnormal: (-1)^s * 2^-14 * (m / 4)
        sign * 2.0f32.powi(-14) * (mant as f32 / 4.0)
    } else if exp == 31 {
        if mant == 0 {
            sign * f32::INFINITY
        } else {
            f32::NAN
        }
    } else {
        // Normal: (-1)^s * 2^(exp - 15) * (1 + m/4)
        sign * 2.0f32.powi(exp as i32 - 15) * (1.0 + mant as f32 / 4.0)
    }
}

/// Computes the optimal scale factor to represent the slice in FP8 (E4M3 default)
pub fn compute_optimal_scale(data: &[f32], max_representable: f32) -> f32 {
    let mut max_abs = 0.0f32;
    for &val in data {
        let abs = val.abs();
        if abs > max_abs && !val.is_nan() && !val.is_infinite() {
            max_abs = abs;
        }
    }
    if max_abs == 0.0 {
        1.0
    } else {
        max_abs / max_representable
    }
}

/// Quantizes float data into E4M3 bytes using scaling factor.
pub fn quantize_e4m3_scaled(data: &[f32], scale: f32) -> Vec<u8> {
    data.iter().map(|&x| f32_to_e4m3(x / scale)).collect()
}

/// Dequantizes E4M3 bytes back to float using scaling factor.
pub fn dequantize_e4m3_scaled(data: &[u8], scale: f32) -> Vec<f32> {
    data.iter().map(|&x| e4m3_to_f32(x) * scale).collect()
}

/// Quantizes float data into E5M2 bytes using scaling factor.
pub fn quantize_e5m2_scaled(data: &[f32], scale: f32) -> Vec<u8> {
    data.iter().map(|&x| f32_to_e5m2(x / scale)).collect()
}

/// Dequantizes E5M2 bytes back to float using scaling factor.
pub fn dequantize_e5m2_scaled(data: &[u8], scale: f32) -> Vec<f32> {
    data.iter().map(|&x| e5m2_to_f32(x) * scale).collect()
}

pub fn encode_qatq_phase2_transfer(data: &[f32]) -> Result<QatqPhase2Transfer> {
    encode_qatq_exact_f32le_transfer(data)
}

pub fn encode_qatq_exact_f32le_transfer(data: &[f32]) -> Result<QatqPhase2Transfer> {
    let raw_f32le_len = data.len() * 4;
    let mut bytes = Vec::with_capacity(raw_f32le_len);
    for value in data {
        bytes.extend_from_slice(&value.to_le_bytes());
    }
    let payload = qatq::try_encode_qatq_exact_tensor_le(&bytes, qatq::TensorDType::F32)
        .map_err(|err| anyhow::anyhow!("QATQ exact f32le encode failed: {err}"))?;

    Ok(QatqPhase2Transfer {
        storage: QatqTransferStorage::QatqExactF32Le,
        payload,
        raw_f32le_len,
    })
}

pub fn decode_qatq_phase2_transfer(
    storage: &str,
    payload: &[u8],
    expected_len: usize,
) -> Result<Vec<f32>> {
    match storage {
        QATQ_EXACT_F32LE_STORAGE => {
            let decoded = qatq::decode_qatq_exact_tensor_le(payload)
                .map_err(|err| anyhow::anyhow!("QATQ exact f32le decode failed: {err}"))?;
            if decoded.dtype != qatq::TensorDType::F32 {
                bail!("QATQ exact payload dtype mismatch: expected f32");
            }
            if decoded.bytes_le.len() != expected_len * 4 {
                bail!(
                    "QATQ exact f32le payload length mismatch: expected {} bytes, got {}",
                    expected_len * 4,
                    decoded.bytes_le.len()
                );
            }
            let mut values = Vec::with_capacity(expected_len);
            for chunk in decoded.bytes_le.chunks_exact(4) {
                let bytes: [u8; 4] = chunk.try_into()?;
                values.push(f32::from_le_bytes(bytes));
            }
            Ok(values)
        }
        QATQ_PHASE2_STORAGE => {
            let values = qatq::decode(payload)
                .map_err(|err| anyhow::anyhow!("QATQ phase2 decode failed: {err}"))?;
            ensure_qatq_decoded_len(storage, values, expected_len)
        }
        RAW_F32LE_PASS_THROUGH_STORAGE => {
            if payload.len() != expected_len * 4 {
                bail!(
                    "raw f32le pass-through payload length mismatch: expected {} bytes, got {}",
                    expected_len * 4,
                    payload.len()
                );
            }
            let mut values = Vec::with_capacity(expected_len);
            for chunk in payload.chunks_exact(4) {
                let bytes: [u8; 4] = chunk.try_into()?;
                values.push(f32::from_le_bytes(bytes));
            }
            Ok(values)
        }
        other => bail!("Unsupported QATQ transfer storage: {other}"),
    }
}

fn ensure_qatq_decoded_len(
    storage: &str,
    values: Vec<f32>,
    expected_len: usize,
) -> Result<Vec<f32>> {
    if values.len() != expected_len {
        bail!(
            "{} decoded payload length mismatch: expected {}, got {}",
            storage,
            expected_len,
            values.len()
        );
    }
    Ok(values)
}

/// Experimental Quaternion-Augmented TurboQuant transfer codec.
///
/// This codec treats each consecutive group of four KV values as a quaternion
/// lane and stores signed int4 coefficients packed two per byte with one
/// chunk-level scale. It is intentionally simple and deterministic so E2E
/// validation can measure real transfer/fidelity behavior before a production
/// QATQ codec exists.
pub fn quantize_qatq_i4(data: &[f32]) -> Vec<u8> {
    let scale = compute_optimal_scale(data, 7.0);
    let scale = if scale.is_finite() && scale > 0.0 {
        scale
    } else {
        1.0
    };
    let mut out = Vec::with_capacity(8 + data.len().div_ceil(2));
    out.extend_from_slice(&(data.len() as u32).to_be_bytes());
    out.extend_from_slice(&scale.to_be_bytes());

    let mut index = 0;
    while index < data.len() {
        let first = quantize_i4_nibble(data[index], scale);
        let second = if index + 1 < data.len() {
            quantize_i4_nibble(data[index + 1], scale)
        } else {
            0
        };
        out.push((first << 4) | second);
        index += 2;
    }
    out
}

pub fn dequantize_qatq_i4(data: &[u8], expected_len: usize) -> Result<Vec<f32>> {
    if data.len() < 8 {
        bail!("QATQ payload is too short: {} bytes", data.len());
    }
    let encoded_len = u32::from_be_bytes(data[0..4].try_into()?) as usize;
    if encoded_len != expected_len {
        bail!(
            "QATQ payload length mismatch: expected {}, encoded {}",
            expected_len,
            encoded_len
        );
    }
    let scale = f32::from_be_bytes(data[4..8].try_into()?);
    if !scale.is_finite() || scale <= 0.0 {
        bail!("QATQ payload scale is invalid: {}", scale);
    }
    let packed = &data[8..];
    let needed = expected_len.div_ceil(2);
    if packed.len() != needed {
        bail!(
            "QATQ packed payload length mismatch: expected {}, got {}",
            needed,
            packed.len()
        );
    }
    let mut out = Vec::with_capacity(expected_len);
    for byte in packed {
        out.push(dequantize_i4_nibble(byte >> 4, scale));
        if out.len() < expected_len {
            out.push(dequantize_i4_nibble(byte & 0x0f, scale));
        }
    }
    Ok(out)
}

fn quantize_i4_nibble(value: f32, scale: f32) -> u8 {
    let scaled = if value.is_finite() {
        (value / scale).round()
    } else {
        0.0
    };
    let quantized = (scaled as i32).clamp(-7, 7);
    ((quantized + 8) as u8) & 0x0f
}

fn dequantize_i4_nibble(nibble: u8, scale: f32) -> f32 {
    let signed = ((nibble & 0x0f) as i8) - 8;
    (signed as f32) * scale
}
