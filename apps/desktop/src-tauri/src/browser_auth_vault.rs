//! Edition-scoped OS secrets. Network refresh must commit against the generation
//! it read, so a late response cannot undo logout or replace a newer account.
use std::{collections::HashMap, fmt, sync::Mutex};

const CURRENT_SESSION_KEY: &str = "current";
const MAX_CREDENTIAL_BYTES: usize = 2_560;

#[derive(Clone, Eq, PartialEq)]
pub(crate) struct StoredBrowserAuthSession {
    pub subject_hash: String,
    pub refresh_token: String,
}

impl fmt::Debug for StoredBrowserAuthSession {
    /// Diagnostics must never serialize the recoverable refresh credential.
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("StoredBrowserAuthSession")
            .field("subject_hash", &self.subject_hash)
            .field("refresh_token", &"[redacted]")
            .finish()
    }
}

/// Process-local compare-and-swap ticket; not a session secret or server grant.
#[derive(Clone, Debug)]
pub(crate) struct VaultRevision {
    namespace: String,
    generation: u64,
}

struct CredentialVault<B> {
    backend: B,
    generations: Mutex<HashMap<String, u64>>,
}

impl<B: CredentialBackend> CredentialVault<B> {
    /// A backend plus one lock owns every pointer/secret mutation in this process.
    fn new(backend: B) -> Self {
        Self {
            backend,
            generations: Mutex::new(HashMap::new()),
        }
    }

    /// Snapshot before asynchronous authorization; do not hold a lock over HTTP.
    fn revision(&self, namespace: &str) -> Result<VaultRevision, String> {
        validate_namespace(namespace)?;
        let state = self
            .generations
            .lock()
            .map_err(|_| "The desktop credential lock is unavailable.")?;
        Ok(VaultRevision {
            namespace: namespace.into(),
            generation: *state.get(namespace).unwrap_or(&0),
        })
    }

    /// Read the pointer and secret together with the generation they came from.
    fn load(
        &self,
        namespace: &str,
    ) -> Result<Option<(StoredBrowserAuthSession, VaultRevision)>, String> {
        validate_namespace(namespace)?;
        let state = self
            .generations
            .lock()
            .map_err(|_| "The desktop credential lock is unavailable.")?;
        Ok(load_with(&self.backend, namespace)?.map(|session| {
            (
                session,
                VaultRevision {
                    namespace: namespace.into(),
                    generation: *state.get(namespace).unwrap_or(&0),
                },
            )
        }))
    }

    /// Commit only if no store/logout has superseded the asynchronous operation.
    fn store(
        &self,
        expected: &VaultRevision,
        subject_hash: &str,
        refresh_token: &str,
    ) -> Result<VaultRevision, String> {
        validate_namespace(&expected.namespace)?;
        validate_subject_hash(subject_hash)?;
        validate_refresh_token(refresh_token)?;
        let mut state = self
            .generations
            .lock()
            .map_err(|_| "The desktop credential lock is unavailable.")?;
        let generation = state.entry(expected.namespace.clone()).or_default();
        if *generation != expected.generation {
            return Err("The desktop authentication session changed during sign-in.".into());
        }
        // Invalidate old tickets even when an OS write fails partway through.
        *generation = generation
            .checked_add(1)
            .ok_or("The desktop credential generation is exhausted.")?;
        store_with(
            &self.backend,
            &expected.namespace,
            subject_hash,
            refresh_token,
        )?;
        Ok(VaultRevision {
            namespace: expected.namespace.clone(),
            generation: *generation,
        })
    }

    /// Explicit logout always advances; stale failure cleanup is a no-op instead.
    fn clear(&self, namespace: &str, expected: Option<&VaultRevision>) -> Result<bool, String> {
        validate_namespace(namespace)?;
        let mut state = self
            .generations
            .lock()
            .map_err(|_| "The desktop credential lock is unavailable.")?;
        let generation = state.entry(namespace.into()).or_default();
        if expected
            .is_some_and(|ticket| ticket.namespace != namespace || ticket.generation != *generation)
        {
            return Ok(false);
        }
        *generation = generation
            .checked_add(1)
            .ok_or("The desktop credential generation is exhausted.")?;
        clear_with(&self.backend, namespace)
    }
}

trait CredentialBackend {
    fn write(&self, target: &str, user_name: &str, value: &[u8]) -> Result<(), String>;
    fn read(&self, target: &str) -> Result<Option<Vec<u8>>, String>;
    fn delete(&self, target: &str) -> Result<bool, String>;
}

/// Separate the active account pointer from its recoverable refresh credential.
fn current_target(namespace: &str) -> String {
    format!("{namespace}/{CURRENT_SESSION_KEY}")
}

/// Account records are keyed by an already validated hash, never raw email.
fn account_target(namespace: &str, subject_hash: &str) -> String {
    format!("{namespace}/{subject_hash}")
}

/// Only the five compiled product identities may own a credential namespace.
fn validate_namespace(namespace: &str) -> Result<(), String> {
    if !["universal", "sim", "lab", "field", "autonomy"]
        .iter()
        .any(|edition| namespace == format!("DroneDream/Auth/{edition}/v1"))
    {
        return Err("The desktop credential namespace is invalid.".to_owned());
    }
    Ok(())
}

/// Reject ambiguous or path-like account identifiers at the vault boundary.
fn validate_subject_hash(subject_hash: &str) -> Result<(), String> {
    if subject_hash.len() != 64
        || !subject_hash
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err("The desktop account subject binding is invalid.".to_owned());
    }
    Ok(())
}

/// Enforce the OS blob limit and the printable, whitespace-free token contract.
fn validate_refresh_token(refresh_token: &str) -> Result<(), String> {
    if refresh_token.is_empty()
        || refresh_token.len() > MAX_CREDENTIAL_BYTES
        || !refresh_token
            .bytes()
            .all(|byte| (0x21..=0x7e).contains(&byte))
    {
        return Err("The desktop refresh token cannot be stored safely.".to_owned());
    }
    Ok(())
}

/// Error messages describe the field, never the corrupt credential bytes.
fn decode_utf8(value: Vec<u8>, label: &str) -> Result<String, String> {
    String::from_utf8(value).map_err(|_| format!("The stored desktop {label} is invalid."))
}

/// Publish the secret before the pointer; roll back a newly orphaned secret.
/// Caller serializes the multi-record operation, since the OS has no transaction here.
fn store_with<B: CredentialBackend>(
    backend: &B,
    namespace: &str,
    subject_hash: &str,
    refresh_token: &str,
) -> Result<(), String> {
    validate_namespace(namespace)?;
    validate_subject_hash(subject_hash)?;
    validate_refresh_token(refresh_token)?;
    let pointer_target = current_target(namespace);
    let previous_subject = match backend.read(&pointer_target)? {
        Some(value) => match decode_utf8(value, "account pointer")
            .and_then(|subject| validate_subject_hash(&subject).map(|()| subject))
        {
            Ok(subject) => Some(subject),
            Err(_) => {
                backend.delete(&pointer_target)?;
                None
            }
        },
        None => None,
    };

    let new_account_target = account_target(namespace, subject_hash);
    backend.write(&new_account_target, subject_hash, refresh_token.as_bytes())?;
    if previous_subject.as_deref() != Some(subject_hash) {
        if let Err(error) = backend.write(&pointer_target, subject_hash, subject_hash.as_bytes()) {
            let _ = backend.delete(&new_account_target);
            return Err(error);
        }
    }
    if let Some(previous) = previous_subject {
        if previous != subject_hash {
            let _ = backend.delete(&account_target(namespace, &previous));
        }
    }
    Ok(())
}

/// Remove corrupt pointers/secrets rather than returning a partially valid session.
fn load_with<B: CredentialBackend>(
    backend: &B,
    namespace: &str,
) -> Result<Option<StoredBrowserAuthSession>, String> {
    validate_namespace(namespace)?;
    let Some(pointer) = backend.read(&current_target(namespace))? else {
        return Ok(None);
    };
    let subject_hash = match decode_utf8(pointer, "account pointer")
        .and_then(|subject| validate_subject_hash(&subject).map(|()| subject))
    {
        Ok(subject) => subject,
        Err(_) => {
            backend.delete(&current_target(namespace))?;
            return Ok(None);
        }
    };
    let target = account_target(namespace, &subject_hash);
    let Some(token) = backend.read(&target)? else {
        backend.delete(&current_target(namespace))?;
        return Ok(None);
    };
    let refresh_token = match decode_utf8(token, "refresh token")
        .and_then(|token| validate_refresh_token(&token).map(|()| token))
    {
        Ok(token) => token,
        Err(_) => {
            backend.delete(&target)?;
            backend.delete(&current_target(namespace))?;
            return Ok(None);
        }
    };
    Ok(Some(StoredBrowserAuthSession {
        subject_hash,
        refresh_token,
    }))
}

/// Clear only this edition's active account; do not enumerate unrelated OS secrets.
fn clear_with<B: CredentialBackend>(backend: &B, namespace: &str) -> Result<bool, String> {
    validate_namespace(namespace)?;
    let pointer_target = current_target(namespace);
    let Some(pointer) = backend.read(&pointer_target)? else {
        return Ok(false);
    };
    let subject_hash = match decode_utf8(pointer, "account pointer")
        .and_then(|subject| validate_subject_hash(&subject).map(|()| subject))
    {
        Ok(subject) => subject,
        Err(_) => return backend.delete(&pointer_target),
    };
    let deleted_account = backend.delete(&account_target(namespace, &subject_hash))?;
    let deleted_pointer = backend.delete(&pointer_target)?;
    Ok(deleted_account || deleted_pointer)
}

#[cfg(windows)]
struct WindowsCredentialBackend;

#[cfg(windows)]
impl WindowsCredentialBackend {
    /// Arguments are validated before encoding; the trailing NUL is for Win32 only.
    fn wide(value: &str) -> Vec<u16> {
        value.encode_utf16().chain(std::iter::once(0)).collect()
    }

    /// Keep the OS diagnostic without including credential targets or token bytes.
    fn os_error(action: &str) -> String {
        format!(
            "Windows Credential Manager could not {action} the DroneDream session: {}",
            std::io::Error::last_os_error()
        )
    }
}

#[cfg(windows)]
impl CredentialBackend for WindowsCredentialBackend {
    /// Generic credentials remain under the current Windows user across app restarts.
    fn write(&self, target: &str, user_name: &str, value: &[u8]) -> Result<(), String> {
        use windows_sys::Win32::Security::Credentials::{
            CredWriteW, CREDENTIALW, CRED_PERSIST_LOCAL_MACHINE, CRED_TYPE_GENERIC,
        };

        if value.is_empty() || value.len() > MAX_CREDENTIAL_BYTES {
            return Err("The desktop credential value is outside Windows limits.".to_owned());
        }
        let mut target_wide = Self::wide(target);
        let mut user_wide = Self::wide(user_name);
        let mut blob = value.to_vec();
        let credential = CREDENTIALW {
            Type: CRED_TYPE_GENERIC,
            TargetName: target_wide.as_mut_ptr(),
            CredentialBlobSize: blob.len() as u32,
            CredentialBlob: blob.as_mut_ptr(),
            Persist: CRED_PERSIST_LOCAL_MACHINE,
            UserName: user_wide.as_mut_ptr(),
            ..Default::default()
        };
        // All backing buffers outlive the FFI call. Clearing this temporary copy
        // does not claim that the caller's String or allocator memory is zeroized.
        let written = unsafe { CredWriteW(&credential, 0) };
        blob.fill(0);
        if written == 0 {
            return Err(Self::os_error("store"));
        }
        Ok(())
    }

    /// Copy a bounded blob before CredFree; distinguish missing from unreadable.
    fn read(&self, target: &str) -> Result<Option<Vec<u8>>, String> {
        use windows_sys::Win32::{
            Foundation::{GetLastError, ERROR_NOT_FOUND},
            Security::Credentials::{CredFree, CredReadW, CREDENTIALW, CRED_TYPE_GENERIC},
        };

        let target_wide = Self::wide(target);
        let mut credential: *mut CREDENTIALW = std::ptr::null_mut();
        let found =
            unsafe { CredReadW(target_wide.as_ptr(), CRED_TYPE_GENERIC, 0, &mut credential) };
        if found == 0 {
            let error = unsafe { GetLastError() };
            if error == ERROR_NOT_FOUND {
                return Ok(None);
            }
            return Err(Self::os_error("read"));
        }
        if credential.is_null() {
            return Err("Windows Credential Manager returned an empty session.".to_owned());
        }
        let value = unsafe {
            let credential_ref = &*credential;
            if credential_ref.CredentialBlob.is_null()
                || credential_ref.CredentialBlobSize == 0
                || credential_ref.CredentialBlobSize as usize > MAX_CREDENTIAL_BYTES
            {
                CredFree(credential.cast());
                return Err("Windows Credential Manager returned an invalid session.".to_owned());
            }
            let value = std::slice::from_raw_parts(
                credential_ref.CredentialBlob,
                credential_ref.CredentialBlobSize as usize,
            )
            .to_vec();
            CredFree(credential.cast());
            value
        };
        Ok(Some(value))
    }

    /// Missing is idempotent success, while other OS errors remain visible.
    fn delete(&self, target: &str) -> Result<bool, String> {
        use windows_sys::Win32::{
            Foundation::{GetLastError, ERROR_NOT_FOUND},
            Security::Credentials::{CredDeleteW, CRED_TYPE_GENERIC},
        };

        let target_wide = Self::wide(target);
        let deleted = unsafe { CredDeleteW(target_wide.as_ptr(), CRED_TYPE_GENERIC, 0) };
        if deleted != 0 {
            return Ok(true);
        }
        let error = unsafe { GetLastError() };
        if error == ERROR_NOT_FOUND {
            return Ok(false);
        }
        Err(Self::os_error("delete"))
    }
}

#[cfg(windows)]
fn windows_vault() -> &'static CredentialVault<WindowsCredentialBackend> {
    // One process-wide coordinator is shared by login, refresh and logout.
    static VAULT: std::sync::OnceLock<CredentialVault<WindowsCredentialBackend>> =
        std::sync::OnceLock::new();
    VAULT.get_or_init(|| CredentialVault::new(WindowsCredentialBackend))
}

/// Capture ownership before starting a native browser authorization.
#[cfg(windows)]
pub(crate) fn begin_vault_operation(namespace: &str) -> Result<VaultRevision, String> {
    windows_vault().revision(namespace)
}

#[cfg(not(windows))]
pub(crate) fn begin_vault_operation(_namespace: &str) -> Result<VaultRevision, String> {
    Err("Persistent desktop authentication is supported only on Windows.".to_owned())
}

/// Commit a new/rotated secret only while this operation still owns the session.
#[cfg(windows)]
pub(crate) fn store_refresh_token(
    revision: &VaultRevision,
    subject_hash: &str,
    refresh_token: &str,
) -> Result<VaultRevision, String> {
    windows_vault().store(revision, subject_hash, refresh_token)
}

#[cfg(not(windows))]
pub(crate) fn store_refresh_token(
    _revision: &VaultRevision,
    _subject_hash: &str,
    _refresh_token: &str,
) -> Result<VaultRevision, String> {
    Err("Persistent desktop authentication is supported only on Windows.".to_owned())
}

#[cfg(windows)]
/// Return both stored bytes and the ticket required for refresh/invalid-token cleanup.
pub(crate) fn load_refresh_token(
    namespace: &str,
) -> Result<Option<(StoredBrowserAuthSession, VaultRevision)>, String> {
    windows_vault().load(namespace)
}

#[cfg(not(windows))]
pub(crate) fn load_refresh_token(
    _namespace: &str,
) -> Result<Option<(StoredBrowserAuthSession, VaultRevision)>, String> {
    Ok(None)
}

#[cfg(windows)]
/// User-requested logout invalidates even a pending refresh of an empty vault.
pub(crate) fn clear_refresh_token(namespace: &str) -> Result<bool, String> {
    windows_vault().clear(namespace, None)
}

#[cfg(not(windows))]
pub(crate) fn clear_refresh_token(_namespace: &str) -> Result<bool, String> {
    Ok(false)
}

/// Failure of an older operation must not erase credentials published since then.
#[cfg(windows)]
pub(crate) fn clear_refresh_token_if_current(revision: &VaultRevision) -> Result<bool, String> {
    windows_vault().clear(&revision.namespace, Some(revision))
}

#[cfg(not(windows))]
pub(crate) fn clear_refresh_token_if_current(_revision: &VaultRevision) -> Result<bool, String> {
    Ok(false)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{cell::RefCell, collections::HashMap};

    #[derive(Default)]
    struct MemoryBackend {
        values: RefCell<HashMap<String, Vec<u8>>>,
        fail_pointer_write: RefCell<bool>,
    }

    impl CredentialBackend for MemoryBackend {
        fn write(&self, target: &str, _user_name: &str, value: &[u8]) -> Result<(), String> {
            if target.ends_with("/current") && *self.fail_pointer_write.borrow() {
                return Err("injected pointer failure".to_owned());
            }
            self.values
                .borrow_mut()
                .insert(target.to_owned(), value.to_vec());
            Ok(())
        }

        fn read(&self, target: &str) -> Result<Option<Vec<u8>>, String> {
            Ok(self.values.borrow().get(target).cloned())
        }

        fn delete(&self, target: &str) -> Result<bool, String> {
            Ok(self.values.borrow_mut().remove(target).is_some())
        }
    }

    const NAMESPACE: &str = "DroneDream/Auth/sim/v1";
    const OTHER_NAMESPACE: &str = "DroneDream/Auth/lab/v1";
    const SUBJECT_A: &str = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
    const SUBJECT_B: &str = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";

    #[test]
    fn diagnostics_redact_refresh_secrets_and_namespaces_are_exact() {
        let session = StoredBrowserAuthSession {
            subject_hash: SUBJECT_A.into(),
            refresh_token: "synthetic-secret-never-log".into(),
        };
        assert!(!format!("{session:?}").contains(&session.refresh_token));
        for namespace in [
            "DroneDream/Auth/other/v1",
            "DroneDream/Auth/sim/../lab/v1",
            "DroneDream/Auth//v1",
        ] {
            assert!(validate_namespace(namespace).is_err());
        }
    }

    #[test]
    fn logout_cannot_be_undone_by_a_late_refresh_or_authorization() {
        let vault = CredentialVault::new(MemoryBackend::default());
        let initial = vault.revision(NAMESPACE).unwrap();
        vault.store(&initial, SUBJECT_A, "first-token").unwrap();
        let (_, refresh) = vault.load(NAMESPACE).unwrap().unwrap();
        let authorization = vault.revision(NAMESPACE).unwrap();
        vault.clear(NAMESPACE, None).unwrap();
        assert!(vault.store(&refresh, SUBJECT_A, "late-refresh").is_err());
        assert!(vault
            .store(&authorization, SUBJECT_B, "late-login")
            .is_err());
        assert!(vault.load(NAMESPACE).unwrap().is_none());
    }

    #[test]
    fn stale_failure_and_refresh_do_not_touch_new_account_even_with_same_token() {
        let vault = CredentialVault::new(MemoryBackend::default());
        let first = vault.revision(NAMESPACE).unwrap();
        let old = vault.store(&first, SUBJECT_A, "first-token").unwrap();
        vault.clear(NAMESPACE, None).unwrap();
        let login = vault.revision(NAMESPACE).unwrap();
        // Include the ABA case: identical account/token bytes are still a new session.
        vault.store(&login, SUBJECT_A, "first-token").unwrap();
        assert!(!vault.clear(NAMESPACE, Some(&old)).unwrap());
        assert!(vault.store(&old, SUBJECT_A, "late-token").is_err());
        assert_eq!(
            vault.load(NAMESPACE).unwrap().unwrap().0.refresh_token,
            "first-token"
        );
    }

    #[test]
    fn generation_is_edition_scoped_and_failed_writes_invalidate_old_tickets() {
        let vault = CredentialVault::new(MemoryBackend::default());
        let sim = vault.revision(NAMESPACE).unwrap();
        vault.clear(OTHER_NAMESPACE, None).unwrap();
        *vault.backend.fail_pointer_write.borrow_mut() = true;
        assert!(vault.store(&sim, SUBJECT_A, "failed-token").is_err());
        *vault.backend.fail_pointer_write.borrow_mut() = false;
        assert!(vault.store(&sim, SUBJECT_A, "late-token").is_err());
        let retry = vault.revision(NAMESPACE).unwrap();
        vault.store(&retry, SUBJECT_A, "new-token").unwrap();
    }

    #[test]
    fn stores_loads_rotates_and_clears_only_the_current_edition_session() {
        let backend = MemoryBackend::default();
        store_with(&backend, NAMESPACE, SUBJECT_A, "refresh-token-a").unwrap();
        store_with(&backend, OTHER_NAMESPACE, SUBJECT_A, "refresh-token-lab").unwrap();
        assert_eq!(
            load_with(&backend, NAMESPACE).unwrap(),
            Some(StoredBrowserAuthSession {
                subject_hash: SUBJECT_A.to_owned(),
                refresh_token: "refresh-token-a".to_owned(),
            })
        );
        store_with(&backend, NAMESPACE, SUBJECT_B, "refresh-token-b").unwrap();
        assert!(!backend
            .values
            .borrow()
            .contains_key(&account_target(NAMESPACE, SUBJECT_A)));
        assert_eq!(
            load_with(&backend, NAMESPACE)
                .unwrap()
                .unwrap()
                .subject_hash,
            SUBJECT_B
        );
        assert!(clear_with(&backend, NAMESPACE).unwrap());
        assert_eq!(load_with(&backend, NAMESPACE).unwrap(), None);
        assert_eq!(
            load_with(&backend, OTHER_NAMESPACE)
                .unwrap()
                .unwrap()
                .refresh_token,
            "refresh-token-lab"
        );
        assert!(!clear_with(&backend, NAMESPACE).unwrap());
    }

    #[test]
    fn pointer_failure_rolls_back_the_new_secret() {
        let backend = MemoryBackend::default();
        *backend.fail_pointer_write.borrow_mut() = true;
        assert!(store_with(&backend, NAMESPACE, SUBJECT_A, "refresh-token-a").is_err());
        assert!(backend.values.borrow().is_empty());
    }

    #[test]
    fn same_account_refresh_rotation_does_not_rewrite_or_lose_the_pointer() {
        let backend = MemoryBackend::default();
        store_with(&backend, NAMESPACE, SUBJECT_A, "refresh-token-a").unwrap();
        *backend.fail_pointer_write.borrow_mut() = true;

        store_with(&backend, NAMESPACE, SUBJECT_A, "refresh-token-rotated").unwrap();
        assert_eq!(
            load_with(&backend, NAMESPACE)
                .unwrap()
                .unwrap()
                .refresh_token,
            "refresh-token-rotated"
        );
    }

    #[test]
    fn corrupted_pointer_missing_secret_and_unsafe_values_fail_closed_and_recover() {
        let backend = MemoryBackend::default();
        backend
            .values
            .borrow_mut()
            .insert(current_target(NAMESPACE), b"not-a-hash".to_vec());
        assert_eq!(load_with(&backend, NAMESPACE).unwrap(), None);
        assert!(backend.values.borrow().is_empty());
        backend.values.borrow_mut().clear();
        backend
            .values
            .borrow_mut()
            .insert(current_target(NAMESPACE), SUBJECT_A.as_bytes().to_vec());
        assert_eq!(load_with(&backend, NAMESPACE).unwrap(), None);
        assert!(backend.values.borrow().is_empty());
        assert!(store_with(&backend, NAMESPACE, SUBJECT_A, "token with spaces").is_err());
        assert!(store_with(&backend, NAMESPACE, SUBJECT_A, "token-with-\u{00e9}").is_err());
        assert!(store_with(&backend, "Other/App/v1", SUBJECT_A, "token").is_err());
    }

    #[test]
    fn a_corrupted_pointer_cannot_block_new_authorization_or_local_logout() {
        let backend = MemoryBackend::default();
        backend
            .values
            .borrow_mut()
            .insert(current_target(NAMESPACE), b"corrupt".to_vec());
        store_with(&backend, NAMESPACE, SUBJECT_A, "replacement-token").unwrap();
        assert_eq!(
            load_with(&backend, NAMESPACE)
                .unwrap()
                .unwrap()
                .refresh_token,
            "replacement-token"
        );

        backend
            .values
            .borrow_mut()
            .insert(current_target(NAMESPACE), b"corrupt-again".to_vec());
        assert!(clear_with(&backend, NAMESPACE).unwrap());
        assert_eq!(load_with(&backend, NAMESPACE).unwrap(), None);
    }
}
