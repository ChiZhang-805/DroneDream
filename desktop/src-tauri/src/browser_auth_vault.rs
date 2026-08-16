const CURRENT_SESSION_KEY: &str = "current";
const MAX_CREDENTIAL_BYTES: usize = 2_560;

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct StoredBrowserAuthSession {
    pub subject_hash: String,
    pub refresh_token: String,
}

trait CredentialBackend {
    fn write(&self, target: &str, user_name: &str, value: &[u8]) -> Result<(), String>;
    fn read(&self, target: &str) -> Result<Option<Vec<u8>>, String>;
    fn delete(&self, target: &str) -> Result<bool, String>;
}

fn current_target(namespace: &str) -> String {
    format!("{namespace}/{CURRENT_SESSION_KEY}")
}

fn account_target(namespace: &str, subject_hash: &str) -> String {
    format!("{namespace}/{subject_hash}")
}

fn validate_namespace(namespace: &str) -> Result<(), String> {
    if !namespace.starts_with("DroneDream/Auth/")
        || !namespace.ends_with("/v1")
        || namespace.len() > 128
        || namespace.chars().any(char::is_control)
    {
        return Err("The desktop credential namespace is invalid.".to_owned());
    }
    Ok(())
}

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

fn decode_utf8(value: Vec<u8>, label: &str) -> Result<String, String> {
    String::from_utf8(value).map_err(|_| format!("The stored desktop {label} is invalid."))
}

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
    fn wide(value: &str) -> Vec<u16> {
        value.encode_utf16().chain(std::iter::once(0)).collect()
    }

    fn os_error(action: &str) -> String {
        format!(
            "Windows Credential Manager could not {action} the DroneDream session: {}",
            std::io::Error::last_os_error()
        )
    }
}

#[cfg(windows)]
impl CredentialBackend for WindowsCredentialBackend {
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
        let written = unsafe { CredWriteW(&credential, 0) };
        blob.fill(0);
        if written == 0 {
            return Err(Self::os_error("store"));
        }
        Ok(())
    }

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
pub(crate) fn store_refresh_token(
    namespace: &str,
    subject_hash: &str,
    refresh_token: &str,
) -> Result<(), String> {
    store_with(
        &WindowsCredentialBackend,
        namespace,
        subject_hash,
        refresh_token,
    )
}

#[cfg(not(windows))]
pub(crate) fn store_refresh_token(
    _namespace: &str,
    _subject_hash: &str,
    _refresh_token: &str,
) -> Result<(), String> {
    Err("Persistent desktop authentication is supported only on Windows.".to_owned())
}

#[cfg(windows)]
pub(crate) fn load_refresh_token(
    namespace: &str,
) -> Result<Option<StoredBrowserAuthSession>, String> {
    load_with(&WindowsCredentialBackend, namespace)
}

#[cfg(not(windows))]
pub(crate) fn load_refresh_token(
    _namespace: &str,
) -> Result<Option<StoredBrowserAuthSession>, String> {
    Ok(None)
}

#[cfg(windows)]
pub(crate) fn clear_refresh_token(namespace: &str) -> Result<bool, String> {
    clear_with(&WindowsCredentialBackend, namespace)
}

#[cfg(not(windows))]
pub(crate) fn clear_refresh_token(_namespace: &str) -> Result<bool, String> {
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
