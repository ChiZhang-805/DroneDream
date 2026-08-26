//! Same-display-version updater ordering for the 1.0.0 internal-test channel.

const BUILD_NUMBER_PREFIX: &str = "build-number: ";
const EDITION_ID_PREFIX: &str = "edition-id: ";
const SOURCE_COMMIT_PREFIX: &str = "source-commit: ";
const COMPILED_EDITION_ID: &str = env!("DRONEDREAM_DESKTOP_EDITION_ID");

fn local_build_number() -> Option<u64> {
    env!("DRONEDREAM_BUILD_NUMBER").parse().ok()
}

fn is_lower_hex(value: &str, length: usize) -> bool {
    value.len() == length
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn release_identity(notes: Option<&str>) -> Option<(&str, u64, &str)> {
    let notes = notes?;
    let mut edition_id = None;
    let mut build_number = None;
    let mut source_commit = None;
    for line in notes.lines() {
        if let Some(value) = line.strip_prefix(EDITION_ID_PREFIX) {
            if edition_id.is_some()
                || !matches!(value, "universal" | "sim" | "lab" | "field" | "autonomy")
            {
                return None;
            }
            edition_id = Some(value);
        }
        if let Some(value) = line.strip_prefix(BUILD_NUMBER_PREFIX) {
            if build_number.is_some() || value.trim() != value {
                return None;
            }
            build_number = value.parse::<u64>().ok().filter(|number| *number > 0);
        }
        if let Some(value) = line.strip_prefix(SOURCE_COMMIT_PREFIX) {
            if source_commit.is_some() || !is_lower_hex(value, 40) {
                return None;
            }
            source_commit = Some(value);
        }
    }
    Some((edition_id?, build_number?, source_commit?))
}

pub(crate) fn release_matches_compiled_edition(notes: Option<&str>) -> bool {
    release_identity(notes).is_some_and(|(edition_id, _, _)| edition_id == COMPILED_EDITION_ID)
}

pub(crate) fn newer_equal_version_release(notes: Option<&str>) -> bool {
    let Some((edition_id, remote_build_number, remote_source_commit)) = release_identity(notes)
    else {
        return false;
    };
    if edition_id != COMPILED_EDITION_ID {
        return false;
    }
    let Some(local_build_number) = local_build_number() else {
        return false;
    };
    remote_build_number > local_build_number
        && remote_source_commit != env!("DRONEDREAM_SOURCE_COMMIT")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn equal_display_version_requires_a_strictly_newer_authenticated_identity() {
        let local = local_build_number().expect("local build number");
        assert!(!newer_equal_version_release(Some(&format!(
            "DroneDream 1.0.0 for Windows x64.\nedition-id: {COMPILED_EDITION_ID}\nbuild-number: {local}\nsource-commit: {}",
            "1".repeat(40)
        ))));
        assert!(newer_equal_version_release(Some(&format!(
            "DroneDream 1.0.0 for Windows x64.\nedition-id: {COMPILED_EDITION_ID}\nbuild-number: {}\nsource-commit: {}",
            local + 1,
            "1".repeat(40)
        ))));
    }

    #[test]
    fn malformed_or_replayed_metadata_fails_closed() {
        let local = local_build_number().expect("local build number");
        for notes in [
            None,
            Some("build-number: nope\nsource-commit: 123"),
            Some("edition-id: unknown\nbuild-number: 2\nsource-commit: 1111111111111111111111111111111111111111"),
            Some("edition-id: sim\nedition-id: sim\nbuild-number: 2\nsource-commit: 1111111111111111111111111111111111111111"),
            Some("build-number: 999999999999999999999999999999999999999"),
            Some("build-number: 2\nbuild-number: 3\nsource-commit: 1111111111111111111111111111111111111111"),
        ] {
            assert!(!newer_equal_version_release(notes));
        }
        assert!(!newer_equal_version_release(Some(&format!(
            "edition-id: {COMPILED_EDITION_ID}\nbuild-number: {}\nsource-commit: {}",
            local + 1,
            env!("DRONEDREAM_SOURCE_COMMIT")
        ))));
        let wrong_edition = match COMPILED_EDITION_ID {
            "sim" => "lab",
            _ => "sim",
        };
        let cross_edition = format!(
            "edition-id: {wrong_edition}\nbuild-number: {}\nsource-commit: {}",
            local + 1,
            "1".repeat(40)
        );
        assert!(!release_matches_compiled_edition(Some(&cross_edition)));
        assert!(!newer_equal_version_release(Some(&cross_edition)));
    }
}
