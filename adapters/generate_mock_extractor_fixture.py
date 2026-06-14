#!/usr/bin/env python3
import argparse
import json
from pathlib import Path


def build_tensors(seq_len: int, n_layers: int, n_kv_heads: int, head_dim: int):
    tensors = []
    tensor_len = n_kv_heads * seq_len * head_dim
    for layer_idx in range(n_layers):
        key_data = []
        value_data = []
        key_data.reserve if False else None
        for token_idx in range(seq_len):
            for kv_head_idx in range(n_kv_heads):
                for dim_idx in range(head_dim):
                    base = float((layer_idx * 1_000_000) + (token_idx * 10_000) + (kv_head_idx * 100) + dim_idx)
                    key_data.append(base / 10_000.0)
                    value_data.append((base + 1.0) / 10_000.0)
        shape = [seq_len, n_kv_heads, head_dim]
        tensors.append({"name": f"layer.{layer_idx}.key", "shape": shape, "data": key_data})
        tensors.append({"name": f"layer.{layer_idx}.value", "shape": shape, "data": value_data})
    return {"tensors": tensors, "tensor_count": len(tensors), "elements_per_tensor": tensor_len}


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a mock extractor fixture matching the built-in PermeantOS tensor layout")
    parser.add_argument("--seq-len", type=int, default=8192)
    parser.add_argument("--layers", type=int, default=4)
    parser.add_argument("--kv-heads", type=int, default=2)
    parser.add_argument("--head-dim", type=int, default=64)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    payload = build_tensors(args.seq_len, args.layers, args.kv_heads, args.head_dim)
    output = Path(args.output)
    output.write_text(json.dumps(payload))
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
