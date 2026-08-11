use std::path::PathBuf;
use std::process::Command;

fn emit_rerun_tree(path: &std::path::Path) {
    println!("cargo:rerun-if-changed={}", path.display());
    if !path.is_dir() {
        return;
    }
    let mut entries = std::fs::read_dir(path)
        .unwrap_or_else(|error| panic!("unable to inspect {}: {error}", path.display()))
        .collect::<Result<Vec<_>, _>>()
        .unwrap_or_else(|error| panic!("unable to enumerate {}: {error}", path.display()));
    entries.sort_by_key(|entry| entry.file_name());
    for entry in entries {
        emit_rerun_tree(&entry.path());
    }
}

fn git_output(repository_root: &std::path::Path, arguments: &[&str]) -> String {
    let output = Command::new("git")
        .args(arguments)
        .current_dir(repository_root)
        .output()
        .unwrap_or_else(|error| panic!("unable to run git for Engine Pack provenance: {error}"));
    assert!(
        output.status.success(),
        "git could not resolve Engine Pack provenance: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    String::from_utf8(output.stdout)
        .expect("git Engine Pack provenance must be UTF-8")
        .trim()
        .to_string()
}

fn git_output_optional(repository_root: &std::path::Path, arguments: &[&str]) -> Option<String> {
    let output = Command::new("git")
        .args(arguments)
        .current_dir(repository_root)
        .output()
        .ok()?;
    if !output.status.success() {
        return None;
    }
    Some(String::from_utf8(output.stdout).ok()?.trim().to_string())
}

fn emit_git_provenance_reruns(repository_root: &std::path::Path) {
    for git_path in ["HEAD", "packed-refs"] {
        let path = PathBuf::from(git_output(
            repository_root,
            &["rev-parse", "--git-path", git_path],
        ));
        if path.exists() {
            println!("cargo:rerun-if-changed={}", path.display());
        }
    }
    if let Some(symbolic_ref) =
        git_output_optional(repository_root, &["symbolic-ref", "-q", "HEAD"])
    {
        let path = PathBuf::from(git_output(
            repository_root,
            &["rev-parse", "--git-path", &symbolic_ref],
        ));
        if path.exists() {
            println!("cargo:rerun-if-changed={}", path.display());
        }
    }
    println!("cargo:rerun-if-env-changed=DRONEDREAM_RELEASE_SOURCE_COMMIT");
    println!("cargo:rerun-if-env-changed=DRONEDREAM_RELEASE_BUILD_NUMBER");
    println!("cargo:rerun-if-env-changed=DRONEDREAM_EDITION_PROFILE");
    println!("cargo:rerun-if-env-changed=DRONEDREAM_DESKTOP_EDITION_ID");
    println!("cargo:rerun-if-env-changed=DRONEDREAM_OAUTH_CLIENT_ID");
}

fn expected_engine_pack_profile(manifest_dir: &std::path::Path, edition_id: &str) -> String {
    let registry_path =
        manifest_dir.join("../../distribution/desktop/edition-runtime-update-families.v1.json");
    println!("cargo:rerun-if-changed={}", registry_path.display());
    let registry: serde_json::Value = serde_json::from_slice(
        &std::fs::read(&registry_path)
            .expect("desktop Runtime/update family registry must be readable"),
    )
    .expect("desktop Runtime/update family registry must be valid JSON");
    assert_eq!(
        registry.get("kind").and_then(serde_json::Value::as_str),
        Some("dronedream-desktop-runtime-update-families"),
        "desktop Runtime/update family registry kind is invalid"
    );
    let matches = registry
        .get("editions")
        .and_then(serde_json::Value::as_array)
        .expect("desktop Runtime/update family registry has no editions")
        .iter()
        .filter(|entry| {
            entry.get("editionId").and_then(serde_json::Value::as_str) == Some(edition_id)
        })
        .collect::<Vec<_>>();
    assert_eq!(
        matches.len(),
        1,
        "desktop edition must have exactly one Runtime/update family"
    );
    let profile = matches[0]
        .get("runtimeProfileId")
        .and_then(serde_json::Value::as_str)
        .expect("desktop Runtime/update family has no runtimeProfileId");
    assert!(
        matches!(
            profile,
            "unified-sim-lab" | "sim-only" | "field-lightweight"
        ),
        "desktop Runtime/update family selected an unsupported Engine Pack profile"
    );
    profile.to_owned()
}

fn configure_desktop_auth_identity(manifest_dir: &std::path::Path) -> String {
    let release_build = std::env::var_os("DRONEDREAM_RELEASE_SOURCE_COMMIT").is_some();
    let edition_id = std::env::var("DRONEDREAM_DESKTOP_EDITION_ID").unwrap_or_else(|_| {
        assert!(
            !release_build,
            "release builds require DRONEDREAM_DESKTOP_EDITION_ID"
        );
        "universal".to_owned()
    });
    assert!(
        matches!(edition_id.as_str(), "universal" | "sim" | "lab" | "field"),
        "DRONEDREAM_DESKTOP_EDITION_ID is not a supported desktop edition"
    );
    let expected_profile = expected_engine_pack_profile(manifest_dir, &edition_id);
    let edition_profile =
        std::env::var("DRONEDREAM_EDITION_PROFILE").unwrap_or_else(|_| expected_profile.clone());
    assert_eq!(
        edition_profile, expected_profile,
        "DRONEDREAM_EDITION_PROFILE does not match the desktop edition identity"
    );

    let oauth_client_id = std::env::var("DRONEDREAM_OAUTH_CLIENT_ID").unwrap_or_else(|_| {
        assert!(
            !release_build,
            "release builds require the registered public DRONEDREAM_OAUTH_CLIENT_ID"
        );
        "unregistered-development-client".to_owned()
    });
    assert!(
        oauth_client_id.len() >= 8
            && oauth_client_id.len() <= 512
            && oauth_client_id
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.')),
        "DRONEDREAM_OAUTH_CLIENT_ID is malformed"
    );
    assert!(
        !release_build || !oauth_client_id.starts_with("unregistered-"),
        "release builds cannot use an unregistered OAuth client"
    );
    println!("cargo:rustc-env=DRONEDREAM_DESKTOP_EDITION_ID={edition_id}");
    println!("cargo:rustc-env=DRONEDREAM_EDITION_PROFILE={edition_profile}");
    println!("cargo:rustc-env=DRONEDREAM_OAUTH_CLIENT_ID={oauth_client_id}");
    println!("cargo:rustc-check-cfg=cfg(dronedream_hardware_domain)");
    println!("cargo:rustc-check-cfg=cfg(dronedream_lab)");
    if matches!(edition_id.as_str(), "universal" | "lab" | "field") {
        println!("cargo:rustc-cfg=dronedream_hardware_domain");
    }
    if matches!(edition_id.as_str(), "universal" | "lab") {
        println!("cargo:rustc-cfg=dronedream_lab");
    }
    edition_profile
}

fn prepare_generated_directory(path: &std::path::Path) {
    match std::fs::symlink_metadata(path) {
        Ok(metadata) => {
            assert!(
                metadata.is_dir() && !metadata.file_type().is_symlink(),
                "refusing to replace an unsafe generated Engine Pack path: {}",
                path.display()
            );
            std::fs::remove_dir_all(path).unwrap_or_else(|error| {
                panic!(
                    "unable to reset the generated Engine Pack directory {}: {error}",
                    path.display()
                )
            });
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
        Err(error) => panic!(
            "unable to inspect the generated Engine Pack directory {}: {error}",
            path.display()
        ),
    }
    std::fs::create_dir(path).unwrap_or_else(|error| {
        panic!(
            "unable to create the generated Engine Pack directory {}: {error}",
            path.display()
        )
    });
}

fn build_engine_pack(manifest_dir: &std::path::Path, edition_profile: &str) {
    let repository_root = manifest_dir
        .join("../..")
        .canonicalize()
        .expect("repository root must be available to the desktop build");
    emit_git_provenance_reruns(&repository_root);
    for relative in [
        "backend/app",
        "backend/alembic",
        "backend/alembic.ini",
        "backend/pyproject.toml",
        "worker/drone_dream_worker",
        "worker/pyproject.toml",
        "scripts/simulators",
        "runtime/pins.env",
        "runtime/locks/python-requirements.lock",
        "engine-pack/tools/engine_pack.py",
        "distribution",
    ] {
        emit_rerun_tree(&repository_root.join(relative));
    }
    let source_commit = git_output(&repository_root, &["rev-parse", "--verify", "HEAD"]);
    let source_tree_clean = git_output(
        &repository_root,
        &["status", "--porcelain=v1", "--untracked-files=all"],
    )
    .is_empty();
    let source_date_epoch = git_output(
        &repository_root,
        &["show", "-s", "--format=%ct", &source_commit],
    );
    let build_number = git_output(&repository_root, &["rev-list", "--count", &source_commit]);
    assert!(
        build_number.parse::<u64>().is_ok_and(|value| value > 0),
        "Git history did not produce a positive updater build number"
    );
    if let Ok(expected) = std::env::var("DRONEDREAM_RELEASE_SOURCE_COMMIT") {
        assert_eq!(
            source_commit, expected,
            "Git HEAD changed after the release build was frozen"
        );
    }
    if let Ok(expected) = std::env::var("DRONEDREAM_RELEASE_BUILD_NUMBER") {
        assert_eq!(
            build_number, expected,
            "Git build number changed after the release build was frozen"
        );
    }
    let output_directory = PathBuf::from(
        std::env::var("OUT_DIR").expect("Cargo must set OUT_DIR for the Engine Pack build"),
    )
    .join("engine-pack");
    prepare_generated_directory(&output_directory);
    let tool = repository_root.join("engine-pack/tools/engine_pack.py");
    let python = std::env::var("PYTHON").unwrap_or_else(|_| {
        if cfg!(windows) {
            "python".to_string()
        } else {
            "python3".to_string()
        }
    });
    let status = Command::new(&python)
        .arg(&tool)
        .arg("build")
        .arg("--repository-root")
        .arg(&repository_root)
        .arg("--output-directory")
        .arg(&output_directory)
        .arg("--source-commit")
        .arg(&source_commit)
        .arg("--edition-profile")
        .arg(edition_profile)
        .env("SOURCE_DATE_EPOCH", &source_date_epoch)
        .status()
        .unwrap_or_else(|error| {
            panic!("unable to build the embedded Engine Pack with {python}: {error}")
        });
    assert!(status.success(), "embedded Engine Pack generation failed");
    let descriptor_path = output_directory.join("engine-pack-bundle.json");
    let descriptor: serde_json::Value = serde_json::from_slice(
        &std::fs::read(&descriptor_path).expect("embedded Engine Pack descriptor is missing"),
    )
    .expect("embedded Engine Pack descriptor is invalid");
    let pack_id = descriptor
        .get("packId")
        .and_then(serde_json::Value::as_str)
        .expect("embedded Engine Pack descriptor has no packId");
    println!("cargo:rustc-env=DRONEDREAM_ENGINE_PACK_ID={pack_id}");
    println!("cargo:rustc-env=DRONEDREAM_SOURCE_COMMIT={source_commit}");
    println!("cargo:rustc-env=DRONEDREAM_SOURCE_TREE_CLEAN={source_tree_clean}");
    println!("cargo:rustc-env=DRONEDREAM_BUILD_NUMBER={build_number}");
}

fn main() {
    let manifest_dir = PathBuf::from(
        std::env::var("CARGO_MANIFEST_DIR").expect("Cargo must set CARGO_MANIFEST_DIR"),
    );
    let edition_profile = configure_desktop_auth_identity(&manifest_dir);
    build_engine_pack(&manifest_dir, &edition_profile);
    let frontend_environment = manifest_dir.join("../../frontend/.env.production");
    println!("cargo:rerun-if-changed={}", frontend_environment.display());
    let raw = std::fs::read_to_string(&frontend_environment)
        .expect("frontend/.env.production must be readable for the desktop build");
    let prefix = "VITE_RUNTIME_RELEASE_MANIFEST_URL=";
    let values = raw
        .lines()
        .filter_map(|line| line.strip_prefix(prefix))
        .collect::<Vec<_>>();
    assert_eq!(
        values.len(),
        1,
        "frontend/.env.production must define VITE_RUNTIME_RELEASE_MANIFEST_URL exactly once"
    );
    let url = values[0].trim();
    assert!(
        url.starts_with("https://") && !url.contains(char::is_whitespace),
        "the production runtime release manifest URL must be an absolute HTTPS URL"
    );
    println!("cargo:rustc-env=DRONEDREAM_PRODUCTION_RUNTIME_RELEASE_MANIFEST_URL={url}");
    tauri_build::build()
}
