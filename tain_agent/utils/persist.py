"""Unified persistence utilities with atomic writes."""
import os
import tempfile
from enum import Enum
from pathlib import Path
from typing import Any


class WritePolicy(Enum):
    IMMEDIATE = "immediate"
    BUFFERED = "buffered"
    LAZY = "lazy"


# Per-file policy declarations
FILE_POLICIES: dict[str, WritePolicy] = {
    "personality.json": WritePolicy.IMMEDIATE,
    "decisions.jsonl": WritePolicy.BUFFERED,
    "memory.json": WritePolicy.LAZY,
    "conversation_checkpoint.json": WritePolicy.BUFFERED,
    "version.json": WritePolicy.IMMEDIATE,
    "lineage.jsonl": WritePolicy.BUFFERED,
    "_registry.json": WritePolicy.IMMEDIATE,
}


def atomic_write_json(path: Path, data: Any, indent: int = 2) -> None:
    """Write JSON atomically using tempfile + rename."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp", prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            import json
            json.dump(data, f, ensure_ascii=False, indent=indent, default=str)
        os.replace(tmp, str(path))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def atomic_write_text(path: Path, content: str) -> None:
    """Write text atomically using tempfile + rename."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp", prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, str(path))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def get_policy(file_name: str) -> WritePolicy:
    """Get the declared write policy for a file."""
    return FILE_POLICIES.get(file_name, WritePolicy.IMMEDIATE)
