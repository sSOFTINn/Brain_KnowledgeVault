from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import os
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vaultctl.config import load_config
from vaultctl.doctor import has_failures, run_doctor
from vaultctl.scaffold import initialize
from vaultctl.validator import has_errors, validate_vault

from test_router import CONFIG


def tree_hash(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            result[str(path.relative_to(root))] = sha256(path.read_bytes()).hexdigest()
    return result


class Phase1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config_path = self.root / "source.toml"
        self.config_path.write_text(CONFIG, encoding="utf-8")
        self.config = load_config(self.config_path)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_init_creates_complete_valid_skeleton(self) -> None:
        result = initialize(self.config)
        self.assertTrue(result.created)
        self.assertTrue((self.root / "Vault/00_System/Home.md").is_file())
        self.assertTrue((self.root / "Vault/90_Templates/Project.md").is_file())
        self.assertFalse(has_errors(validate_vault(self.config)))

    def test_second_init_changes_nothing(self) -> None:
        initialize(self.config)
        before = tree_hash(self.root)
        result = initialize(self.config)
        after = tree_hash(self.root)
        self.assertEqual(before, after)
        self.assertFalse(result.created)
        self.assertFalse(result.updated)

    def test_generated_root_config_is_loadable(self) -> None:
        initialize(self.config)
        generated = load_config(self.root / "vault.toml")
        self.assertTrue(os.path.samefile(generated.root, self.root))
        self.assertEqual(len(generated.projects), 2)
        self.assertEqual(len(generated.rules), 2)

    def test_dry_run_writes_nothing(self) -> None:
        initialize(self.config, dry_run=True)
        self.assertEqual({path.name for path in self.root.iterdir()}, {"source.toml"})

    def test_duplicate_uid_is_error(self) -> None:
        initialize(self.config)
        source = self.root / "Vault/00_System/Context.md"
        duplicate = self.root / "Vault/04_Knowledge/Concepts/Duplicate.md"
        duplicate.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        findings = validate_vault(self.config)
        self.assertTrue(any(item.code == "duplicate-uid" for item in findings))

    def test_invalid_status_is_error(self) -> None:
        initialize(self.config)
        path = self.root / "Vault/00_System/Context.md"
        text = path.read_text(encoding="utf-8").replace("status: active", "status: done")
        path.write_text(text, encoding="utf-8")
        findings = validate_vault(self.config)
        self.assertTrue(any(item.code == "metadata" and "invalid" in item.message for item in findings))

    def test_doctor_passes_after_init(self) -> None:
        initialize(self.config)
        self.assertFalse(has_failures(run_doctor(self.config)))


if __name__ == "__main__":
    unittest.main()
