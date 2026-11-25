use anyhow::{ensure, Context, Result};
use permeant_transpiler::{
    decode_qatq_phase2_transfer, encode_qatq_exact_f32le_transfer, QATQ_EXACT_F32LE_STORAGE,
};
use serde::{Deserialize, Serialize};
use std::collections::HashSet;
use std::fs::{self, File, OpenOptions};
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::time::Instant;
use usxf_core::{compute_sha256, Signature, Signer, SigningKey, VerifyingKey};

#[derive(Clone, Copy, PartialEq, Eq)]
struct WriteLease(u64);

#[derive(Clone, Copy)]
struct RecoveryEpoch(u64);

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Gateway {
    epoch: u64,
    active: bool,
    completed: HashSet<u64>,
    #[serde(default, skip_serializing_if = "HashSet::is_empty")]
    unresolved: HashSet<u64>,
}

impl Gateway {
    fn stage(&self, dir: &Path) -> Result<PathBuf> {
        let staged = dir.join("gateway.next");
        let file = File::create_new(&staged).context("create staged gateway state")?;
        serde_json::to_writer(&file, self).context("serialize gateway state")?;
        file.sync_all().context("sync staged gateway state")?;
        Ok(staged)
    }

    fn persist(&self, dir: &Path) -> Result<()> {
        self.publish(dir)?;
        Self::sync_directory(dir)
    }

    fn publish(&self, dir: &Path) -> Result<()> {
        let staged = self.stage(dir)?;
        fs::rename(staged, dir.join("gateway.json")).context("commit gateway state")?;
        Ok(())
    }

    fn sync_directory(_dir: &Path) -> Result<()> {
        #[cfg(unix)]
        File::open(_dir)?
            .sync_all()
            .context("sync gateway directory")?;
        Ok(())
    }

    fn reopen(dir: &Path) -> Result<Self> {
        const MAX_STATE_BYTES: u64 = 4096;
        let mut bytes = Vec::new();
        File::open(dir.join("gateway.json"))?
            .take(MAX_STATE_BYTES + 1)
            .read_to_end(&mut bytes)?;
        ensure!(
            bytes.len() as u64 <= MAX_STATE_BYTES,
            "gateway state exceeds drill limit"
        );
        serde_json::from_slice(&bytes).context("read persisted gateway state")
    }

    fn new() -> (Self, WriteLease) {
        (
            Self {
                epoch: 0,
                active: true,
                completed: HashSet::new(),
                unresolved: HashSet::new(),
            },
            WriteLease(0),
        )
    }

    fn write(&mut self, lease: WriteLease, operation: u64) -> bool {
        self.active
            && lease.0 == self.epoch
            && !self.unresolved.contains(&operation)
            && self.completed.insert(operation)
    }

    /// Record uncertain work before simulated dispatch. The caller persists it before dispatching.
    fn begin_external_write(&mut self, lease: WriteLease, operation: u64) -> bool {
        self.active
            && lease.0 == self.epoch
            && !self.completed.contains(&operation)
            && self.unresolved.insert(operation)
    }

    /// Apply a positive completion receipt from the pinned tool verifier.
    fn reconcile_completed(
        &mut self,
        operation: u64,
        signature: &Signature,
        tool_key: &VerifyingKey,
        session: &[u8; 16],
    ) -> bool {
        if tool_key
            .verify_strict(&receipt_message(session, operation), signature)
            .is_err()
        {
            return false;
        }
        if !self.unresolved.remove(&operation) {
            return false;
        }
        self.completed.insert(operation)
    }

    fn fence(&mut self) -> Result<RecoveryEpoch> {
        self.active = false;
        self.epoch = self.epoch.checked_add(1).context("write epoch exhausted")?;
        Ok(RecoveryEpoch(self.epoch))
    }

    fn activate_target(
        &mut self,
        recovery: RecoveryEpoch,
        restored: &[u8],
        trusted_digest: &str,
    ) -> Result<WriteLease> {
        ensure!(
            !self.active && recovery.0 == self.epoch,
            "activation requires the current fenced epoch"
        );
        ensure!(
            compute_sha256(restored) == trusted_digest,
            "restored checkpoint digest mismatch"
        );
        self.active = true;
        Ok(WriteLease(self.epoch))
    }
}

fn receipt_message(session: &[u8; 16], operation: u64) -> Vec<u8> {
    let mut message = b"permeantos/integrity-drill/tool-completed/v1\0".to_vec();
    message.extend_from_slice(session);
    message.extend_from_slice(&operation.to_be_bytes());
    message
}

const INTERRUPTED_ACTIVATION_EXIT: i32 = 86;
const INTERRUPTED_COMPLETION_EXIT: i32 = 87;
const DUPLICATE_OPERATION_EXIT: i32 = 88;
const STALE_LEASE_EXIT: i32 = 89;
const FILE_EFFECT: &[u8] = b"permeantos recovery demo: operation 5\n";

pub(super) fn execute_file_effect(dir: &Path) -> Result<()> {
    let _lock = lock_gateway(dir)?;
    let gateway = Gateway::reopen(dir)?;
    if !gateway.active || gateway.epoch != 1 {
        std::process::exit(STALE_LEASE_EXIT);
    }
    ensure!(
        gateway.unresolved.contains(&5),
        "file tool has no recorded intent"
    );
    let path = dir.join("operation-5.effect");
    let mut file = match File::create_new(path) {
        Ok(file) => file,
        Err(error) if error.kind() == io::ErrorKind::AlreadyExists => {
            std::process::exit(DUPLICATE_OPERATION_EXIT);
        }
        Err(error) => return Err(error).context("create file tool effect"),
    };
    file.write_all(FILE_EFFECT)?;
    file.sync_all()?;
    Gateway::sync_directory(dir)
}

fn dispatch_file_effect(dir: &Path) -> Result<std::process::ExitStatus> {
    Command::new(std::env::current_exe()?)
        .arg("integrity-gateway-probe")
        .arg(dir)
        .arg("--file-effect")
        .status()
        .context("dispatch local file tool")
}

fn sign_file_effect(dir: &Path, session: &[u8; 16], tool: &SigningKey) -> Result<Signature> {
    let mut bytes = Vec::new();
    File::open(dir.join("operation-5.effect"))?
        .take((FILE_EFFECT.len() + 1) as u64)
        .read_to_end(&mut bytes)?;
    ensure!(
        bytes == FILE_EFFECT,
        "file tool effect is incomplete or inconsistent"
    );
    Ok(tool.sign(&receipt_message(session, 5)))
}

pub(super) fn run_tool_signer(dir: &Path) -> Result<()> {
    let tool = SigningKey::from_bytes(&rand::random());
    let mut output = io::stdout().lock();
    output.write_all(tool.verifying_key().as_bytes())?;
    output.flush()?;
    let mut session = [0; 16];
    io::stdin().lock().read_exact(&mut session)?;
    let signature = {
        let _lock = lock_gateway(dir)?;
        let gateway = Gateway::reopen(dir)?;
        ensure!(
            !gateway.active && gateway.unresolved.contains(&5),
            "file tool has no fenced unresolved intent"
        );
        sign_file_effect(dir, &session, &tool)?
    };
    output.write_all(&signature.to_bytes())?;
    output.flush()?;
    Ok(())
}

struct ToolSigner(Child);

impl ToolSigner {
    fn start(dir: &Path) -> Result<(Self, VerifyingKey)> {
        let mut child = Self(
            Command::new(std::env::current_exe()?)
                .arg("integrity-tool-signer")
                .arg(dir)
                .stdin(Stdio::piped())
                .stdout(Stdio::piped())
                .spawn()?,
        );
        let mut public_key = [0; 32];
        child
            .0
            .stdout
            .as_mut()
            .context("missing signer output")?
            .read_exact(&mut public_key)?;
        Ok((child, VerifyingKey::from_bytes(&public_key)?))
    }

    fn receipt(mut self, session: &[u8; 16]) -> Result<Signature> {
        self.0
            .stdin
            .take()
            .context("missing signer input")?
            .write_all(session)?;
        let mut receipt = [0; 64];
        self.0
            .stdout
            .as_mut()
            .context("missing signer output")?
            .read_exact(&mut receipt)?;
        ensure!(self.0.wait()?.success(), "file tool signer failed");
        Ok(Signature::from_bytes(&receipt))
    }
}

impl Drop for ToolSigner {
    fn drop(&mut self) {
        if matches!(self.0.try_wait(), Ok(None)) {
            let _ = self.0.kill();
            let _ = self.0.wait();
        }
    }
}

fn lock_gateway(dir: &Path) -> Result<File> {
    // Lock a stable file. The state file itself is replaced by rename.
    let lock = OpenOptions::new()
        .read(true)
        .write(true)
        .open(dir.join("gateway.lock"))?;
    lock.lock().context("lock local gateway")?;
    Ok(lock)
}

pub(super) fn fence_shared_gateway(dir: &Path) -> Result<()> {
    let _lock = lock_gateway(dir)?;
    let mut gateway = Gateway::reopen(dir)?;
    ensure!(
        gateway.active && gateway.epoch == 1,
        "unexpected state before shared fence"
    );
    gateway.fence()?;
    gateway.persist(dir)
}

pub(super) fn contend_for_operation(dir: &Path, operation: u64) -> Result<()> {
    let _lock = lock_gateway(dir)?;
    let mut gateway = Gateway::reopen(dir)?;
    if !gateway.active || gateway.epoch != 1 {
        std::process::exit(STALE_LEASE_EXIT);
    }
    if !gateway.write(WriteLease(1), operation) {
        std::process::exit(DUPLICATE_OPERATION_EXIT);
    }
    gateway.persist(dir)
}

fn verify_concurrent_completion(dir: &Path) -> Result<()> {
    File::create_new(dir.join("gateway.lock"))?;
    let executable = std::env::current_exe()?;
    let mut command = Command::new(executable);
    command
        .arg("integrity-gateway-probe")
        .arg(dir)
        .args(["--contend", "3"]);
    let mut first = command.spawn().context("start first gateway writer")?;
    let second = command.status().context("run second gateway writer");
    let first = first.wait().context("wait for first gateway writer")?;
    let second = second?;
    ensure!(
        (first.success() && second.code() == Some(DUPLICATE_OPERATION_EXIT))
            || (second.success() && first.code() == Some(DUPLICATE_OPERATION_EXIT)),
        "expected one committed write and one duplicate rejection: {first}, {second}"
    );
    let persisted = Gateway::reopen(dir)?;
    ensure!(
        persisted.completed == HashSet::from([1, 2, 3]),
        "concurrent completion ledger mismatch"
    );
    Ok(())
}

fn verify_concurrent_fence(dir: &Path) -> Result<()> {
    let executable = std::env::current_exe()?;
    let mut writer = Command::new(&executable);
    writer
        .arg("integrity-gateway-probe")
        .arg(dir)
        .args(["--contend", "4"]);
    let mut child = writer.spawn().context("start writer racing fence")?;
    let fence = Command::new(&executable)
        .arg("integrity-gateway-probe")
        .arg(dir)
        .arg("--fence")
        .status();
    let raced_write = child.wait()?;
    ensure!(fence?.success(), "shared fence did not commit");
    let persisted = Gateway::reopen(dir)?;
    ensure!(
        persisted.epoch == 2 && !persisted.active,
        "shared gateway is not fenced"
    );
    let mut expected = HashSet::from([1, 2, 3]);
    if raced_write.success() {
        expected.insert(4);
    } else {
        ensure!(
            raced_write.code() == Some(STALE_LEASE_EXIT),
            "unexpected raced write status: {raced_write}"
        );
    }
    ensure!(
        persisted.completed == expected,
        "shared fence lost or admitted a write"
    );
    let late_write = writer.status()?;
    ensure!(
        late_write.code() == Some(STALE_LEASE_EXIT),
        "old lease accepted after shared fence"
    );
    Ok(())
}

fn verify_unresolved_write(
    dir: &Path,
    session: &[u8; 16],
    tool: ToolSigner,
    key: VerifyingKey,
) -> Result<()> {
    let mut gateway = Gateway::reopen(dir)?;
    let recovered = b"verified recovery fixture";
    let lease = gateway.activate_target(
        RecoveryEpoch(gateway.epoch),
        recovered,
        &compute_sha256(recovered),
    )?;
    ensure!(
        gateway.unresolved.contains(&5),
        "unresolved operation was lost"
    );
    ensure!(
        !gateway.write(lease, 5),
        "unresolved operation was replayed"
    );
    ensure!(
        !gateway.begin_external_write(lease, 5),
        "unresolved operation was dispatched again"
    );
    ensure!(gateway.write(lease, 6), "unrelated operation was blocked");
    // Reconcile the retained ledger while it is fenced using the observed effect.
    ensure!(
        dispatch_file_effect(dir)?.code() == Some(STALE_LEASE_EXIT),
        "fenced file tool accepted stale dispatch"
    );
    let receipt = tool.receipt(session)?;
    let _lock = lock_gateway(dir)?;
    let mut gateway = Gateway::reopen(dir)?;
    let wrong_tool = SigningKey::from_bytes(&rand::random());
    let mut other_session = *session;
    other_session[0] ^= 1;
    ensure!(
        !gateway.reconcile_completed(5, &receipt, &wrong_tool.verifying_key(), session),
        "receipt from an untrusted key accepted"
    );
    ensure!(
        !gateway.reconcile_completed(5, &receipt, &key, &other_session),
        "receipt from another session accepted"
    );
    ensure!(
        key.verify_strict(&receipt_message(session, 6), &receipt)
            .is_err(),
        "receipt for another operation accepted"
    );
    ensure!(
        gateway.reconcile_completed(5, &receipt, &key, session),
        "completion receipt was rejected"
    );
    gateway.persist(dir)?;
    let mut gateway = Gateway::reopen(dir)?;
    ensure!(
        !gateway.active && gateway.completed.contains(&5) && !gateway.unresolved.contains(&5),
        "reconciled state was not persisted"
    );
    ensure!(
        !gateway.reconcile_completed(5, &receipt, &key, session),
        "receipt was consumed twice"
    );
    let lease = gateway.activate_target(
        RecoveryEpoch(gateway.epoch),
        recovered,
        &compute_sha256(recovered),
    )?;
    ensure!(
        !gateway.write(lease, 5),
        "reconciled operation was replayed"
    );
    Ok(())
}

pub(super) fn interrupt_completion(dir: &Path) -> Result<()> {
    let mut gateway = Gateway::reopen(dir)?;
    ensure!(
        gateway.epoch == 1 && gateway.completed.len() == 1 && gateway.completed.contains(&1),
        "unexpected gateway before completion"
    );
    ensure!(
        gateway.write(WriteLease(1), 2),
        "pending operation did not complete"
    );
    gateway.publish(dir)?;
    // The replacement is visible to live processes. The directory is not synced yet.
    std::process::exit(INTERRUPTED_COMPLETION_EXIT);
}

fn verify_interrupted_completion(dir: &Path) -> Result<()> {
    let status = Command::new(std::env::current_exe()?)
        .arg("integrity-gateway-probe")
        .arg(dir)
        .arg("--interrupt-completion")
        .status()
        .context("start interrupted completion probe")?;
    ensure!(
        status.code() == Some(INTERRUPTED_COMPLETION_EXIT),
        "completion probe did not reach the post-rename interruption point: {status}"
    );
    probe_in_fresh_process(dir, true)?;
    Gateway::sync_directory(dir)
}

pub(super) fn interrupt_activation(dir: &Path) -> Result<()> {
    probe_gateway(dir, false)?;
    let mut gateway = Gateway::reopen(dir)?;
    let fixture = b"verified restart probe";
    gateway.activate_target(RecoveryEpoch(1), fixture, &compute_sha256(fixture))?;
    gateway.stage(dir)?;
    // Exit without unwinding after sync and before publishing the staged file.
    std::process::exit(INTERRUPTED_ACTIVATION_EXIT);
}

fn verify_interrupted_activation(dir: &Path) -> Result<()> {
    let status = Command::new(std::env::current_exe()?)
        .arg("integrity-gateway-probe")
        .arg(dir)
        .arg("--interrupt-activation")
        .status()
        .context("start interrupted activation probe")?;
    ensure!(
        status.code() == Some(INTERRUPTED_ACTIVATION_EXIT),
        "activation probe did not reach the pre-commit interruption point: {status}"
    );
    probe_in_fresh_process(dir, false)?;
    fs::remove_file(dir.join("gateway.next")).context("discard interrupted staged activation")?;
    Ok(())
}

pub(super) fn probe_gateway(dir: &Path, completed: bool) -> Result<()> {
    let mut gateway = Gateway::reopen(dir)?;
    let expected_operations = if completed { &[1, 2][..] } else { &[1][..] };
    ensure!(
        gateway.epoch == 1
            && gateway.active == completed
            && gateway.completed.len() == expected_operations.len()
            && expected_operations
                .iter()
                .all(|op| gateway.completed.contains(op)),
        "unexpected persisted gateway state"
    );
    ensure!(
        !gateway.write(WriteLease(0), 3),
        "stale lease accepted after reopen"
    );
    let current = WriteLease(1);
    ensure!(
        !gateway.write(current, 2),
        "fenced or completed operation accepted after reopen"
    );
    ensure!(
        gateway.write(current, 3) == completed,
        "reopened gateway write state mismatch"
    );
    Ok(())
}

fn probe_in_fresh_process(dir: &Path, completed: bool) -> Result<()> {
    let mut command = Command::new(std::env::current_exe()?);
    command.arg("integrity-gateway-probe").arg(dir);
    if completed {
        command.arg("--completed");
    }
    let status = command.status().context("start gateway probe process")?;
    ensure!(status.success(), "gateway probe failed with {status}");
    Ok(())
}

#[derive(Clone, Copy, Serialize)]
#[serde(rename_all = "kebab-case")]
enum Codec {
    Raw,
    ZstdLevel3,
    Lz4Block,
    QatqExact,
    QatqExactExhaustive,
}

const CODECS: [Codec; 5] = [
    Codec::Raw,
    Codec::ZstdLevel3,
    Codec::Lz4Block,
    Codec::QatqExact,
    Codec::QatqExactExhaustive,
];

impl Codec {
    fn encode(self, bytes: &[u8]) -> Result<Vec<u8>> {
        Ok(match self {
            Self::Raw => bytes.to_vec(),
            Self::ZstdLevel3 => zstd::bulk::compress(bytes, 3)?,
            Self::Lz4Block => lz4_flex::block::compress(bytes),
            Self::QatqExact | Self::QatqExactExhaustive => {
                let values: Vec<_> = bytes
                    .chunks_exact(4)
                    .map(|chunk| f32::from_le_bytes([chunk[0], chunk[1], chunk[2], chunk[3]]))
                    .collect();
                match self {
                    Self::QatqExactExhaustive => {
                        qatq::try_encode_qatq_exact_exhaustive_with_config(
                            &values,
                            qatq::Phase1Config::default(),
                        )?
                    }
                    _ => encode_qatq_exact_f32le_transfer(&values)?.payload,
                }
            }
        })
    }

    fn decode(self, payload: Vec<u8>, raw_len: usize) -> Result<Vec<u8>> {
        Ok(match self {
            Self::Raw => payload,
            Self::ZstdLevel3 => zstd::bulk::decompress(&payload, raw_len)?,
            Self::Lz4Block => lz4_flex::block::decompress(&payload, raw_len)?,
            Self::QatqExact => {
                decode_qatq_phase2_transfer(QATQ_EXACT_F32LE_STORAGE, &payload, raw_len / 4)?
                    .into_iter()
                    .flat_map(f32::to_le_bytes)
                    .collect()
            }
            Self::QatqExactExhaustive => qatq::decode_qatq_exact(&payload)?
                .into_iter()
                .flat_map(f32::to_le_bytes)
                .collect(),
        })
    }
}

#[derive(Serialize)]
struct Sample {
    trial: usize,
    codec: Codec,
    payload_bytes: usize,
    detect_us: u128,
    checkpoint_select_us: u128,
    restored_generation: u64,
    checkpoint_rollback_generations: u64,
    encode_us: u128,
    decode_us: u128,
    alert_to_activation_us: u128,
    alert_to_task_us: u128,
}

struct Checkpoint<'a> {
    generation: u64,
    bytes: &'a [u8],
    trusted_digest: String,
    signature: Signature,
}

struct CheckpointTrust {
    key: VerifyingKey,
    session: [u8; 16],
}

impl<'a> Checkpoint<'a> {
    fn sign(generation: u64, bytes: &'a [u8], signer: &SigningKey, session: &[u8; 16]) -> Self {
        let trusted_digest = compute_sha256(bytes);
        let signature = signer.sign(&Self::signed_message(session, generation, &trusted_digest));
        Self {
            generation,
            bytes,
            trusted_digest,
            signature,
        }
    }

    fn signed_message(session: &[u8; 16], generation: u64, digest: &str) -> Vec<u8> {
        let mut message = b"permeantos/integrity-drill/checkpoint/v2\0".to_vec();
        message.extend_from_slice(session);
        message.extend_from_slice(&generation.to_be_bytes());
        message.extend_from_slice(digest.as_bytes());
        message
    }

    fn metadata_verifies(&self, trust: &CheckpointTrust) -> bool {
        trust
            .key
            .verify_strict(
                &Self::signed_message(&trust.session, self.generation, &self.trusted_digest),
                &self.signature,
            )
            .is_ok()
    }

    fn bytes_verify(&self) -> bool {
        compute_sha256(self.bytes) == self.trusted_digest
    }
}

fn latest_verified_before<'a>(
    history: &'a [Checkpoint<'a>],
    rejected_generation: u64,
    trust: &CheckpointTrust,
) -> Result<&'a Checkpoint<'a>> {
    let mut newest = None::<&Checkpoint<'_>>;
    for checkpoint in history {
        if checkpoint.generation < rejected_generation
            && newest.is_none_or(|verified| checkpoint.generation > verified.generation)
            && checkpoint.metadata_verifies(trust)
            && checkpoint.bytes_verify()
        {
            newest = Some(checkpoint);
        }
    }
    newest.context("no verified checkpoint predates the rejected generation")
}

fn drill(
    trial: usize,
    codec: Codec,
    history: &[Checkpoint<'_>],
    candidate: &Checkpoint<'_>,
    trust: &CheckpointTrust,
    state_dir: Option<&Path>,
) -> Result<Sample> {
    let (mut gateway, source) = Gateway::new();
    ensure!(gateway.write(source, 1), "fixture operation failed");
    if let Some(dir) = state_dir {
        gateway.persist(dir)?;
    }
    let start = Instant::now();
    ensure!(
        candidate.metadata_verifies(trust),
        "candidate generation metadata is unauthenticated"
    );
    ensure!(
        !candidate.bytes_verify(),
        "fixture corruption went undetected"
    );
    let alert = Instant::now();
    let recovery = gateway.fence()?;
    if let Some(dir) = state_dir {
        gateway.persist(dir)?;
        drop(gateway);
        verify_interrupted_activation(dir)?;
        gateway = Gateway::reopen(dir)?;
    }
    ensure!(!gateway.write(source, 2), "fenced source accepted");
    let selection = Instant::now();
    let selected = latest_verified_before(history, candidate.generation, trust)?;
    let checkpoint_select_us = selection.elapsed().as_micros();
    let encoding = Instant::now();
    let payload = codec.encode(selected.bytes)?;
    let encode_us = encoding.elapsed().as_micros();
    let payload_bytes = payload.len();
    let decoding = Instant::now();
    let restored = codec.decode(payload, selected.bytes.len())?;
    let decode_us = decoding.elapsed().as_micros();
    let target = gateway.activate_target(recovery, &restored, &selected.trusted_digest)?;
    if let Some(dir) = state_dir {
        gateway.persist(dir)?;
    }
    let alert_to_activation_us = alert.elapsed().as_micros();
    ensure!(
        !gateway.write(source, 2),
        "stale source accepted after activation"
    );
    ensure!(!gateway.write(target, 1), "completed operation replayed");
    if let Some(dir) = state_dir {
        drop(gateway);
        verify_interrupted_completion(dir)?;
        gateway = Gateway::reopen(dir)?;
    } else {
        ensure!(
            gateway.write(target, 2),
            "pending operation did not complete"
        );
    }
    let alert_to_task_us = alert.elapsed().as_micros();
    ensure!(
        !gateway.write(target, 2),
        "pending operation completed twice"
    );
    if let Some(dir) = state_dir {
        verify_concurrent_completion(dir)?;
        // The two contenders have exited. Record a new intent before the next fence.
        let mut shared = Gateway::reopen(dir)?;
        ensure!(
            shared.begin_external_write(target, 5),
            "could not record external write intent"
        );
        shared.persist(dir)?;
        let (tool, key) = ToolSigner::start(dir)?;
        ensure!(
            dispatch_file_effect(dir)?.success(),
            "file tool did not complete"
        );
        ensure!(
            dispatch_file_effect(dir)?.code() == Some(DUPLICATE_OPERATION_EXIT),
            "file tool accepted duplicate dispatch"
        );
        verify_concurrent_fence(dir)?;
        verify_unresolved_write(dir, &trust.session, tool, key)?;
    }
    Ok(Sample {
        trial,
        codec,
        payload_bytes,
        detect_us: (alert - start).as_micros(),
        checkpoint_select_us,
        restored_generation: selected.generation,
        checkpoint_rollback_generations: candidate.generation - selected.generation,
        encode_us,
        decode_us,
        alert_to_activation_us,
        alert_to_task_us,
    })
}

pub(super) fn run(
    trials: u8,
    fixture: Option<&Path>,
    gateway_state_dir: Option<&Path>,
) -> Result<()> {
    const MAX_FIXTURE_BYTES: u64 = 16 * 1024 * 1024;
    let trusted = if let Some(path) = fixture {
        ensure!(path.metadata()?.is_file(), "fixture must be a regular file");
        let mut bytes = Vec::new();
        File::open(path)
            .context("open checkpoint fixture")?
            .take(MAX_FIXTURE_BYTES + 1)
            .read_to_end(&mut bytes)?;
        ensure!(
            !bytes.is_empty() && bytes.len() % 4 == 0 && bytes.len() as u64 <= MAX_FIXTURE_BYTES,
            "fixture must contain 4 bytes to 16 MiB of little-endian f32 data"
        );
        bytes
    } else {
        (0..65_536)
            .flat_map(|i| (((i % 257) as f32 - 128.0) / 256.0).to_le_bytes())
            .collect()
    };
    let mut advanced = trusted.clone();
    advanced[0] ^= 1;
    let mut corrupted = advanced.clone();
    corrupted[1] ^= 1;
    let (trust, history, mut candidate) = {
        let signer = SigningKey::from_bytes(&rand::random());
        let session = rand::random();
        (
            CheckpointTrust {
                key: signer.verifying_key(),
                session,
            },
            [Checkpoint::sign(1, &trusted, &signer, &session)],
            Checkpoint::sign(2, &advanced, &signer, &session),
        )
    };
    candidate.bytes = &corrupted;
    let mut samples = Vec::new();
    if let Some(dir) = gateway_state_dir {
        fs::create_dir(dir).context("gateway state directory must be new")?;
    }
    for trial in 0..usize::from(trials) {
        for offset in 0..CODECS.len() {
            let state_dir = gateway_state_dir
                .map(|dir| dir.join(format!("trial-{}-{}", trial + 1, offset + 1)));
            if let Some(dir) = &state_dir {
                fs::create_dir(dir)?;
            }
            samples.push(drill(
                trial + 1,
                CODECS[(trial + offset) % CODECS.len()],
                &history,
                &candidate,
                &trust,
                state_dir.as_deref(),
            )?);
        }
    }
    serde_json::to_writer_pretty(
        io::stdout().lock(),
        &serde_json::json!({
            "schema": "permeantos-local-integrity-drill-v1",
        "fixture": if fixture.is_some() { "provided-f32le" } else { "synthetic-periodic-f32le" },
            "raw_bytes": trusted.len(),
            "rejected_generation": candidate.generation,
            "checkpoint_authentication": "ed25519-session-generation-and-sha256",
            "gateway_storage": if gateway_state_dir.is_some() { "local-file-reopen" } else { "memory" },
            "gateway_cross_process_probe": gateway_state_dir.is_some(),
            "gateway_interrupted_activation_probe": gateway_state_dir.is_some(),
            "gateway_interrupted_completion_probe": gateway_state_dir.is_some(),
            "gateway_concurrent_completion_probe": gateway_state_dir.is_some(),
            "gateway_concurrent_fence_probe": gateway_state_dir.is_some(),
            "gateway_unresolved_write_probe": gateway_state_dir.is_some(),
            "gateway_signed_receipt_probe": gateway_state_dir.is_some(),
            "gateway_file_effect_probe": gateway_state_dir.is_some(),
            "gateway_tool_process_signer_probe": gateway_state_dir.is_some(),
            "samples": samples,
        }),
    )?;
    println!();
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn missing_partial_and_mismatched_effects_cannot_be_receipted() -> Result<()> {
        let dir = std::env::temp_dir().join(format!(
            "permeantos-effect-test-{:032x}",
            rand::random::<u128>()
        ));
        fs::create_dir(&dir)?;
        let effect = dir.join("operation-5.effect");
        let result = (|| {
            let tool = SigningKey::from_bytes(&[9; 32]);
            let session = [1; 16];
            let (mut gateway, lease) = Gateway::new();
            assert!(gateway.begin_external_write(lease, 5));
            let recovery = gateway.fence()?;
            assert!(sign_file_effect(&dir, &session, &tool).is_err());
            fs::write(&effect, &FILE_EFFECT[..FILE_EFFECT.len() - 1])?;
            assert!(sign_file_effect(&dir, &session, &tool).is_err());
            fs::write(&effect, vec![0; FILE_EFFECT.len()])?;
            assert!(sign_file_effect(&dir, &session, &tool).is_err());
            let restored = b"verified checkpoint";
            let lease = gateway.activate_target(recovery, restored, &compute_sha256(restored))?;
            assert!(!gateway.begin_external_write(lease, 5));
            assert!(gateway.unresolved.contains(&5));
            fs::write(&effect, FILE_EFFECT)?;
            let receipt = sign_file_effect(&dir, &session, &tool)?;
            assert!(gateway.reconcile_completed(5, &receipt, &tool.verifying_key(), &session));
            assert!(!gateway.write(lease, 5));
            Ok::<_, anyhow::Error>(())
        })();
        if effect.exists() {
            fs::remove_file(effect)?;
        }
        fs::remove_dir(dir)?;
        result
    }

    #[test]
    fn corrupt_restore_leaves_both_writers_fenced() {
        let (mut gateway, source) = Gateway::new();
        let recovery = gateway.fence().unwrap();
        assert!(gateway
            .activate_target(recovery, b"bad", &compute_sha256(b"trusted"))
            .is_err());
        assert!(!gateway.write(source, 1));
        assert!(!gateway.active);
    }

    #[test]
    fn newer_fence_rejects_delayed_activation_and_previous_leases() {
        let (mut gateway, source) = Gateway::new();
        let digest = compute_sha256(b"trusted");
        let first = gateway.fence().unwrap();
        let first_target = gateway.activate_target(first, b"trusted", &digest).unwrap();
        assert!(gateway.write(first_target, 1));
        let superseded = gateway.fence().unwrap();
        let current = gateway.fence().unwrap();
        assert!(gateway
            .activate_target(superseded, b"trusted", &digest)
            .is_err());
        let current_target = gateway
            .activate_target(current, b"trusted", &digest)
            .unwrap();
        assert!(!gateway.write(source, 2));
        assert!(!gateway.write(first_target, 2));
        assert!(!gateway.write(current_target, 1));
        assert!(gateway.write(current_target, 2));
    }

    #[test]
    fn each_codec_restores_verified_state_and_enforces_handoff() {
        let signer = SigningKey::from_bytes(&[7; 32]);
        let key = CheckpointTrust {
            key: signer.verifying_key(),
            session: [1; 16],
        };
        let trusted = [0_u8; 4096];
        let mut candidate = trusted;
        candidate[23] = 1;
        let history = [Checkpoint::sign(3, &trusted, &signer, &key.session)];
        let candidate = Checkpoint {
            bytes: &candidate,
            ..Checkpoint::sign(5, &trusted, &signer, &key.session)
        };
        for codec in CODECS {
            assert!(drill(1, codec, &[], &candidate, &key, None).is_err());
            assert!(drill(1, codec, &history, &history[0], &key, None).is_err());
            let sample = drill(1, codec, &history, &candidate, &key, None).unwrap();
            assert_eq!(sample.restored_generation, 3);
            assert_eq!(sample.checkpoint_rollback_generations, 2);
        }
    }

    #[test]
    fn recovery_ignores_corrupt_and_ineligible_generations() {
        let signer = SigningKey::from_bytes(&[7; 32]);
        let key = CheckpointTrust {
            key: signer.verifying_key(),
            session: [1; 16],
        };
        let other = SigningKey::from_bytes(&[8; 32]);
        let history = [
            Checkpoint::sign(2, b"valid", &signer, &key.session),
            Checkpoint {
                bytes: b"bad",
                ..Checkpoint::sign(4, b"valid", &signer, &key.session)
            },
            Checkpoint::sign(8, b"valid", &signer, &key.session),
            Checkpoint::sign(3, b"valid", &signer, &key.session),
            Checkpoint::sign(5, b"valid", &other, &key.session),
            Checkpoint::sign(7, b"valid", &signer, &[2; 16]),
            Checkpoint {
                generation: 6,
                ..Checkpoint::sign(1, b"valid", &signer, &key.session)
            },
        ];
        assert_eq!(
            latest_verified_before(&history, 8, &key)
                .unwrap()
                .generation,
            3
        );
        assert!(latest_verified_before(&history, 2, &key).is_err());
    }
}
