---
name: Runtime adapter proposal
description: Propose or discuss a new source/target runtime adapter
title: "adapter: "
labels: [adapter, enhancement]
body:
  - type: input
    id: runtime
    attributes:
      label: Runtime
      placeholder: e.g. vLLM, MLX, llama.cpp, TensorRT-LLM
    validations:
      required: true
  - type: input
    id: direction
    attributes:
      label: Adapter direction
      placeholder: source extraction, target import, or both
    validations:
      required: true
  - type: textarea
    id: api
    attributes:
      label: Relevant runtime APIs
      description: What APIs expose KV cache, tokenization, block tables, prefix cache, or decode state?
    validations:
      required: false
  - type: textarea
    id: layout
    attributes:
      label: Tensor layout assumptions
      description: Include layer/head/block/sequence dimensions if known.
    validations:
      required: false
  - type: textarea
    id: fidelity
    attributes:
      label: Validation plan
      description: How should we prove migrated decode fidelity for this runtime?
    validations:
      required: false
