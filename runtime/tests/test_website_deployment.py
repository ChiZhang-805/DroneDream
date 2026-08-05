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

    def test_targets_define_global_pages_and_bare_ip_mirror(self) -> None:
        targets = json.loads(self.read("website/deployment-targets.json"))
        global_target = targets["global"]
        mirror = targets["mirror"]

        self.assertEqual(set(targets), {"global", "mirror"})
        self.assertEqual(global_target["platform"], "github-pages")
        self.assertEqual(global_target["publicHost"], "getdronedream.com")
        self.assertEqual(mirror["platform"], "baota")
        self.assertEqual(mirror["publicHost"], "47.93.180.216")
        self.assertEqual(mirror["vhostMode"], "install")
        self.assertEqual(
            global_target["artifactDirectory"],
            mirror["artifactDirectory"],
        )

        for name, target, expected_scheme in (
            ("global", global_target, "https"),
            ("mirror", mirror, "http"),
        ):
            with self.subTest(name=name):
                uri = urlsplit(target["publicBaseUri"])
                self.assertEqual(uri.scheme, expected_scheme)
                self.assertEqual(uri.hostname, target["publicHost"])
                self.assertEqual(uri.path, "/")
                self.assertFalse(uri.query)
                self.assertFalse(uri.fragment)

    def test_managed_vhosts_name_only_the_bare_ip_mirror(self) -> None:
        for name in ("dronedream-public.conf", "dronedream-staging.conf"):
            with self.subTest(name=name):
                config = self.read(f"website/nginx/baota/{name}")
                configured_names: set[str] = set()
                for directive in re.findall(
                    r"(?m)^\s*server_name\s+([^;]+);",
                    config,
                ):
                    configured_names.update(directive.split())
                self.assertIn("47.93.180.216", configured_names)
                self.assertNotIn("cn.getdronedream.com", configured_names)

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
        self.assertIn("same commit-pinned artifact", readme)
        self.assertNotIn("cn.getdronedream.com", readme)
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
        self.assertIn("Site artifact contains an unlisted file", wrapper)
        self.assertIn("-Recurse -Force -File", wrapper)
        self.assertIn("deploy-static-baota.sh", wrapper)
        self.assertIn("dronedream-staging.conf", wrapper)
        self.assertIn("dronedream-public.conf", wrapper)
        self.assertIn("deployment-targets.json", wrapper)
        self.assertIn('[string]$ArtifactDirectory = ""', wrapper)
        self.assertIn("[string]$ExpectedCommit", wrapper)
        self.assertNotIn("$TargetMode", wrapper)
        self.assertNotIn("Production deployments", wrapper)
        self.assertNotIn("Preview deployments", wrapper)
        self.assertIn("dronedream-shared-static-site", wrapper)
        self.assertIn("public-SHA256SUMS", wrapper)
        self.assertIn("Verified the versioned GitHub release asset", wrapper)
        self.assertIn('"${expectedDownloadUrl}?sha256=$installerSha256"', wrapper)
        self.assertIn('"${expectedChecksumUrl}?sha256=$installerSha256"', wrapper)
        self.assertIn("verify-site-parity.ps1", self.read("website/README.md"))
        self.assertIn("max-age=31536000", wrapper)
        self.assertNotRegex(wrapper, re.compile(r"(?i)private[-_ ]?key\s*=\s*['\"]"))

        remote_deploy = self.read("website/scripts/deploy-static-baota.sh")
        self.assertIn("http://127.0.0.1:18080/console/", remote_deploy)
        self.assertIn("the approved bare-IP mirror", remote_deploy)
        self.assertNotIn("validate_preserved_public_vhost", remote_deploy)
        self.assertNotIn("public_scheme", remote_deploy)
        self.assertNotIn("vhost_mode", remote_deploy)
        self.assertIn("build-manifest.json", remote_deploy)
        self.assertIn("camera=\\(self\\)", remote_deploy)

    def test_remote_rollback_restores_the_previous_mirror_vhost(self) -> None:
        remote_deploy = self.read("website/scripts/deploy-static-baota.sh")

        self.assertIn("public_config_changed=0", remote_deploy)
        self.assertIn("if [[ $public_config_changed -eq 1 ]]; then", remote_deploy)
        self.assertEqual(remote_deploy.count("public_config_changed=1"), 1)
        rollback = remote_deploy[
            remote_deploy.index("rollback() {") : remote_deploy.index("curl_until_contains() {")
        ]
        changed_gate = rollback.index("if [[ $public_config_changed -eq 1 ]]; then")
        remove_vhost = rollback.index('rm -f "$public_vhost"')
        self.assertLess(changed_gate, remove_vhost)

    def test_local_quality_gates_cover_every_public_entry(self) -> None:
        matrix = self.read("website/scripts/audit-browser-matrix.mjs")
        performance = self.read("website/scripts/audit-site-performance.mjs")
        readme = self.read("website/README.md")

        for route in ("home", "product", "pricing", "manual", "community", "account", "console"):
            with self.subTest(route=route):
                self.assertIn(f'name: "{route}"', matrix)
                self.assertIn(f'name: "{route}"', performance)
        for browser in ("edge", "chrome", "lenovo", "firefox"):
            with self.subTest(browser=browser):
                self.assertIn(browser, matrix)
        self.assertIn("collectAccessibility", matrix)
        self.assertIn("prefers-reduced-motion: reduce", matrix)
        self.assertIn("totalGzipBytes", performance)
        self.assertIn("largestResourceRawBytes", performance)
        self.assertIn("audit-browser-matrix.mjs", readme)
        self.assertIn("audit-site-performance.mjs", readme)

    def test_pages_build_pins_the_verified_global_domain_and_shared_artifact(self) -> None:
        builder = self.read("website/scripts/build-pages-site.ps1")
        workflow = self.read(".github/workflows/pages.yml")

        self.assertNotIn("DRONEDREAM_CUSTOM_DOMAIN", builder)
        self.assertIn("$customDomain = [string]$globalTarget.publicHost", builder)
        self.assertIn("build-manifest.json", builder)
        self.assertIn("SHA256SUMS", builder)
        self.assertIn("dronedream-shared-static-site", builder)
        self.assertIn("DRONEDREAM_RELEASE_STAGING_DIRECTORY", builder)
        self.assertIn("DRONEDREAM_EDITION_STAGING_DIRECTORY", builder)
        self.assertIn("stage-edition-release-assets.mjs", builder)
        self.assertIn("edition-artifacts.json", builder)
        self.assertIn("editionArtifacts = $editionArtifactManifest", builder)
        self.assertIn("ConvertTo-Json -Depth 8", builder)
        self.assertIn("updaterSignature", builder)
        self.assertIn("updaterManifest", builder)
        self.assertIn("Publication file verification failed", builder)
        self.assertIn("-Recurse -Force -File", builder)
        self.assertIn("dronedream-site-${{ github.sha }}", workflow)
        self.assertIn("include-hidden-files: true", workflow)
        self.assertIn('"website/releases/edition-handoff-status.json"', workflow)
        self.assertIn('"website/scripts/stage-edition-release-assets.mjs"', workflow)
        self.assertIn("preserve_release_artifact:", workflow)
        self.assertIn(
            "github.event_name == 'workflow_dispatch' "
            "&& inputs.preserve_release_artifact && 30 || 3",
            workflow,
        )

    def test_pages_404_bridge_restores_public_and_console_deep_links(self) -> None:
        builder = self.read("website/scripts/build-pages-site.ps1")
        console_entry = self.read("frontend/index.html")
        site_entry = self.read("frontend/site.html")
        not_found_bridge = self.read("frontend/public/spa-redirect-404.js")
        restore_bridge = self.read("frontend/public/spa-redirect-restore.js")

        self.assertNotIn(
            'Copy-Item -LiteralPath $siteHtml -Destination '
            '(Join-Path $outputDirectory "404.html")',
            builder,
        )
        self.assertIn(
            '<script src="/spa-redirect-404.js" defer></script>', builder
        )
        self.assertNotIn("<script>", builder)
        self.assertIn(
            'const redirectKey = "dronedream:spa-redirect";', not_found_bridge
        )
        self.assertIn('window.location.pathname === "/console"', not_found_bridge)
        self.assertIn(
            'window.location.pathname.startsWith("/console/")', not_found_bridge
        )
        self.assertIn(
            'const entryPath = isConsolePath ? "/console/" : "/";',
            not_found_bridge,
        )
        self.assertIn(
            "window.sessionStorage.setItem(redirectKey, requestedPath)",
            not_found_bridge,
        )
        self.assertIn("window.location.replace(entryPath)", not_found_bridge)

        for entry in (console_entry, site_entry):
            with self.subTest(entry=entry[:40]):
                self.assertIn(
                    '<link rel="icon" type="image/png" href="/drone-favicon.png" />',
                    entry,
                )
                self.assertIn(
                    '<script src="/spa-redirect-restore.js" defer></script>', entry
                )
                self.assertNotIn("<script>", entry)

        self.assertIn(
            'const redirectKey = "dronedream:spa-redirect";', restore_bridge
        )
        self.assertIn(
            "window.sessionStorage.getItem(redirectKey)", restore_bridge
        )
        self.assertIn(
            "window.sessionStorage.removeItem(redirectKey)", restore_bridge
        )
        self.assertIn(
            'window.history.replaceState(null, "", redirectTarget)', restore_bridge
        )
        self.assertIn('!redirectTarget.startsWith("//")', restore_bridge)

    def test_pages_build_publishes_real_fixed_console_route_entries(self) -> None:
        builder = self.read("website/scripts/build-pages-site.ps1")

        self.assertIn('$consoleStaticRoutes = @(', builder)
        for route in (
            "assistant",
            "dashboard",
            "history",
            "scenarios",
            "admin",
            "compare",
            "jobs\\new",
            "desktop\\setup",
        ):
            with self.subTest(route=route):
                self.assertRegex(builder, rf'(?m)^    "{re.escape(route)}",?$')
        self.assertIn(
            '$routeDirectory = Join-Path (Join-Path $outputDirectory "console") '
            "$consoleStaticRoute",
            builder,
        )
        self.assertIn('Join-Path $routeDirectory "index.html"', builder)

    def test_parity_verifies_public_release_metadata_on_both_origins(self) -> None:
        parity = self.read("website/scripts/verify-site-parity.ps1")
        readme = self.read("website/README.md")

        self.assertIn("'^downloads/latest\\.json$'", parity)
        self.assertIn(
            "if ($relativePath -ceq 'downloads/latest.json')",
            parity,
        )
        self.assertIn("$verifiedReleaseMetadata[$originName]", parity)
        self.assertIn(
            "$verifiedReleaseMetadata.Count -ne $originUris.Count",
            parity,
        )
        for field in (
            "version",
            "fileName",
            "sha256",
            "sizeBytes",
            "publishedAt",
            "downloadUrl",
            "checksumUrl",
        ):
            with self.subTest(field=field):
                self.assertIn(f"metadata.{field}", parity)
        self.assertIn(
            "downloads/latest.json does not match the shared release metadata",
            parity,
        )
        self.assertIn("downloads/latest.json", readme)
        self.assertIn("downloads/editions.json", parity)
        self.assertIn("downloads/edition-artifacts.json", parity)
        self.assertIn("$snapshots.global.BuildManifest.editionArtifacts.entries", parity)
        self.assertIn("Parity verification missed edition artifact paths", parity)
        self.assertIn("including edition downloads", parity)

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
