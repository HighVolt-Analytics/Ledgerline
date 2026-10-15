import hashlib
import os
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CREATE_SCRIPT = ROOT / "scripts" / "create-hostinger-snapshot.sh"
RESTORE_SCRIPT = ROOT / "scripts" / "restore-hostinger-snapshot.sh"
SUFFIX = "/domains/quantumledgerline.com/public_html"
RELEASE_COMMIT = "2d63c76fbe09b6cdd2d7ac3b0775bc442d7f14a2"
OLD_COMMIT = "31f80592b385eabfc559e12b23e52d3b9da9b811"


def file_manifest(root):
    rows = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        relative = "./" + path.relative_to(root).as_posix()
        rows.append(f"{digest}  {relative}\n".encode())
    return hashlib.sha256(b"".join(rows)).hexdigest()


class HostingerSnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bash = os.environ.get("BASH_BIN") or shutil.which("bash")
        if not cls.bash:
            raise unittest.SkipTest("bash is required for snapshot tests")
        probe = subprocess.run([cls.bash, "-c", "exit 0"], capture_output=True, check=False, timeout=5)
        if probe.returncode != 0:
            raise unittest.SkipTest("a working Bash runtime is required for snapshot tests")

    def make_layout(self, temp_root):
        home = Path(temp_root) / "home"
        target = home / SUFFIX.lstrip("/")
        sibling = home / "domains" / "unrelated.example" / "public_html"
        target.mkdir(parents=True)
        sibling.mkdir(parents=True)
        (target / "index.html").write_text("old release", encoding="utf-8")
        (target / "deploy-info.txt").write_text(f"Commit: {OLD_COMMIT}\n", encoding="utf-8")
        (target / ".htaccess").write_text("fallback", encoding="utf-8")
        (target / "assets").mkdir()
        (target / "assets" / "old.js").write_text("old bundle", encoding="utf-8")
        (sibling / "keep.txt").write_text("unrelated site", encoding="utf-8")
        return home, target, sibling

    def run_script(self, script, home, *args):
        env = os.environ.copy()
        env["HOME"] = str(home)
        return subprocess.run(
            [self.bash, str(script), *map(str, args)],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )

    def make_archive(self, home, target, name, alter=None):
        backup_dir = home / "deployment_backups" / "ledgerline-production"
        backup_dir.mkdir(parents=True)
        archive = backup_dir / name
        with tarfile.open(archive, "w:gz") as output:
            output.add(target, arcname=".")
        if alter:
            with tempfile.TemporaryDirectory() as temp_extract:
                with tarfile.open(archive, "r:gz") as source:
                    source.extractall(temp_extract)
                changed = Path(temp_extract) / alter[0]
                changed.write_text(alter[1], encoding="utf-8")
                with tarfile.open(archive, "w:gz") as output:
                    output.add(temp_extract, arcname=".")
        return archive

    def test_snapshot_helper_verifies_archive_matches_live_tree(self):
        with tempfile.TemporaryDirectory() as temp_root:
            home, target, _ = self.make_layout(temp_root)
            result = self.run_script(CREATE_SCRIPT, home, target, SUFFIX, RELEASE_COMMIT, "12345")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("BACKUP_OK", result.stdout)
            archive_name = next(line.split(":", 1)[1] for line in result.stdout.splitlines() if line.startswith("BACKUP_NAME:"))
            archive = home / "deployment_backups" / "ledgerline-production" / archive_name
            self.assertTrue(archive.is_file())
            self.assertIn(file_manifest(target), result.stdout)

    def test_rollback_preflight_rejects_bad_manifest_without_touching_target(self):
        with tempfile.TemporaryDirectory() as temp_root:
            home, target, sibling = self.make_layout(temp_root)
            expected = file_manifest(target)
            name = f"backup-20261015-010203-12345-{RELEASE_COMMIT}.tar.gz"
            archive = self.make_archive(home, target, name, ("index.html", "corrupted backup"))
            archive_sha256 = hashlib.sha256(archive.read_bytes()).hexdigest()
            (target / "index.html").write_text("current site must remain", encoding="utf-8")
            before = file_manifest(target)
            result = self.run_script(RESTORE_SCRIPT, home, target, SUFFIX, name, expected, OLD_COMMIT, archive_sha256)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("ROLLBACK_FAILURE stage=snapshot category=preflight_manifest_mismatch", result.stderr)
            self.assertEqual(file_manifest(target), before)
            self.assertEqual((sibling / "keep.txt").read_text(encoding="utf-8"), "unrelated site")

    def test_rollback_rejects_backup_checksum_change_before_touching_target(self):
        with tempfile.TemporaryDirectory() as temp_root:
            home, target, _ = self.make_layout(temp_root)
            expected = file_manifest(target)
            name = f"backup-20261015-010203-12345-{RELEASE_COMMIT}.tar.gz"
            archive = self.make_archive(home, target, name)
            expected_sha256 = hashlib.sha256(archive.read_bytes()).hexdigest()
            archive.write_bytes(archive.read_bytes() + b"tampered")
            (target / "index.html").write_text("leave current contents", encoding="utf-8")
            before = file_manifest(target)
            result = self.run_script(RESTORE_SCRIPT, home, target, SUFFIX, name, expected, OLD_COMMIT, expected_sha256)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("ROLLBACK_FAILURE stage=snapshot category=archive_checksum_mismatch", result.stderr)
            self.assertEqual(file_manifest(target), before)

    def test_valid_rollback_restores_exact_site_and_preserves_sibling(self):
        with tempfile.TemporaryDirectory() as temp_root:
            home, target, sibling = self.make_layout(temp_root)
            expected = file_manifest(target)
            name = f"backup-20261015-010203-12345-{RELEASE_COMMIT}.tar.gz"
            archive = self.make_archive(home, target, name)
            archive_sha256 = hashlib.sha256(archive.read_bytes()).hexdigest()
            (target / "index.html").write_text("new release", encoding="utf-8")
            (target / "deploy-info.txt").write_text(f"Commit: {RELEASE_COMMIT}\n", encoding="utf-8")
            (target / "assets" / "new.js").write_text("new bundle", encoding="utf-8")
            result = self.run_script(RESTORE_SCRIPT, home, target, SUFFIX, name, expected, OLD_COMMIT, archive_sha256)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("ROLLBACK_CONTENTS_OK", result.stdout)
            self.assertEqual(file_manifest(target), expected)
            self.assertEqual((target / "deploy-info.txt").read_text(encoding="utf-8").strip(), f"Commit: {OLD_COMMIT}")
            self.assertFalse((target / "assets" / "new.js").exists())
            self.assertEqual((sibling / "keep.txt").read_text(encoding="utf-8"), "unrelated site")

    def test_target_containment_rejects_sibling_path(self):
        with tempfile.TemporaryDirectory() as temp_root:
            home, target, sibling = self.make_layout(temp_root)
            result = self.run_script(CREATE_SCRIPT, home, sibling, SUFFIX, RELEASE_COMMIT, "12345")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("SNAPSHOT_FAILURE stage=target category=target_mismatch", result.stderr)
            self.assertTrue((target / "index.html").is_file())


if __name__ == "__main__":
    unittest.main()
