#!/usr/bin/env python3
"""Inspect, patch, or restore one exact Windows fingerprint-chromium build.

Standard library only. No browser binaries, account data, or network access.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO


class PatchError(Exception):
    """A precondition or integrity check failed."""


@dataclass(frozen=True)
class PatchSpec:
    version: str
    size: int
    offset: int
    before: bytes
    after: bytes
    original_sha256: str
    patched_sha256: str


SUPPORTED = PatchSpec(
    version="150.0.7871.186 Windows x64",
    size=315028992,
    offset=0xC392046,
    before=bytes.fromhex("49 01 c0"),
    after=bytes.fromhex("49 89 d0"),
    original_sha256="6464a50a8f8eae824f85733b52bc42912405390ac7dcb2a7fda7228ea51cbbac",
    patched_sha256="2a2ca874e7944c9496888b07d56c8dd1ed76bf0a2b87c005874fe0a2729bbeed",
)
REFERENCE = "https://github.com/adryfish/fingerprint-chromium/issues/94"


def stream_digest(stream: BinaryIO) -> str:
    stream.seek(0)
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def file_digest(path: Path) -> str:
    with path.open("rb") as stream:
        return stream_digest(stream)


def describe_stream(stream: BinaryIO, spec: PatchSpec) -> dict:
    size = stream.seek(0, os.SEEK_END)
    digest = stream_digest(stream)
    stream.seek(spec.offset)
    instruction = stream.read(len(spec.before))
    state = "unsupported"
    if size == spec.size:
        if digest == spec.original_sha256 and instruction == spec.before:
            state = "original"
        elif digest == spec.patched_sha256 and instruction == spec.after:
            state = "patched"
    return {"state": state, "size": size, "sha256": digest,
            "instruction_offset": hex(spec.offset), "instruction": instruction.hex(" ")}


def inspect_dll(dll: Path, spec: PatchSpec = SUPPORTED) -> dict:
    dll = dll.expanduser().resolve(strict=True)
    with dll.open("rb") as stream:
        return {"dll": str(dll), "supported_build": spec.version,
                **describe_stream(stream, spec)}


def require_state(info: dict, expected: str) -> None:
    if info["state"] != expected:
        raise PatchError(
            f"Expected {expected} DLL; found {info['state']} "
            f"(SHA-256 {info['sha256']}). No unsupported build is patched."
        )


def create_backup(dll: Path, backup_dir: Path, spec: PatchSpec) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / f"chrome.dll.{spec.original_sha256[:12]}.original"
    if backup.exists():
        if file_digest(backup) != spec.original_sha256:
            raise PatchError("Existing backup has the wrong hash; refusing to overwrite it.")
        return backup
    with dll.open("rb") as source, backup.open("xb") as target:
        shutil.copyfileobj(source, target, length=1024 * 1024)
        target.flush()
        os.fsync(target.fileno())
    if file_digest(backup) != spec.original_sha256:
        raise PatchError("Backup verification failed; target DLL has not been changed.")
    return backup


def rewrite_instruction(dll: Path, spec: PatchSpec, source: str, target: str) -> None:
    before = spec.before if source == "original" else spec.after
    after = spec.after if target == "patched" else spec.before
    # A mapped Windows executable image normally denies writable access. Stop
    # every instance using this core first; this tool never kills user processes.
    try:
        stream = dll.open("r+b")
    except OSError as exc:
        raise PatchError("Cannot open DLL for writing. Stop instances using this core "
                         "and check file permissions; no DLL bytes were changed.") from exc
    with stream:
        require_state(describe_stream(stream, spec), source)
        try:
            stream.seek(spec.offset)
            written = stream.write(after)
            if written != len(after):
                raise PatchError("Short write while changing the instruction.")
            stream.flush()
            os.fsync(stream.fileno())
            require_state(describe_stream(stream, spec), target)
        except BaseException:
            stream.seek(spec.offset)
            stream.write(before)
            stream.flush()
            os.fsync(stream.fileno())
            if describe_stream(stream, spec)["state"] != source:
                raise PatchError("Write failed and rollback could not be verified. "
                                 "Keep the browser stopped and restore the verified backup.")
            raise


def save_manifest(result: dict, backup_dir: Path, spec: PatchSpec) -> None:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = backup_dir / f"canvas-fix-{stamp}.json"
    record = {**result, "build": spec.version, "reference": REFERENCE,
              "original_sha256": spec.original_sha256,
              "patched_sha256": spec.patched_sha256,
              "instruction_offset": hex(spec.offset),
              "before": spec.before.hex(" "), "after": spec.after.hex(" ")}
    try:
        with path.open("x", encoding="utf-8") as stream:
            json.dump(record, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        result["manifest"] = str(path)
    except OSError as exc:
        result["manifest_warning"] = f"DLL operation succeeded, but manifest could not be saved: {exc}"


def apply(dll: Path, backup_dir: Path, spec: PatchSpec = SUPPORTED) -> dict:
    dll = dll.expanduser().resolve(strict=True)
    backup_dir = backup_dir.expanduser().resolve()
    info = inspect_dll(dll, spec)
    if info["state"] == "patched":
        return {"status": "already_fixed", **info}
    require_state(info, "original")
    backup = create_backup(dll, backup_dir, spec)
    rewrite_instruction(dll, spec, "original", "patched")
    result = {"status": "fixed", **inspect_dll(dll, spec), "backup": str(backup)}
    save_manifest(result, backup_dir, spec)
    return result


def restore(dll: Path, backup: Path, spec: PatchSpec = SUPPORTED) -> dict:
    dll = dll.expanduser().resolve(strict=True)
    backup = backup.expanduser().resolve(strict=True)
    if file_digest(backup) != spec.original_sha256:
        raise PatchError("Backup hash does not match the supported original DLL.")
    info = inspect_dll(dll, spec)
    if info["state"] == "original":
        return {"status": "already_restored", **info}
    require_state(info, "patched")
    rewrite_instruction(dll, spec, "patched", "original")
    result = {"status": "restored", **inspect_dll(dll, spec), "backup": str(backup)}
    save_manifest(result, backup.parent, spec)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("inspect", "apply", "restore"):
        item = commands.add_parser(command)
        item.add_argument("--dll", required=True, type=Path, help="Path to chrome.dll")
        if command == "apply":
            item.add_argument("--backup-dir", required=True, type=Path)
        if command == "restore":
            item.add_argument("--backup", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "inspect":
            result = inspect_dll(args.dll)
        elif args.command == "apply":
            result = apply(args.dll, args.backup_dir)
        else:
            result = restore(args.dll, args.backup)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2 if result.get("state") == "unsupported" else 0
    except (PatchError, OSError) as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
