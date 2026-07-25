import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class WebsiteDeploymentContractTests(unittest.TestCase):
    def read(self, relative_path: str) -> str:
        return (ROOT / relative_path).read_text(encoding="utf-8")

    def test_prune_and_deploy_share_the_same_lock(self) -> None:
        deploy = self.read("website/scripts/deploy-static-baota.sh")
        prune = self.read("website/scripts/prune-static-baota.sh")

        lock_statement = 'exec 9>"$base/.deploy.lock"'
        self.assertIn(lock_statement, deploy)
        self.assertIn(lock_statement, prune)
        self.assertIn("flock -n 9", deploy)
        self.assertIn("flock -n 9", prune)
        self.assertLess(
            prune.index(lock_statement),
            prune.index('current=$(readlink -f "$base/current"'),
        )
        self.assertEqual(prune.count("rm -rf --"), 1)

    def test_baota_vhosts_own_compression_and_immutable_cache(self) -> None:
        for name in ("dronedream-public.conf", "dronedream-staging.conf"):
            with self.subTest(name=name):
                config = self.read(f"website/nginx/baota/{name}")
                self.assertRegex(config, r"(?m)^\s*gzip on;")
                self.assertRegex(config, r"(?m)^\s*gzip_vary on;")
                self.assertIn("application/javascript", config)
                self.assertIn("image/svg+xml", config)
                self.assertRegex(
                    config,
                    r'~\^/assets/\s+"public, max-age=31536000, immutable";',
                )
                self.assertIn("~^/console/assets/", config)
                self.assertIn("location /console/", config)
                self.assertIn("/console/index.html", config)
                self.assertIn("https://*.supabase.co", config)
                self.assertIn("camera=(self)", config)
                self.assertIn("microphone=(self)", config)
                self.assertRegex(
                    config,
                    r'~\^/downloads/latest\\\.json\$\s+"no-store";',
                )
                self.assertRegex(config, r'default\s+"no-cache";')

    def test_readme_routes_baota_deployments_through_the_wrapper(self) -> None:
        readme = self.read("website/README.md")
        legacy_script = self.read("website/scripts/deploy-static.sh")

        self.assertIn("deploy-static-baota.ps1", readme)
        self.assertIn('-SshKeyPath "$HOME\\.ssh\\DroneDream-deploy.pem"', readme)
        self.assertIn("StrictHostKeyChecking=yes", readme)
        self.assertRegex(readme, r"(?i)legacy generic-nginx workflow")
        self.assertRegex(readme, r"(?i)not the supported path")
        self.assertIn("bare-IP", readme)
        self.assertIn("HTTPS", readme)
        self.assertIn("LEGACY", legacy_script)
        self.assertIn("deploy-static-baota.ps1", legacy_script)

    def test_wrapper_accepts_only_a_key_path_and_keeps_release_gates(self) -> None:
        wrapper = self.read("website/scripts/deploy-static-baota.ps1")

        self.assertRegex(
            wrapper,
            r"\[Parameter\(Mandatory = \$true\)\]\s+"
            r"\[ValidateNotNullOrEmpty\(\)\]\s+\[string\]\$SshKeyPath",
        )
        self.assertNotIn("BEGIN OPENSSH PRIVATE KEY", wrapper)
        self.assertIn("StrictHostKeyChecking=yes", wrapper)
        self.assertIn("BatchMode=yes", wrapper)
        self.assertIn("Test-SiteIntegrityManifest", wrapper)
        self.assertIn("sha256sum --check -", wrapper)
        self.assertIn("deploy-static-baota.sh", wrapper)
        self.assertIn("dronedream-staging.conf", wrapper)
        self.assertIn("dronedream-public.conf", wrapper)
        self.assertIn("max-age=31536000", wrapper)
        self.assertNotRegex(wrapper, re.compile(r"(?i)private[-_ ]?key\s*=\s*['\"]"))

        remote_deploy = self.read("website/scripts/deploy-static-baota.sh")
        self.assertIn("http://127.0.0.1:18080/console/", remote_deploy)
        self.assertIn("http://127.0.0.1/console/", remote_deploy)
        self.assertIn("camera=\\(self\\)", remote_deploy)

    def test_pages_custom_domain_is_opt_in_until_dns_is_ready(self) -> None:
        builder = self.read("website/scripts/build-pages-site.ps1")
        workflow = self.read(".github/workflows/pages.yml")

        self.assertIn("DRONEDREAM_CUSTOM_DOMAIN", builder)
        self.assertIn("Remove-Item -LiteralPath $cnamePath", builder)
        self.assertNotIn('"getdronedream.com$([Environment]::NewLine)"', builder)
        self.assertIn(
            "DRONEDREAM_CUSTOM_DOMAIN: ${{ vars.DRONEDREAM_CUSTOM_DOMAIN }}",
            workflow,
        )


if __name__ == "__main__":
    unittest.main()
