# PermeantOS Deployment and Testing Guideline

This guide details how to build, run, and verify the PermeantOS hypervisor system and the USXF v1.1 exchange format locally.

---

## 1. Prerequisites
Ensure the following tools are installed on your system:
* **Rust Toolchain:** Version `1.70+` (standard Cargo workspace build tools). Verify using `cargo --version`.
* **Python 3:** Version `3.8+` (for Python SDK and memory graph scripting). Verify using `python3 --version`.

---

## 2. Workspace Overview
The project is organized as a Rust cargo workspace containing the following crates:
* `crates/usxf-core`: Implementations of USXF v1.1 schemas, AES encryption, and Ed25519 signatures.
* `crates/transpiler`: Reshaping logic for GQA tensors and FP8 scaled quantizers.
* `crates/transport`: The framed TCP streaming server and client protocols.
* `crates/orchestrator`: The transition state machine, quotas, and warm-start decision math.
* `crates/extractor` & `crates/injector`: Device cache extraction and `KVConnectorBase_V1` layout injection.
* `crates/cli`: CLI binaries exposing the daemon and client subcommands.
* `sdk/python`: Companion Python client and agent conversation graph tracking.

---

## 3. Step-by-Step Testing Guide

### Step 3.1: Build the Workspace
Compile the entire workspace crates:
```bash
cargo build
```

---

### Step 3.2: Run the Automated Unit & Integration Tests
Execute all unit tests and socket-streaming integration tests (including packet tampering, invalid CRC32 payload injection, token offsets, and socket dropouts):
```bash
cargo test
```
*Expected Output:* You should see all tests pass successfully, including:
* `tests::test_migration_state_transitions` (Orchestrator state verification)
* `tests::test_warm_start_decision_boundary` (Empirical warm-start model checks)
* `tests::test_gqa_layout_exactness` (Reshaping layout correctness)
* `tests::test_extreme_quantization_values` (FP8 saturation, subnormal, and NaN propagation)
* `test_tcp_handshake_and_exchange` (E2E TCP socket handshake integration)
* `test_crc32_corruption_handling` (Checksum fail verification)
* `test_protocol_abort_mid_stream` (Graceful rollback on network failures)

---

### Step 3.3: Run the Local End-to-End Live Migration
You can run a complete, simulated migration process locally using the CLI binary.

1. **Start the Hypervisor Daemon Listener:**
   Open a terminal and start the target daemon. It will listen for incoming migrations:
   ```bash
   cargo run --bin permeant-cli -- daemon --addr 127.0.0.1:9099
   ```

2. **Trigger the Migration Client:**
   Open a second terminal window and run the migration runner to transmit a mock KV cache context (e.g. 512 tokens) to the listener:
   ```bash
   cargo run --bin permeant-cli -- sim-migrate --target-addr 127.0.0.1:9099 --seq-len 512
   ```
   *Expected Client Output:*
   * Connection to target established.
   * Capability handshake succeeds.
   * Signed and encrypted USXF header is transmitted.
   * GQA blocks are reshaped, sent chunk-by-chunk, and acknowledged.
   * Two-phase commit succeeds, confirming all layers have been verified.

3. **Run with FP8 Quantization Enabled:**
   To test streaming compression, run the migration client with the `--quant` flag:
   ```bash
   cargo run --bin permeant-cli -- sim-migrate --target-addr 127.0.0.1:9099 --seq-len 512 --quant
   ```
   *Note:* The target daemon will dynamically detect the quantization metadata in the decrypted header, dequantize the FP8 inputs, and verify block consistency on the fly.

4. **Inspect the Migration Benchmark Manifest:**
   Each completed simulated migration writes a manifest file in the working directory:
   ```bash
   migration-YYYYMMDD-HHMMSS-PID-manifest.json
   ```
   The manifest captures enough context for post-run analysis and benchmark comparison, including:
   * Source environment: OS, architecture, hostname, Git commit, process ID, and working directory.
   * Target information: target address and negotiated target device.
   * Model/cache geometry: model identity, USXF version, attention type, sequence length, layers, head counts, head dimension, block size, expected blocks, and block hash count.
   * Transfer configuration: dtype, source quantization, transfer quantization, uncompressed bytes, transferred bytes, compression ratio, chunks sent, and average chunk size.
   * Phase timings: handshake, header, transfer, commit, total time, and effective bandwidth.
   * Outcome metadata: phase status, success flag, and optional error message.
   * Optional Agent Memory Graph metadata when `sim-migrate` is run with
     `--agent-graph-manifest <path>`: graph hash, prompt byte/token hashes,
     tokenizer hash, artifact hashes, simulated KV hash, and daemon graph/KV
     transaction binding evidence.

   Failed target commits also write a manifest with `success: false` and `phase_status: "commit_failed"` before returning the error, so failed benchmark attempts can still be analyzed after the fact.
   Failed graph-bound migrations rejected before commit write
   `phase_status: "graph_binding_failed"`.

---

### Step 3.4: Test the Python SDK and Memory Graph
Run the Python SDK verification script to check the conversation turn mapping and header serialization:
```bash
python3 sdk/python/test_sdk.py
```
*Expected Output:*
```
Testing AgentMemoryGraph...
AgentMemoryGraph test: PASSED
All SDK unit tests: PASSED
```

---

### Step 3.5: Inspect USXF Header Files
If you serialize metadata to a local JSON file, you can verify and print its structure using the inspect subcommand:
```bash
cargo run --bin permeant-cli -- inspect --file /path/to/usxf_header.json
```
This utility parses and displays the version, model configuration weights, attention types (GQA/MLA), and content-addressable block hashes.

---

## 4. Observed Local Validation Results

The following results were captured on **June 13, 2026** by running the guide end to end on a local macOS Apple Silicon host:

```bash
cargo build
cargo test
python3 sdk/python/test_sdk.py
cargo run --bin permeant-cli -- daemon --addr 127.0.0.1:9099
cargo run --bin permeant-cli -- sim-migrate --target-addr 127.0.0.1:9099 --seq-len 512
cargo run --bin permeant-cli -- sim-migrate --target-addr 127.0.0.1:9099 --seq-len 512 --quant
```

### Validation Summary

* `cargo build` completed successfully.
* `cargo test` passed, including orchestrator state tests, transpiler quantization/layout tests, transport integration tests, and USXF crypto/serialization tests.
* `python3 sdk/python/test_sdk.py` passed:
  * `AgentMemoryGraph test: PASSED`
  * `All SDK unit tests: PASSED`
* The daemon accepted both migration runs, verified the encrypted USXF header, streamed all payload chunks, passed numerical continuation validation, and committed both migrations successfully.

### Benchmark Manifests Captured

* `migration-20260613-224249-18942-manifest.json`
* `migration-20260613-224255-19470-manifest.json`

### Benchmark Snapshot

| Run | Transfer Quantization | Transferred Bytes | Compression Ratio | Transfer Time (ms) | Total Time (ms) | Effective Bandwidth (Gbps) | Result |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| Baseline | `none` | 2,097,152 | 1.00 | 425.394 | 456.196 | 0.0394 | `committed` |
| Compressed | `fp8` | 524,288 | 0.25 | 132.369 | 166.572 | 0.0317 | `committed` |

### Analysis

* FP8 transfer quantization reduced payload size by **75%** relative to the uncompressed baseline.
* Total end-to-end runtime improved from **456.196 ms** to **166.572 ms**, a reduction of about **63.5%** for the local 512-token migration.
* Transfer time improved from **425.394 ms** to **132.369 ms**, a reduction of about **68.9%**.
* Both runs sent `16` chunks because the block geometry was unchanged; the performance gain came from smaller chunk payloads, with average chunk size dropping from `131,072` bytes to `32,768` bytes.
* The reported effective bandwidth is lower than real hardware/network ceilings because this benchmark exercises a localhost mock transport path and includes application-level framing and processing overhead.

### Environment Snapshot

The captured manifests recorded the following source environment for both runs:

* OS: `macos`
* Architecture: `aarch64`
* Hostname: `Mac.lan`
* Git commit: `9f0ecf5`
* Working directory: `/Users/kabudu/projex/permeant-os`
* Target address: `127.0.0.1:9099`
* Negotiated target device: `Metal/Mock`

### Interpretation and Limits

These results validate that the current local migration path, manifest generation, header verification, chunk streaming, and commit flow all work together as documented.

These numbers should **not** be treated as cloud or cross-hardware production benchmarks. The current run used:

* A single local host
* Loopback networking
* A mock target device string (`Metal/Mock`)
* A short `512` token context

For publishable performance claims, the next benchmark pass should repeat this flow across two hosts and record:

* Source and target hardware types
* Real network latency and throughput
* Larger sequence lengths such as `16k`, `32k`, and `64k`
* Re-prefill baselines for direct comparison
* Multiple repeated runs per configuration

---

## 5. Cloud Host Benchmark Procedure

This section turns the local validation flow into a repeatable two-host benchmark for real networked machines.

### Goal

Use one machine as the **source** host running `sim-migrate` and a second machine as the **target** host running the PermeantOS daemon. Collect manifests from the source host for each run and summarize them into benchmark notes.

This procedure is intentionally provider-agnostic. It does not assume AWS, GCP, Azure, or any specific image. The only hard requirement is that both hosts can build the workspace and that the source host can reach the target host over TCP.

### Recommended Test Topology

* **Source host:** machine that runs `sim-migrate`
* **Target host:** machine that runs `daemon`
* **Network path:** public IP, private VPC/VNet IP, or VPN/private tunnel
* **Port:** `9099/tcp` unless you intentionally choose another port

### Minimum Host Setup

Perform the following on **both** hosts:

1. Clone the repository and enter the workspace:
   ```bash
   git clone <repo-url>
   cd permeant-os
   ```

2. Confirm toolchain availability:
   ```bash
   cargo --version
   python3 --version
   ```

3. Build the workspace:
   ```bash
   cargo build
   ```

4. Run the test suite once before benchmarking:
   ```bash
   cargo test
   python3 sdk/python/test_sdk.py
   ```

### Network and Security Setup

On the **target** host:

1. Ensure the daemon port is reachable from the source host.
2. Open inbound `9099/tcp` in the host firewall or cloud security group.
3. Prefer a private network path when available.
4. Record the target IP or DNS name that the source host will use.

Suggested verification from the **target** host:

```bash
ss -ltn | grep 9099
```

Important: avoid probing the running daemon with a raw TCP check such as `nc -vz <target-host> 9099`. The current daemon expects a PermeantOS migration protocol handshake on the first accepted connection, so a generic probe can cause an early EOF and force a daemon restart before the real benchmark run.

### Target Host Procedure

Start the daemon on the target host:

```bash
cargo run --bin permeant-cli -- daemon --addr 0.0.0.0:9099
```

Notes:

* Use `0.0.0.0:9099` only when you intend to accept remote connections.
* If you want to restrict binding to a private interface, replace `0.0.0.0` with that interface IP.
* Keep the daemon terminal open for the duration of the benchmark run set.

### Source Host Procedure

Run one migration per benchmark point. Start with a small sanity check:

```bash
cargo run --bin permeant-cli -- sim-migrate --target-addr <target-host>:9099 --seq-len 512
```

Then run the same point with transfer quantization:

```bash
cargo run --bin permeant-cli -- sim-migrate --target-addr <target-host>:9099 --seq-len 512 --quant
```

After the connectivity check passes, expand to larger benchmark points such as:

```bash
cargo run --bin permeant-cli -- sim-migrate --target-addr <target-host>:9099 --seq-len 16384
cargo run --bin permeant-cli -- sim-migrate --target-addr <target-host>:9099 --seq-len 16384 --quant
cargo run --bin permeant-cli -- sim-migrate --target-addr <target-host>:9099 --seq-len 32768
cargo run --bin permeant-cli -- sim-migrate --target-addr <target-host>:9099 --seq-len 32768 --quant
cargo run --bin permeant-cli -- sim-migrate --target-addr <target-host>:9099 --seq-len 65536
cargo run --bin permeant-cli -- sim-migrate --target-addr <target-host>:9099 --seq-len 65536 --quant
```

### Benchmark Matrix

At minimum, collect the following matrix:

| Sequence Length | Transfer Quantization | Repetitions |
| --- | --- | ---: |
| `512` | `none`, `fp8` | `3` |
| `16384` | `none`, `fp8` | `3` |
| `32768` | `none`, `fp8` | `3` |
| `65536` | `none`, `fp8` | `3` |

If the environment is stable enough, extend the matrix with:

* Different source/target hardware pairings
* Different regions or availability zones
* Different network types such as public internet vs private VPC

### Manifest Collection

Each successful source-host run writes a manifest file named like:

```bash
migration-YYYYMMDD-HHMMSS-PID-manifest.json
```

After each batch, archive the manifests into a run directory:

```bash
mkdir -p benchmark-manifests/<run-label>
mv migration-*-manifest.json benchmark-manifests/<run-label>/
```

Recommended run label format:

```text
YYYYMMDD-source-to-target-region-or-network
```

Example:

```text
20260613-macos-metal-to-linux-cuda-private-vpc
```

### Benchmark Notes Template

For each benchmark batch, record the following alongside the manifests:

* Date and operator
* Git commit on source and target
* Source hardware and OS
* Target hardware and OS
* Cloud provider and instance types
* Region / zone
* Network path type
* Daemon bind address and advertised target address
* Sequence lengths tested
* Whether `--quant` was used
* Any failures, retries, or anomalies

### How to Analyze the Manifests

For each manifest, extract and compare:

* `sequence_length`
* `transfer_quantization`
* `uncompressed_bytes`
* `transferred_bytes`
* `compression_ratio`
* `transfer_time_ms`
* `total_time_ms`
* `effective_bandwidth_gbps`
* `success`
* `error_message`

Recommended summary outputs:

* Mean and median `transfer_time_ms` per sequence length
* Mean and median `total_time_ms` per sequence length
* Compression savings for `fp8` vs `none`
* Failure rate by configuration
* Best and worst run per configuration

### Validation Criteria

A cloud-host benchmark batch should be considered valid when:

* All prerequisite builds and tests pass on both hosts
* The daemon accepts connections from the source host
* Each benchmark point produces at least one successful manifest
* Repeated runs remain within an acceptable variance band for your environment
* Any failed manifests are preserved and documented rather than discarded

### Interpreting Results

Use the cloud-host numbers to answer these questions:

* At what sequence length does migration begin to outperform re-prefill in your environment?
* How much does FP8 reduce transfer time relative to uncompressed transfer?
* Is network latency or payload size the dominant contributor to total runtime?
* Does performance remain stable across repeated runs?

### Recommended Follow-On Documentation

After running a cloud-host batch, add a short benchmark note to the repository that includes:

* The benchmark matrix used
* The environment summary
* A compact table of mean timings
* A short interpretation of where migration becomes attractive
* Links or paths to the raw manifest files used for the summary

### Observed AWS Cross-Host Results

The following cross-host run was captured on **June 14, 2026** with:

* Source host: local macOS Apple Silicon laptop running the migration client
* Target host: disposable AWS `t4g.small` VM in `eu-west-1`
* Target OS: Amazon Linux 2023 ARM64
* Network path: public internet
* Sequence length: `512`
* Runs: baseline plus `--quant`

### Cross-Host Validation Summary

* The AWS VM built `permeant-cli` successfully and accepted remote connections on `9099/tcp`.
* Both cross-host migration runs completed successfully.
* The daemon verified the encrypted header, streamed all chunks, passed continuation validation, and committed both migrations.
* All disposable AWS resources created for the run were torn down afterward.

### Cross-Host Benchmark Manifests Captured

* `migration-20260613-230944-45124-manifest.json`
* `migration-20260613-230955-45910-manifest.json`

### Cross-Host Benchmark Snapshot

| Run | Transfer Quantization | Transferred Bytes | Compression Ratio | Handshake Time (ms) | Transfer Time (ms) | Total Time (ms) | Effective Bandwidth (Gbps) | Result |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Baseline | `none` | 2,097,152 | 1.00 | 68.376 | 2162.037 | 2372.120 | 0.0078 | `committed` |
| Compressed | `fp8` | 524,288 | 0.25 | 65.976 | 1256.565 | 1503.203 | 0.0033 | `committed` |

### Cross-Host Analysis

* FP8 transfer quantization reduced payload size by **75%** relative to the uncompressed cross-host baseline.
* Total end-to-end runtime improved from **2372.120 ms** to **1503.203 ms**, a reduction of about **36.6%**.
* Transfer time improved from **2162.037 ms** to **1256.565 ms**, a reduction of about **41.9%**.
* Both runs still sent `16` chunks; the gain came from reduced payload size, with average chunk size dropping from `131,072` bytes to `32,768` bytes.
* Relative to the earlier localhost validation, handshake and transfer phases are meaningfully slower, which is expected for a real public-network cross-host run.

### Cross-Host Interpretation and Limits

These numbers are more representative than the localhost run because they include a real remote host and public-network latency.

They are still limited in scope:

* The target is a small CPU-only cloud instance, not a GPU-backed inference node.
* The benchmark used a short `512` token context.
* Only a single successful run per configuration was captured.
* The current protocol and daemon are still a simulation path rather than a production inference integration.

For a stronger benchmark set, repeat the same matrix at `16k`, `32k`, and `64k`, and capture at least three runs per configuration.

## AWS fallback cross-host result (June 15, 2026)

After a fresh Runpod retry was blocked by Cloudflare `403` / `1010` from the current environment, and after AWS rejected `g4dn.xlarge` launches because the account GPU vCPU quota was `0`, we ran the Amazon fallback path on the cheapest disposable x86 EC2 host that could still exercise the current target daemon flow.

Successful fallback run details:

- Provider: AWS EC2
- Target instance: `t3.medium`
- Region: `us-east-1`
- Source runtime: live `mlx_lm` process on the laptop
- Transport path: local SSH tunnel to the remote daemon
- Successful transfer mode: `fp8`
- Sequence length: `2048`
- Layers transferred by the current CLI path: `4`
- Expected blocks: `8`
- Chunks sent: `64`
- Transferred bytes: `2097152`
- Handshake time: `223.81562499999998 ms`
- Header time: `135.27108299999998 ms`
- Transfer time: `9837.705375000001 ms`
- Commit time: `1190.1692500000001 ms`
- Total time: `23106.294833 ms`
- Effective bandwidth: about `0.001705 Gbps`
- Manifest: `migration-20260615-195032-6976-manifest.json`

Target-side evidence captured during the successful run:

- The remote daemon accepted the capability request, verified the encrypted header, streamed all payload chunks, and committed successfully.
- The staged target payload and ready descriptor were present in `/tmp/permeant-vllm-import`.
- The staged block hash matched the earlier successful cross-host proof runs: `sha256:752b47177c4c532507d41557f9c2079d59d7ae8c676281199e826a6636c76640`.

Important interpretation:

- This is a successful Amazon cross-host proof run with a live MLX source and a real public-network target.
- It is not yet the final AWS GPU benchmark because the target was CPU-backed and the account GPU quota blocked `g4dn.xlarge`.
- The direct SSH-forwarded TCP path performed substantially better than the temporary Runpod HTTP bridge used when raw port forwarding was unavailable.

Cleanup result from the June 15, 2026 AWS fallback run:

- The EC2 instance was terminated immediately after the run.
- The temporary security group and EC2 key pair were deleted.
- The local SSH tunnel and local temporary AWS state artifacts were removed.
- The final AWS leftover check for the tagged instance returned `[]`.

AWS GPU rerun gate:

- Before rerunning this flow on a real GPU-backed Amazon target, the account needs a GPU quota increase.
- The cheapest practical rerun target remains `g4dn.xlarge`.

## AWS GPU-backed cross-host result (June 15, 2026)

After the `us-east-1` EC2 `Running On-Demand G and VT instances` quota propagated, we reran the same live-source AWS path against a disposable `g4dn.xlarge` target.

Successful GPU-backed run details:

- Provider: AWS EC2
- Target instance: `g4dn.xlarge`
- Region: `us-east-1`
- Availability Zone: `us-east-1d`
- Source runtime: live `mlx_lm` process on the laptop
- Transport path: local SSH tunnel to the remote daemon
- Successful transfer mode: `fp8`
- Sequence length: `2048`
- Layers transferred by the current CLI path: `4`
- Expected blocks: `8`
- Chunks sent: `64`
- Transferred bytes: `2097152`
- Handshake time: `186.936667 ms`
- Header time: `197.943916 ms`
- Transfer time: `11665.199417 ms`
- Commit time: `871.152375 ms`
- Total time: `25245.342833 ms`
- Effective bandwidth: about `0.001438 Gbps`
- Manifest: `migration-20260615-215310-60139-manifest.json`

Comparison against the June 15 AWS CPU fallback and earlier Runpod proofs:

| Run | Target | Transfer time (ms) | Commit time (ms) | Total time (ms) | Effective bandwidth (Gbps) | Result |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| AWS GPU | `g4dn.xlarge` | 11665.199417 | 871.152375 | 25245.342833 | 0.001438227963385703 | `committed` |
| AWS CPU fallback | `t3.medium` | 9837.705375000001 | 1190.1692500000001 | 23106.294833 | 0.0017053993142176205 | `committed` |
| Runpod live-source proof | RTX 3090 | 143485.886833 | 690.566042 | 156377.4295 | 0.00011692589682723728 | `committed` |
| Runpod HTTP bridge proof | RTX 3090 | 40803.50075 | 613.6366250000001 | 54649.212125 | 0.0016446839797195588 | `committed` |

Important interpretation:

- The GPU-backed AWS run is much stronger than the earlier Runpod proofs as a cloud-host benchmark point.
- The current benchmark still appears transport- and staged-import-bound rather than GPU-compute-bound, because the CPU fallback remained slightly faster on this exact 2048-token slice.
- The result still meaningfully de-risks the intended target environment shape because the cross-host path now works end to end on a GPU-backed public-cloud instance.

Cleanup result from the June 15, 2026 AWS GPU-backed run:

- The EC2 instance was terminated immediately after the run.
- The temporary security group and EC2 key pair were deleted.
- The local SSH tunnel and local temporary AWS state artifacts were removed.
- Final leftover verification returned `instances=[]` and `security_groups=[]`.

After the June 16, 2026 rerun against the live in-process `vLLM` target path, we also captured the first exact source-versus-target continuation comparison.

Successful live-runtime comparison run details:

- Provider: AWS EC2
- Target instance: `g4dn.xlarge`
- Region: `us-east-1`
- Availability Zone: `us-east-1d`
- Source runtime: live `mlx_lm` process on the laptop
- Transport path: local SSH tunnel to the remote daemon
- Successful transfer mode: `fp8`
- Sequence length: `2048`
- Manifest: `migration-20260616-120353-7158-manifest.json`
- Transfer time: `10966.254541 ms`
- Commit time: `200688.12758300002 ms`
- Total time: `222650.506042 ms`
- Effective bandwidth: `0.001529894818442734 Gbps`

Verdict after the June 16, 2026 live-runtime comparison run:

- PermeantOS works end to end on the intended live-source to live-target runtime path.
- The system successfully completed extraction, cross-host transfer, target-side live cache registration, post-migration generation, and committed migration state.
- The new comparison harness shows that continuation fidelity is close but not yet exact: the first `15` generated tokens matched and the first divergence happened at token index `15`.
- This moves the project out of the “prototype might work” category and into “real system works, with a measurable remaining fidelity gap.”

Interpretation of the long total runtime:

- The transfer path stayed in-family with earlier successful AWS runs.
- The much larger total time came from a cold target-runtime bring-up cost inside commit: first-time `vLLM` initialization, model load, KV-cache sizing, and FlashInfer warmup on a fresh cloud host.
- That means this run is the strongest functional proof so far, but not yet the best steady-state latency benchmark.

## Runpod cloud-host preflight and cleanup notes

The June 14, 2026 Runpod validation established that the cheapest usable GPU host for this project can be provisioned automatically, but a stock pod is not reachable for bootstrap unless the Runpod account already has an SSH public key configured.

Observed results from the automated provisioning pass:

- Provider: Runpod
- Credit balance before cleanup: about `$10`
- Working stock image path: `runpod/base:1.0.2-ubuntu2204`
- Cheapest healthy pod we brought up: community `NVIDIA GeForce RTX 3090` at `$0.22/hr`
- Pod health: `running`
- Public SSH mapping: assigned successfully
- Bootstrap blocker: account `pubKey` was `null`, so SSH login failed with `Permission denied (publickey,password)`

What this means operationally:

- Runpod can serve as the target cloud host for the cross-host migration plan.
- The missing prerequisite is not pod capacity; it is account-level SSH bootstrap access.
- Until a public key is configured in the Runpod account, we should treat automated pod creation as a preflight-only step, not a runnable benchmark step.

Recommended preflight before the next Runpod attempt:

1. Add an SSH public key to the Runpod account settings.
2. Re-run pod provisioning with the stock `runpod-ubuntu-2204` settings.
3. Use SSH tunnel forwarding for the migration daemon instead of exposing `9099` directly.
4. Capture the migration manifest after the remote daemon is reachable.

Cleanup guidance:

- Terminate the pod immediately after each attempt.
- Confirm `myself { pods { ... } currentSpendPerHr }` returns an empty pod list and `currentSpendPerHr: 0`.
- Prefer `volumeInGb: 0` for disposable validation hosts unless persistent storage is explicitly required.

Cleanup result from the June 14, 2026 Runpod attempt:

- Active pods after teardown: `0`
- Reported spend rate after teardown: `$0/hr`

## Runpod cross-host benchmark result (June 14, 2026)

A full cross-host migration completed successfully with the laptop as source and a disposable Runpod GPU VM as target.

Successful run details:

- Provider: Runpod
- Pod image: `runpod/base:1.0.2-ubuntu2204`
- GPU class: community `NVIDIA GeForce RTX 3090`
- Source host: `macos/aarch64/Mac.lan`
- Target host identity reported by daemon: `linux/x86_64/f3ce1078eff4`
- Transport path: local SSH tunnel to the remote daemon
- Successful transfer mode: `fp8`
- Sequence length: `8192`
- Layers: `4`
- Expected blocks: `32`
- Chunks sent: `256`
- Uncompressed bytes: `33554432`
- Transferred bytes: `8388608`
- Compression ratio: `0.25`
- Handshake time: `213.42025 ms`
- Header time: `3672.869 ms`
- Transfer time: `466088.31875 ms`
- Commit time: `105.85575 ms`
- Total time: `470178.86379100004 ms`
- Effective bandwidth: about `0.000144 Gbps`
- Manifest: `migration-20260614-071430-98488-manifest.json`

Important interpretation:

- The full end-to-end cross-host path works.
- The network path was the bottleneck, not the daemon handshake or commit path.
- An earlier payload implementation encoded chunk bytes as JSON arrays; switching payload chunks to compact binary framing materially improved the real WAN run.
- The successful result is still a runtime-simulated migration, not yet a real MLX-to-real-target-runtime state transfer.

## Runtime adapter milestone

The codebase now has a first real runtime adapter contract.

- Extractor can stay in mock mode or switch to `PERMEANT_EXTRACTOR_MODE=json_command`.
- Injector can stay in mock mode or switch to `PERMEANT_INJECTOR_MODE=json_command`.
- The adapter protocol is documented in `docs/runtime-adapter-protocol.md`.

That means the next milestone is no longer “invent the integration seam.”
It is now “implement concrete adapters,” starting with an MLX extractor and a Linux target-runtime injector.

## Live MLX source to Runpod target result (June 14, 2026)

A stronger cross-host run completed successfully with a real live MLX source runtime on the laptop and a disposable Runpod GPU target.

Successful run details:

- Provider: Runpod
- Pod image: `runpod/base:1.0.2-ubuntu2204`
- GPU class: community `NVIDIA GeForce RTX 3090`
- Source runtime: live `mlx_lm` process on the laptop
- Source model used for the live-source validation: `Qwen/Qwen2.5-0.5B-Instruct`
- Source host: `macos/aarch64/Mac.lan`
- Target host identity reported by daemon: `linux/x86_64/267476bfc675`
- Transport path: local SSH tunnel to the remote daemon
- Successful transfer mode: `fp8`
- Sequence length: `2048`
- Layers transferred by the current CLI path: `4`
- Expected blocks: `8`
- Chunks sent: `64`
- Uncompressed bytes: `8388608`
- Transferred bytes: `2097152`
- Compression ratio: `0.25`
- Handshake time: `347.537625 ms`
- Header time: `723.296959 ms`
- Transfer time: `143485.886833 ms`
- Commit time: `690.566042 ms`
- Total time: `156377.4295 ms`
- Effective bandwidth: about `0.000117 Gbps`
- Manifest: `migration-20260614-154223-70658-manifest.json`

Target-side staging evidence captured during the successful run:

- The remote receiver acknowledged the transferred block hash.
- The staged block payload was written on the target before teardown.
- The corresponding ready descriptor was also written on the target.
- The staged block hash for the successful run was `sha256:752b47177c4c532507d41557f9c2079d59d7ae8c676281199e826a6636c76640`.

Important interpretation:

- This is materially stronger than the earlier Runpod success because the source side was no longer a mock extractor path.
- The live laptop source runtime, live cross-host transport, remote staged injection path, and commit/verification flow all worked together in one run.
- The remaining gap is still direct registration into a live target inference runtime and continuation generation from that runtime.
- In other words, PermeantOS now demonstrates:
  - real live-source extraction
  - real cross-host transfer
  - real target-side staged receipt and acknowledgement
  - successful orchestrated commit

Recommended next milestone after this result:

1. Replace the directory-spool consumer with a real target-runtime consumer.
2. Preserve richer per-layer staging metadata for inspection and debugging.
3. Capture the first target-runtime continuation run and compare outputs against the source.

## Reusable Runpod HTTP-bridge workflow

Use this workflow when:
- the source host is your laptop
- the target host is a Runpod pod
- Runpod basic SSH gives you shell access but does not support SSH port forwarding for the daemon protocol

### What this workflow does

It keeps the successful migration path unchanged and swaps only the network carriage:
- pod side: `adapters/runpod_http_daemon_bridge.py server` exposes the daemon over the Runpod HTTP proxy
- local side: `adapters/runpod_http_daemon_bridge.py client` presents that HTTP path back to `sim-migrate` as a normal local TCP target

### Pod-side services

Start the target receiver:

```bash
mkdir -p /tmp/permeant-vllm-state /tmp/permeant-vllm-import /tmp/permeant-logs

export PERMEANT_VLLM_IMPORT_DIR=/tmp/permeant-vllm-import
export PERMEANT_VLLM_CONSUMER_HOOK=/workspace/permeant-os/adapters/vllm_directory_consumer.py:consume

nohup python3 /workspace/permeant-os/adapters/vllm_runtime_receiver.py \
  --host 127.0.0.1 \
  --port 29100 \
  --state-dir /tmp/permeant-vllm-state \
  >/tmp/permeant-logs/receiver.log 2>&1 &
```

Start the target daemon:

```bash
export PERMEANT_INJECTOR_MODE=json_command
export PERMEANT_INJECTOR_CMD='python3 /workspace/permeant-os/adapters/vllm_injector.py'
export PERMEANT_INJECTOR_HOOK=/workspace/permeant-os/adapters/vllm_hook_template.py:injector_hook
export PERMEANT_VLLM_RUNTIME_HOOK=/workspace/permeant-os/adapters/vllm_http_runtime_hook.py:runtime_hook
export PERMEANT_VLLM_RUNTIME_URL=http://127.0.0.1:29100

nohup /workspace/permeant-os/target/debug/permeant-cli daemon \
  --addr 127.0.0.1:29099 \
  >/tmp/permeant-logs/daemon.log 2>&1 &
```

Start the pod-side HTTP bridge on the Runpod-mapped HTTP port:

```bash
nohup python3 /workspace/permeant-os/adapters/runpod_http_daemon_bridge.py server \
  --host 0.0.0.0 \
  --port 19123 \
  --target-host 127.0.0.1 \
  --target-port 29099 \
  >/tmp/permeant-logs/http-bridge.log 2>&1 &
```

Health check:

```bash
curl -sS https://POD_ID-19123.proxy.runpod.net/health
```

Expected result:

```json
{"ok": true}
```

### Local source-side bridge

Expose the remote HTTP bridge as a local TCP target:

```bash
python3 /ABS/PATH/adapters/runpod_http_daemon_bridge.py client \
  --host 127.0.0.1 \
  --port 39099 \
  --remote-url https://POD_ID-19123.proxy.runpod.net
```

### Source-side migration command

Use the live MLX exporter as the source:

```bash
export PERMEANT_EXTRACTOR_MODE=json_command
export PERMEANT_EXTRACTOR_CMD='python3 /ABS/PATH/adapters/mlx_extractor.py'
export PERMEANT_EXTRACTOR_HOOK='/ABS/PATH/adapters/mlx_http_cache_provider.py:get_live_cache'
export PERMEANT_MLX_RUNTIME_URL='http://127.0.0.1:29101'

./target/debug/permeant-cli sim-migrate \
  --target-addr 127.0.0.1:39099 \
  --seq-len 2048
```

### What to record after the run

Capture these artifacts after each Runpod HTTP-bridge run:
- local migration manifest
- `/tmp/permeant-logs/daemon.log`
- `/tmp/permeant-logs/http-bridge.log`
- target staged files under `/tmp/permeant-vllm-import`
- any target-side state files under `/tmp/permeant-vllm-state`

### Benchmark interpretation

Use this path for:
- functional proof
- staging/commit validation
- manifest capture
- teardown rehearsal

Do not use it as the final transport benchmark because:
- Cloudflare proxy overhead dominates transfer timing
- the bridge serializes request/response hops that a direct TCP path would avoid

### Teardown

After a successful or failed run:
- stop the local bridge client
- terminate the Runpod pod
- verify the Runpod pod list is empty or contains no active billable pod for the test

## Addendum: real-runtime fidelity follow-up (2026-06-16)

A corrected 24-layer live migration was rerun against a real AWS `vLLM` target both with FP8 transfer quantization and with no transfer quantization.

Observed result:
- both runs completed successfully end to end
- both runs populated all `24` layers into the live target KV caches
- both runs generated the same target continuation mismatch at token index `15`
- removing FP8 transfer quantization did not change the mismatch

Conclusion:
- the remaining fidelity gap is not primarily a transfer-compression artifact
- the next debugging focus should be live `vLLM` cache semantics and any non-KV runtime state required for exact next-token parity

Reference:
- `docs/aws-real-runtime-fidelity-followup-2026-06-16.md`
