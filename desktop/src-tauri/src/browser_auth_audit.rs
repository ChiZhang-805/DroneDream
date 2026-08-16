use chrono::{DateTime, Utc};
use serde::Serialize;
use std::{
    fs::{self, OpenOptions},
    io::Write,
    path::{Path, PathBuf},
    sync::{Mutex, OnceLock},
};

const RECEIPT_KIND: &str = "dronedream-desktop-browser-auth-attempt";
const RECEIPT_VERSION: u8 = 1;
const CONTRACT_VERSION: &str = "1.0.0";
const MAX_DAILY_AUDIT_BYTES: u64 = 8 * 1024 * 1024;
const HASH_BYTES: usize = 64;

static APPEND_LOCK: OnceLock<Mutex<()>> = OnceLock::new();

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct BrowserAuthAuditReceipt<'a> {
    kind: &'static str,
    receipt_version: u8,
    contract_version: &'static str,
    edition_id: &'a str,
    auth_client_id: &'a str,
    attempt_id_hash: &'a str,
    state_hash: &'a str,
    subject_hash: Option<&'a str>,
    result: &'a str,
    failure_code: Option<&'a str>,
    issued_at: &'a str,
    completed_at: &'a str,
    callback_transport: &'a str,
    broker_origin: &'static str,
}

impl<'a> BrowserAuthAuditReceipt<'a> {
    #[allow(clippy::too_many_arguments)]
    pub(crate) fn new(
        edition_id: &'a str,
        auth_client_id: &'a str,
        attempt_id_hash: &'a str,
        state_hash: &'a str,
        subject_hash: Option<&'a str>,
        result: &'a str,
        failure_code: Option<&'a str>,
        issued_at: &'a str,
        completed_at: &'a str,
        callback_transport: &'a str,
    ) -> Self {
        Self {
            kind: RECEIPT_KIND,
            receipt_version: RECEIPT_VERSION,
            contract_version: CONTRACT_VERSION,
            edition_id,
            auth_client_id,
            attempt_id_hash,
            state_hash,
            subject_hash,
            result,
            failure_code,
            issued_at,
            completed_at,
            callback_transport,
            broker_origin: "https://yggabfynndpzymlqvnim.supabase.co",
        }
    }
}

fn valid_hash(value: &str) -> bool {
    value.len() == HASH_BYTES
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn valid_code(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit() || byte == b'_')
}

fn validate_receipt(receipt: &BrowserAuthAuditReceipt<'_>) -> Result<DateTime<Utc>, String> {
    if !["universal", "sim", "lab", "field"].contains(&receipt.edition_id)
        || receipt.auth_client_id != format!("dronedream-desktop-{}", receipt.edition_id)
    {
        return Err("The desktop authentication audit identity is invalid.".to_owned());
    }
    if !valid_hash(receipt.attempt_id_hash)
        || !valid_hash(receipt.state_hash)
        || receipt.subject_hash.is_some_and(|value| !valid_hash(value))
        || !valid_code(receipt.result)
        || receipt.failure_code.is_some_and(|value| !valid_code(value))
    {
        return Err("The desktop authentication audit fields are invalid.".to_owned());
    }
    if !["loopback-http", "credential-vault", "native-command"]
        .contains(&receipt.callback_transport)
    {
        return Err("The desktop authentication audit transport is invalid.".to_owned());
    }
    let issued = DateTime::parse_from_rfc3339(receipt.issued_at)
        .map_err(|_| "The desktop authentication audit issue time is invalid.".to_owned())?
        .with_timezone(&Utc);
    let completed = DateTime::parse_from_rfc3339(receipt.completed_at)
        .map_err(|_| "The desktop authentication audit completion time is invalid.".to_owned())?
        .with_timezone(&Utc);
    if completed < issued {
        return Err("The desktop authentication audit time order is invalid.".to_owned());
    }
    Ok(completed)
}

fn edition_directory(base: &Path, edition_id: &str) -> PathBuf {
    base.join(format!("io.dronedream.desktop.{edition_id}"))
        .join("audit")
        .join("browser-auth")
}

fn ensure_plain_path(path: &Path, label: &str) -> Result<(), String> {
    match fs::symlink_metadata(path) {
        Ok(metadata) if metadata.file_type().is_symlink() => Err(format!(
            "The desktop authentication {label} cannot be a link."
        )),
        Ok(metadata) if label == "audit file" && !metadata.is_file() => {
            Err("The desktop authentication audit target is not a file.".to_owned())
        }
        Ok(metadata) if label != "audit file" && !metadata.is_dir() => {
            Err("The desktop authentication audit directory is invalid.".to_owned())
        }
        Ok(_) => Ok(()),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(_) => Err(format!(
            "The desktop authentication {label} is unavailable."
        )),
    }
}

fn append_at(base: &Path, receipt: &BrowserAuthAuditReceipt<'_>) -> Result<PathBuf, String> {
    let completed = validate_receipt(receipt)?;
    ensure_plain_path(base, "audit root")?;
    let directory = edition_directory(base, receipt.edition_id);
    fs::create_dir_all(&directory).map_err(|_| {
        "The desktop authentication audit directory could not be created.".to_owned()
    })?;
    ensure_plain_path(&directory, "audit directory")?;
    let path = directory.join(format!(
        "browser-auth-attempts-{}.v1.jsonl",
        completed.format("%Y-%m-%d")
    ));
    ensure_plain_path(&path, "audit file")?;
    let mut encoded = serde_json::to_vec(receipt)
        .map_err(|_| "The desktop authentication audit receipt is invalid.".to_owned())?;
    encoded.push(b'\n');
    let _guard = APPEND_LOCK
        .get_or_init(|| Mutex::new(()))
        .lock()
        .map_err(|_| "The desktop authentication audit lock is unavailable.".to_owned())?;
    let existing_bytes = fs::metadata(&path).map(|value| value.len()).unwrap_or(0);
    if existing_bytes.saturating_add(encoded.len() as u64) > MAX_DAILY_AUDIT_BYTES {
        return Err("The daily desktop authentication audit file is full.".to_owned());
    }
    let mut file = OpenOptions::new()
        .create(true)
        .append(true)
        .open(&path)
        .map_err(|_| "The desktop authentication audit file could not be opened.".to_owned())?;
    file.write_all(&encoded)
        .and_then(|()| file.sync_data())
        .map_err(|_| {
            "The desktop authentication audit receipt could not be persisted.".to_owned()
        })?;
    Ok(path)
}

pub(crate) fn append_browser_auth_audit(
    receipt: &BrowserAuthAuditReceipt<'_>,
) -> Result<(), String> {
    let base = std::env::var_os("LOCALAPPDATA")
        .filter(|value| !value.is_empty())
        .map(PathBuf::from)
        .ok_or_else(|| {
            "LOCALAPPDATA is unavailable for desktop authentication audit.".to_owned()
        })?;
    append_at(&base, receipt).map(|_| ())
}

#[cfg(test)]
mod tests {
    use super::*;

    const ATTEMPT_HASH: &str = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
    const STATE_HASH: &str = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
    const SUBJECT_HASH: &str = "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc";
    const UNIVERSAL_ATTEMPT_HASH: &str =
        "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd";
    const UNIVERSAL_STATE_HASH: &str =
        "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee";

    fn receipt<'a>(result: &'a str, failure_code: Option<&'a str>) -> BrowserAuthAuditReceipt<'a> {
        BrowserAuthAuditReceipt::new(
            "sim",
            "dronedream-desktop-sim",
            ATTEMPT_HASH,
            STATE_HASH,
            Some(SUBJECT_HASH),
            result,
            failure_code,
            "2026-08-05T04:00:00Z",
            "2026-08-05T04:00:01Z",
            "loopback-http",
        )
    }

    #[test]
    fn receipt_has_only_allowlisted_fields_and_no_sensitive_values() {
        let value = serde_json::to_value(receipt("authorized", None)).unwrap();
        let keys = value
            .as_object()
            .unwrap()
            .keys()
            .cloned()
            .collect::<Vec<_>>();
        assert_eq!(
            keys,
            [
                "attemptIdHash",
                "authClientId",
                "brokerOrigin",
                "callbackTransport",
                "completedAt",
                "contractVersion",
                "editionId",
                "failureCode",
                "issuedAt",
                "kind",
                "receiptVersion",
                "result",
                "stateHash",
                "subjectHash",
            ]
        );
        let serialized = serde_json::to_string(&value).unwrap().to_lowercase();
        for forbidden in [
            "accesstoken",
            "refreshtoken",
            "password",
            "cookie",
            "rawcallback",
            "providerrequestid",
        ] {
            assert!(!serialized.contains(forbidden));
        }
    }

    #[test]
    fn appends_without_rewriting_prior_receipts_and_isolates_editions() {
        let root =
            std::env::temp_dir().join(format!("dronedream-auth-audit-{}", uuid::Uuid::new_v4()));
        fs::create_dir(&root).unwrap();
        let first_path = append_at(&root, &receipt("authorized", None)).unwrap();
        let first_bytes = fs::read(&first_path).unwrap();
        append_at(&root, &receipt("denied", Some("user_denied"))).unwrap();
        let all_bytes = fs::read(&first_path).unwrap();
        assert!(all_bytes.starts_with(&first_bytes));
        assert_eq!(all_bytes.iter().filter(|byte| **byte == b'\n').count(), 2);

        let universal = BrowserAuthAuditReceipt::new(
            "universal",
            "dronedream-desktop-universal",
            UNIVERSAL_ATTEMPT_HASH,
            UNIVERSAL_STATE_HASH,
            None,
            "no_saved_session",
            None,
            "2026-08-05T04:00:00Z",
            "2026-08-05T04:00:01Z",
            "credential-vault",
        );
        let other_path = append_at(&root, &universal).unwrap();
        assert_ne!(first_path.parent(), other_path.parent());
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn daily_cap_fails_closed_without_appending_partial_receipt() {
        let root =
            std::env::temp_dir().join(format!("dronedream-auth-audit-{}", uuid::Uuid::new_v4()));
        fs::create_dir(&root).unwrap();
        let directory = edition_directory(&root, "sim");
        fs::create_dir_all(&directory).unwrap();
        let path = directory.join("browser-auth-attempts-2026-08-05.v1.jsonl");
        let file = OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(&path)
            .unwrap();
        file.set_len(MAX_DAILY_AUDIT_BYTES).unwrap();
        drop(file);

        let error = append_at(&root, &receipt("authorized", None)).unwrap_err();
        assert!(error.contains("audit file is full"));
        assert_eq!(fs::metadata(&path).unwrap().len(), MAX_DAILY_AUDIT_BYTES);
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn invalid_identity_hash_time_transport_and_codes_fail_closed() {
        let mut invalid = receipt("authorized", None);
        invalid.auth_client_id = "dronedream-desktop-lab";
        assert!(validate_receipt(&invalid).is_err());
        let mut invalid = receipt("authorized", None);
        invalid.state_hash = "not-a-hash";
        assert!(validate_receipt(&invalid).is_err());
        let mut invalid = receipt("authorized", None);
        invalid.completed_at = "2026-08-05T03:59:59Z";
        assert!(validate_receipt(&invalid).is_err());
        let mut invalid = receipt("contains-hyphen", None);
        assert!(validate_receipt(&invalid).is_err());
        invalid.result = "authorized";
        invalid.callback_transport = "raw-token-loopback";
        assert!(validate_receipt(&invalid).is_err());
    }
}
