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

   Failed target commits also write a manifest with `success: false` and `phase_status: "commit_failed"` before returning the error, so failed benchmark attempts can still be analyzed after the fact.

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
