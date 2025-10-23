"""Utilities for working with uploaded files."""
from __future__ import annotations

import hashlib
import os
import time
import uuid
from pathlib import Path
from typing import BinaryIO


_DEFAULT_CHUNK_SIZE = 1024 * 1024


def generate_uuid7() -> str:
    """Return a UUIDv7 string, falling back to a local implementation."""

    if hasattr(uuid, "uuid7"):
        return str(uuid.uuid7())  # type: ignore[attr-defined]

    timestamp_ms = int(time.time() * 1000)
    timestamp_bytes = timestamp_ms.to_bytes(6, "big", signed=False)
    random_bytes = os.urandom(10)
    uuid_bytes = bytearray(timestamp_bytes + random_bytes)
    uuid_bytes[6] = (uuid_bytes[6] & 0x0F) | 0x70
    uuid_bytes[8] = (uuid_bytes[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(uuid_bytes)))


def compute_stream_sha256(stream: BinaryIO, *, chunk_size: int = _DEFAULT_CHUNK_SIZE) -> str:
    """Compute a SHA-256 checksum from a stream without exhausting memory."""

    digest = hashlib.sha256()
    can_seek = hasattr(stream, "seek")

    if can_seek:
        try:
            stream.seek(0)
        except (OSError, ValueError):
            can_seek = False

    while True:
        chunk = stream.read(chunk_size)
        if not chunk:
            break
        digest.update(chunk)

    if can_seek:
        stream.seek(0)

    return digest.hexdigest()


def compute_file_sha256(path: Path, *, chunk_size: int = _DEFAULT_CHUNK_SIZE) -> str:
    """Compute the SHA-256 checksum of a file on disk."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()
