# Larger Context Benchmark Matrix

PermeantOS can plan larger-than-2k benchmark points with explicit target
context-window requirements. The planner does not run cloud infrastructure; it
generates a checked matrix and environment blocks for the AWS runner.

Generate the default larger-context matrix:

```bash
scripts/plan-context-benchmarks.py \
  --markdown-out benchmark-manifests/context-matrix.md \
  --env-out benchmark-manifests/context-matrix.env \
  --pretty
```

The default matrix covers `4096`, `8192`, `16384`, and `32768` token prefixes,
with both raw and FP8 transfer modes, three repetitions, and a 16-token
continuation horizon. For each point the planner computes:

- `required_context_window`: sequence length plus continuation tokens plus
  tokenizer/runtime overhead allowance.
- `runner_env`: environment variables for `scripts/aws-real-runtime-e2e.sh`.
- `source_env`: matching source runtime settings for the MLX source process.
- `valid`: whether the point is larger than 2k and inside any configured
  `--max-model-len-limit`.

Example larger context run:

```bash
PERMEANT_SEQ_LEN=8192 \
PERMEANT_VLLM_MAX_MODEL_LEN=8224 \
PERMEANT_TRANSFER_QUANTIZATION=none \
PERMEANT_CONTINUATION_MAX_TOKENS=16 \
PERMEANT_FIDELITY_HORIZONS=16 \
scripts/aws-real-runtime-e2e.sh run
```

Before running the AWS runner, the source MLX runtime must be started with the
matching source environment from the matrix:

```bash
PERMEANT_MLX_TARGET_SEQ_LEN=8192 \
PERMEANT_SOURCE_CONTINUATION_MAX_TOKENS=16 \
PERMEANT_SOURCE_CONTINUATION_FILE=/tmp/permeant-source-continuation.json \
PERMEANT_SOURCE_CONTINUATION_USE_PREFILL_PROMPT=1 \
PERMEANT_MLX_EXPORTER_HOOK="$PWD/adapters/mlx_live_runtime.py:provider" \
python3 adapters/mlx_runtime_exporter.py --host 127.0.0.1 --port 29101
```

Current limitations:

- This release adds repeatable planning and runner configuration for larger
  contexts; it does not claim new real-runtime larger-context benchmark
  results.
- Larger contexts require enough GPU memory for the selected model, vLLM
  `max_model_len`, continuation horizon, and runtime overhead.
- A benchmark point should not be treated as valid unless its manifest,
  fidelity analysis, fidelity-horizon report, slot-probe summary, and cleanup
  status are all collected.
