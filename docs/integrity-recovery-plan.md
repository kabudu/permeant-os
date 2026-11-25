# Integrity-triggered recovery implementation plan

## Objective and trust boundary

Recover an active agent from the last independently verified checkpoint after
an integrity alert. Measure recovery from detection to the first valid token
and to the first completed task. Measure the compression and recovery-time
trade-off over identical checkpoint data.

The supervisor, checkpoint store, tool gateway and target are trusted within
this model. A suspect source cannot approve a checkpoint or retain write
authority. A recovery failure leaves writes fenced. Durable checkpoints need
authenticated generation numbers and explicit compatibility checks for model,
tokenizer, layout and tool policy. Credentials must be reissued at the target.
Recovery from a compromised supervisor or tool gateway is outside this model.

## Implementation checklist

- [x] Inventory existing graph verification, migration paths and exact codec support.
- [x] Add a bounded local CLI drill. Inject a one-byte checkpoint fault, detect
  it independently, revoke simulated source writes, restore the prior
  checkpoint and verify its digest before enabling target writes.
- [x] Verify the rejected generation against its own trusted digest. Select
  the highest verified generation strictly older than the rejected one.
  Reject missing history and report the selected generation, rollback depth
  and selection latency for each trial.
- [x] Sign the generation and checkpoint SHA-256 together with an ephemeral
  Ed25519 key for the local drill. Verify with the pinned public key before
  using any generation metadata. Test corrupt payloads, substituted
  generations and signatures from another key.
- [x] Bind checkpoint signatures to the supervisor's expected recovery session.
  Reject a checkpoint from a different session even under the same signing key.
- [x] Add a PR CI smoke test for the disk-backed drill and both process
  interruption probes across every codec.
- [x] Exercise a simulated tool ledger across the handoff. Check that source
  writes and replay of a completed operation are denied and that one pending
  target operation completes.
- [x] Issue epoch-scoped write leases in the simulated gateway. Increment the
  epoch on every fence and require the current recovery epoch for activation.
  Test that a delayed activation and old leases fail across successive fences,
  while completed operation IDs survive the handoff.
- [x] Add an opt-in local persistence drill. Replace the gateway state file
  atomically and reload it after fencing and after completing a simulated
  operation. Verify stale leases and completed operations survive reload.
- [x] Probe both committed states from fresh CLI processes. Verify the
  fenced state rejects even the current epoch, and the active state rejects
  stale leases and duplicate operations while accepting a new operation.
- [x] Interrupt a child process after syncing staged activation and before
  renaming it. Verify from a fresh process that the prior fence remains
  authoritative, discard the staged activation and complete normal recovery.
- [x] Interrupt the simulated operation writer after atomic rename and before
  directory sync. Verify that a fresh process sees the completion record and
  rejects replay, then sync the directory before reporting success.
- [x] Start two local writers against one completion ledger. Hold an exclusive
  lock on a stable file across lease validation, replay check and snapshot
  commit. Check one success, one duplicate rejection and one persisted operation.
- [x] Race a writer against a fence through the same local lock. If the
  write commits first, preserve its record through the fence. If the fence
  commits first, reject the write. Confirm all later old-lease writes fail.
- [x] Persist a simulated external write intent before fencing. After recovery,
  reject redispatch and replay while its outcome is unknown. Allow unrelated
  work and keep the operation blocked after a simulated completion receipt.
- [x] Execute an actual disposable file effect in a child process after
  recording the intent. Reject duplicate creation and stale dispatch, and
  reconcile only after reading the complete expected effect.
- [x] Run raw, zstd level 3, LZ4 block, the deployed QATQ exact f32 codec and
  QATQ 0.1.1's exhaustive exact profile over identical bytes. The exhaustive
  profile is local-only and measures QATQ's wider exact strategy search.
  Rotate codec order, report each trial and require
  exact restore before accepting its timing.
- [x] Repeat the exact codec comparison over all 48 tensors of a real
  MLX Qwen2.5 KV capture and report the local CPU versus payload trade-off.
- [ ] Integrate a supervisor outside the source trust domain. Store signed
  checkpoints off-host and atomically advance a durable fencing epoch in the
  shared tool gateway. Handle concurrent incidents, stale epochs, expired or
  missing checkpoints, target failure and ambiguous tool outcomes. Require
  tool-side idempotency or send ambiguous writes to manual reconciliation.
- [ ] Wire the supervisor into the pinned MLX to vLLM runner with a prewarmed
  target and disposable credentials. Inject a synthetic checkpoint corruption
  during active work. Verify that the latest trusted checkpoint is selected,
  old source authority cannot write, and the target completes a task once.
- [x] Add an opt-in AWS runner path that prewarms the receiver, detects a
  fault in a shadow of the live-exported KV snapshot and transfers the
  unchanged checkpoint with an exact codec. Require target cache attachment
  and exact continuation before running target graph activity.
- [ ] Capture detection, fencing, checkpoint read, encode, transport, decode,
  import, first valid token and first completed task times. Report retries,
  rollback depth, actual wire bytes, p50/p95 and trial spread, with warm/cold
  conditions and network bandwidth recorded. Include prompt re-prefill as a
  recovery baseline and failure drills for unavailable targets and checkpoints.
- [ ] Inventory and pin eligible QATQ profiles. Compare exact modes on the same
  boundaries and enable lossy profiles only in a separate experiment with
  explicit continuation and task acceptance criteria. Rank successful trials
  by bytes under a recovery budget derived from the workload. Report fastest
  recovery separately from smallest transfer.

## Running the local drill

```sh
cargo run --release --locked --bin permeant-cli -- integrity-drill --trials 5
```

The JSON report uses a deterministic synthetic f32 fixture. The supervisor
holds the verification key in memory and verifies signed generation metadata.
The key is generated per drill run. The simulated gateway owns a single
in-memory write lease and completion ledger. Payload sizes exclude transport
framing. Timings exclude GPU setup, networking and model inference. Trial
count is capped at 20 and the default fixture is 256 KiB. To compare real
checkpoint distributions locally, pass `--fixture` with a non-sensitive raw
little-endian f32 tensor file of at most 16 MiB. This command exercises the
recovery rules and real codecs locally. The unchecked gates require live
runtime and durable control-plane integration.

Pass `--gateway-state-dir ./recovery-evidence` to create a new evidence
directory with one state file per codec trial. Fresh CLI subprocesses reload
and probe the fenced and completed states before the parent reloads them.
Probes change only their own in-memory copies. File writes, syncs, reloads
and subprocess startup are included in this mode's recovery timings. Each
trial owns its directory. The interruption probes use a single writer and
cover process termination before publication and after publication but before
directory sync. The latter verifies visibility to other processes on the
running system. Power-loss durability and shared-gateway integration remain
unverified.

The concurrent completion probe runs after the timed recovery sample. It
serializes cooperating local processes through an OS file lock. It exercises
the simulated operation ledger. Real tool effects still need their own
idempotency or reconciliation contract.
The subsequent fence race also runs outside the timed sample and leaves the
retained evidence snapshot fenced at epoch 2.

The drill verifies a local test tool's Ed25519 completion receipt against a
pinned key, session and operation ID, then persists the reconciled ledger
while the gateway remains fenced. A child process creates and syncs one
file per trial using exclusive creation under the same gateway lock.
The supervisor pins a tool subprocess's public key before dispatch. The
private key stays in that subprocess, which issues a receipt only after
observing the complete expected file. A partial file keeps the operation
unresolved. The subprocess runs under the same OS user as the supervisor.
Remote tool identity and host isolation remain unverified.
The regression suite checks missing, truncated and wrong-content effect files.
All three leave the operation unresolved and block redispatch. A complete
matching effect can be reconciled and subsequently rejects replay.

## Local validation before generation selection

Release build on Darwin arm64 with Rust 1.97.0 and QATQ 0.1.1.
These v0 timings predate the v1 report and checkpoint selection phase.
Five samples per codec, with the codec order rotated and every restore
verified by SHA-256 before enabling target writes. Times cover alert through
the first simulated task.

| Codec | Payload bytes | Median ms | Min–max ms |
| --- | ---: | ---: | ---: |
| Raw | 262,144 | 1.042 | 0.483–1.351 |
| zstd level 3 | 565 | 1.148 | 1.124–1.492 |
| LZ4 block | 2,066 | 1.043 | 0.624–1.561 |
| QATQ exact | 121 | 9.367 | 5.124–13.334 |
| QATQ exhaustive exact | 121 | 6.496 | 5.697–11.598 |

The fixture repeats a short sequence and compresses unusually well. Both
QATQ profiles tied for smallest payload. Their timing ranges overlap, so
the trial does not establish a stable speed difference between them.

## Local comparison on real MLX KV tensors

On 23 November 2026, the canonical exporter captured all 24 key tensors and
all 24 value tensors for Qwen/Qwen2.5-0.5B-Instruct at revision
`7ae557604adf67be50417f59c2c2f167def9a775`, with the default synthetic prompt
at 1,920 tokens. The release build ran on Darwin arm64 with Rust 1.97.0 and
QATQ 0.1.1. Every tensor was tested separately using its original tensor
boundary. There were three trials per tensor and codec, and every restore
passed digest verification. The timings sum the 48 local alert-to-simulated-task
measurements within each trial. The in-memory gateway excludes disk and process
startup. No network transfer or model continuation is timed.

| Codec | Total payload bytes | Median encode ms | Median decode ms | Median local recovery ms | Local recovery range ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| Raw | 47,185,920 | 1.345 | 0 | 179.006 | 174.946–180.827 |
| zstd level 3 | 20,566,211 | 180.853 | 34.459 | 390.761 | 389.496–396.615 |
| LZ4 block | 29,820,661 | 80.536 | 11.475 | 268.689 | 268.543–271.690 |
| QATQ exact | 13,958,432 | 612.113 | 92.497 | 881.336 | 871.925–907.742 |
| QATQ exhaustive exact | 13,958,432 | 649.350 | 78.814 | 905.842 | 903.037–914.418 |

Both QATQ profiles tied for smallest total payload, 70.4% below raw and
32.1% below zstd. The production-path exact profile had the lower median
local time of the two. A simple serial model that adds payload transfer
time to these local medians puts QATQ exact's break-even against zstd
near 108 Mbit/s of effective throughput. This is an estimate and excludes
network framing, concurrency, and target import.

To repeat, choose a new capture directory and run:

```sh
capture_dir="$(mktemp -d)"
.venv-mlx/bin/python scripts/export-mlx-canonical-kv-for-llamacpp.py \
  --seq-len 1920 --output-dir "$capture_dir"
cargo build --release --locked --bin permeant-cli
for tensor in "$capture_dir"/tensors/*.f32le; do
  target/release/permeant-cli integrity-drill --trials 3 --fixture "$tensor" \
    > "$tensor.report.json" || exit 1
done
jq -s '[.[].samples[]] | group_by(.codec) |
  map({codec: .[0].codec, trials: (group_by(.trial) |
    map({bytes: (map(.payload_bytes) | add),
         recovery_ms: ((map(.alert_to_task_us) | add) / 1000)}))})' \
  "$capture_dir"/tensors/*.report.json
```

The AWS identity check returned an expired session. The local MLX capture
clears the source-side data prerequisite for this benchmark. An authenticated
AWS session and the shared-gateway integration are still required for the
live integrity-triggered recovery drill.

## Opt-in AWS runtime wiring

```sh
cargo build --locked --bin permeant-cli
PERMEANT_INTEGRITY_RECOVERY_DRILL=1 \
  PERMEANT_TRANSFER_QUANTIZATION=qatq \
  PERMEANT_SEQ_LEN=1920 PERMEANT_CONTINUATION_MAX_TOKENS=128 \
  scripts/aws-real-runtime-e2e.sh run
```

The vLLM receiver completes model initialization and baseline generation
before migration. The launch supervisor captures the extractor response and
pins its SHA-256 digest before uploading it to the target. The controlled
fault mutates a separate origin copy. After detection, the target-side
SQLite gateway advances its write epoch. The supervisor demonstrates a
source write before the alert and rejection of the same lease after it.
The transfer reads the off-host snapshot back over SSH, verifies the pinned
digest and uses the restored file as the extractor input. This mode disallows
reverse import, return-home activity, and the separate Agent Memory Graph tool
demo, which does not route its writes through the fixture gateway.

The runner emits `integrity-recovery.json` after target cache attachment and
exact continuation verification. It derives the first valid token time from
vLLM's per-request first-token metric and checks that token against the source
and target baselines. The first completed task is a committed gateway write
of the recovered token. The runner also checks that replay is rejected.
SSH clock samples bracket cross-host timing uncertainty. Routine proof
collection and fidelity checking are included in the task interval.

The drill places the checkpoint and gateway on the existing target instance.
The local launcher is the trusted operator and submits the fixture source and
target requests through its authenticated SSH channel. This verifies lease
revocation at the fixture's write boundary. Isolating the operator from a
compromised origin host, managing signed checkpoint history, and integrating
arbitrary external tools remain separate work.

### Preview candidate gate

- [x] Separate the source fence from target activation. The fixture gateway
  denies both leases after fencing and enables target writes only after the
  runner verifies the exact continuation and validates its first token.
- [ ] On one disposable `g4dn.xlarge`, run the release-built source and
  target with the previously pinned 1,920-token checkpoint, QATQ 0.4.5,
  Qwen2.5-0.5B-Instruct revision `7ae557604adf67be50417f59c2c2f167def9a775`,
  and vLLM 0.23.0. Verify all recovery gates and cleanup.
- [ ] Require green PR CI and the repository packaging checks before tagging.

Use `cargo build --release --locked --bin permeant-cli` on the origin and
set `PERMEANT_BUILD_PROFILE=release` on the runner. Set
`PERMEANT_TARGET_GIT_TREE` to the same commit used to build the origin binary;
an explicit tree disables live file overlays. Set
`PERMEANT_VLLM_MODEL_REVISION` to the pinned revision above and keep the
origin model snapshot on that revision. Set `PERMEANT_EXPECTED_CHECKPOINT_SHA`
to the known extractor-response digest before provisioning.

With `PERMEANT_RECOVERY_FAILURE_PROBES=1`, the runner requests a missing
artifact and a same-length corrupt archive over SSH. Neither may publish a
restored checkpoint or open the write fence. The runner also kills and
restarts the prewarmed receiver before transfer and verifies that neither
lease can write while it is unavailable. After the verified migration and
activation, it discards the original task reply and requires the retry and
replay to return the same durable completion. Alert-relative timings from
this mode include those deliberate interruptions and must not be compared to
ordinary recovery timings as a regression test. If interrupted, run
`scripts/aws-real-runtime-e2e.sh cleanup <state.json>` using the printed
state file; do not restart the origin or remove a fence to work around a failure.

### Live QATQ v0.4.5 comparison

On 24 November 2026, the off-host drill passed on one on-demand
`g4dn.xlarge` with a Tesla T4, prewarmed vLLM 0.23.0 and a 1,920-token
Qwen2.5-0.5B-Instruct checkpoint. The v0.4.5 source and target used the same
Cargo lockfile. The restored checkpoint digest matched the v0.1.1 input,
and both runs used WSS/mTLS and the same 50,331,648-byte padded raw baseline.

| Metric | QATQ v0.1.1 | QATQ v0.4.5 | Difference |
| --- | ---: | ---: | ---: |
| Exact QATQ payload | 14,004,990 bytes | 13,320,355 bytes | 684,635 bytes smaller (4.89%) |
| Alert to first valid token | 209.36 s | 191.02 s | 18.34 s sooner |
| Alert to first completed task | 224.03 s | 205.55 s | 18.48 s sooner |
| Streaming phase | 83.14 s | 74.13 s | 9.02 s shorter |
| Target commit phase | 90.77 s | 91.97 s | 1.20 s longer |

Both runs restored the off-host checkpoint, fenced the source lease, seeded
16 vLLM prefix blocks, matched all 128 tokens against MLX and the target
baseline, and rejected task replay. The cross-host clock uncertainty was
±0.74 s for v0.1.1 and ±0.61 s for v0.4.5. Timings are observations from
one run per version in different Virginia zones (`us-east-1a` and
`us-east-1d`), so they do not isolate the codec's contribution to latency.

### Streaming and commit profiling

Set `PERMEANT_RECOVERY_FAST_PATH=1` alongside the integrity drill to send up
to eight chunks before draining their ordered acknowledgements and to use
batched tensor copies for preblocked vLLM cache input. The wire messages,
QATQ settings, target allocator, slot probes, and continuation checks are
unchanged. A wrong or missing acknowledgement stops streaming before commit.
Set `PERMEANT_EXPECTED_CHECKPOINT_SHA` to the baseline digest to make a
comparison fail if the live exporter produces different input.

The source migration manifest separates layout, comparator compression,
payload encoding, send, and acknowledgement wait. The target daemon log
separates injection from verification. Registration probe events break down
tensor writes and slot sampling. Copy timings are host wall time and can
include GPU dispatch, with later samples observing completion.

In an Apple Silicon CPU probe on one real MLX key/value layer, 256 tokens
split into sixteen 16-token tiles, scalar and batched writes produced
identical FP16 caches. Three alternating trials gave median write times of
321.26 ms and 1.45 ms respectively. The CPU probe measures tensor placement
and leaves out transport, receiver serialization, and vLLM continuation.

The live fast-path run used the same checkpoint SHA-256, QATQ v0.4.5 and
prewarmed vLLM 0.23.0 on one `g4dn.xlarge` in `us-east-1a`. The original
v0.4.5 run was in `us-east-1d`. Each measurement is a single trial.

| Metric | Original v0.4.5 | Fast path | Reduction |
| --- | ---: | ---: | ---: |
| Exact QATQ payload | 13,320,355 bytes | 13,320,355 bytes | 0 |
| Streaming | 74.13 s | 16.72 s | 77.4% |
| Target commit | 91.97 s | 18.06 s | 80.4% |
| Alert to first valid token | 191.02 s | 51.31 s | 73.1% |
| Alert to first completed task | 205.55 s | 66.04 s | 67.9% |

The optimized stream spent 9.31 s waiting for acknowledgements, 4.11 s
encoding comparator baselines and 3.07 s encoding the payload. The daemon
spent 15.19 s in injection and 2.66 s in verification. Registration
reported 0.26 s of host wall time in batched tensor writes and 0.018 s in
slot probes across 48 layer registrations. The observed first-token and
task times had ±0.61 s of cross-host clock uncertainty.

Checkpoint digest verification, source fencing, target task replay
rejection, recorded slot probes and both 128-token continuation
comparisons passed. A limitation applies to both comparison runs: the
source CLI builds header hashes from placeholder tokens. Eight logical
blocks were streamed, but repeated hashes reduced the target's hash-keyed
staging to two distinct registrations. The receiver seeded 16 vLLM prefix
blocks. These results validate the existing continuation fixture and the
profiled path. Full eight-block KV restoration requires distinct block
identities and position-aware attachment validation.

### Full checkpoint KV restoration

Set `PERMEANT_FULL_KV_RESTORE=1` with the fast integrity drill and a pinned
`PERMEANT_EXPECTED_CHECKPOINT_SHA`. The checkpoint digest and logical
position determine each transport block ID. These IDs are not tensor
digests or vLLM cache keys. The receiver checks the ordered identities
before accepting any tensor chunks and injects blocks in that same order.

- [x] Preserve all eight 256-token logical blocks without hash collisions.
- [x] Require pooled vLLM slots, all-layer tensor readback and independent
  slot samples for every registered block.
- [x] Reset the target baseline cache before importing any blocks. Check
  that the vLLM scheduler resolves the prompt prefix to the exact ordered
  imported IDs, then verify the generated request reports the expected
  cache hit. With this 1,920-token prompt and 16-token vLLM tiles, vLLM V1
  recomputes the final tile to obtain logits, so the expected hit is
  1,904 tokens.
- [x] Require the requested continuation length and exact token matches
  against both MLX and the native vLLM baseline before committing.
- [x] Record an end-to-end full-restore run on one `g4dn.xlarge` and
  independently verify teardown.

The full-restore mode uses a fresh, single-transaction vLLM worker and
refuses duplicate registrations. Do not use it to host concurrent serving
or retries in the same worker. The preceding timing figures do not
measure this stronger restore contract.

The loopback daemon accepted the same pinned checkpoint with all eight
ordered IDs and committed 384 exact QATQ v0.4.5 chunks (13,320,355 bytes,
no pass-through). The same fixture with IDs from a different checkpoint
digest was rejected at header validation. This test used the mock injector
and supplies no vLLM reuse, continuation, or live recovery timings.

The 24 November 2026 live attempt did not provision a GPU. All five
`us-east-1` zones offering `g4dn.xlarge` rejected the launch for capacity,
including a retry in two zones. The same image release was available in
`us-east-2`, but the account's On-Demand G/VT quota there was zero. AWS API
queries confirmed that no instance was created and all temporary launch
security groups and key pairs were deleted. The live acceptance item
remained open until the following retry.

#### Live full-restore baseline

The 25 November 2026 run passed on one on-demand `g4dn.xlarge` in
`us-east-1d` with a Tesla T4 and prewarmed vLLM 0.23.0. It used the same
1,920-token Qwen2.5-0.5B-Instruct checkpoint, QATQ v0.4.5 and WSS/mTLS.
The restored off-host copy matched the pinned SHA-256; the corrupted
origin copy did not. The source write passed at epoch 1 and the same lease
was rejected after fencing at epoch 2. The recovered gateway task
completed once at epoch 2 and its replay was rejected.

| Metric | Full restore (one run) |
| --- | ---: |
| Alert to first valid token | 113.35 s |
| Alert to first completed task | 128.18 s |
| Cross-host clock uncertainty | ±0.58 s |
| QATQ payload | 13,320,355 bytes in 384 exact chunks |
| Streaming phase | 16.82 s |
| Target commit phase | 62.06 s |

All eight logical blocks passed placement checks across 24 layers
(192 layer registrations and 128 allocated physical slots, including
padding). The native baseline prefix was cleared before import. vLLM
seeded 120 prompt tiles, resolved the ordered imported slots, and reported
a hit on 1,904 prompt tokens during decode. All 128 continuation tokens
matched both MLX and the independent native vLLM baseline. QATQ used no
pass-through and reduced the padded raw payload by 73.5%.

The earlier 51.31 s / 66.04 s run registered only two distinct logical
blocks and cannot serve as a like-for-like baseline. In the full run,
the daemon spent 59.08 s in injection and 2.67 s verifying; tensor
writes plus readback accounted for 0.93 s within injection. Profile the
per-block injector process, serialization and receiver handoff before
changing GPU copy kernels.

Independent AWS queries confirmed that the test instance terminated and its
root volume and network interface were deleted. Both attempts' security
groups and key pairs were absent. Temporary local checkpoint copies and
private keys were removed, and neither local test listener was running.

#### Injector handoff profiling

One pair of loopback replays on the same pinned MLX checkpoint used the
production injector, HTTP relay, staging and acknowledgement logic but no
GPU consumer. JSON injection took 8.81 s and binary injection took 1.15 s
for all eight blocks. Across those blocks, median Rust JSON encoding was
357 ms, relay JSON encoding 256 ms, and receiver JSON staging 262 ms.
Spawning the subprocess took 0.62 ms (interpreter startup overlaps the
stdin phase). The binary path removes both float-to-JSON encoding passes
and stages the received frame directly. All 384 staged tensors matched
the JSON path bit-for-bit when interpreted as float32.

Set `PERMEANT_BINARY_INJECTOR=1` with full KV restore to select this
opt-in, loopback-only handoff. It uses a versioned length-prefixed JSON
metadata header and flat little-endian float32 data, up to 64 KiB of
metadata and 64 MiB per block. It does not change the QATQ payload sent
over WSS/mTLS or the vLLM commit gates. The receiver records a block
acknowledgement only after successful registration. A malformed,
duplicate or partially registered block cannot activate recovery; failed
stages require a fresh disposable receiver.

The binary path passed one live run on 25 November 2026 with the same
checkpoint, QATQ v0.4.5, WSS/mTLS, and vLLM 0.23.0 on one T4-backed
`g4dn.xlarge` in `us-east-1d`, the same type and zone as the JSON
full-restore baseline. This is one run per variant, not a distribution;
Ubuntu's background updater was active during the binary run.

| Metric | JSON full restore | Binary full restore |
| --- | ---: | ---: |
| Alert to first valid token | 113.35 s | 88.16 s |
| Alert to first completed task | 128.18 s | 102.96 s |
| QATQ payload | 13,320,355 bytes | 13,320,355 bytes |
| Streaming | 16.82 s | 16.56 s |
| Target commit | 62.06 s | 38.15 s |
| Injector work within commit | 59.08 s | 34.88 s |

The binary run's cross-host clock uncertainty was ±0.59 s. It restored
the pinned off-host copy, fenced the old lease at epoch 2, verified
192 layer registrations across all eight blocks, reused 1,904 prompt
tokens in vLLM and matched all 128 continuation tokens against both
references. The recovered gateway write completed once and replay was
rejected. The compression gate recorded 384 exact chunks and no
pass-through.

Independent AWS queries confirmed termination and removal of the volume,
network interface, security group and key pair. Temporary local
checkpoints and private keys were removed and no test listeners remained.

The receiver spent 32.01 s in direct cache registration, including only
0.99 s in tensor writes and full readback and 0.07 s in separate slot
samples. A hot-path candidate was the diagnostic preview: it
copied whole cache tensors to host before selecting eight values, despite
those previews not being used by the commit gates. The observed shapes
represent about 34 GiB across the 192 preview calls at FP16. Measure the
preview directly, then test selecting only the needed values before
copying to host.

#### Bounded diagnostic previews

Select the preview on the device before transferring it to the host.
The contiguous case takes a view; the strided case selects a short row
or the exact row-major prefix across rows. It does not flatten a whole
strided tensor. Full tensor readback and independent slot samples remain
unchanged. Registration now reports target-cache summary time separately
from writes, readback, and slot samples.

In a synthetic replay of the recorded FP16 cache shape
`[23462, 2, 16, 2, 64]`, the legacy preview copied 192,200,704 bytes per
layer and the bounded preview copied 16 bytes for the same eight
values. Five alternate calls on Apple Silicon MPS gave medians of 16.40 ms
(13.74–29.21 ms) and 1.17 ms (0.37–1.49 ms), respectively. These are
isolated preview measurements, not recovery timings. CPU regression tests
also cover transposed, cross-row, expanded, scalar, and empty tensors.

On the Tesla T4, five alternating calls before the recovery run gave
medians of 237.72 ms (233.74–276.07 ms) for the legacy preview and
0.17 ms (0.06–0.20 ms) for the bounded preview. This is a single
synthetic layer; do not multiply its timings into a recovery claim.

The 25 November 2026 full recovery passed on one on-demand
`g4dn.xlarge` (Tesla T4, `us-east-1d`, vLLM 0.23.0). It retained
the binary injector, pinned checkpoint, QATQ v0.4.5, and WSS/mTLS.

| Metric | Binary baseline | Bounded preview |
| --- | ---: | ---: |
| Alert to first valid token | 88.16 s | 48.04 s |
| Alert to first completed task | 102.96 s | 62.95 s |
| QATQ payload | 13,320,355 bytes | 13,320,355 bytes |
| Streaming | 16.56 s | 16.89 s |
| Target commit | 38.15 s | 6.75 s |
| Injector work within commit | 34.88 s | 3.75 s |
| Direct vLLM registration | 32.01 s | 1.00 s |

All 192 target-cache summaries still contained eight values and took
21.73 ms combined. Writes and full readback took 0.92 s, and independent
slot samples took 0.06 s. The run restored the pinned off-host copy,
rejected the fenced lease, verified all eight logical blocks and 128
allocated slots, and reused 1,904 prompt tokens after resetting the
native baseline cache. All 128 continuation tokens matched MLX and
native vLLM. The recovered gateway write completed once and replay was
rejected. The 384 exact QATQ chunks had no pass-through.

The bounded run's timing uncertainty was ±0.57 s. The comparison is
one observation per variant; the older run had a background OS updater
active, and other portions of the alert-to-recovery interval also
varied. The commit breakdown and isolated CUDA preview timing are
stronger evidence of the optimisation's mechanism than the full
alert-to-recovery difference alone.

Independent AWS queries verified termination and deletion of the volume,
network interface, security group and key pair. Temporary local
checkpoint copies and private keys were removed, and no test listeners
remained.

#### Recovery orchestration

The bounded-preview run's retained timestamps put roughly 17 s between
observing the stale-lease rejection and starting the migration process,
and roughly 11 s between starting artifact collection and starting
fidelity analysis. These were wall-clock estimates from persisted
artifacts, not dedicated stage timings.

The runner now records local monotonic milestones for verified fencing,
stale-write rejection, checkpoint download and digest check, migration
commit, artifact collection, fidelity verification, task completion,
and replay rejection. The cross-host first-token and task timestamps
retain their original clock-offset checks.

Set `PERMEANT_RECOVERY_SSH_REUSE=1` for the integrity drill to pre-open
an authenticated OpenSSH control connection before the alert. It uses a
private per-attempt socket, strict host-key checking, and a bounded idle
lifetime. Gateway invocations and SCP reuse it; WSS/mTLS migration is
unchanged. The runner still fences the source before fetching the
off-host checkpoint, checks the restored digest before streaming, and
verifies continuation before enabling the recovered task.

On the test instance, four alternating pairs of small, identical
operations confirmed the setup-cost reduction. A short SSH command
took 1,058.6 ms with a fresh connection and 183.9 ms with reuse (medians).
A small SCP transfer took 1,847.5 ms fresh and 971.8 ms reused. These
checks exclude checkpoint-sized transfer and ran outside the recovery
timer.

The live orchestration run on 25 November 2026 used the same pinned
checkpoint, QATQ v0.4.5, binary injector, bounded previews, vLLM 0.23.0
and one `g4dn.xlarge` in `us-east-1d`. It passed all eight restore
blocks, reused 1,904 imported prompt tokens and matched all 128 tokens
against MLX and native vLLM. The stale source lease and replay of the
recovered task were rejected.

| Metric | Bounded-preview baseline | SSH reuse |
| --- | ---: | ---: |
| Alert to first valid token | 48.04 s | 55.94 s |
| Alert to first completed task | 62.95 s | 65.11 s |
| QATQ migration payload | 13,320,355 bytes | 13,320,355 bytes |
| Streaming | 16.89 s | 17.03 s |
| Target commit | 6.75 s | 6.97 s |

The new trace measured 0.84 s to fence and verify stale-lease rejection.
Downloading the 140,072,828-byte checkpoint took another 25.85 s,
and verifying its digest took 0.31 s. Artifact collection took 5.88 s
after the migration command returned, versus roughly 11 s from the
baseline's retained timestamps. The new cross-host clock uncertainty
was ±0.35 s.

SSH reuse reduced per-operation setup cost in the isolated same-host
test but did not improve the observed end-to-end timings. One full run
per configuration cannot establish why checkpoint throughput differed.
Leave reuse opt-in. The next candidate is to compress the trusted
checkpoint before the alert, download it only after fencing, and
revalidate the original plaintext digest after decompression. Also
separate the verification probe needed for the task from diagnostic
logs that are not needed on the task's critical path.

A local probe of the actual 140,072,828-byte restored checkpoint produced
27,390,571 bytes with Zstd level 3 (80.4% smaller), 37,812,424 bytes with
gzip level 1, and 42,300,142 bytes with LZ4 level 1. All three decoded to
the pinned plaintext SHA-256. Zstd compression took 0.18 s and decoding
plus hashing 0.09 s on the local Mac. These results support testing a
bounded, off-host compressed artifact, but do not measure its AWS latency.

Independent AWS queries verified termination and deletion of the root
volume, network interface, security group and key pair. The private SSH
directory, local listeners, temporary checkpoint copies and private keys
were also gone after cleanup.

#### Precompressed off-host checkpoint

Set `PERMEANT_RECOVERY_CHECKPOINT_CODEC=zstd` for the integrity drill.
Before the alert, the launcher verifies the pinned plaintext checkpoint,
compresses it with Zstd level 3, uploads only the archive to the trusted
host, verifies the remote archive digest and discards its local archive
copy. The origin shadow mutation is unchanged. After fencing and the
stale-lease probe, the launcher downloads the archive and verifies its
exact size and SHA-256 before decoding. The decoder bounds its window
and output, checks the original plaintext size and SHA-256, and only
then publishes the file used for migration. It does not reuse the
origin copy or fall back silently to uncompressed restore.

The phase report distinguishes archive bytes from plaintext bytes and
QATQ migration bytes. The default is still uncompressed checkpoint
restore. The optional path requires the Zstd CLI on the launcher;
the off-host store holds opaque bytes and does not need Zstd installed.

On 25 November 2026 one `g4dn.xlarge` in `us-east-1d`, with the same
SSH reuse, checkpoint, QATQ v0.4.5, binary injector and bounded previews
as the raw-artifact comparison, passed the full recovery drill.

| Metric | Raw checkpoint | Zstd checkpoint |
| --- | ---: | ---: |
| Checkpoint artifact | 140,072,828 bytes | 27,390,575 bytes |
| Checkpoint download | 25.85 s | 3.32 s |
| Verify or decompress and verify | 0.31 s | 1.33 s |
| Alert to first valid token | 55.94 s | 50.46 s |
| Alert to first completed task | 65.11 s | 60.23 s |
| QATQ migration payload | 13,320,355 bytes | 13,320,355 bytes |

The original plaintext digest matched. All eight blocks were restored;
vLLM reused 1,904 imported prompt tokens and matched all 128 continuation
tokens against both MLX and native vLLM. The source lease and recovered
task replay were rejected. The QATQ gate recorded 384 exact chunks and
no pass-through. Cross-host timing uncertainty was ±0.16 s.
The migration command itself took 47.73 s versus 31.99 s in the raw
comparison; one trial per variant does not isolate that variation. The
archive download, rather than the entire recovery interval, is the
strongest observed improvement.

The AWS login expired at teardown, so AWS termination and resource
deletion remained unverified when the benchmark was recorded. The runner
formerly treated failed AWS queries like absent resources; cleanup now
clears stale verification status, requires successful AWS checks and
retains the local SSH key on verification failure. The completed run used
the old teardown code; its local tunnel, control socket, private keys and
temporary checkpoints are gone. After reauthentication, the instance
was found running and terminated. Independent AWS queries confirmed
the instance terminated and the root volume, network interface,
security group and key pair were all removed.

#### Deferred recovery diagnostics

`PERMEANT_RECOVERY_DEFER_DIAGNOSTICS=1` fetches only the target fidelity
probe before the recovery gates. A missing or empty probe stops the run
before any recovered gateway write; continuation, slot, prefix-reuse,
and QATQ checks still run before task commit. The runner downloads the
reverse-state export and logs only after the task, replay rejection, and
clock sample. The total timing report distinguishes the required probe
from these best-effort downloads. Failure cleanup still attempts to
collect available evidence. The default evidence order is unchanged.

The 25 November 2026 live test used one `g4dn.xlarge` in `us-east-1d`,
vLLM 0.23.0 and the same pinned checkpoint, SSH reuse, Zstd archive,
QATQ v0.4.5, binary injector and bounded previews as the prior Zstd run.

| Metric | Collect all before task | Defer optional diagnostics |
| --- | ---: | ---: |
| Alert to first valid token | 50.46 s | 37.21 s |
| Alert to first completed task | 60.23 s | 42.19 s |
| Migration return to evidence ready for local verification | 6.22 s | 1.80 s |
| QATQ migration payload | 13,320,355 bytes | 13,320,355 bytes |

The trace placed the verified task commit and replay rejection before
completion of the four deferred downloads, which took about 4.61 s
after replay (including the trailing clock sample). The original
plaintext digest matched, all eight blocks restored, vLLM reused
1,904 imported prompt tokens, and all 128 continuation tokens matched
MLX and native vLLM. The fenced lease and task replay were rejected.
Cross-host timing uncertainty was ±0.28 s.

The baseline took 47.73 s inside the migration command, compared with
31.71 s in the deferred-diagnostics run. Because diagnostics run after
that command, the change cannot explain the first-token difference
or the entire end-to-end task difference. The measured reduction
in pre-task artifact collection (about 4.42 s) is the direct evidence.
These are single observations per configuration.

Independent AWS queries confirmed termination and deletion of the root
volume, network interface, security group, and key pair. The local
control socket, listeners, checkpoint copies, and private keys were
also gone after cleanup.

#### Wider, byte-bounded ACK batches

The deferred-diagnostics baseline spent 9.68 s of 16.73 s in ACK
drains. At eight chunks per batch, the 384-chunk workload waits at 48
batch boundaries. Set `PERMEANT_STREAM_WINDOW_CHUNKS=32` to evaluate a
larger batch on the same recovery workload. The fast recovery runner
still defaults to eight; the standalone CLI still defaults to one.

Windows larger than eight also cap unacknowledged encoded payload at
4 MiB, draining before the next chunk would exceed that cap. A single
payload larger than the cap is rejected in wide mode; it remains
compatible with the legacy window. ACKs stay ordered and use the same
timeouts. No wire messages or target verification gates change.
The streaming report records the number of nonempty ACK batches and
the peak unacknowledged payload bytes.

In an exact-QATQ localhost replay with the same synthetic input on each
run, the two window sizes committed 384 chunks and 247,512 encoded
bytes. The eight-chunk run drained 48 batches; the 32-chunk run drained
12 and peaked at 23,887 unacknowledged payload bytes. This validates
the sender behavior but does not predict the speedup over WSS/mTLS.

The 25 November 2026 live comparison used one `g4dn.xlarge` in
`us-east-1d` with the same checkpoint, vLLM 0.23.0, QATQ v0.4.5,
WSS/mTLS, and deferred diagnostics as the eight-chunk baseline.

| Metric | Eight chunks | 32 chunks |
| --- | ---: | ---: |
| ACK batches (384 chunks) | 48 | 12 |
| ACK wait | 9.68 s | 2.26 s |
| Streaming | 16.73 s | 9.23 s |
| Alert to first valid token | 37.21 s | 29.08 s |
| Alert to first completed task | 42.19 s | 34.60 s |
| QATQ payload | 13,320,355 bytes | 13,320,355 bytes |

The wide run peaked at 1,159,676 unacknowledged payload bytes
(about 1.11 MiB). The checkpoint digest matched, all eight blocks
restored, vLLM reused 1,904 tokens, and all 128 continuation tokens
matched both baseline references. Stale-source write and task replay
rejection passed. The QATQ gate recorded 384 exact chunks and no
pass-through. Cross-host timing uncertainty was ±0.34 s.
This is one run per configuration. The 7.42 s reduction in ACK wait
accounts for almost all of the 7.50 s observed streaming difference,
but this run does not establish a general latency distribution.

Independent AWS queries verified instance termination and deletion of
the root volume, network interface, security group, and key pair.
The temporary local checkpoint copies, private keys, and control
socket were removed, and no test listeners remained.

#### Streaming compression profile

The streaming manifest's additive `compression_detail` fields report
the raw F32-to-little-endian packing used by the comparators, Zstd level 3,
LZ4, the separate QATQ input packing, and the call into the locked
QATQ v0.4.5 encoder. All are source-side wall-clock totals nested under
the existing comparator and payload-encoding totals. The fields do not
change the codec choice, input bytes, compression gate, or ACK path.

A separate sampled localhost replay used the actual pinned checkpoint
with a mock injector. It committed the same 384 chunks and the same
13,320,355 bytes. The sample caught QATQ converting the typed
little-endian input back to F32, as well as run-length candidate
encoding and byte-plane Zstd. The upstream typed F32 entry point
decodes to a float slice and calls the default exact F32 encoder;
the direct F32 entry point is therefore a candidate to test for
byte-for-byte parity. The sampler perturbs timing, so its timings
are not used as the WAN baseline.

The instrumented run on 25 November 2026 used the same pinned
checkpoint, 32-chunk window, QATQ v0.4.5 and vLLM 0.23.0 on one
`g4dn.xlarge` in `us-east-1d`. The streaming timings below are
source-side on an Apple Silicon debug build:

| Streaming work | Wall time |
| --- | ---: |
| Comparator input packing | 0.33 s |
| Zstd level 3 comparison | 0.97 s |
| LZ4 comparison | 2.55 s |
| QATQ input packing | 0.32 s |
| QATQ library call, including internal F32 unpack | 2.60 s |
| ACK wait across 12 batches | 2.51 s |
| Layout | 0.20 s |
| Send (incl. CRC) | 0.02 s |
| Streaming total | 9.50 s |

The two standalone comparisons plus their packing took 3.85 s;
packing and exact QATQ encoding took 2.92 s. Together they account
for about 71% of this streaming interval. Payload sizes were unchanged:
13,320,355 bytes with QATQ, 20,405,381 with Zstd, and 28,739,217
with LZ4, against 50,331,648 raw padded bytes. All 384 chunks used
exact QATQ; no pass-through was used.

First valid token and first completed task took 30.60 s and 35.63 s
(±0.13 s cross-host uncertainty), versus 29.08 s and 34.60 s in the
previous run. Streaming was 9.50 s versus 9.23 s. Single-run differences
do not estimate instrumentation overhead. The verified off-host copy
restored all eight blocks, vLLM reused 1,904 tokens after clearing
its baseline cache, and the 128 continuation tokens matched MLX and
native vLLM. The fenced source lease and replayed task were rejected.

The biggest measured opportunity is the 3.85 s spent computing
comparator evidence on the streaming path. Test overlapping it or
precomputing it for the pinned checkpoint and layout without bypassing
the compression gate. Separately, test direct F32 encoding for exact
byte parity before removing the redundant conversion.

Independent AWS queries verified termination and deletion of the root
volume, network interface, security group, and key pair. Local
checkpoint copies and private keys were removed; the loopback daemon,
migration listener, and SSH control socket were gone.

### Earlier local validation

Local integration passed with a live Qwen2.5 MLX exporter and the loopback
mock injector. The run transferred 172,109 QATQ payload bytes for 16 tokens
across 24 layers and committed approximately 1.46 seconds after the alert.
This run did not use vLLM. AWS rejected the identity check because the
session had expired, so the prewarmed target flow was not run.
