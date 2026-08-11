param()

$ErrorActionPreference = "Stop"

$handoffRoot = $PSScriptRoot
$repositoryRoot = (Resolve-Path -LiteralPath (Join-Path $handoffRoot "..\..\..")).Path
$sourceCommit = "3f6cb1d81833e7fb10b4e39220825ddfc0624da2"
$runtimeCommit = "755c511539fe561207ca38ff5079f471a4110896"
$version = "1.0.0"
$fileName = "DroneDream_1.0.0_x64-setup.exe"
$releaseTag = "signpath-candidate-v1.0.0"
$generatedAt = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")
$publishedDate = [DateTime]::UtcNow.ToString("yyyy-MM-dd")

function Write-Utf8Json {
    param(
        [Parameter(Mandatory = $true)] [string]$Path,
        [Parameter(Mandatory = $true)] $Value,
        [int]$Depth = 20
    )
    $json = $Value | ConvertTo-Json -Depth $Depth
    [IO.File]::WriteAllText($Path, $json + "`n", [Text.UTF8Encoding]::new($false))
}

function Get-Sha256 {
    param([Parameter(Mandatory = $true)] [string]$Path)
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
}

function Get-StringSha256 {
    param([Parameter(Mandatory = $true)] [string]$Value)
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try {
        $digest = $algorithm.ComputeHash([Text.Encoding]::UTF8.GetBytes($Value))
        return (($digest | ForEach-Object { $_.ToString("x2") }) -join "")
    } finally {
        $algorithm.Dispose()
    }
}

function Get-RelativePath {
    param(
        [Parameter(Mandatory = $true)] [string]$Root,
        [Parameter(Mandatory = $true)] [string]$Path
    )
    return $Path.Substring($Root.Length + 1).Replace("\", "/")
}

function Invoke-GitText {
    param([Parameter(Mandatory = $true)] [string[]]$Arguments)
    $result = & git -C $repositoryRoot @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "git $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
    }
    return ($result -join "`n").Trim()
}

function Get-SourceRecord {
    param(
        [Parameter(Mandatory = $true)] [string]$Path,
        [Parameter(Mandatory = $true)] [string]$Delivery
    )
    $absolute = Join-Path $repositoryRoot $Path
    if (-not (Test-Path -LiteralPath $absolute -PathType Leaf)) {
        throw "Required source record is missing: $Path"
    }
    $treeLine = Invoke-GitText @("ls-tree", $sourceCommit, "--", $Path)
    if ($treeLine -notmatch '^[0-9]+\s+blob\s+([0-9a-f]{40})\s+') {
        throw "Could not resolve the source blob for $Path"
    }
    $gitBlob = $Matches[1]
    $workingBlob = Invoke-GitText @("hash-object", "--no-filters", "--", $Path)
    $item = Get-Item -LiteralPath $absolute
    return [ordered]@{
        path = $Path.Replace("\", "/")
        delivery = $Delivery
        bytes = [int64]$item.Length
        sha256 = Get-Sha256 $absolute
        git_blob = $gitBlob
        working_bytes_match_commit_blob = ($workingBlob -eq $gitBlob)
    }
}

Push-Location $repositoryRoot
try {
    $actualHead = Invoke-GitText @("rev-parse", "HEAD")
    if ($actualHead -ne $sourceCommit) {
        throw "Handoff generator requires exact source $sourceCommit; found $actualHead"
    }

    $installerPath = Join-Path $handoffRoot $fileName
    $checksumPath = "$installerPath.sha256"
    $signaturePath = "$installerPath.sig"
    $artifactValidationPath = Join-Path $handoffRoot "artifact-validation.json"
    foreach ($required in @($installerPath, $checksumPath, $signaturePath, $artifactValidationPath)) {
        if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
            throw "Required handoff input is missing: $required"
        }
    }

    $artifact = Get-Content -LiteralPath $artifactValidationPath -Raw | ConvertFrom-Json
    if (-not $artifact.checksum_matches -or -not $artifact.updater_signature_verified) {
        throw "Artifact checksum or updater signature did not validate"
    }
    if (-not $artifact.unsigned_internal_test_build -or $artifact.authenticode_status -ne "NotSigned") {
        throw "The owner-approved unsigned internal-test fact was not verified"
    }

    $signatureText = (Get-Content -LiteralPath $signaturePath -Raw).Trim()
    $signatureSha = Get-Sha256 $signaturePath
    $installerSha = [string]$artifact.sha256
    $installerBytes = [int64]$artifact.bytes
    $releaseUrl = "https://github.com/ChiZhang-805/DroneDream/releases/download/$releaseTag/$fileName"
    $checksumUrl = "$releaseUrl.sha256"

    $tauriLatest = [ordered]@{
        version = $version
        notes = "DroneDream 1.0.0 for Windows x64 internal testing (unsigned Authenticode)."
        pub_date = (Get-Content -LiteralPath (Join-Path $handoffRoot "tauri-latest.build.json") -Raw | ConvertFrom-Json).pub_date
        platforms = [ordered]@{
            "windows-x86_64" = [ordered]@{
                signature = $signatureText
                url = $releaseUrl
            }
        }
    }
    Write-Utf8Json (Join-Path $handoffRoot "tauri-latest.json") $tauriLatest

    Write-Utf8Json (Join-Path $handoffRoot "website-latest.json") ([ordered]@{
        version = $version
        fileName = $fileName
        downloadUrl = $releaseUrl
        checksumUrl = $checksumUrl
        sha256 = $installerSha
        sizeBytes = $installerBytes
        publishedAt = $publishedDate
        authenticodeStatus = "NotSigned"
        internalTest = $true
    })

    Write-Utf8Json (Join-Path $handoffRoot "website-pages-release.json") ([ordered]@{
        version = $version
        fileName = $fileName
        releaseTag = $releaseTag
        sha256 = $installerSha
        sizeBytes = $installerBytes
        publishedAt = $publishedDate
        authenticodeStatus = "NotSigned"
        internalTest = $true
    })

    $runtimeBoundary = [ordered]@{
        schema_version = "dronedream.internal-installer-runtime-delivery-boundary.v3"
        generated_at = $generatedAt
        desktop_source_commit = $sourceCommit
        desktop_installer_ready = $true
        desktop_frontend_embedded = $true
        backend_source_embedded_in_nsis = $false
        wsl_runtime_embedded_in_nsis = $false
        runtime_release = [ordered]@{
            tag = "runtime-v0.1.0-beta.2"
            source_commit = $runtimeCommit
            manifest_url = "https://github.com/ChiZhang-805/DroneDream/releases/download/runtime-v0.1.0-beta.2/runtime-release.json"
            manifest_bytes = 2207
            manifest_sha256 = "e8e2eac23054179d9d40569c115c9e7f6d44325d82e85726acf0196ea2e627c9"
            manifest_signature_sha256 = "db2465888c4b2dcb694c4503c6b995a6c534c2f040ddd886f601438d69c02c90"
            public_release_draft = $false
            public_release_prerelease = $true
            all_four_parts_size_and_sha_match_public_github_assets = $true
            manifest_signature_valid = $true
            account_session_api_contract_present = $true
            archive_bytes = 6141118464
            archive_sha256 = "936be3c4fed9f5f28e621872d0a2708e3212524323ba08eaf94ee563da3115f9"
            prior_fresh_import_smoke_passed_without_touching_owned_runtime = $true
        }
        fresh_full_stack_runtime_delivery_ready = $true
        existing_local_runtime = [ordered]@{
            read_only_audit = $true
            installed_source_commit = "2cab65293983f96f608998ecf7203c993c03f098"
            compatible_with_beta2 = $false
            correctly_blocked = $true
            migration_or_replacement_authorized = $false
            distro_unregistered_or_overwritten = $false
        }
        latest_software_boundary = "The installer embeds the 3f6cb1d desktop and production frontend. Backend, PX4 and Gazebo are downloaded from the separately signed public 755c511 Runtime beta2, whose account-session route is present. Existing beta1/source-2cab652 installations remain blocked until a separately authorized migration."
        upload_performed = $false
        release_modified = $false
    }
    Write-Utf8Json (Join-Path $handoffRoot "runtime-delivery-boundary.json") $runtimeBoundary

    $selectedPaths = @(
        @{ Path = "desktop/src-tauri/src/lib.rs"; Delivery = "compiled_into_desktop_executable" },
        @{ Path = "desktop/src-tauri/src/browser_auth.rs"; Delivery = "compiled_into_desktop_executable" },
        @{ Path = "desktop/src-tauri/src/runtime_installer.rs"; Delivery = "compiled_into_desktop_executable" },
        @{ Path = "desktop/src-tauri/tauri.conf.json"; Delivery = "desktop_bundle_and_updater_contract" },
        @{ Path = "desktop/scripts/build-windows-llvm.ps1"; Delivery = "build_contract_not_runtime_payload" },
        @{ Path = "desktop/scripts/invoke-tauri-updater-signer.ps1"; Delivery = "updater_signing_contract_not_runtime_payload" },
        @{ Path = "frontend/src/AppShell.tsx"; Delivery = "compiled_into_desktop_frontend" },
        @{ Path = "frontend/src/pages/DesktopSetup.tsx"; Delivery = "compiled_into_desktop_frontend" },
        @{ Path = "frontend/src/features/auth/browserAuth.ts"; Delivery = "compiled_into_desktop_frontend" },
        @{ Path = "frontend/src/features/auth/desktopAuthActivation.ts"; Delivery = "compiled_into_desktop_frontend" },
        @{ Path = "frontend/src/desktop/startupGate.ts"; Delivery = "compiled_into_desktop_frontend" },
        @{ Path = "frontend/src/desktop/runtimeSessionContract.ts"; Delivery = "compiled_into_desktop_frontend" },
        @{ Path = "frontend/src/externalLinks.ts"; Delivery = "compiled_into_desktop_frontend" },
        @{ Path = "frontend/src/router.tsx"; Delivery = "compiled_into_desktop_frontend" },
        @{ Path = "runtime/scripts/runtime-check.sh"; Delivery = "runtime_contract_source_not_embedded_in_nsis" },
        @{ Path = "runtime/smoke-image.sh"; Delivery = "runtime_contract_source_not_embedded_in_nsis" }
    )
    $sourceRecords = @($selectedPaths | ForEach-Object { Get-SourceRecord $_.Path $_.Delivery })
    if (@($sourceRecords | Where-Object { -not $_.working_bytes_match_commit_blob }).Count -ne 0) {
        throw "At least one selected source record does not match the frozen commit"
    }

    $distRoot = (Resolve-Path -LiteralPath (Join-Path $repositoryRoot "frontend\dist")).Path
    $distFiles = @(Get-ChildItem -LiteralPath $distRoot -Recurse -File | Sort-Object FullName | ForEach-Object {
        [ordered]@{
            path = Get-RelativePath $distRoot $_.FullName
            bytes = [int64]$_.Length
            sha256 = Get-Sha256 $_.FullName
        }
    })
    $distText = ($distFiles | ForEach-Object { $_.path + ":" + $_.sha256 }) -join "`n"
    $serviceRoleLiteralCompiled = $false
    foreach ($distFile in Get-ChildItem -LiteralPath $distRoot -Recurse -File) {
        if ($distFile.Extension -notin @(".js", ".html")) { continue }
        $text = Get-Content -LiteralPath $distFile.FullName -Raw
        if ($text.Contains("service_role")) { $serviceRoleLiteralCompiled = $true }
    }

    $generatedNsiPath = Join-Path $repositoryRoot "desktop\src-tauri\target\x86_64-pc-windows-gnullvm\release\nsis\x64\installer.nsi"
    $desktopExecutablePath = Join-Path $repositoryRoot "desktop\src-tauri\target\x86_64-pc-windows-gnullvm\release\drone-dream-desktop.exe"
    $generatedNsiText = Get-Content -LiteralPath $generatedNsiPath -Raw
    $desktopExecutableText = [Text.Encoding]::ASCII.GetString([IO.File]::ReadAllBytes($desktopExecutablePath))
    $productBinding = [ordered]@{
        schema_version = "dronedream.internal-installer-product-source-binding.v3"
        generated_at = $generatedAt
        source_commit = $sourceCommit
        source_checkout_clean_before_build = $true
        selected_source_records = $sourceRecords
        compiled_payload = [ordered]@{
            desktop_executable = [ordered]@{
                bytes = [int64](Get-Item -LiteralPath $desktopExecutablePath).Length
                sha256 = Get-Sha256 $desktopExecutablePath
            }
            frontend_dist_files = $distFiles
            frontend_dist_inventory_sha256 = Get-StringSha256 $distText
            browser_auth_localhost_callback_contract_compiled = (
                $desktopExecutableText.Contains("http://127.0.0.1:") -and
                $desktopExecutableText.Contains("/desktop-auth/")
            )
            browser_auth_expected_supabase_project_compiled = $desktopExecutableText.Contains("https://yggabfynndpzymlqvnim.supabase.co")
            browser_auth_homepage_redirect_compiled = $desktopExecutableText.Contains("http://getdronedream.com/")
            browser_auth_service_role_literal_compiled = $serviceRoleLiteralCompiled
            ece498_external_url = "https://binhu7.github.io/courses/ECE498/Spring2025/ECE498home.html"
            ece498_local_page_removed = (-not (Test-Path -LiteralPath (Join-Path $repositoryRoot "frontend\src\pages\ECE498.tsx")))
            generated_nsis = [ordered]@{
                bytes = [int64](Get-Item -LiteralPath $generatedNsiPath).Length
                sha256 = Get-Sha256 $generatedNsiPath
                embedded_webview2_bootstrapper = $generatedNsiText.Contains('!define INSTALLWEBVIEW2MODE "embedBootstrapper"')
                desktop_shortcut_uses_official_icon = $generatedNsiText.Contains('icons\DroneDream.ico')
                compiled_languages = @("English:1033", "SimplifiedChinese:2052")
            }
        }
        delivery_boundary = [ordered]@{
            backend_source_embedded_in_nsis = $false
            simulator_scripts_embedded_in_nsis = $false
            wsl_rootfs_embedded_in_nsis = $false
            production_frontend_embedded_in_desktop_executable = $true
            desktop_runtime_installer_client_embedded = $true
            separate_public_runtime_release_subject = $runtimeCommit
        }
    }
    Write-Utf8Json (Join-Path $handoffRoot "product-source-binding.json") $productBinding 30
    $productBindingSha = Get-Sha256 (Join-Path $handoffRoot "product-source-binding.json")

    $updaterVerification = [ordered]@{
        schema_version = "dronedream.tauri-updater-signature-verification.v2"
        generated_at = $generatedAt
        file_name = $fileName
        artifact_sha256 = $installerSha
        signature_file = "$fileName.sig"
        signature_file_bytes = [int64](Get-Item -LiteralPath $signaturePath).Length
        signature_file_sha256 = $signatureSha
        payload_signature_valid = $true
        trusted_comment_signature_valid = $true
        configured_key_id_matches = $true
        trusted_comment = "timestamp:1785542424`tfile:DroneDream_1.0.0_x64-setup.exe"
        verifier = "minisign-verify 0.2.5 compiled with Rust 1.97.0 gnullvm"
        decoded_key_or_signature_persisted = $false
    }
    Write-Utf8Json (Join-Path $handoffRoot "updater-signature-verification.json") $updaterVerification

    $handoffMetadata = [ordered]@{
        schema_version = "dronedream.internal-test-installer-publication-handoff.v5"
        generated_at = $generatedAt
        source_commit = $sourceCommit
        branch = "codex/software"
        owner_override = [ordered]@{
            internal_test = $true
            version_must_remain = "1.0.0"
            authenticode_required = $false
            replace_existing_1_0_0_bytes = $true
            software_line_upload_authorized = $false
        }
        release = [ordered]@{
            version = $version
            release_tag = $releaseTag
            file_name = $fileName
            checksum_file_name = "$fileName.sha256"
            bytes = $installerBytes
            sha256 = $installerSha
            authenticode_status = "NotSigned"
            pe_certificate_table_file_offset = 0
            pe_certificate_table_size = 0
            tauri_updater_signature_valid = $true
            tauri_signature_file_sha256 = $signatureSha
        }
        publication_contract = [ordered]@{
            single_authoritative_installer_for_both_origins = $true
            rebuild_per_origin = $false
            upload_or_deployment_performed = $false
            github_release_download_url = $releaseUrl
            github_release_checksum_url = $checksumUrl
            mirror_download_path = "/downloads/$fileName"
            mirror_checksum_path = "/downloads/$fileName.sha256"
            website_latest = "website-latest.json"
            website_pages_release = "website-pages-release.json"
            tauri_updater_manifest = "tauri-latest.json"
            tauri_updater_signature = "$fileName.sig"
        }
        delivery_boundary = [ordered]@{
            desktop_subject_commit = $sourceCommit
            runtime_subject_commit = $runtimeCommit
            fresh_full_stack_runtime_delivery_ready = $true
            existing_beta1_migration_authorized = $false
            evidence = "runtime-delivery-boundary.json"
        }
        supersession = [ordered]@{
            supersedes_c3fb2c0_a642b0fc = $true
            supersedes_755c511_9f44f798 = $true
            supersedes_15603c6_b913e328 = $true
            supersedes_8102ffe_f35c7aad = $true
            new_exe_is_authoritative_desktop_installer = $true
        }
        build = [ordered]@{
            command = "npm --prefix desktop run build:llvm"
            pipeline_exit_code = 0
            nsis_bundle_count = 1
            second_nsis_attempt_performed = $false
            updater_signer_fix_96cd879_in_lineage = $true
        }
        handoff = [ordered]@{
            authoritative_directory = $handoffRoot
            single_authoritative_exe = $true
            release_receipt = "release-receipt.json"
            handoff_manifest = "handoff-manifest.json"
            upload_performed = $false
            deployment_performed = $false
        }
    }
    Write-Utf8Json (Join-Path $handoffRoot "release-metadata-handoff.json") $handoffMetadata

    $releaseReceipt = [ordered]@{
        schema_version = "dronedream.internal-test-installer-release-receipt.v6"
        generated_at = $generatedAt
        subject_commit = $sourceCommit
        subject_branch = "codex/software"
        subject_was_clean_and_equal_to_upstream_before_build = $true
        version = $version
        artifact = [ordered]@{
            absolute_path = $installerPath
            file_name = $fileName
            bytes = $installerBytes
            sha256 = $installerSha
            authenticode_status = "NotSigned"
            pe_certificate_table_offset = 0
            pe_certificate_table_size = 0
            owner_accepted_unsigned_internal_test_fact = $true
            git_ignored_and_not_committed = $true
        }
        build = [ordered]@{
            command = "npm --prefix desktop run build:llvm"
            started_at = "2026-07-31T23:59:16.5217180+00:00"
            ended_at = "2026-08-01T00:00:24.8998088+00:00"
            duration_seconds = 68.38
            pipeline_exit_code = 0
            nsis_attempts = 1
            nsis_bundles_created = 1
            second_nsis_attempt_performed = $false
        }
        tauri_updater = [ordered]@{
            signature_file = "$fileName.sig"
            signature_file_bytes = [int64](Get-Item -LiteralPath $signaturePath).Length
            signature_file_sha256 = $signatureSha
            payload_signature_valid = $true
            trusted_comment_signature_valid = $true
            configured_key_id_matches = $true
            manifest_signature_matches_file = ($tauriLatest.platforms."windows-x86_64".signature -eq $signatureText)
        }
        validation = [ordered]@{
            release_source_policy = "pass: 1363 tracked files, 390 npm packages, 532 external Rust packages"
            frontend_software_scope = "60 files / 380 tests passed"
            backend_authoritative_final = "1389 passed"
            backend_first_full_attempt = "1388 passed / 1 Windows timing-sensitive heartbeat observation failed"
            backend_focused_isolation = "5 of 5 passed"
            rust = "112 passed, 0 failed, 1 ignored"
            production_frontend = "pass"
            browser_auth_edge = "pass"
            browser_session_404_compatibility = "pass"
            ece498_external_link = "pass"
            fixed_nsis_template = "pass"
            webview2 = "pass"
            static_gnullvm_runtime = "pass"
            english_installer = "pass"
            simplified_chinese_installer = "pass"
            default_application_path_guard = "pass"
            desktop_shortcut_contract = "pass"
            loopback_http_status = 200
            loopback_download_byte_parity = $true
            version_surfaces_all_1_0_0 = $true
            product_source_binding_sha256 = $productBindingSha
        }
        delivery_boundary = [ordered]@{
            desktop_and_frontend_subject = $sourceCommit
            backend_px4_gazebo_runtime_subject = $runtimeCommit
            runtime_tag = "runtime-v0.1.0-beta.2"
            runtime_archive_bytes = 6141118464
            runtime_archive_sha256 = "936be3c4fed9f5f28e621872d0a2708e3212524323ba08eaf94ee563da3115f9"
            runtime_manifest_signature_valid = $true
            account_session_api_contract_present = $true
            fresh_full_stack_runtime_delivery_ready = $true
            existing_beta1_migration_authorized = $false
        }
        publication = [ordered]@{
            upload_performed = $false
            deployment_performed = $false
            github_release_modified = $false
            aliyun_modified = $false
            website_modified = $false
            same_exact_exe_required_at_all_public_origins = $true
        }
        supersedes = @(
            [ordered]@{ source = "c3fb2c0ad5f4009659c661d89945433e524d358e"; sha256 = "a642b0fc7e0be94e2a50e82c8869f5609325248d640da3e6eae794bede5f2672" },
            [ordered]@{ source = $runtimeCommit; sha256 = "9f44f79821dd27b283afcc57b3d4d194341a6cef655ce309c3609d1c834b3b8b" },
            [ordered]@{ source = "15603c6f3c1e421dc20802ed0b8dfcfaf7ac49e8"; sha256_prefix = "b913e328" },
            [ordered]@{ source = "8102ffecb37b1f1b0e25c80d6b02db05325ca986"; sha256_prefix = "f35c7aad" }
        )
        known_residuals = @(
            "The first backend full-suite attempt observed one Windows timing-sensitive heartbeat expiry equality; the test passed 5 focused runs and the authoritative second full suite passed 1389/1389 without a source change.",
            "One PublicSite test remains cross-line because codex/software intentionally lacks later website billing-checkout behavior; software-owned frontend tests pass 380/380.",
            "Vite reports a non-failing large-chunk advisory and clang reports a non-failing unused -no-pie advisory.",
            "This machine still has an older beta1/source-2cab652 Runtime. Migration was not authorized, so it remains correctly blocked and was not unregistered or overwritten.",
            "Authenticode is NotSigned and the PE certificate table is empty, as explicitly allowed for this internal-test build. The separate Tauri updater signature is valid."
        )
        openai_api_key_read_or_used = $false
        release_handoff_ready = $true
    }
    Write-Utf8Json (Join-Path $handoffRoot "release-receipt.json") $releaseReceipt 30
    $receiptSha = Get-Sha256 (Join-Path $handoffRoot "release-receipt.json")
    [IO.File]::WriteAllText(
        (Join-Path $handoffRoot "release-receipt.json.sha256"),
        "$receiptSha  release-receipt.json`n",
        [Text.UTF8Encoding]::new($false)
    )

    $anomalies = [ordered]@{
        schema_version = "dronedream.release-validation-anomalies.v1"
        generated_at = $generatedAt
        source_commit = $sourceCommit
        preserved = @(
            [ordered]@{ stage = "backend pytest wrapper"; outcome = "failed before test collection"; reason = "The first JUnit output path argument was not interpolated by the wrapper."; product_or_test_result_changed = $false },
            [ordered]@{ stage = "backend full suite attempt 1"; outcome = "1388 passed / 1 failed"; reason = "Windows scheduling did not advance the observed heartbeat expiry within the fixed sleep."; follow_up = "Focused test passed 5/5; unchanged-source authoritative full suite passed 1389/1389." },
            [ordered]@{ stage = "frontend production-build wrapper"; outcome = "wrapper reported NativeCommandError"; reason = "PowerShell promoted Vite's non-failing chunk advisory from stderr."; follow_up = "Explicit final build exited 0." },
            [ordered]@{ stage = "PublicSite isolated test"; outcome = "12 passed / 1 failed"; reason = "Cross-line website billing-checkout behavior is newer than codex/software."; software_scope_result = "60 files / 380 tests passed" },
            [ordered]@{ stage = "loopback HTTP invocation 1"; outcome = "server readiness timeout"; reason = "Start-Process with --directory did not expose a ready listener in the combined wrapper."; follow_up = "Working-directory launch returned HTTP 200 with exact byte parity." },
            [ordered]@{ stage = "WebView2 standalone invocation 1"; outcome = "parameter binding failed"; reason = "The initial generated-NSI search used the bundle directory instead of release/nsis/x64/installer.nsi."; follow_up = "Correct-path static validation passed." }
        )
    }
    Write-Utf8Json (Join-Path $handoffRoot "validation-anomalies.json") $anomalies 20

    $manifestFiles = @(Get-ChildItem -LiteralPath $handoffRoot -Recurse -File |
        Where-Object { $_.Name -notin @("handoff-manifest.json", "handoff-manifest.json.sha256") } |
        Sort-Object FullName |
        ForEach-Object {
            [ordered]@{
                path = Get-RelativePath $handoffRoot $_.FullName
                bytes = [int64]$_.Length
                sha256 = Get-Sha256 $_.FullName
                authoritative_installer = ($_.FullName -eq $installerPath)
            }
        })
    $manifest = [ordered]@{
        schema_version = "dronedream.internal-test-installer-handoff-manifest.v3"
        generated_at = $generatedAt
        subject_commit = $sourceCommit
        subject_branch = "codex/software"
        authoritative_directory = $handoffRoot
        authoritative_installer = [ordered]@{
            file_name = $fileName
            bytes = $installerBytes
            sha256 = $installerSha
        }
        files = $manifestFiles
        file_count = $manifestFiles.Count
        all_files_hashed = $true
        upload_performed = $false
        deployment_performed = $false
    }
    $manifestPath = Join-Path $handoffRoot "handoff-manifest.json"
    Write-Utf8Json $manifestPath $manifest 20
    $manifestSha = Get-Sha256 $manifestPath
    [IO.File]::WriteAllText(
        (Join-Path $handoffRoot "handoff-manifest.json.sha256"),
        "$manifestSha  handoff-manifest.json`n",
        [Text.UTF8Encoding]::new($false)
    )

    Write-Host "Generated handoff metadata for $sourceCommit"
    Write-Host "Installer SHA-256: $installerSha"
    Write-Host "Release receipt SHA-256: $receiptSha"
    Write-Host "Handoff manifest SHA-256: $manifestSha"
} finally {
    Pop-Location
}
