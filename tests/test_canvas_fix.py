import dataclasses
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import canvas_fix
from verify_canvas import parse_result, summarize


class PatchTests(unittest.TestCase):
    def setUp(self):
        self.temp_parent = Path(tempfile.gettempdir()).resolve()
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.cleanup_temp)
        self.dll = self.root / "chrome.dll"
        self.backups = self.root / "backups"
        self.old = b"MZ" + b"\x00" * 32 + bytes.fromhex("49 01 c0") + b"fixture-tail"
        self.new = self.old[:34] + bytes.fromhex("49 89 d0") + self.old[37:]
        self.spec = canvas_fix.PatchSpec(
            "synthetic test fixture", len(self.old), 34,
            bytes.fromhex("49 01 c0"), bytes.fromhex("49 89 d0"),
            hashlib.sha256(self.old).hexdigest(), hashlib.sha256(self.new).hexdigest())
        self.dll.write_bytes(self.old)

    def cleanup_temp(self):
        if self.root.resolve().parent != self.temp_parent:
            raise RuntimeError("Refusing cleanup outside the expected temporary directory")
        self.temp.cleanup()

    def test_inspect_has_no_side_effects(self):
        self.assertEqual(canvas_fix.inspect_dll(self.dll, self.spec)["state"], "original")
        self.assertEqual(self.dll.read_bytes(), self.old)
        self.assertFalse(self.backups.exists())

    def test_apply_backup_restore_round_trip(self):
        result = canvas_fix.apply(self.dll, self.backups, self.spec)
        self.assertEqual(result["status"], "fixed")
        self.assertEqual(self.dll.read_bytes(), self.new)
        backup = Path(result["backup"])
        self.assertEqual(backup.read_bytes(), self.old)
        record = json.loads(Path(result["manifest"]).read_text())
        self.assertEqual(record["original_sha256"], self.spec.original_sha256)
        restored = canvas_fix.restore(self.dll, backup, self.spec)
        self.assertEqual(restored["status"], "restored")
        self.assertEqual(self.dll.read_bytes(), self.old)
        self.assertEqual(backup.read_bytes(), self.old)

    def test_apply_and_restore_are_idempotent(self):
        first = canvas_fix.apply(self.dll, self.backups, self.spec)
        backup = Path(first["backup"])
        self.assertEqual(canvas_fix.apply(self.dll, self.backups, self.spec)["status"], "already_fixed")
        canvas_fix.restore(self.dll, backup, self.spec)
        self.assertEqual(canvas_fix.restore(self.dll, backup, self.spec)["status"], "already_restored")

    def test_same_size_wrong_hash_is_rejected_without_backup(self):
        wrong = b"XX" + self.old[2:]
        self.dll.write_bytes(wrong)
        with self.assertRaises(canvas_fix.PatchError):
            canvas_fix.apply(self.dll, self.backups, self.spec)
        self.assertEqual(self.dll.read_bytes(), wrong)
        self.assertFalse(self.backups.exists())

    def test_wrong_instruction_is_rejected_even_with_matching_test_hash(self):
        wrong = self.old[:34] + b"XYZ" + self.old[37:]
        self.dll.write_bytes(wrong)
        spec = dataclasses.replace(self.spec, original_sha256=hashlib.sha256(wrong).hexdigest())
        with self.assertRaises(canvas_fix.PatchError):
            canvas_fix.apply(self.dll, self.backups, spec)
        self.assertEqual(self.dll.read_bytes(), wrong)

    def test_existing_invalid_backup_is_not_overwritten(self):
        self.backups.mkdir()
        backup = self.backups / f"chrome.dll.{self.spec.original_sha256[:12]}.original"
        backup.write_bytes(b"do not overwrite")
        with self.assertRaises(canvas_fix.PatchError):
            canvas_fix.apply(self.dll, self.backups, self.spec)
        self.assertEqual(self.dll.read_bytes(), self.old)
        self.assertEqual(backup.read_bytes(), b"do not overwrite")

    def test_restore_refuses_corrupt_backup(self):
        result = canvas_fix.apply(self.dll, self.backups, self.spec)
        backup = Path(result["backup"])
        backup.write_bytes(b"corrupt")
        with self.assertRaises(canvas_fix.PatchError):
            canvas_fix.restore(self.dll, backup, self.spec)
        self.assertEqual(self.dll.read_bytes(), self.new)

    def test_failed_post_write_verification_rolls_back(self):
        invalid_result_spec = dataclasses.replace(self.spec, patched_sha256="0" * 64)
        with self.assertRaises(canvas_fix.PatchError):
            canvas_fix.apply(self.dll, self.backups, invalid_result_spec)
        self.assertEqual(self.dll.read_bytes(), self.old)
        backups = list(self.backups.glob("*.original"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), self.old)

    def test_change_between_backup_and_write_is_rejected(self):
        original_create = canvas_fix.create_backup
        changed = b"XX" + self.old[2:]
        def create_then_change(*args):
            result = original_create(*args)
            self.dll.write_bytes(changed)
            return result
        with mock.patch.object(canvas_fix, "create_backup", side_effect=create_then_change):
            with self.assertRaises(canvas_fix.PatchError):
                canvas_fix.apply(self.dll, self.backups, self.spec)
        self.assertEqual(self.dll.read_bytes(), changed)

    def test_public_cli_rejects_toy_fixture(self):
        with mock.patch("sys.stdout", new_callable=io.StringIO) as output:
            code = canvas_fix.main(["inspect", "--dll", str(self.dll)])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output.getvalue())["state"], "unsupported")


class VerificationTests(unittest.TestCase):
    def test_parse_only_result_pre(self):
        data = parse_result('<pre id="other">ignore</pre><pre id="result">'
                            '{"ok":true,"text":"a&amp;b"}</pre>')
        self.assertTrue(data["ok"])
        self.assertEqual(data["text"], "a&b")

    def test_incomplete_page_does_not_pass(self):
        self.assertFalse(summarize([{"exit_code": 0, "timed_out": False}])["passed"])
        self.assertFalse(summarize([])["passed"])

    def test_same_fingerprint_for_different_seeds_does_not_pass(self):
        results = [{"exit_code": 0, "timed_out": False,
                    "canvas": {"ok": True, "consistent": True, "reads": 250, "pixelHash": 42}} for _ in range(2)]
        self.assertFalse(summarize(results)["passed"])
        results[1]["canvas"]["pixelHash"] = 43
        self.assertTrue(summarize(results)["passed"])
        results[1]["timed_out"] = True
        self.assertFalse(summarize(results)["passed"])


if __name__ == "__main__":
    unittest.main()
