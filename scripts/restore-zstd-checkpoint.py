#!/usr/bin/env python3
"""Validate a downloaded recovery artifact and publish its exact plaintext."""

import hashlib
import os
import selectors
import subprocess
import sys
import tempfile
import time
from pathlib import Path


MAX_CHECKPOINT_BYTES = 512 * 1024 * 1024
CHUNK_BYTES = 1024 * 1024
DECODE_TIMEOUT_SECONDS = 30


def restore(archive, destination, artifact_bytes, artifact_sha, plaintext_bytes, plaintext_sha):
    if not 0 < artifact_bytes < plaintext_bytes <= MAX_CHECKPOINT_BYTES:
        raise ValueError("checkpoint sizes outside the compressed restore limits")
    if destination.exists():
        raise ValueError("checkpoint destination already exists")

    with archive.open("rb") as source:
        if os.fstat(source.fileno()).st_size != artifact_bytes:
            raise ValueError("compressed checkpoint size mismatch")
        actual = hashlib.sha256()
        remaining_bytes = artifact_bytes
        while remaining_bytes:
            chunk = source.read(min(CHUNK_BYTES, remaining_bytes))
            if not chunk:
                raise ValueError("truncated compressed checkpoint")
            actual.update(chunk)
            remaining_bytes -= len(chunk)
        if source.read(1) or actual.hexdigest() != artifact_sha:
            raise ValueError("compressed checkpoint digest mismatch")
        source.seek(0)
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".checkpoint-", delete=False) as staged:
            temporary = Path(staged.name)
            try:
                plain_digest = hashlib.sha256()
                count = 0
                deadline = time.monotonic() + DECODE_TIMEOUT_SECONDS
                with subprocess.Popen(
                    ["zstd", "-q", "-d", "-c", "-M128MB"], stdin=source, stdout=subprocess.PIPE,
                ) as decoder:
                    try:
                        with selectors.DefaultSelector() as reader:
                            reader.register(decoder.stdout, selectors.EVENT_READ)
                            while True:
                                remaining = deadline - time.monotonic()
                                if remaining <= 0 or not reader.select(remaining):
                                    raise ValueError("checkpoint decode timed out")
                                data = os.read(decoder.stdout.fileno(), min(CHUNK_BYTES, plaintext_bytes - count + 1))
                                if not data:
                                    break
                                count += len(data)
                                if count > plaintext_bytes:
                                    raise ValueError("decoded checkpoint exceeds trusted size")
                                plain_digest.update(data)
                                staged.write(data)
                        if decoder.wait(timeout=max(0, deadline - time.monotonic())) != 0:
                            raise ValueError("Zstd checkpoint decode failed")
                    except BaseException:
                        decoder.kill()
                        raise
                if count != plaintext_bytes or plain_digest.hexdigest() != plaintext_sha:
                    raise ValueError("restored checkpoint size or digest mismatch")
                staged.close()
                os.replace(temporary, destination)
            finally:
                temporary.unlink(missing_ok=True)


def main():
    source, destination, artifact_size, artifact_sha, plaintext_size, plaintext_sha = sys.argv[1:]
    try:
        restore(Path(source), Path(destination), int(artifact_size), artifact_sha, int(plaintext_size), plaintext_sha)
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        raise SystemExit(f"restore-zstd-checkpoint: {error}") from None


if __name__ == "__main__":
    main()
