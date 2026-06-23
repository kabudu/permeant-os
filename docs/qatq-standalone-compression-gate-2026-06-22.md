# QATQ Standalone Compression Gate - 2026-06-22

This report records the first proper standalone QATQ compression test against a
real PermeantOS KV migration bundle. It is separate from the AWS exact
compatibility proof in
[`docs/aws-real-runtime-qatq-exact-complex-2026-06-22.md`](aws-real-runtime-qatq-exact-complex-2026-06-22.md).

## Summary

| Field | Value |
| --- | --- |
| PermeantOS branch | `codex/qatq-exact-migration-artifacts` |
| QATQ repository | `/Users/kabudu/projex/qatq` |
| QATQ branch | `codex/qatq-standalone-production` |
| QATQ commit | `3d223bc` |
| Model | `Qwen/Qwen2.5-0.5B-Instruct` |
| Source runtime | MLX live runtime |
| Exported prefix | 1,920 tokens |
| Bundle layout | layer-major, key then value, raw f32 little-endian |
| Captures | 48 tensors, 24 layers x key/value |
| Raw bytes | 47,185,920 |
| Bundle SHA-256 | `sha256:33f27c620996893bba290447d5b889b80b607b162d6bfb973697584ee05ccede` |
| Gate policy | `competitive-compression` |
| Gate status | pass |

## Compression Results

The benchmark used the standalone QATQ `qatq-bench` binary with synthetic
fixtures disabled:

```sh
/Users/kabudu/projex/qatq/target/debug/qatq-bench \
  --input permeantos-qwen25-1920-full-kv:/tmp/permeantos-qatq-proper-20260622/permeantos-qwen25-1920-full-kv.layer-major.f32le \
  --output /tmp/permeantos-qatq-proper-20260622/qatq-bench.md \
  --gate-output /tmp/permeantos-qatq-proper-20260622/qatq-competitive-gate.md \
  --no-synthetic \
  --exact-only \
  --gate-policy competitive-compression
```

| Codec | Encoded bytes | Ratio vs raw f32 | Encode us | Decode us | Exact bits |
| --- | ---: | ---: | ---: | ---: | --- |
| `zstd-raw-f32le` | 20,713,110 | 0.4390 | 1,118,314.17 | 659,291.32 | yes |
| `lz4-raw-f32le` | 29,767,595 | 0.6309 | 2,331,303.37 | 891,025.49 | yes |
| `qatq-exact` | 14,097,901 | 0.2988 | 7,283,395.97 | 708,777.81 | yes |
| `qatq-exact-container` | 14,522,992 | 0.3078 | 7,428,728.44 | 767,545.96 | yes |

QATQ passed the acceptance gate:

- `qatq-exact` ratio `0.2988` beat raw, `zstd` ratio `0.4390`, and `lz4`
  ratio `0.6309`.
- `qatq-exact-container` ratio `0.3078` also beat raw, `zstd`, and `lz4`.
- QATC transferred 14,522,992 bytes instead of 47,185,920 raw bytes, saving
  32,662,928 bytes.

## Independent Exactness Check

The standalone QATQ CLI also encoded and decoded the same packed KV bundle, and
`cmp` verified byte-for-byte restoration:

```sh
/Users/kabudu/projex/qatq/target/debug/qatq encode-chunked \
  --max-values-per-chunk 65536 \
  --dtype f32 \
  /tmp/permeantos-qatq-proper-20260622/permeantos-qwen25-1920-full-kv.layer-major.f32le \
  /tmp/permeantos-qatq-proper-20260622/permeantos-qwen25-1920-full-kv.qatc

/Users/kabudu/projex/qatq/target/debug/qatq decode \
  /tmp/permeantos-qatq-proper-20260622/permeantos-qwen25-1920-full-kv.qatc \
  /tmp/permeantos-qatq-proper-20260622/permeantos-qwen25-1920-full-kv.decoded.f32le

cmp \
  /tmp/permeantos-qatq-proper-20260622/permeantos-qwen25-1920-full-kv.layer-major.f32le \
  /tmp/permeantos-qatq-proper-20260622/permeantos-qwen25-1920-full-kv.decoded.f32le
```

File sizes from the independent CLI path:

| Artifact | Bytes |
| --- | ---: |
| Raw packed bundle | 47,185,920 |
| QATC container | 14,522,992 |
| Decoded raw bundle | 47,185,920 |

## What This Does And Does Not Prove

This is the proper local compression gate for QATQ on a real PermeantOS KV
bundle. It proves that the standalone QATQ crate can compress this exported
full-KV bundle exactly and beat raw, `zstd`, and `lz4` on transfer size.

It does not yet prove live AWS migration with the standalone QATQ crate wired
into PermeantOS. The next production validation step is to replace the in-tree
compatibility path in live migration with the pinned standalone crate, rerun the
AWS E2E profile, and require both continuation fidelity and the same
compression gate on the transferred migration artifacts.
