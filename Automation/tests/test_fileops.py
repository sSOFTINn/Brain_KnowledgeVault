from __future__ import annotations

from pathlib import Path
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vaultctl.fileops import (
    CopyVerificationError,
    SourceChangedError,
    choose_destination,
    file_sha256,
    verified_copy,
)


class FileOperationsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source.bin"
        self.source.write_bytes(b"verified source")
        self.digest = file_sha256(self.source)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_verified_copy_preserves_source_and_verifies_destination(self) -> None:
        destination = self.root / "out" / "copy.bin"
        result = verified_copy(
            self.source,
            destination,
            expected_size=self.source.stat().st_size,
            expected_sha256=self.digest,
            preserve_timestamps=True,
        )
        self.assertTrue(self.source.is_file())
        self.assertEqual(result.destination, destination)
        self.assertEqual(file_sha256(destination), self.digest)

    def test_hash_mismatch_is_fail_closed(self) -> None:
        destination = self.root / "copy.bin"
        with self.assertRaises(SourceChangedError):
            verified_copy(
                self.source,
                destination,
                expected_size=self.source.stat().st_size,
                expected_sha256="0" * 64,
                preserve_timestamps=True,
            )
        self.assertFalse(destination.exists())

    def test_corrupt_copy_is_removed_and_never_published(self) -> None:
        destination = self.root / "copy.bin"

        def corrupt(_source: Path, temporary: Path):
            temporary.write_bytes(b"corrupt")
            return str(temporary)

        with patch("vaultctl.fileops.shutil.copy2", side_effect=corrupt):
            with self.assertRaises(CopyVerificationError):
                verified_copy(
                    self.source,
                    destination,
                    expected_size=self.source.stat().st_size,
                    expected_sha256=self.digest,
                    preserve_timestamps=True,
                )
        self.assertFalse(destination.exists())
        self.assertEqual(list(self.root.glob("*.partial")), [])

    def test_destination_race_does_not_overwrite(self) -> None:
        destination = self.root / "copy.bin"

        def race(temporary: Path, target: Path):
            target.write_bytes(b"other writer")
            raise FileExistsError("simulated race")

        with patch("vaultctl.fileops.os.rename", side_effect=race):
            with self.assertRaises(FileExistsError):
                verified_copy(
                    self.source,
                    destination,
                    expected_size=self.source.stat().st_size,
                    expected_sha256=self.digest,
                    preserve_timestamps=True,
                )
        self.assertEqual(destination.read_bytes(), b"other writer")

    def test_preserve_timestamps_knob_changes_copy_behavior(self) -> None:
        old = time.time() - 86_400
        os.utime(self.source, (old, old))
        preserved = self.root / "preserved.bin"
        fresh = self.root / "fresh.bin"
        verified_copy(
            self.source,
            preserved,
            expected_size=self.source.stat().st_size,
            expected_sha256=self.digest,
            preserve_timestamps=True,
        )
        verified_copy(
            self.source,
            fresh,
            expected_size=self.source.stat().st_size,
            expected_sha256=self.digest,
            preserve_timestamps=False,
        )
        self.assertEqual(preserved.stat().st_mtime_ns, self.source.stat().st_mtime_ns)
        self.assertNotEqual(fresh.stat().st_mtime_ns, self.source.stat().st_mtime_ns)

    def test_shared_collision_resolution_is_deterministic(self) -> None:
        destination = self.root / "copy.bin"
        destination.write_bytes(b"different")
        selected, state = choose_destination(destination, self.digest)
        self.assertEqual(state, "collision")
        self.assertIn(self.digest[:8], selected.name)

    def test_symlink_source_is_rejected_when_supported(self) -> None:
        link = self.root / "link.bin"
        try:
            link.symlink_to(self.source)
        except OSError as exc:
            self.skipTest(f"symlink creation unavailable: {exc}")
        with self.assertRaisesRegex(SourceChangedError, "reparse"):
            verified_copy(
                link,
                self.root / "copy.bin",
                expected_size=self.source.stat().st_size,
                expected_sha256=self.digest,
                preserve_timestamps=True,
            )


if __name__ == "__main__":
    unittest.main()
