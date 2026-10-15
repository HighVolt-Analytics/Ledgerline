import os
import hashlib
import shutil
import subprocess
import tempfile
import threading
import tarfile
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
HEALTH_SCRIPT = ROOT / "scripts" / "verify-deployed-health.sh"
EXPECTED_COMMIT = "2d63c76fbe09b6cdd2d7ac3b0775bc442d7f14a2"
STALE_COMMIT = "31f80592b385eabfc559e12b23e52d3b9da9b811"
ROOT_SHELL = b"<!doctype html><html><body><div id=\"root\"></div>"


class FixtureServer(ThreadingHTTPServer):
    daemon_threads = True
    mode = "healthy"
    marker_calls = 0


class FixtureHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def send_body(self, body, content_type):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlsplit(self.path).path
        if self.server.mode == "redirect_home" and path == "/":
            self.send_response(302)
            self.send_header("Location", "/unexpected/")
            self.end_headers()
            return
        if path == "/deploy-info.txt":
            self.server.marker_calls += 1
            if self.server.mode == "stale_once" and self.server.marker_calls == 1:
                body = f"Website: Quantum Ledgerline\nCommit: {STALE_COMMIT}\n".encode()
            elif self.server.mode == "stale_forever":
                body = f"Sensitive-Body-Sentinel\nCommit: {STALE_COMMIT}\n".encode()
            else:
                body = f"Website: Quantum Ledgerline\nCommit: {EXPECTED_COMMIT}\n".encode()
            self.send_body(body, "text/plain")
        elif path == "/robots.txt":
            self.send_body(b"User-agent: *\nAllow: /\n", "text/plain")
        elif path == "/sitemap.xml":
            self.send_body(b"<urlset></urlset>", "application/xml")
        elif path == "/assets/app.js":
            self.send_body(b"const app = true;", "application/x-javascript")
        elif path == "/assets/app.css":
            self.send_body(b"body{color:#000}", "text/css")
        elif path == "/assets/missing.js":
            # Model the Hostinger .htaccess SPA fallback for a missing file.
            self.send_body(ROOT_SHELL, "text/html")
        else:
            self.send_body(ROOT_SHELL, "text/html")


class DeployedHealthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bash = os.environ.get("BASH_BIN") or shutil.which("bash")
        if not cls.bash:
            raise unittest.SkipTest("bash is required for deployment-health tests")
        cls.server = FixtureServer(("127.0.0.1", 0), FixtureHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "server"):
            cls.server.shutdown()
            cls.server.server_close()
            cls.thread.join(timeout=2)

    def setUp(self):
        self.server.mode = "healthy"
        self.server.marker_calls = 0
        self.temp_dir = tempfile.TemporaryDirectory()
        self.index = Path(self.temp_dir.name) / "index.html"
        self.index.write_text(
            '<div id="root"></div><script src="/assets/app.js"></script>'
            '<link href="/assets/app.css">',
            encoding="utf-8",
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def run_health(self):
        env = os.environ.copy()
        env.update(
            HEALTH_TEST_ALLOW_HTTP="true",
            HEALTH_MARKER_RETRIES="2",
            HEALTH_MARKER_INTERVAL="0",
            GITHUB_RUN_ID="fixture-run",
        )
        return subprocess.run(
            [self.bash, str(HEALTH_SCRIPT), self.base_url, EXPECTED_COMMIT, str(self.index), "fixture-run"],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
            timeout=15,
        )

    def test_healthy_release_routes_marker_and_assets_pass(self):
        result = self.run_health()
        self.assertEqual(result.returncode, 0, result.stderr)
        for stage in ("public_home", "public_marker", "spa_interactive_tour", "spa_resources", "robots", "sitemap", "static_assets"):
            self.assertIn(f"HEALTH_OK stage={stage}", result.stdout)

    def test_stale_marker_is_retried_then_passes(self):
        self.server.mode = "stale_once"
        result = self.run_health()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertGreaterEqual(self.server.marker_calls, 2)

    def test_persistent_marker_mismatch_reports_safe_stage(self):
        self.server.mode = "stale_forever"
        result = self.run_health()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("HEALTH_FAILURE stage=public_marker category=marker_mismatch", result.stderr)
        self.assertNotIn("Sensitive-Body-Sentinel", result.stdout + result.stderr)
        self.assertNotIn(self.base_url, result.stdout + result.stderr)

    def test_spa_fallback_cannot_masquerade_as_javascript_asset(self):
        self.index.write_text('<div id="root"></div><script src="/assets/missing.js"></script>', encoding="utf-8")
        result = self.run_health()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("HEALTH_FAILURE stage=static_assets category=content_type_mismatch", result.stderr)

    def test_unexpected_redirect_path_is_reported(self):
        self.server.mode = "redirect_home"
        result = self.run_health()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("HEALTH_FAILURE stage=public_home category=redirect_path_mismatch", result.stderr)
        self.assertNotIn(self.base_url, result.stdout + result.stderr)

    def test_snapshot_manifest_restores_only_site_and_preserves_sibling(self):
        with tempfile.TemporaryDirectory() as temp_root:
            home = Path(temp_root) / "home"
            target = home / "domains" / "quantumledgerline.com" / "public_html"
            sibling = home / "domains" / "unrelated.example" / "public_html"
            target_assets = target / "assets"
            target_assets.mkdir(parents=True)
            sibling.mkdir(parents=True)
            (target / "index.html").write_text("old index", encoding="utf-8")
            (target / "deploy-info.txt").write_text(f"Commit: {STALE_COMMIT}\n", encoding="utf-8")
            (target / ".htaccess").write_text("old routing rules", encoding="utf-8")
            (target_assets / "old.js").write_text("old asset", encoding="utf-8")
            (sibling / "keep.txt").write_text("unrelated site", encoding="utf-8")

            def manifest(root):
                rows = []
                for path in sorted(p for p in root.rglob("*") if p.is_file()):
                    digest = hashlib.sha256(path.read_bytes()).hexdigest()
                    relative = "./" + path.relative_to(root).as_posix()
                    rows.append(f"{digest}  {relative}\n".encode())
                return hashlib.sha256(b"".join(rows)).hexdigest()

            expected_manifest = manifest(target)
            snapshot = Path(temp_root) / "snapshot.tar.gz"
            with tarfile.open(snapshot, "w:gz") as archive:
                archive.add(target, arcname=".")

            # Simulate the successful overlay followed by the workflow's exact
            # target-only clear and snapshot extraction after a failed health check.
            (target / "index.html").write_text("new index", encoding="utf-8")
            (target / "deploy-info.txt").write_text(f"Commit: {EXPECTED_COMMIT}\n", encoding="utf-8")
            (target_assets / "new.js").write_text("new asset", encoding="utf-8")
            self.assertNotEqual(manifest(target), expected_manifest)

            verification_root = Path(temp_root) / "verification"
            verification_root.mkdir()
            with tarfile.open(snapshot, "r:gz") as archive:
                archive.extractall(verification_root)
            self.assertEqual(manifest(verification_root), expected_manifest)

            for child in target.iterdir():
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
            with tarfile.open(snapshot, "r:gz") as archive:
                archive.extractall(target)

            self.assertEqual(manifest(target), expected_manifest)
            self.assertEqual((target / "deploy-info.txt").read_text().strip(), f"Commit: {STALE_COMMIT}")
            self.assertFalse((target_assets / "new.js").exists())
            self.assertEqual((sibling / "keep.txt").read_text(), "unrelated site")


if __name__ == "__main__":
    unittest.main()
