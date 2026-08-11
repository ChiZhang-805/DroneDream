import json
import re
import unittest
from pathlib import Path
from urllib.parse import urlsplit

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

    def test_mainland_targets_separate_production_https_from_ip_preview(self) -> None:
        targets = json.loads(self.read("website/deployment-targets.json"))
        production = targets["production"]
        preview = targets["preview"]

        self.assertEqual(production["remote"], preview["remote"])
        self.assertEqual(production["publicHost"], "cn.getdronedream.com")
        self.assertEqual(production["vhostMode"], "preserve")
        self.assertEqual(preview["publicHost"], "47.93.180.216")
        self.assertEqual(preview["vhostMode"], "install")

        for name, target, expected_scheme in (
            ("production", production, "https"),
            ("preview", preview, "http"),
        ):
            with self.subTest(name=name):
                uri = urlsplit(target["publicBaseUri"])
                self.assertEqual(uri.scheme, expected_scheme)
                self.assertEqual(uri.hostname, target["publicHost"])
                self.assertEqual(uri.path, "/")
                self.assertFalse(uri.query)
                self.assertFalse(uri.fragment)

    def test_managed_vhosts_name_canonical_and_preview_hosts(self) -> None:
        required_names = {
            "cn.getdronedream.com",
            "47.93.180.216",
        }
        for name in ("dronedream-public.conf", "dronedream-staging.conf"):
            with self.subTest(name=name):
                config = self.read(f"website/nginx/baota/{name}")
                configured_names: set[str] = set()
                for directive in re.findall(
                    r"(?m)^\s*server_name\s+([^;]+);",
                    config,
                ):
                    configured_names.update(directive.split())
                self.assertTrue(required_names.issubset(configured_names))

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
        self.assertIn("deployment-targets.json", wrapper)
        self.assertIn('[string]$TargetMode = "Production"', wrapper)
        self.assertIn("Production deployments require HTTPS.", wrapper)
        self.assertIn("Preview deployments use the explicit bare-IP HTTP target.", wrapper)
        self.assertIn("Remote=$expectedRemote", wrapper)
        self.assertIn("max-age=31536000", wrapper)
        self.assertNotRegex(wrapper, re.compile(r"(?i)private[-_ ]?key\s*=\s*['\"]"))

        remote_deploy = self.read("website/scripts/deploy-static-baota.sh")
        self.assertIn("http://127.0.0.1:18080/console/", remote_deploy)
        self.assertIn('--resolve "$public_host:443:127.0.0.1"', remote_deploy)
        self.assertIn("validate_preserved_public_vhost", remote_deploy)
        self.assertIn("preserved vhost does not declare server_name", remote_deploy)
        self.assertIn("does not listen on 443 with TLS", remote_deploy)
        self.assertIn("^strict-transport-security:", remote_deploy)
        self.assertIn("camera=\\(self\\)", remote_deploy)

    def test_remote_rollback_never_removes_a_preserved_tls_vhost(self) -> None:
        remote_deploy = self.read("website/scripts/deploy-static-baota.sh")

        self.assertIn("public_config_changed=0", remote_deploy)
        self.assertIn("if [[ $public_config_changed -eq 1 ]]; then", remote_deploy)
        self.assertIn("if [[ $vhost_mode == install ]]; then", remote_deploy)
        self.assertEqual(remote_deploy.count("public_config_changed=1"), 1)
        assignment = remote_deploy.index("public_config_changed=1")
        install_gate = remote_deploy.rfind(
            "if [[ $vhost_mode == install ]]; then",
            0,
            assignment,
        )
        self.assertNotEqual(install_gate, -1)
        rollback = remote_deploy[
            remote_deploy.index("rollback() {") : remote_deploy.index("curl_until_contains() {")
        ]
        changed_gate = rollback.index("if [[ $public_config_changed -eq 1 ]]; then")
        remove_vhost = rollback.index('rm -f "$public_vhost"')
        self.assertLess(changed_gate, remove_vhost)

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

    def test_public_console_build_is_pinned_to_universal_demo_mode(self) -> None:
        config = self.read("frontend/vite.console.config.ts")

        self.assertIn(
            '"import.meta.env.VITE_PUBLIC_DEMO_CONSOLE": JSON.stringify("true")',
            config,
        )
        self.assertIn(
            '__DRONEDREAM_BUILD_EDITION__: JSON.stringify("universal")',
            config,
        )

    def test_site_build_includes_the_role_gated_organization_route(self) -> None:
        config = self.read("frontend/vite.site.config.ts")
        route = self.read("frontend/organization/index.html")
        pages_builder = self.read("website/scripts/build-pages-site.ps1")
        release_builder = self.read("website/scripts/build-release-site.ps1")

        self.assertIn(
            'organization: `${projectRoot}organization/index.html`',
            config,
        )
        self.assertIn('name="robots" content="noindex,nofollow"', route)
        self.assertIn("organization\\index.html", pages_builder)
        self.assertIn("organization\\index.html", release_builder)

    def test_pages_build_verifies_policy_source_and_compiled_policy_links(self) -> None:
        builder = self.read("website/scripts/build-pages-site.ps1")
        policy = self.read("CODE_SIGNING_POLICY.md")

        self.assertIn('"SignPath.io"', builder)
        self.assertIn('"SignPath Foundation"', builder)
        self.assertIn(
            "The code signing policy is missing required attribution",
            builder,
        )
        self.assertIn('"CODE_SIGNING_POLICY.md"', builder)
        self.assertIn('"PRIVACY.md"', builder)
        self.assertNotRegex(
            builder,
            re.compile(
                r"\$publishedAt,\s*"
                r'"SignPath\.io",\s*'
                r'"SignPath Foundation"',
            ),
        )
        self.assertIn("Free code signing provided by [SignPath.io]", policy)
        self.assertIn("certificate by [SignPath Foundation]", policy)


if __name__ == "__main__":
    unittest.main()
