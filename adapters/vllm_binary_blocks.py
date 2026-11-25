"""PKV1 framing for the private, loopback vLLM recovery handoff."""

import json
import re
import struct
import sys
from array import array
from math import prod

from runtime_adapter_utils import AdapterError

MAX_BINARY_HEADER = 64 * 1024
MAX_BINARY_BLOCK = 64 * 1024 * 1024
CONTENT_TYPE = "application/vnd.permeant.kv-block"


def decode_binary_block(frame: bytes) -> dict:
    if not 8 <= len(frame) <= MAX_BINARY_BLOCK or frame[:4] != b"PKV1":
        raise AdapterError("invalid binary injector frame")
    header_size = struct.unpack_from("<I", frame, 4)[0]
    offset = 8 + header_size
    if not 0 < header_size <= MAX_BINARY_HEADER or offset > len(frame):
        raise AdapterError("invalid binary injector header length")
    header = json.loads(frame[8:offset])
    if not isinstance(header, dict):
        raise AdapterError("invalid binary injector header")
    block_hash = header.get("block_hash")
    block_size = header.get("block_size")
    descriptors = header.get("tensors")
    if (
        not isinstance(block_hash, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", block_hash) is None
        or type(block_size) is not int or block_size <= 0
        or not isinstance(descriptors, list) or not descriptors
    ):
        raise AdapterError("invalid binary injector block metadata")

    layers: dict[int, dict] = {}
    view = memoryview(frame)
    for descriptor in descriptors:
        name = descriptor.get("name") if isinstance(descriptor, dict) else None
        match = re.fullmatch(r"layer\.(0|[1-9][0-9]{0,8})\.(key|value)", name) if isinstance(name, str) else None
        if match is None:
            raise AdapterError("invalid binary injector tensor name")
        index, kind = int(match[1]), match[2]
        shape = descriptor.get("shape")
        token_axis = 3 if kind == "key" else 2
        if (
            not isinstance(shape, list) or len(shape) != 4
            or any(type(dim) is not int or not 0 < dim <= MAX_BINARY_BLOCK // 4 for dim in shape)
            or shape[0] != 1 or shape[token_axis] != block_size
        ):
            raise AdapterError("invalid binary injector tensor shape")
        end = offset + 4 * prod(shape)
        if end > len(frame):
            raise AdapterError("truncated binary injector tensor")
        layer = layers.setdefault(index, {"layer_index": index, "shape_mode": "preblocked"})
        field = f"{kind}_tensor"
        if field in layer:
            raise AdapterError("duplicate binary injector tensor")
        values = array("f")
        values.frombytes(view[offset:end])
        if sys.byteorder != "little":
            values.byteswap()
        layer[field] = {"name": name, "shape": shape, "data": values.tolist()}
        offset = end

    if offset != len(frame):
        raise AdapterError("trailing binary injector data")
    if sorted(layers) != list(range(len(layers))):
        raise AdapterError("binary injector layer indices must be contiguous")
    for layer in layers.values():
        key, value = layer.get("key_tensor"), layer.get("value_tensor")
        if key is None or value is None or value["shape"] != [
            1, key["shape"][1], block_size, key["shape"][2]
        ]:
            raise AdapterError("binary injector layer has unpaired key/value shapes")

    return {
        "hash": block_hash,
        "block_size": block_size,
        "layer_count": len(layers),
        "layers": [layers[index] for index in range(len(layers))],
    }
