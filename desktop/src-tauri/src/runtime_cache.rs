//! Safe lifecycle primitives for the signed runtime-image installer.

use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};
use std::fs::{self, OpenOptions};
use std::io::{ErrorKind, Read, Write};
use std::path::{Component, Path, PathBuf};

// Keep downloads beside the WSL import target, never inside it. `wsl --import`
// requires a clean target and the install-plan safety check intentionally
// rejects non-empty unmarked targets after a restart.
const CACHE_DIRECTORY: &str = "DroneDream.download-cache";
const ARTIFACT_DIRECTORY: &str = "artifacts";
const CACHE_MARKER: &str = ".dronedream-download-cache.json";
const CACHE_MARKER_OWNER: &str = "DroneDreamDesktop";
const RUNTIME_NAME: &str = "DroneDreamRuntime";
const MAX_MARKER_BYTES: u64 = 4096;

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct CacheMarker {
    schema_version: u32,
    owner: String,
    runtime_name: String,
}

#[allow(dead_code)]
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum ImportOutcome {
    Succeeded,
    Failed,
}

#[allow(dead_code)]
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum DownloadArtifactState {
    /// A resumable `.part` or chunk that has not passed its manifest digest.
    Partial,
    /// An archive or chunk whose digest was verified by the downloader.
    Verified,
}

#[allow(dead_code)]
#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct DownloadArtifact {
    relative_path: PathBuf,
    state: DownloadArtifactState,
}

#[allow(dead_code)]
impl DownloadArtifact {
    /// A downloaded path is not eligible for cleanup until its digest is verified.
    pub(crate) fn partial(relative_path: impl Into<PathBuf>) -> Self {
        Self {
            relative_path: relative_path.into(),
            state: DownloadArtifactState::Partial,
        }
    }

    /// Call this only after the release-manifest digest has been verified.
    pub(crate) fn verified(relative_path: impl Into<PathBuf>) -> Self {
        Self {
            relative_path: relative_path.into(),
            state: DownloadArtifactState::Verified,
        }
    }
}

#[allow(dead_code)]
#[derive(Debug, Default, PartialEq, Eq)]
pub(crate) struct CacheCleanupReport {
    pub(crate) removed: Vec<PathBuf>,
    pub(crate) retained: Vec<PathBuf>,
    pub(crate) already_missing: Vec<PathBuf>,
}

enum ArtifactLocation {
    ExistingFile(PathBuf),
    Missing,
}

/// Compute a candidate sibling cache; this alone neither creates nor authorizes it.
pub(crate) fn runtime_download_cache_root(target_root: &str) -> PathBuf {
    runtime_download_cache_root_path(Path::new(target_root))
}

/// Keep resumable downloads out of the WSL import directory, which must stay clean.
fn runtime_download_cache_root_path(target_root: &Path) -> PathBuf {
    target_root
        .parent()
        .unwrap_or_else(|| Path::new(""))
        .join(CACHE_DIRECTORY)
}

/// Creates (or reopens) the marker-owned cache used by the runtime downloader.
#[allow(dead_code)]
pub(crate) fn initialize_runtime_download_cache(
    runtime_target_root: &Path,
) -> Result<PathBuf, String> {
    require_absolute_runtime_root(runtime_target_root)?;
    reject_existing_link_like(runtime_target_root)?;

    let cache_parent = runtime_target_root
        .parent()
        .ok_or_else(|| "The runtime target has no local parent directory.".to_string())?;
    let cache_root = runtime_download_cache_root_path(runtime_target_root);
    reject_existing_link_like(cache_parent)?;
    reject_existing_link_like(&cache_root)?;

    if !cache_root.exists() {
        fs::create_dir_all(&cache_root).map_err(|error| {
            format!(
                "Unable to create the managed runtime download cache {}: {error}",
                cache_root.display()
            )
        })?;
    }
    ensure_real_directory(cache_parent, "runtime cache parent")?;
    ensure_real_directory(&cache_root, "runtime download cache")?;

    let marker_path = cache_root.join(CACHE_MARKER);
    if marker_path.exists() {
        validate_cache_marker(&marker_path)?;
    } else {
        let cache_is_empty = fs::read_dir(&cache_root)
            .map_err(|error| format!("Unable to inspect {}: {error}", cache_root.display()))?
            .next()
            .is_none();
        if !cache_is_empty {
            return Err(format!(
                "{} is not an empty or DroneDream-managed download cache; no files were changed.",
                cache_root.display()
            ));
        }
        write_cache_marker(&marker_path)?;
    }

    let artifacts = cache_root.join(ARTIFACT_DIRECTORY);
    if !artifacts.exists() {
        fs::create_dir(&artifacts).map_err(|error| {
            format!(
                "Unable to create the managed artifact directory {}: {error}",
                artifacts.display()
            )
        })?;
    }
    ensure_real_directory(&artifacts, "runtime artifact cache")?;
    validate_managed_cache(runtime_target_root)?;
    Ok(cache_root)
}

/// Applies the import result without accepting an arbitrary deletion root.
///
/// On failure every entry is retained for resume. On success only entries
/// explicitly marked `Verified` are removed. Every entry is preflighted before
/// the first deletion, and only ordinary files below the marked
/// `artifacts/` directory are accepted.
#[allow(dead_code)]
pub(crate) fn apply_runtime_import_outcome(
    runtime_target_root: &Path,
    outcome: ImportOutcome,
    artifacts: &[DownloadArtifact],
) -> Result<CacheCleanupReport, String> {
    let cache_root = validate_managed_cache(runtime_target_root)?;
    let canonical_artifact_root = fs::canonicalize(cache_root.join(ARTIFACT_DIRECTORY))
        .map_err(|error| format!("Unable to resolve the managed artifact cache: {error}"))?;

    let mut unique = BTreeMap::<PathBuf, DownloadArtifactState>::new();
    let mut spellings = BTreeSet::new();
    for artifact in artifacts {
        validate_artifact_relative_path(&artifact.relative_path)?;
        // Windows ignores case for normal installer paths. A partial and a verified
        // entry must not refer to the same file under different spellings.
        let spelling = artifact.relative_path.to_string_lossy().to_lowercase();
        if !spellings.insert(spelling)
            || unique
                .insert(artifact.relative_path.clone(), artifact.state)
                .is_some()
        {
            return Err(format!(
                "The download manifest contains the duplicate artifact {}.",
                artifact.relative_path.display()
            ));
        }
    }

    // Validate every candidate before changing anything. This prevents a bad
    // late manifest entry from producing a partially cleaned cache.
    let mut preflight = Vec::with_capacity(unique.len());
    for (relative_path, state) in unique {
        let location =
            inspect_artifact_location(&cache_root, &canonical_artifact_root, &relative_path)?;
        preflight.push((relative_path, state, location));
    }

    let mut report = CacheCleanupReport::default();
    for (relative_path, state, location) in preflight {
        match (outcome, state, location) {
            (
                ImportOutcome::Succeeded,
                DownloadArtifactState::Verified,
                ArtifactLocation::ExistingFile(path),
            ) => {
                fs::remove_file(&path).map_err(|error| {
                    format!(
                        "Unable to remove verified temporary artifact {}: {error}",
                        path.display()
                    )
                })?;
                report.removed.push(relative_path);
            }
            (
                ImportOutcome::Succeeded,
                DownloadArtifactState::Verified,
                ArtifactLocation::Missing,
            ) => {
                report.already_missing.push(relative_path);
            }
            (_, _, ArtifactLocation::Missing) => {
                report.already_missing.push(relative_path);
            }
            (_, _, ArtifactLocation::ExistingFile(_)) => {
                report.retained.push(relative_path);
            }
        }
    }
    Ok(report)
}

/// Require marker ownership, plain directories and a canonical same-parent cache.
/// The marker identifies managed data; it is not a cryptographic release signature.
pub(crate) fn validate_managed_cache(runtime_target_root: &Path) -> Result<PathBuf, String> {
    require_absolute_runtime_root(runtime_target_root)?;
    reject_existing_link_like(runtime_target_root)?;
    let cache_parent = runtime_target_root
        .parent()
        .ok_or_else(|| "The runtime target has no local parent directory.".to_string())?;
    let cache_root = runtime_download_cache_root_path(runtime_target_root);
    let artifacts = cache_root.join(ARTIFACT_DIRECTORY);

    ensure_real_directory(cache_parent, "runtime cache parent")?;
    ensure_real_directory(&cache_root, "runtime download cache")?;
    ensure_real_directory(&artifacts, "runtime artifact cache")?;
    validate_cache_marker(&cache_root.join(CACHE_MARKER))?;

    let canonical_parent = fs::canonicalize(cache_parent)
        .map_err(|error| format!("Unable to resolve the runtime target parent: {error}"))?;
    let canonical_cache = fs::canonicalize(&cache_root)
        .map_err(|error| format!("Unable to resolve the runtime download cache: {error}"))?;
    if canonical_cache.parent() != Some(canonical_parent.as_path())
        || canonical_cache.file_name() != Some(std::ffi::OsStr::new(CACHE_DIRECTORY))
    {
        return Err(
            "The runtime download cache is not the expected same-drive sibling of the runtime target."
                .to_string(),
        );
    }
    Ok(cache_root)
}

/// Walk every existing component without following links, then bind its canonical root.
/// The installer must serialize lifecycle changes; path checks are not a hostile-user sandbox.
fn inspect_artifact_location(
    cache_root: &Path,
    canonical_artifact_root: &Path,
    relative_path: &Path,
) -> Result<ArtifactLocation, String> {
    let path = cache_root.join(relative_path);
    let mut current = cache_root.to_path_buf();
    let components = relative_path.components().collect::<Vec<_>>();
    for (index, component) in components.iter().enumerate() {
        let Component::Normal(segment) = component else {
            return Err(format!("Unsafe artifact path {}.", relative_path.display()));
        };
        current.push(segment);
        match fs::symlink_metadata(&current) {
            Ok(metadata) => {
                if is_link_like(&metadata) {
                    return Err(format!(
                        "Artifact path {} crosses a symbolic link, junction, or reparse point.",
                        relative_path.display()
                    ));
                }
                let is_last = index + 1 == components.len();
                if !is_last && !metadata.is_dir() {
                    return Err(format!(
                        "Artifact path {} has a non-directory parent.",
                        relative_path.display()
                    ));
                }
                if is_last && !metadata.is_file() {
                    return Err(format!(
                        "Artifact {} is not an ordinary file.",
                        relative_path.display()
                    ));
                }
            }
            Err(error) if error.kind() == ErrorKind::NotFound => {
                return Ok(ArtifactLocation::Missing);
            }
            Err(error) => {
                return Err(format!(
                    "Unable to inspect artifact {}: {error}",
                    relative_path.display()
                ));
            }
        }
    }

    let canonical_path = fs::canonicalize(&path).map_err(|error| {
        format!(
            "Unable to resolve artifact {} before cleanup: {error}",
            relative_path.display()
        )
    })?;
    if !canonical_path.starts_with(canonical_artifact_root) {
        return Err(format!(
            "Artifact {} resolves outside the managed artifact cache.",
            relative_path.display()
        ));
    }
    Ok(ArtifactLocation::ExistingFile(path))
}

/// Restrict manifests to ordinary Windows-compatible files below artifacts/.
fn validate_artifact_relative_path(relative_path: &Path) -> Result<(), String> {
    if relative_path.as_os_str().is_empty() || relative_path.is_absolute() {
        return Err("Download artifact paths must be non-empty relative paths.".to_string());
    }
    let components = relative_path.components().collect::<Vec<_>>();
    let starts_in_artifact_directory = matches!(
        components.first(),
        Some(Component::Normal(segment)) if *segment == ARTIFACT_DIRECTORY
    );
    if components.len() < 2
        || !starts_in_artifact_directory
        || components
            .iter()
            .any(|component| !matches!(component, Component::Normal(_)))
        || components.iter().any(|component| match component {
            Component::Normal(segment) => !ordinary_segment(segment),
            _ => true,
        })
    {
        return Err(format!(
            "Artifact {} must be a relative ordinary-file path below {ARTIFACT_DIRECTORY}/.",
            relative_path.display()
        ));
    }
    Ok(())
}

/// Reject alternate streams, Win32 device aliases and lossy/trailing path spellings.
fn ordinary_segment(segment: &std::ffi::OsStr) -> bool {
    let Some(name) = segment.to_str() else {
        return false;
    };
    if name.ends_with(['.', ' '])
        || name
            .chars()
            .any(|ch| ch.is_control() || "<>:\"|?*".contains(ch))
    {
        return false;
    }
    let stem = name
        .split('.')
        .next()
        .unwrap_or("")
        .trim_end()
        .to_uppercase();
    !matches!(
        stem.as_str(),
        "CON" | "PRN" | "AUX" | "NUL" | "CONIN$" | "CONOUT$"
    ) && !["COM", "LPT"].iter().any(|prefix| {
        stem.strip_prefix(prefix).is_some_and(|suffix| {
            matches!(
                suffix,
                "1" | "2" | "3" | "4" | "5" | "6" | "7" | "8" | "9" | "¹" | "²" | "³"
            )
        })
    })
}

/// Only the dedicated absolute import directory may determine a sibling cleanup root.
fn require_absolute_runtime_root(runtime_target_root: &Path) -> Result<(), String> {
    if !runtime_target_root.is_absolute() {
        return Err("The managed runtime target must be an absolute path.".to_string());
    }
    if runtime_target_root.file_name() != Some(std::ffi::OsStr::new("DroneDream")) {
        return Err(
            "The managed runtime target must end in the dedicated DroneDream folder.".to_string(),
        );
    }
    Ok(())
}

/// Permit a not-yet-created path, but never reinterpret a link as owned storage.
fn reject_existing_link_like(path: &Path) -> Result<(), String> {
    match fs::symlink_metadata(path) {
        Ok(metadata) if is_link_like(&metadata) => Err(format!(
            "{} is a symbolic link, junction, or reparse point.",
            path.display()
        )),
        Ok(_) => Ok(()),
        Err(error) if error.kind() == ErrorKind::NotFound => Ok(()),
        Err(error) => Err(format!("Unable to inspect {}: {error}", path.display())),
    }
}

/// Existing cache directories must be ordinary filesystem directories.
fn ensure_real_directory(path: &Path, label: &str) -> Result<(), String> {
    let metadata = fs::symlink_metadata(path)
        .map_err(|error| format!("Unable to inspect {label} {}: {error}", path.display()))?;
    if !metadata.is_dir() || is_link_like(&metadata) {
        return Err(format!(
            "The {label} {} must be a real directory, not a file, link, junction, or reparse point.",
            path.display()
        ));
    }
    Ok(())
}

#[cfg(target_os = "windows")]
/// Junctions and other reparse points need the Windows attribute check as well.
pub(crate) fn is_link_like(metadata: &fs::Metadata) -> bool {
    use std::os::windows::fs::MetadataExt;
    const FILE_ATTRIBUTE_REPARSE_POINT: u32 = 0x0400;
    metadata.file_type().is_symlink()
        || metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0
}

#[cfg(not(target_os = "windows"))]
/// Non-Windows fixtures have no Win32 reparse-point attribute.
pub(crate) fn is_link_like(metadata: &fs::Metadata) -> bool {
    metadata.file_type().is_symlink()
}

/// Claim only a new empty cache; create_new must not overwrite somebody else's marker.
fn write_cache_marker(marker_path: &Path) -> Result<(), String> {
    let marker = CacheMarker {
        schema_version: 1,
        owner: CACHE_MARKER_OWNER.to_string(),
        runtime_name: RUNTIME_NAME.to_string(),
    };
    let encoded = serde_json::to_vec(&marker)
        .map_err(|error| format!("Unable to encode the download-cache marker: {error}"))?;
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(marker_path)
        .map_err(|error| {
            format!(
                "Unable to create the download-cache marker {}: {error}",
                marker_path.display()
            )
        })?;
    file.write_all(&encoded)
        .and_then(|()| file.sync_all())
        .map_err(|error| format!("Unable to persist the download-cache marker: {error}"))
}

/// Bound the actual read, not only an earlier stat, before interpreting ownership.
fn validate_cache_marker(marker_path: &Path) -> Result<(), String> {
    let metadata = fs::symlink_metadata(marker_path).map_err(|error| {
        format!(
            "The runtime download cache is not managed: marker {} cannot be read: {error}",
            marker_path.display()
        )
    })?;
    if !metadata.is_file() || is_link_like(&metadata) || metadata.len() > MAX_MARKER_BYTES {
        return Err("The runtime download-cache marker is not a safe ordinary file.".to_string());
    }
    let mut options = OpenOptions::new();
    options.read(true);
    #[cfg(windows)]
    {
        use std::os::windows::fs::OpenOptionsExt;
        options.custom_flags(windows_sys::Win32::Storage::FileSystem::FILE_FLAG_OPEN_REPARSE_POINT);
    }
    let file = options
        .open(marker_path)
        .map_err(|error| format!("Unable to read the download-cache marker: {error}"))?;
    let opened = file
        .metadata()
        .map_err(|_| "Unable to inspect the opened download-cache marker.".to_string())?;
    if !opened.is_file() || is_link_like(&opened) || opened.len() > MAX_MARKER_BYTES {
        return Err("The runtime download-cache marker is not a safe ordinary file.".to_string());
    }
    let mut raw = Vec::new();
    file.take(MAX_MARKER_BYTES + 1)
        .read_to_end(&mut raw)
        .map_err(|_| "Unable to read the download-cache marker.".to_string())?;
    if raw.len() as u64 > MAX_MARKER_BYTES {
        return Err("The runtime download-cache marker is too large.".to_string());
    }
    let marker: CacheMarker = serde_json::from_slice(&raw)
        .map_err(|error| format!("The download-cache marker is invalid JSON: {error}"))?;
    if marker.schema_version != 1
        || marker.owner != CACHE_MARKER_OWNER
        || marker.runtime_name != RUNTIME_NAME
    {
        return Err(
            "The download-cache marker is not owned by this DroneDream runtime.".to_string(),
        );
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::{SystemTime, UNIX_EPOCH};

    struct Sandbox(PathBuf);

    impl Sandbox {
        /// Each test owns one unique root, never an installed runtime/cache location.
        fn new() -> Self {
            let root = std::env::temp_dir().join(format!(
                "dronedream-runtime-cache-{}-{}",
                std::process::id(),
                SystemTime::now()
                    .duration_since(UNIX_EPOCH)
                    .expect("system clock")
                    .as_nanos()
            ));
            fs::create_dir(&root).expect("create sandbox");
            Self(root)
        }

        fn runtime_root(&self) -> PathBuf {
            self.0.join("DroneDream")
        }
    }

    impl Drop for Sandbox {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }

    /// Synthetic cache bytes exercise cleanup without downloading or importing WSL.
    fn write_artifact(runtime_root: &Path, relative: &Path, body: &[u8]) -> PathBuf {
        let cache_root = runtime_download_cache_root_path(runtime_root);
        let path = cache_root.join(relative);
        fs::create_dir_all(path.parent().expect("artifact parent")).expect("create parent");
        fs::write(&path, body).expect("write artifact");
        path
    }

    #[test]
    fn successful_import_removes_only_verified_temporary_files() {
        let sandbox = Sandbox::new();
        let runtime_root = sandbox.runtime_root();
        initialize_runtime_download_cache(&runtime_root).unwrap();
        assert!(
            !runtime_root.exists(),
            "download cache initialization must not pollute the WSL import target"
        );
        assert_eq!(
            runtime_download_cache_root_path(&runtime_root),
            sandbox.0.join(CACHE_DIRECTORY)
        );
        let archive = PathBuf::from(ARTIFACT_DIRECTORY).join("runtime.tar.zst");
        let verified_part = PathBuf::from(ARTIFACT_DIRECTORY).join("runtime.part.001");
        let resumable_part = PathBuf::from(ARTIFACT_DIRECTORY).join("runtime.part.002");
        let archive_path = write_artifact(&runtime_root, &archive, b"archive");
        let verified_part_path = write_artifact(&runtime_root, &verified_part, b"part-one");
        let resumable_part_path = write_artifact(&runtime_root, &resumable_part, b"part-two");

        let report = apply_runtime_import_outcome(
            &runtime_root,
            ImportOutcome::Succeeded,
            &[
                DownloadArtifact::verified(&archive),
                DownloadArtifact::verified(&verified_part),
                DownloadArtifact::partial(&resumable_part),
            ],
        )
        .unwrap();

        assert_eq!(report.removed, vec![verified_part, archive]);
        assert_eq!(report.retained, vec![resumable_part]);
        assert!(!archive_path.exists());
        assert!(!verified_part_path.exists());
        assert!(resumable_part_path.exists());
        assert!(runtime_download_cache_root_path(&runtime_root)
            .join(CACHE_MARKER)
            .exists());
    }

    #[test]
    fn failed_import_retains_verified_and_partial_resume_data() {
        let sandbox = Sandbox::new();
        let runtime_root = sandbox.runtime_root();
        initialize_runtime_download_cache(&runtime_root).unwrap();
        let archive = PathBuf::from(ARTIFACT_DIRECTORY).join("runtime.tar.zst");
        let part = PathBuf::from(ARTIFACT_DIRECTORY).join("runtime.part");
        let archive_path = write_artifact(&runtime_root, &archive, b"archive");
        let part_path = write_artifact(&runtime_root, &part, b"partial");

        let report = apply_runtime_import_outcome(
            &runtime_root,
            ImportOutcome::Failed,
            &[
                DownloadArtifact::verified(&archive),
                DownloadArtifact::partial(&part),
            ],
        )
        .unwrap();

        assert!(report.removed.is_empty());
        assert_eq!(report.retained, vec![part, archive]);
        assert!(archive_path.exists());
        assert!(part_path.exists());
    }

    #[test]
    fn rejects_escape_paths_before_deleting_any_valid_artifact() {
        let sandbox = Sandbox::new();
        let runtime_root = sandbox.runtime_root();
        initialize_runtime_download_cache(&runtime_root).unwrap();
        let valid = PathBuf::from(ARTIFACT_DIRECTORY).join("runtime.tar.zst");
        let valid_path = write_artifact(&runtime_root, &valid, b"archive");
        let outside = sandbox.0.join("do-not-delete.txt");
        fs::write(&outside, b"user data").unwrap();

        let error = apply_runtime_import_outcome(
            &runtime_root,
            ImportOutcome::Succeeded,
            &[
                DownloadArtifact::verified(&valid),
                DownloadArtifact::verified(PathBuf::from(ARTIFACT_DIRECTORY).join("..")),
            ],
        )
        .unwrap_err();

        assert!(error.contains("must be a relative ordinary-file path"));
        assert!(valid_path.exists(), "preflight must happen before deletion");
        assert!(outside.exists(), "cleanup escaped its managed cache root");
    }

    #[test]
    fn refuses_an_unmarked_or_duplicate_artifact_manifest() {
        let sandbox = Sandbox::new();
        let runtime_root = sandbox.runtime_root();
        let artifacts = runtime_download_cache_root_path(&runtime_root).join(ARTIFACT_DIRECTORY);
        fs::create_dir_all(&artifacts).unwrap();
        let artifact = PathBuf::from(ARTIFACT_DIRECTORY).join("runtime.tar.zst");
        fs::write(artifacts.join("runtime.tar.zst"), b"archive").unwrap();

        let error = apply_runtime_import_outcome(
            &runtime_root,
            ImportOutcome::Succeeded,
            &[DownloadArtifact::verified(&artifact)],
        )
        .unwrap_err();
        assert!(error.contains("not managed"));

        fs::remove_dir_all(runtime_download_cache_root_path(&runtime_root)).unwrap();
        initialize_runtime_download_cache(&runtime_root).unwrap();
        write_artifact(&runtime_root, &artifact, b"archive");
        let duplicate_error = apply_runtime_import_outcome(
            &runtime_root,
            ImportOutcome::Succeeded,
            &[
                DownloadArtifact::verified(&artifact),
                DownloadArtifact::verified(&artifact),
            ],
        )
        .unwrap_err();
        assert!(duplicate_error.contains("duplicate artifact"));
        assert!(runtime_download_cache_root_path(&runtime_root)
            .join(&artifact)
            .exists());
    }

    #[test]
    fn rejects_windows_stream_and_alias_names() {
        for path in [
            "artifacts/runtime.tar:secret",
            "artifacts/runtime.tar.",
            "artifacts/runtime.tar ",
            "artifacts/CON",
            "artifacts/NUL.zip",
        ] {
            assert!(
                validate_artifact_relative_path(Path::new(path)).is_err(),
                "unsafe cache path accepted: {path}"
            );
        }
    }

    #[cfg(windows)]
    #[test]
    fn case_aliases_cannot_delete_a_partial_artifact() {
        let sandbox = Sandbox::new();
        let runtime_root = sandbox.runtime_root();
        initialize_runtime_download_cache(&runtime_root).unwrap();
        let relative = Path::new("artifacts/runtime.tar.zst");
        let file = write_artifact(&runtime_root, relative, b"resumable");
        let result = apply_runtime_import_outcome(
            &runtime_root,
            ImportOutcome::Succeeded,
            &[
                DownloadArtifact::verified(relative),
                DownloadArtifact::partial("artifacts/RUNTIME.TAR.ZST"),
            ],
        );
        assert!(
            result.is_err(),
            "two spellings must not assign conflicting states to one file"
        );
        assert!(file.exists(), "reject aliases before deleting anything");
    }
}
