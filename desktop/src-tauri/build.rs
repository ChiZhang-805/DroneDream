use std::path::PathBuf;
use std::process::Command;

#[path = "build_support/frontend_assets.rs"]
mod frontend_assets;

// 功能：
//   在发布模式编译前验证真正生效的前端入口，阻止生成打开本机目录的空壳 EXE。
// 输入：
//   manifest_dir：桌面 crate 及规范 Tauri 配置所在目录。
// 输出：
//   无；缺失、非字符串或不适合嵌入的入口会直接中止构建。
fn require_embedded_frontend(manifest_dir: &std::path::Path) {
    if std::env::var("PROFILE").as_deref() != Ok("release") {
        return;
    }
    println!("cargo:rerun-if-env-changed=TAURI_CONFIG");
    let base: serde_json::Value = serde_json::from_slice(
        &std::fs::read(manifest_dir.join("tauri.conf.json")).expect("Tauri base config is missing"),
    ).expect("Tauri base config is invalid");
    let overlay: serde_json::Value = std::env::var("TAURI_CONFIG").ok()
        .map(|value| serde_json::from_str(&value).expect("Tauri build overlay is invalid"))
        .unwrap_or(serde_json::Value::Null);
    let frontend = overlay.pointer("/build/frontendDist")
        .or_else(|| base.pointer("/build/frontendDist"))
        .and_then(serde_json::Value::as_str)
        .expect("frontendDist must name an embedded directory");
    frontend_assets::validate_embedded_frontend(frontend, manifest_dir)
        .unwrap_or_else(|error| panic!("{error}"));
}

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
            "unified-sim-lab" | "sim-only" | "field-lightweight" | "autonomy-full"
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
        matches!(
            edition_id.as_str(),
            "universal" | "sim" | "lab" | "field" | "autonomy"
        ),
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
    let oauth_segments = oauth_client_id.split('-').collect::<Vec<_>>();
    let registered_oauth_client = oauth_segments.len() == 5
        && oauth_segments
            .iter()
            .map(|segment| segment.len())
            .eq([8, 4, 4, 4, 12])
        && oauth_client_id
            .bytes()
            .filter(|byte| *byte != b'-')
            .all(|byte| byte.is_ascii_hexdigit());
    let development_placeholder = !release_build && oauth_client_id.starts_with("unregistered-");
    assert!(
        registered_oauth_client || development_placeholder,
        "DRONEDREAM_OAUTH_CLIENT_ID is malformed"
    );
    assert!(
        !release_build || registered_oauth_client,
        "release builds cannot use an unregistered OAuth client"
    );
    println!("cargo:rustc-env=DRONEDREAM_DESKTOP_EDITION_ID={edition_id}");
    println!("cargo:rustc-env=DRONEDREAM_EDITION_PROFILE={edition_profile}");
    println!("cargo:rustc-env=DRONEDREAM_OAUTH_CLIENT_ID={oauth_client_id}");
    println!("cargo:rustc-check-cfg=cfg(dronedream_hardware_domain)");
    println!("cargo:rustc-check-cfg=cfg(dronedream_lab)");
    println!("cargo:rustc-check-cfg=cfg(dronedream_field)");
    println!("cargo:rustc-check-cfg=cfg(dronedream_agent)");
    if matches!(
        edition_id.as_str(),
        "universal" | "lab" | "field" | "autonomy"
    ) {
        println!("cargo:rustc-cfg=dronedream_hardware_domain");
    }
    if matches!(edition_id.as_str(), "universal" | "lab") {
        println!("cargo:rustc-cfg=dronedream_lab");
    }
    if edition_id == "field" {
        println!("cargo:rustc-cfg=dronedream_field");
    }
    // Every desktop edition exposes the AGENT workspace. Compile the same
    // private sidecar bridge into all five products so SIM, LAB, FIELD and
    // Universal never degrade into a presentation-only shell.
    println!("cargo:rustc-cfg=dronedream_agent");
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

// 功能：
//   为明确指定的本机界面补丁复用已安装且通过完整性校验的 Engine Pack，禁止伪造更新顺序。
// 输入：
//   output：隔离构建目录；tool：组件校验程序；python：解释器；profile：版本配置；commit：源码提交。
// 输出：
//   reused：是否使用显式指定的本机组件包。
fn reuse_local_engine_pack(output: &std::path::Path, tool: &std::path::Path, python: &str, profile: &str, commit: &str) -> bool {
    println!("cargo:rerun-if-env-changed=DRONEDREAM_LOCAL_ENGINE_PACK_DIRECTORY");
    println!("cargo:rerun-if-env-changed=DRONEDREAM_LOCAL_ENGINE_PACK_ID");
    let Some(directory) = std::env::var_os("DRONEDREAM_LOCAL_ENGINE_PACK_DIRECTORY") else { return false; };
    assert!(std::env::var_os("DRONEDREAM_RELEASE_SOURCE_COMMIT").is_none()
        && std::env::var_os("DRONEDREAM_RELEASE_BUILD_NUMBER").is_none(),
        "Official releases cannot reuse a local component override");
    let directory = PathBuf::from(directory).canonicalize().expect("Local Engine Pack directory is missing");
    emit_rerun_tree(&directory);
    let descriptor_path = directory.join("engine-pack-bundle.json");
    let manifest_path = directory.join("engine-pack-manifest.json");
    let descriptor: serde_json::Value = serde_json::from_slice(&std::fs::read(&descriptor_path).expect("Local Engine Pack descriptor is missing")).expect("Invalid local descriptor");
    let manifest: serde_json::Value = serde_json::from_slice(&std::fs::read(&manifest_path).expect("Local Engine Pack manifest is missing")).expect("Invalid local manifest");
    let expected_id = std::env::var("DRONEDREAM_LOCAL_ENGINE_PACK_ID").expect("Local Engine Pack reuse requires an explicit content identity");
    assert_eq!(descriptor["packId"].as_str(), Some(expected_id.as_str()), "Local Engine Pack pin mismatch");
    assert_eq!(descriptor["sourceCommit"].as_str(), Some(commit), "Local Engine Pack belongs to a different source commit");
    assert_eq!(manifest["editionProfile"]["profileId"].as_str(), Some(profile), "Local Engine Pack belongs to a different edition");
    // 校验工具检查归档内每个文件及外部清单的大小和摘要，而非只相信版本字符串。
    let verified = Command::new(python).arg(tool).arg("verify")
        .arg("--descriptor").arg(&descriptor_path)
        .arg("--archive").arg(directory.join("DroneDreamEnginePack.tar.gz"))
        .status().expect("Unable to verify local Engine Pack");
    assert!(verified.success(), "Local Engine Pack failed content verification");
    for name in ["engine-pack-bundle.json", "engine-pack-manifest.json", "DroneDreamEnginePack.tar.gz"] {
        std::fs::copy(directory.join(name), output.join(name)).expect("Unable to stage verified local Engine Pack");
    }
    let staged: serde_json::Value = serde_json::from_slice(&std::fs::read(output.join("engine-pack-bundle.json")).expect("Staged descriptor is missing")).expect("Staged descriptor is invalid");
    assert_eq!(staged, descriptor, "Local Engine Pack changed during staging");
    let staged_verified = Command::new(python).arg(tool).arg("verify")
        .arg("--descriptor").arg(output.join("engine-pack-bundle.json"))
        .arg("--archive").arg(output.join("DroneDreamEnginePack.tar.gz"))
        .status().expect("Unable to verify staged Engine Pack");
    assert!(staged_verified.success(), "Staged Engine Pack failed content verification");
    println!("cargo:warning=Local UI build preserves explicitly pinned Engine Pack {expected_id}; this is not an official release");
    true
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
    if !reuse_local_engine_pack(&output_directory, &tool, &python, edition_profile, &source_commit) {
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
    }
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
    require_embedded_frontend(&manifest_dir);
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
    let component_prefix = "VITE_COMPONENT_UPDATE_CATALOG_URL=";
    let component_values = raw
        .lines()
        .filter_map(|line| line.strip_prefix(component_prefix))
        .collect::<Vec<_>>();
    assert_eq!(
        component_values.len(),
        1,
        "frontend/.env.production must define VITE_COMPONENT_UPDATE_CATALOG_URL exactly once"
    );
    let component_url = component_values[0].trim();
    assert!(
        component_url.starts_with("https://") && !component_url.contains(char::is_whitespace),
        "the production component catalog URL must be an absolute HTTPS URL"
    );
    println!("cargo:rustc-env=DRONEDREAM_PRODUCTION_COMPONENT_CATALOG_URL={component_url}");
    tauri_build::build()
}
