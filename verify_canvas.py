#!/usr/bin/env python3
"""Run an offline Canvas regression page in fresh browser profiles."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import signal
import subprocess
import tempfile
from html.parser import HTMLParser
from pathlib import Path


class ResultParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.active = False
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == "pre" and dict(attrs).get("id") == "result":
            self.active = True

    def handle_endtag(self, tag):
        if tag == "pre":
            self.active = False

    def handle_data(self, data):
        if self.active:
            self.parts.append(data)


def parse_result(dom: str) -> dict:
    parser = ResultParser()
    parser.feed(dom)
    result = json.loads("".join(parser.parts))
    if not isinstance(result, dict):
        raise ValueError("Canvas result must be an object")
    return result


def stop_probe_tree(proc: subprocess.Popen) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill.exe", "/PID", str(proc.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=subprocess.CREATE_NO_WINDOW, check=False)
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def run_probe(chrome: Path, folder: Path, url: str, seed: int, timeout: int) -> dict:
    folder.mkdir()
    args = [str(chrome), "--headless=new", "--no-first-run", "--disable-sync",
            "--no-default-browser-check", "--disable-background-networking",
            f"--user-data-dir={folder / 'profile'}", f"--fingerprint={seed}",
            "--fingerprint-brand=Chrome", "--fingerprint-platform=windows",
            "--timeout=15000", "--dump-dom", url]
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **options)
    timed_out = False
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        stop_probe_tree(proc)
        stdout, stderr = proc.communicate(timeout=10)
    (folder / "page.html").write_bytes(stdout)
    (folder / "stderr.log").write_bytes(stderr)
    result = {"seed": seed, "exit_code": proc.returncode, "timed_out": timed_out}
    try:
        result["canvas"] = parse_result(stdout.decode("utf-8", errors="replace"))
    except (ValueError, TypeError) as exc:
        result["parse_error"] = str(exc)
    return result


def summarize(results: list[dict]) -> dict:
    passed = all(r.get("exit_code") == 0 and not r.get("timed_out")
                 and r.get("canvas", {}).get("ok") is True
                 and r.get("canvas", {}).get("consistent") is True
                 and r.get("canvas", {}).get("reads") == 250
                 and type(r.get("canvas", {}).get("pixelHash")) is int for r in results)
    hashes = [r.get("canvas", {}).get("pixelHash") for r in results]
    differ = (len(results) == 2 and passed and hashes[0] != hashes[1])
    return {"passed": bool(differ), "different_seeds_differ": bool(differ), "results": results}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chrome", required=True, type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts"))
    parser.add_argument("--timeout", type=int, default=45)
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    chrome = args.chrome.expanduser().resolve(strict=True)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="canvas-verify-", dir=args.output_dir.resolve()))
    fixture = (Path(__file__).resolve().parent / "fixtures" / "canvas_probe.html").as_uri()
    results = [run_probe(chrome, root / f"seed-{seed}", fixture, seed, args.timeout)
               for seed in (10001, 10002)]
    report = {"timestamp_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
              "artifact_dir": str(root), **summarize(results)}
    (root / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
