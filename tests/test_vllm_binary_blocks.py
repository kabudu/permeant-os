import json
import struct
import sys
import threading
import urllib.error
import urllib.request
from http.server import HTTPServer
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "adapters"))
from runtime_adapter_utils import AdapterError
from vllm_binary_blocks import CONTENT_TYPE, decode_binary_block
from vllm_runtime_receiver import Receiver


BLOCK_HASH = "sha256:" + "a" * 64
KEY = {"name": "layer.0.key", "shape": [1, 1, 1, 2]}
VALUE = {"name": "layer.0.value", "shape": [1, 1, 2, 1]}


def frame(tensors=(VALUE, KEY), *, block_hash=BLOCK_HASH):
    header = json.dumps({"block_hash": block_hash, "block_size": 2, "tensors": tensors}).encode()
    return b"PKV1" + struct.pack("<I", len(header)) + header + struct.pack("<4f", 2, -2, -0.0, 1.5)


def test_binary_decode_preserves_shape_and_float32_bits():
    state = decode_binary_block(frame())
    key = state["layers"][0]["key_tensor"]
    value = state["layers"][0]["value_tensor"]
    assert key["shape"] == KEY["shape"]
    assert value["data"] == [2, -2]
    assert struct.pack("<2f", *key["data"]) == bytes.fromhex("000000800000c03f")


@pytest.mark.parametrize("data", [
    frame()[:-1], frame() + b"x", frame((KEY, KEY)), frame((KEY, {**VALUE, "shape": [1, 2, 2, 1]})),
    frame(block_hash="../bad"), frame((KEY,)), b"PKV1" + struct.pack("<I", 2**32 - 1),
])
def test_binary_decode_rejects_malformed_frames(data):
    with pytest.raises(AdapterError):
        decode_binary_block(data)


@pytest.mark.parametrize("consumer_success", [False, True])
def test_binary_receiver_only_acknowledges_completed_consumer(tmp_path, consumer_success):
    def consume(payload):
        if "layers" in payload:
            assert payload["layers"][0]["value_tensor"]["data"] == [2, -2]
            return {"success": consumer_success}
        return {"success": True}

    with HTTPServer(("127.0.0.1", 0), Receiver) as server:
        server.state_dir = tmp_path
        server.token = "test-token"
        server.consumer_hook = consume
        server.binary_recovery = True
        worker = threading.Thread(target=server.serve_forever)
        worker.start()
        try:
            def post(path, data, content_type="application/json"):
                request = urllib.request.Request(
                    f"http://127.0.0.1:{server.server_port}{path}",
                    data=data,
                    headers={"Content-Type": content_type, "Authorization": "Bearer test-token"},
                )
                with urllib.request.urlopen(request, timeout=5) as response:
                    return json.load(response)

            with pytest.raises(urllib.error.HTTPError) as error:
                post("/inject_binary_block", frame()[:-1], CONTENT_TYPE)
            assert error.value.code == 400
            assert list(tmp_path.iterdir()) == []
            assert post("/inject_binary_block", frame(), CONTENT_TYPE)["success"] is consumer_success
            assert (tmp_path / f"{BLOCK_HASH}.pkv").read_bytes() == frame()
            with pytest.raises(urllib.error.HTTPError) as error:
                post("/inject_binary_block", frame(), CONTENT_TYPE)
            assert error.value.code == 400
            result = post("/verify_continuation", json.dumps({"block_hashes": [BLOCK_HASH]}).encode())
            assert result["success"] is consumer_success
        finally:
            server.shutdown()
            worker.join(timeout=5)
