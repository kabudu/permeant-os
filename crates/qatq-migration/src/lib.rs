use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use thiserror::Error;

pub const SCHEMA: &str = "permeantos.qatq-migration.v1";
pub const DEFAULT_CODEC: &str = "qatq-exact";
pub const DEFAULT_CONTAINER: &str = "QATC-v2";

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum MigrationDType {
    F32,
    F16,
    Bf16,
}

impl MigrationDType {
    pub fn element_width(self) -> usize {
        match self {
            Self::F32 => 4,
            Self::F16 | Self::Bf16 => 2,
        }
    }

    fn to_qatq(self) -> qatq::TensorDType {
        match self {
            Self::F32 => qatq::TensorDType::F32,
            Self::F16 => qatq::TensorDType::F16,
            Self::Bf16 => qatq::TensorDType::BF16,
        }
    }

    fn from_qatq(dtype: qatq::TensorDType) -> Self {
        match dtype {
            qatq::TensorDType::F32 => Self::F32,
            qatq::TensorDType::F16 => Self::F16,
            qatq::TensorDType::BF16 => Self::Bf16,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct QatqCodecInfo {
    pub commit: String,
    pub codec: String,
    pub container: String,
    pub max_values_per_chunk: usize,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct RuntimeIdentity {
    pub name: String,
    pub version: String,
    pub model_id: String,
    pub checkpoint_id: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct EndpointIdentity {
    pub instance_id: String,
    pub region: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct QatqArtifactManifest {
    pub name: String,
    pub tensor_kind: String,
    pub dtype: MigrationDType,
    pub byte_order: String,
    pub layout: String,
    pub shape: BTreeMap<String, u64>,
    pub raw_bytes: u64,
    pub encoded_bytes: u64,
    pub raw_sha256: String,
    pub encoded_sha256: String,
    pub uri: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct QatqMigrationManifest {
    pub schema: String,
    pub migration_id: String,
    pub qatq: QatqCodecInfo,
    pub runtime: RuntimeIdentity,
    pub source: EndpointIdentity,
    pub target: EndpointIdentity,
    pub artifacts: Vec<QatqArtifactManifest>,
}

#[derive(Clone, Debug)]
pub struct TensorBundleInput<'a> {
    pub name: &'a str,
    pub tensor_kind: &'a str,
    pub dtype: MigrationDType,
    pub layout: &'a str,
    pub shape: BTreeMap<String, u64>,
    pub uri: &'a str,
    pub bytes_le: &'a [u8],
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EncodedQatqArtifact {
    pub manifest: QatqArtifactManifest,
    pub payload: Vec<u8>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct QatqMigrationLimits {
    pub max_artifacts: usize,
    pub max_raw_bytes: usize,
    pub max_encoded_bytes: usize,
    pub max_shape_dims: usize,
}

impl Default for QatqMigrationLimits {
    fn default() -> Self {
        Self {
            max_artifacts: 64,
            max_raw_bytes: 1 << 30,
            max_encoded_bytes: 1 << 30,
            max_shape_dims: 8,
        }
    }
}

#[derive(Debug, Error)]
pub enum QatqMigrationError {
    #[error("unsupported manifest schema: {0}")]
    UnsupportedSchema(String),
    #[error("unsupported QATQ codec: {0}")]
    UnsupportedCodec(String),
    #[error("unsupported QATQ container: {0}")]
    UnsupportedContainer(String),
    #[error("migration artifact count {actual} exceeds limit {limit}")]
    TooManyArtifacts { actual: usize, limit: usize },
    #[error("{field} must not be empty")]
    EmptyField { field: &'static str },
    #[error("artifact {name} must use little-endian byte order")]
    UnsupportedByteOrder { name: String },
    #[error("artifact {name} has raw size {actual} bytes, exceeding limit {limit}")]
    RawTooLarge {
        name: String,
        actual: usize,
        limit: usize,
    },
    #[error("artifact {name} has encoded size {actual} bytes, exceeding limit {limit}")]
    EncodedTooLarge {
        name: String,
        actual: usize,
        limit: usize,
    },
    #[error("artifact {name} has {actual} shape dimensions, exceeding limit {limit}")]
    TooManyShapeDims {
        name: String,
        actual: usize,
        limit: usize,
    },
    #[error("artifact {name} shape byte count {shape_bytes} does not match raw bytes {raw_bytes}")]
    ShapeByteCountMismatch {
        name: String,
        shape_bytes: u128,
        raw_bytes: u64,
    },
    #[error("artifact {name} encoded size mismatch: manifest {manifest}, payload {payload}")]
    EncodedSizeMismatch {
        name: String,
        manifest: u64,
        payload: usize,
    },
    #[error("artifact {name} encoded checksum mismatch")]
    EncodedChecksumMismatch { name: String },
    #[error("artifact {name} raw checksum mismatch")]
    RawChecksumMismatch { name: String },
    #[error("artifact {name} decoded dtype mismatch: manifest {expected:?}, payload {actual:?}")]
    DTypeMismatch {
        name: String,
        expected: MigrationDType,
        actual: MigrationDType,
    },
    #[error("QATQ codec error: {0}")]
    Codec(String),
}

pub fn default_qatq_info(commit: impl Into<String>, max_values_per_chunk: usize) -> QatqCodecInfo {
    QatqCodecInfo {
        commit: commit.into(),
        codec: DEFAULT_CODEC.to_string(),
        container: DEFAULT_CONTAINER.to_string(),
        max_values_per_chunk,
    }
}

pub fn encode_qatq_artifact(
    input: TensorBundleInput<'_>,
    limits: QatqMigrationLimits,
) -> Result<EncodedQatqArtifact, QatqMigrationError> {
    validate_non_empty("artifact.name", input.name)?;
    validate_non_empty("artifact.tensor_kind", input.tensor_kind)?;
    validate_non_empty("artifact.layout", input.layout)?;
    validate_non_empty("artifact.uri", input.uri)?;
    validate_shape(
        input.name,
        input.dtype,
        &input.shape,
        input.bytes_le.len(),
        limits,
    )?;
    if input.bytes_le.len() > limits.max_raw_bytes {
        return Err(QatqMigrationError::RawTooLarge {
            name: input.name.to_string(),
            actual: input.bytes_le.len(),
            limit: limits.max_raw_bytes,
        });
    }

    let payload = qatq::try_encode_qatq_exact_tensor_le(input.bytes_le, input.dtype.to_qatq())
        .map_err(|error| QatqMigrationError::Codec(error.to_string()))?;
    if payload.len() > limits.max_encoded_bytes {
        return Err(QatqMigrationError::EncodedTooLarge {
            name: input.name.to_string(),
            actual: payload.len(),
            limit: limits.max_encoded_bytes,
        });
    }
    let manifest = QatqArtifactManifest {
        name: input.name.to_string(),
        tensor_kind: input.tensor_kind.to_string(),
        dtype: input.dtype,
        byte_order: "little".to_string(),
        layout: input.layout.to_string(),
        shape: input.shape,
        raw_bytes: input.bytes_le.len() as u64,
        encoded_bytes: payload.len() as u64,
        raw_sha256: sha256_hex(input.bytes_le),
        encoded_sha256: sha256_hex(&payload),
        uri: input.uri.to_string(),
    };
    Ok(EncodedQatqArtifact { manifest, payload })
}

pub fn decode_qatq_artifact(
    artifact: &QatqArtifactManifest,
    payload: &[u8],
    limits: QatqMigrationLimits,
) -> Result<Vec<u8>, QatqMigrationError> {
    validate_artifact_manifest(artifact, limits)?;
    if artifact.encoded_bytes != payload.len() as u64 {
        return Err(QatqMigrationError::EncodedSizeMismatch {
            name: artifact.name.clone(),
            manifest: artifact.encoded_bytes,
            payload: payload.len(),
        });
    }
    if payload.len() > limits.max_encoded_bytes {
        return Err(QatqMigrationError::EncodedTooLarge {
            name: artifact.name.clone(),
            actual: payload.len(),
            limit: limits.max_encoded_bytes,
        });
    }
    if sha256_hex(payload) != artifact.encoded_sha256 {
        return Err(QatqMigrationError::EncodedChecksumMismatch {
            name: artifact.name.clone(),
        });
    }

    let decoded = qatq::decode_qatq_exact_tensor_le(payload)
        .map_err(|error| QatqMigrationError::Codec(error.to_string()))?;
    let actual_dtype = MigrationDType::from_qatq(decoded.dtype);
    if actual_dtype != artifact.dtype {
        return Err(QatqMigrationError::DTypeMismatch {
            name: artifact.name.clone(),
            expected: artifact.dtype,
            actual: actual_dtype,
        });
    }
    if decoded.bytes_le.len() > limits.max_raw_bytes {
        return Err(QatqMigrationError::RawTooLarge {
            name: artifact.name.clone(),
            actual: decoded.bytes_le.len(),
            limit: limits.max_raw_bytes,
        });
    }
    if decoded.bytes_le.len() as u64 != artifact.raw_bytes {
        return Err(QatqMigrationError::ShapeByteCountMismatch {
            name: artifact.name.clone(),
            shape_bytes: decoded.bytes_le.len() as u128,
            raw_bytes: artifact.raw_bytes,
        });
    }
    if sha256_hex(&decoded.bytes_le) != artifact.raw_sha256 {
        return Err(QatqMigrationError::RawChecksumMismatch {
            name: artifact.name.clone(),
        });
    }
    Ok(decoded.bytes_le)
}

pub fn validate_manifest(
    manifest: &QatqMigrationManifest,
    limits: QatqMigrationLimits,
) -> Result<(), QatqMigrationError> {
    if manifest.schema != SCHEMA {
        return Err(QatqMigrationError::UnsupportedSchema(
            manifest.schema.clone(),
        ));
    }
    validate_non_empty("migration_id", &manifest.migration_id)?;
    validate_non_empty("qatq.commit", &manifest.qatq.commit)?;
    if manifest.qatq.codec != DEFAULT_CODEC {
        return Err(QatqMigrationError::UnsupportedCodec(
            manifest.qatq.codec.clone(),
        ));
    }
    if manifest.qatq.container != DEFAULT_CONTAINER {
        return Err(QatqMigrationError::UnsupportedContainer(
            manifest.qatq.container.clone(),
        ));
    }
    if manifest.artifacts.len() > limits.max_artifacts {
        return Err(QatqMigrationError::TooManyArtifacts {
            actual: manifest.artifacts.len(),
            limit: limits.max_artifacts,
        });
    }
    validate_runtime(&manifest.runtime)?;
    validate_endpoint("source", &manifest.source)?;
    validate_endpoint("target", &manifest.target)?;
    for artifact in &manifest.artifacts {
        validate_artifact_manifest(artifact, limits)?;
    }
    Ok(())
}

fn validate_runtime(runtime: &RuntimeIdentity) -> Result<(), QatqMigrationError> {
    validate_non_empty("runtime.name", &runtime.name)?;
    validate_non_empty("runtime.version", &runtime.version)?;
    validate_non_empty("runtime.model_id", &runtime.model_id)?;
    validate_non_empty("runtime.checkpoint_id", &runtime.checkpoint_id)
}

fn validate_endpoint(
    label: &'static str,
    endpoint: &EndpointIdentity,
) -> Result<(), QatqMigrationError> {
    validate_non_empty(
        match label {
            "source" => "source.instance_id",
            _ => "target.instance_id",
        },
        &endpoint.instance_id,
    )?;
    validate_non_empty(
        match label {
            "source" => "source.region",
            _ => "target.region",
        },
        &endpoint.region,
    )
}

fn validate_artifact_manifest(
    artifact: &QatqArtifactManifest,
    limits: QatqMigrationLimits,
) -> Result<(), QatqMigrationError> {
    validate_non_empty("artifact.name", &artifact.name)?;
    validate_non_empty("artifact.tensor_kind", &artifact.tensor_kind)?;
    validate_non_empty("artifact.layout", &artifact.layout)?;
    validate_non_empty("artifact.uri", &artifact.uri)?;
    if artifact.byte_order != "little" {
        return Err(QatqMigrationError::UnsupportedByteOrder {
            name: artifact.name.clone(),
        });
    }
    if artifact.raw_bytes as usize > limits.max_raw_bytes {
        return Err(QatqMigrationError::RawTooLarge {
            name: artifact.name.clone(),
            actual: artifact.raw_bytes as usize,
            limit: limits.max_raw_bytes,
        });
    }
    if artifact.encoded_bytes as usize > limits.max_encoded_bytes {
        return Err(QatqMigrationError::EncodedTooLarge {
            name: artifact.name.clone(),
            actual: artifact.encoded_bytes as usize,
            limit: limits.max_encoded_bytes,
        });
    }
    validate_shape(
        &artifact.name,
        artifact.dtype,
        &artifact.shape,
        artifact.raw_bytes as usize,
        limits,
    )
}

fn validate_shape(
    name: &str,
    dtype: MigrationDType,
    shape: &BTreeMap<String, u64>,
    raw_bytes: usize,
    limits: QatqMigrationLimits,
) -> Result<(), QatqMigrationError> {
    if shape.is_empty() {
        return Err(QatqMigrationError::EmptyField {
            field: "artifact.shape",
        });
    }
    if shape.len() > limits.max_shape_dims {
        return Err(QatqMigrationError::TooManyShapeDims {
            name: name.to_string(),
            actual: shape.len(),
            limit: limits.max_shape_dims,
        });
    }
    let elements = shape.values().try_fold(1_u128, |acc, dim| {
        acc.checked_mul(*dim as u128)
            .ok_or(QatqMigrationError::ShapeByteCountMismatch {
                name: name.to_string(),
                shape_bytes: u128::MAX,
                raw_bytes: raw_bytes as u64,
            })
    })?;
    let shape_bytes = elements * dtype.element_width() as u128;
    if shape_bytes != raw_bytes as u128 {
        return Err(QatqMigrationError::ShapeByteCountMismatch {
            name: name.to_string(),
            shape_bytes,
            raw_bytes: raw_bytes as u64,
        });
    }
    Ok(())
}

fn validate_non_empty(field: &'static str, value: &str) -> Result<(), QatqMigrationError> {
    if value.trim().is_empty() {
        Err(QatqMigrationError::EmptyField { field })
    } else {
        Ok(())
    }
}

pub fn sha256_hex(bytes: &[u8]) -> String {
    let digest = Sha256::digest(bytes);
    format!("sha256:{digest:x}")
}

#[cfg(test)]
mod tests {
    use super::*;

    fn shape() -> BTreeMap<String, u64> {
        BTreeMap::from([
            ("tokens".to_string(), 4),
            ("layers".to_string(), 1),
            ("kv_heads".to_string(), 2),
            ("head_dim".to_string(), 2),
        ])
    }

    fn input<'a>(bytes_le: &'a [u8]) -> TensorBundleInput<'a> {
        TensorBundleInput {
            name: "cache_all",
            tensor_kind: "kv-cache-packed",
            dtype: MigrationDType::F16,
            layout: "packed-layer-major-kv",
            shape: shape(),
            uri: "s3://permeantos-migrations/test/kv/cache_all.qatc",
            bytes_le,
        }
    }

    fn manifest(artifact: QatqArtifactManifest) -> QatqMigrationManifest {
        QatqMigrationManifest {
            schema: SCHEMA.to_string(),
            migration_id: "mig-test".to_string(),
            qatq: default_qatq_info("369d3ee", 65_536),
            runtime: RuntimeIdentity {
                name: "permeantos-runtime".to_string(),
                version: "0.1.0".to_string(),
                model_id: "test-model".to_string(),
                checkpoint_id: "checkpoint-1".to_string(),
            },
            source: EndpointIdentity {
                instance_id: "i-source".to_string(),
                region: "eu-west-2".to_string(),
            },
            target: EndpointIdentity {
                instance_id: "i-target".to_string(),
                region: "eu-west-2".to_string(),
            },
            artifacts: vec![artifact],
        }
    }

    #[test]
    fn exact_f16_artifact_roundtrip_preserves_bytes_and_manifest() {
        let bytes: Vec<u8> = (0_u16..16).flat_map(u16::to_le_bytes).collect();
        let encoded = encode_qatq_artifact(input(&bytes), QatqMigrationLimits::default()).unwrap();
        assert!(encoded.manifest.encoded_bytes > 0);
        assert_eq!(encoded.manifest.raw_sha256, sha256_hex(&bytes));
        assert_eq!(
            encoded.manifest.encoded_sha256,
            sha256_hex(&encoded.payload)
        );

        let decoded = decode_qatq_artifact(
            &encoded.manifest,
            &encoded.payload,
            QatqMigrationLimits::default(),
        )
        .unwrap();
        assert_eq!(decoded, bytes);
        validate_manifest(&manifest(encoded.manifest), QatqMigrationLimits::default()).unwrap();
    }

    #[test]
    fn encoded_checksum_mismatch_aborts_before_decode() {
        let bytes: Vec<u8> = (0_u16..16).flat_map(u16::to_le_bytes).collect();
        let mut encoded =
            encode_qatq_artifact(input(&bytes), QatqMigrationLimits::default()).unwrap();
        encoded.manifest.encoded_sha256 = sha256_hex(b"wrong");

        let error = decode_qatq_artifact(
            &encoded.manifest,
            &encoded.payload,
            QatqMigrationLimits::default(),
        )
        .unwrap_err();
        assert!(matches!(
            error,
            QatqMigrationError::EncodedChecksumMismatch { .. }
        ));
    }

    #[test]
    fn dtype_mismatch_aborts_restore() {
        let bytes: Vec<u8> = (0_u16..16).flat_map(u16::to_le_bytes).collect();
        let mut encoded =
            encode_qatq_artifact(input(&bytes), QatqMigrationLimits::default()).unwrap();
        encoded.manifest.dtype = MigrationDType::Bf16;

        let error = decode_qatq_artifact(
            &encoded.manifest,
            &encoded.payload,
            QatqMigrationLimits::default(),
        )
        .unwrap_err();
        assert!(matches!(error, QatqMigrationError::DTypeMismatch { .. }));
    }

    #[test]
    fn raw_checksum_mismatch_aborts_activation() {
        let bytes: Vec<u8> = (0_u16..16).flat_map(u16::to_le_bytes).collect();
        let mut encoded =
            encode_qatq_artifact(input(&bytes), QatqMigrationLimits::default()).unwrap();
        encoded.manifest.raw_sha256 = sha256_hex(b"wrong");

        let error = decode_qatq_artifact(
            &encoded.manifest,
            &encoded.payload,
            QatqMigrationLimits::default(),
        )
        .unwrap_err();
        assert!(matches!(
            error,
            QatqMigrationError::RawChecksumMismatch { .. }
        ));
    }

    #[test]
    fn encoded_size_limit_rejects_before_allocation_heavy_decode() {
        let bytes: Vec<u8> = (0_u16..16).flat_map(u16::to_le_bytes).collect();
        let encoded = encode_qatq_artifact(input(&bytes), QatqMigrationLimits::default()).unwrap();
        let limits = QatqMigrationLimits {
            max_encoded_bytes: encoded.payload.len() - 1,
            ..QatqMigrationLimits::default()
        };

        let error = decode_qatq_artifact(&encoded.manifest, &encoded.payload, limits).unwrap_err();
        assert!(matches!(error, QatqMigrationError::EncodedTooLarge { .. }));
    }

    #[test]
    fn wrong_shape_byte_count_is_rejected() {
        let bytes: Vec<u8> = (0_u16..16).flat_map(u16::to_le_bytes).collect();
        let mut bad_shape = shape();
        bad_shape.insert("tokens".to_string(), 5);

        let error = encode_qatq_artifact(
            TensorBundleInput {
                shape: bad_shape,
                ..input(&bytes)
            },
            QatqMigrationLimits::default(),
        )
        .unwrap_err();
        assert!(matches!(
            error,
            QatqMigrationError::ShapeByteCountMismatch { .. }
        ));
    }

    #[test]
    fn manifest_validation_rejects_wrong_schema_and_too_many_artifacts() {
        let bytes: Vec<u8> = (0_u16..16).flat_map(u16::to_le_bytes).collect();
        let encoded = encode_qatq_artifact(input(&bytes), QatqMigrationLimits::default()).unwrap();
        let mut wrong_schema_manifest = manifest(encoded.manifest.clone());
        wrong_schema_manifest.schema = "wrong".to_string();
        assert!(matches!(
            validate_manifest(&wrong_schema_manifest, QatqMigrationLimits::default()).unwrap_err(),
            QatqMigrationError::UnsupportedSchema(_)
        ));

        let mut too_many_artifacts_manifest = manifest(encoded.manifest);
        too_many_artifacts_manifest
            .artifacts
            .push(too_many_artifacts_manifest.artifacts[0].clone());
        let limits = QatqMigrationLimits {
            max_artifacts: 1,
            ..QatqMigrationLimits::default()
        };
        assert!(matches!(
            validate_manifest(&too_many_artifacts_manifest, limits).unwrap_err(),
            QatqMigrationError::TooManyArtifacts { .. }
        ));
    }
}
