# Adaptive Transfer Codec Experiments

PermeantOS can now plan adaptive KV transfer codec experiments without
mislabeling unimplemented codecs as executable runtime paths. The planner
models source and target capabilities, codec preference order, reversible/lossy
semantics, estimated transferred bytes, runner support, and fallback behavior.

Generate the default plan:

```bash
scripts/plan-transfer-codecs.py \
  --markdown-out benchmark-manifests/transfer-codec-plan.md \
  --pretty
```

The JSON output uses schema version `permeantos-transfer-codec-plan-v0`.

## Codec Catalog

| Codec | Manifest value | Runner support | Semantics | Fidelity evidence |
| --- | --- | --- | --- | --- |
| `raw` | `none` | yes | reversible | not required by the codec |
| `fp8` | `fp8` | yes | lossy quantized | required for claims |
| `turboquant` | `turboquant` | no | lossy experimental candidate | required |
| `qatq` | `qatq` | yes | lossy experimental int4 | required |

`qatq` is the planning identifier for Quaternion-Augmented TurboQuant candidate
experiments.

## Capability Negotiation

The planner only selects a codec when both the source and target advertise that
codec. By default, it also requires the current PermeantOS runner to support the
codec. That means the current executable selection is limited to:

- `raw`, represented in existing manifests as `transfer_quantization: none`
- `fp8`, represented as `transfer_quantization: fp8`

For example, if both runtimes advertise `qatq`, the default plan can select it
as an executable experimental codec, but any claim must be backed by
real-runtime fidelity evidence.

To plan speculative codec experiments before runner support exists, pass:

```bash
scripts/plan-transfer-codecs.py \
  --source-codecs raw,fp8,qatq \
  --target-codecs raw,fp8,qatq \
  --allow-unimplemented-codecs \
  --pretty
```

Plans produced with `--allow-unimplemented-codecs` are design artifacts. They do
not produce runnable `PERMEANT_TRANSFER_QUANTIZATION` environment blocks for
unsupported codecs.

## Fallbacks

Each planned point has one selected codec or a fallback action:

- Select the highest-preference codec that is mutually supported and executable.
- If no preferred lossy codec is executable but raw transfer is available,
  select `raw`.
- If no mutual transfer codec exists, fall back to `re_prefill`.

Lossy codecs require decode-fidelity evidence before their performance numbers
can support a real-runtime fidelity claim. Use
`scripts/analyze-fidelity-horizons.py` and
`scripts/compare-transfer-quantization.py --require-fidelity-horizon` for those
claims.

## Current Limitations

- TurboQuant-style codecs are planning candidates only; there is no payload
  encoder/decoder or target rehydration path yet. `qatq` has an experimental
  quaternion-grouped int4 encoder/decoder in the current runner.
- The byte estimates are comparative planning estimates, not measured benchmark
  results.
- The current AWS runner accepts `PERMEANT_TRANSFER_QUANTIZATION` values of
  `none`, `fp8`, and experimental `qatq`.
- Production adaptive codec selection will need runtime capability exchange,
  manifest schema updates, codec-specific validation metadata, and rollback
  behavior in the migration protocol.
