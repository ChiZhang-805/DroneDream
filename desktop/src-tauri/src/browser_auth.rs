use base64::{
    engine::general_purpose::{
        STANDARD as BASE64_STANDARD, URL_SAFE_NO_PAD as BASE64_URL_SAFE_NO_PAD,
    },
    Engine as _,
};
use chrono::Utc;
use reqwest::{blocking::Client, redirect::Policy, StatusCode, Url};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    collections::HashMap,
    io::{Read, Write},
    net::{Ipv4Addr, TcpListener, TcpStream},
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Mutex,
    },
    thread,
    time::{Duration, Instant},
};
use tauri::{AppHandle, Manager};
use tauri_plugin_opener::OpenerExt;
use uuid::Uuid;

use crate::{browser_auth_audit, browser_auth_vault};

const AUTH_RESULT_TEMPLATE: &str = include_str!("../browser-auth.html");
const UNIVERSAL_BRAND_LOCKUP: &[u8] =
    include_bytes!("../../../brand/icons/universal-lockup.png");
const SIM_BRAND_LOCKUP: &[u8] = include_bytes!("../../../brand/icons/sim-lockup.png");
const LAB_BRAND_LOCKUP: &[u8] = include_bytes!("../../../brand/icons/lab-lockup.png");
const FIELD_BRAND_LOCKUP: &[u8] =
    include_bytes!("../../../brand/icons/field-lockup.png");
const AUTONOMY_BRAND_LOCKUP: &[u8] =
    include_bytes!("../../../brand/icons/agent-lockup.png");
const OAUTH_AUTHORIZE_URL: &str =
    "https://yggabfynndpzymlqvnim.supabase.co/auth/v1/oauth/authorize";
const OAUTH_TOKEN_URL: &str = "https://yggabfynndpzymlqvnim.supabase.co/auth/v1/oauth/token";
const EXPECTED_ISSUER: &str = "https://yggabfynndpzymlqvnim.supabase.co/auth/v1";
const HOMEPAGE_URL: &str = "https://getdronedream.com/";
const AUTH_PROTOCOL_VERSION: &str = "desktop-browser-auth-pkce-v1";
const AUTH_TIMEOUT: Duration = Duration::from_secs(10 * 60);
const TOKEN_REQUEST_TIMEOUT: Duration = Duration::from_secs(20);
const MAX_HEADER_BYTES: usize = 32 * 1024;
const MAX_TARGET_BYTES: usize = 4096;
const MAX_CODE_BYTES: usize = 8 * 1024;
const MAX_TOKEN_BYTES: usize = 16 * 1024;
const MAX_TOKEN_RESPONSE_BYTES: usize = 48 * 1024;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct DesktopAuthIdentity {
    edition_id: &'static str,
    auth_client_id: &'static str,
    display_name: &'static str,
    brand_lockup: &'static [u8],
    bundle_identifier: &'static str,
    callback_port: u16,
    callback_path: &'static str,
    redirect_uri: &'static str,
    credential_vault_namespace: &'static str,
}

fn desktop_auth_identity(edition_id: &str) -> Result<DesktopAuthIdentity, String> {
    match edition_id {
        "universal" => Ok(DesktopAuthIdentity {
            edition_id: "universal",
            auth_client_id: "dronedream-desktop-universal",
            display_name: "DroneDream",
            brand_lockup: UNIVERSAL_BRAND_LOCKUP,
            bundle_identifier: "io.dronedream.desktop.universal",
            callback_port: 49210,
            callback_path: "/desktop-auth/universal/callback",
            redirect_uri: "http://127.0.0.1:49210/desktop-auth/universal/callback",
            credential_vault_namespace: "DroneDream/Auth/universal/v1",
        }),
        "sim" => Ok(DesktopAuthIdentity {
            edition_id: "sim",
            auth_client_id: "dronedream-desktop-sim",
            display_name: "DroneDream · SIM",
            brand_lockup: SIM_BRAND_LOCKUP,
            bundle_identifier: "io.dronedream.desktop.sim",
            callback_port: 49211,
            callback_path: "/desktop-auth/sim/callback",
            redirect_uri: "http://127.0.0.1:49211/desktop-auth/sim/callback",
            credential_vault_namespace: "DroneDream/Auth/sim/v1",
        }),
        "lab" => Ok(DesktopAuthIdentity {
            edition_id: "lab",
            auth_client_id: "dronedream-desktop-lab",
            display_name: "DroneDream · LAB",
            brand_lockup: LAB_BRAND_LOCKUP,
            bundle_identifier: "io.dronedream.desktop.lab",
            callback_port: 49212,
            callback_path: "/desktop-auth/lab/callback",
            redirect_uri: "http://127.0.0.1:49212/desktop-auth/lab/callback",
            credential_vault_namespace: "DroneDream/Auth/lab/v1",
        }),
        "field" => Ok(DesktopAuthIdentity {
            edition_id: "field",
            auth_client_id: "dronedream-desktop-field",
            display_name: "DroneDream · FIELD",
            brand_lockup: FIELD_BRAND_LOCKUP,
            bundle_identifier: "io.dronedream.desktop.field",
            callback_port: 49213,
            callback_path: "/desktop-auth/field/callback",
            redirect_uri: "http://127.0.0.1:49213/desktop-auth/field/callback",
            credential_vault_namespace: "DroneDream/Auth/field/v1",
        }),
        "autonomy" => Ok(DesktopAuthIdentity {
            edition_id: "autonomy",
            auth_client_id: "dronedream-desktop-autonomy",
            display_name: "DroneDream · AGENT",
            brand_lockup: AUTONOMY_BRAND_LOCKUP,
            bundle_identifier: "io.dronedream.desktop.autonomy",
            callback_port: 49214,
            callback_path: "/desktop-auth/autonomy/callback",
            redirect_uri: "http://127.0.0.1:49214/desktop-auth/autonomy/callback",
            credential_vault_namespace: "DroneDream/Auth/autonomy/v1",
        }),
        _ => Err("The desktop browser sign-in edition is unsupported.".to_owned()),
    }
}

fn compiled_desktop_auth_identity() -> Result<DesktopAuthIdentity, String> {
    desktop_auth_identity(env!("DRONEDREAM_DESKTOP_EDITION_ID"))
}

fn compiled_oauth_client_id() -> Result<&'static str, String> {
    let client_id = env!("DRONEDREAM_OAUTH_CLIENT_ID");
    let segments = client_id.split('-').collect::<Vec<_>>();
    let registered = segments.len() == 5
        && segments
            .iter()
            .map(|segment| segment.len())
            .eq([8, 4, 4, 4, 12])
        && client_id
            .bytes()
            .filter(|byte| *byte != b'-')
            .all(|byte| byte.is_ascii_hexdigit());
    if !registered {
        return Err("This desktop edition has not been registered for browser sign-in.".to_owned());
    }
    Ok(client_id)
}

#[derive(Default)]
pub struct BrowserAuthCoordinator {
    activity: Mutex<Option<Arc<AtomicBool>>>,
}

impl BrowserAuthCoordinator {
    fn begin(&self) -> Result<Arc<AtomicBool>, String> {
        let mut activity = self
            .activity
            .lock()
            .map_err(|_| "Browser sign-in state is unavailable.".to_owned())?;
        if activity.is_some() {
            return Err("A browser sign-in is already in progress.".to_owned());
        }
        let cancelled = Arc::new(AtomicBool::new(false));
        *activity = Some(cancelled.clone());
        Ok(cancelled)
    }

    fn cancel(&self) -> Result<bool, String> {
        let activity = self
            .activity
            .lock()
            .map_err(|_| "Browser sign-in state is unavailable.".to_owned())?;
        if let Some(cancelled) = activity.as_ref() {
            cancelled.store(true, Ordering::SeqCst);
            Ok(true)
        } else {
            Ok(false)
        }
    }

    fn finish(&self) {
        if let Ok(mut activity) = self.activity.lock() {
            *activity = None;
        }
    }
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct BrowserAuthRequest {
    locale: String,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct BrowserAuthSession {
    protocol_version: &'static str,
    edition_id: &'static str,
    auth_client_id: &'static str,
    access_token: String,
    attempt_id_hash: String,
    state_hash: String,
    subject_hash: String,
    issued_at: String,
    completed_at: String,
}

#[derive(Deserialize)]
struct OAuthTokenResponse {
    access_token: String,
    #[serde(default)]
    refresh_token: Option<String>,
    #[serde(default)]
    id_token: Option<String>,
    token_type: String,
    expires_in: u64,
}

enum TokenHttpOutcome {
    Accepted(OAuthTokenResponse),
    Rejected,
}

enum VaultRestoreOutcome {
    NoSavedSession,
    ReauthorizationRequired,
    Restored(Box<BrowserAuthSession>),
}

fn token_status_is_credential_rejection(status: StatusCode) -> bool {
    matches!(
        status,
        StatusCode::BAD_REQUEST | StatusCode::UNAUTHORIZED | StatusCode::FORBIDDEN
    )
}

#[derive(Debug, Eq, PartialEq)]
enum AuthorizationCallback {
    Authorized { code: String, state: String },
    Denied { state: String },
}

impl AuthorizationCallback {
    fn state(&self) -> &str {
        match self {
            Self::Authorized { state, .. } | Self::Denied { state } => state,
        }
    }
}

struct HttpRequest {
    method: String,
    target: String,
    headers: HashMap<String, String>,
}

#[tauri::command]
pub async fn begin_browser_auth(
    app: AppHandle,
    request: BrowserAuthRequest,
) -> Result<BrowserAuthSession, String> {
    validate_request(&request)?;
    let coordinator = app.state::<BrowserAuthCoordinator>();
    let cancelled = coordinator.begin()?;
    let app_for_listener = app.clone();
    let operation = tauri::async_runtime::spawn_blocking(move || {
        run_browser_auth(app_for_listener, request, cancelled)
    })
    .await
    .map_err(|error| format!("Browser sign-in task failed: {error}"))
    .and_then(|result| result);
    app.state::<BrowserAuthCoordinator>().finish();
    operation
}

#[tauri::command]
pub fn cancel_browser_auth(
    coordinator: tauri::State<'_, BrowserAuthCoordinator>,
) -> Result<bool, String> {
    coordinator.cancel()
}

#[tauri::command]
pub fn clear_browser_auth_vault() -> Result<bool, String> {
    let identity = compiled_desktop_auth_identity()?;
    let attempt_id = random_hex_32();
    let attempt_id_hash = sha256_hex(attempt_id.as_bytes());
    let state_hash = sha256_hex(format!("local-logout:{attempt_id}").as_bytes());
    let issued_at = Utc::now().to_rfc3339();
    let outcome = browser_auth_vault::clear_refresh_token(identity.credential_vault_namespace);
    let completed_at = Utc::now().to_rfc3339();
    let (result, failure_code) = match &outcome {
        Ok(true) => ("local_logout", None),
        Ok(false) => ("local_logout_no_saved_session", None),
        Err(_) => ("local_logout_failed", Some("credential_vault_failed")),
    };
    let receipt = browser_auth_audit::BrowserAuthAuditReceipt::new(
        identity.edition_id,
        identity.auth_client_id,
        &attempt_id_hash,
        &state_hash,
        None,
        result,
        failure_code,
        &issued_at,
        &completed_at,
        "native-command",
    );
    browser_auth_audit::append_browser_auth_audit(&receipt)?;
    outcome
}

#[tauri::command]
pub async fn restore_browser_auth_vault() -> Result<Option<BrowserAuthSession>, String> {
    tauri::async_runtime::spawn_blocking(restore_browser_auth_vault_sync)
        .await
        .map_err(|error| format!("Desktop session restoration task failed: {error}"))?
}

fn validate_request(request: &BrowserAuthRequest) -> Result<(), String> {
    if request.locale != "en" && request.locale != "zh-CN" {
        return Err("Browser sign-in locale must be en or zh-CN.".to_owned());
    }
    Ok(())
}

fn run_browser_auth(
    app: AppHandle,
    request: BrowserAuthRequest,
    cancelled: Arc<AtomicBool>,
) -> Result<BrowserAuthSession, String> {
    let identity = compiled_desktop_auth_identity()?;
    let state = random_hex_32();
    let nonce = random_hex_32();
    let attempt_id = Uuid::new_v4().simple().to_string();
    let code_verifier = random_hex_32();
    let issued_at = Utc::now();
    let issued_at_text = issued_at.to_rfc3339();
    let outcome = (|| -> Result<(BrowserAuthSession, TcpStream), String> {
        let oauth_client_id = compiled_oauth_client_id()?;
        if app.config().identifier != identity.bundle_identifier {
            return Err(
                "The desktop bundle identity does not match its browser sign-in client.".to_owned(),
            );
        }
        let listener =
            TcpListener::bind((Ipv4Addr::LOCALHOST, identity.callback_port)).map_err(|_| {
                format!(
                    "The {} browser sign-in callback is already in use.",
                    identity.edition_id
                )
            })?;
        listener
            .set_nonblocking(true)
            .map_err(|error| format!("Could not configure the local sign-in callback: {error}"))?;
        let code_challenge = pkce_challenge(&code_verifier);
        let authorize_url =
            build_authorize_url(identity, oauth_client_id, &state, &nonce, &code_challenge)?;
        app.opener()
            .open_url(authorize_url.as_str(), None::<&str>)
            .map_err(|error| format!("Could not open the system browser: {error}"))?;

        let deadline = Instant::now() + AUTH_TIMEOUT;
        loop {
            if cancelled.load(Ordering::SeqCst) {
                return Err("Browser sign-in was cancelled.".to_owned());
            }
            if Instant::now() >= deadline {
                return Err("Browser sign-in timed out. Start it again to retry.".to_owned());
            }
            match listener.accept() {
                Ok((mut stream, peer)) => {
                    if !peer.ip().is_loopback() {
                        continue;
                    }
                    stream
                        .set_read_timeout(Some(Duration::from_secs(3)))
                        .map_err(|error| {
                            format!("Could not secure the sign-in connection: {error}")
                        })?;
                    let request_message = match read_http_request(&mut stream) {
                        Ok(message) => message,
                        Err(error) => {
                            let _ = write_text_response(
                                &mut stream,
                                400,
                                "Bad Request",
                                "text/plain; charset=utf-8",
                                error.as_bytes(),
                                &nonce,
                            );
                            continue;
                        }
                    };
                    if !host_is_exact(&request_message, identity.callback_port) {
                        let _ = write_text_response(
                            &mut stream,
                            421,
                            "Misdirected Request",
                            "text/plain; charset=utf-8",
                            b"Invalid local sign-in host.",
                            &attempt_id,
                        );
                        continue;
                    }
                    if request_message.method == "GET"
                        && request_message.target.starts_with(identity.callback_path)
                    {
                        let callback = match parse_authorization_callback(
                            &request_message.target,
                            identity.callback_path,
                        ) {
                            Ok(callback) => callback,
                            Err(error) => {
                                let _ = write_text_response(
                                    &mut stream,
                                    400,
                                    "Bad Request",
                                    "text/plain; charset=utf-8",
                                    error.as_bytes(),
                                    &attempt_id,
                                );
                                continue;
                            }
                        };
                        if !constant_time_equal(callback.state().as_bytes(), state.as_bytes()) {
                            let _ = write_text_response(
                                &mut stream,
                                403,
                                "Forbidden",
                                "text/plain; charset=utf-8",
                                b"Invalid sign-in state.",
                                &attempt_id,
                            );
                            continue;
                        }
                        let AuthorizationCallback::Authorized { code, .. } = callback else {
                            let page = render_auth_result_page(
                                &request.locale,
                                identity,
                                false,
                                &attempt_id,
                            )?;
                            let _ = write_html_response(&mut stream, page.as_bytes(), &attempt_id);
                            return Err("Browser sign-in was denied or cancelled.".to_owned());
                        };
                        let token_response = match exchange_authorization_code(
                            oauth_client_id,
                            identity.redirect_uri,
                            &code,
                            &code_verifier,
                        ) {
                            Ok(response) => response,
                            Err(error) => {
                                let page = render_auth_result_page(
                                    &request.locale,
                                    identity,
                                    false,
                                    &attempt_id,
                                )?;
                                let _ =
                                    write_html_response(&mut stream, page.as_bytes(), &attempt_id);
                                return Err(error);
                            }
                        };
                        let subject =
                            match validate_token_response(&token_response, oauth_client_id, &nonce)
                            {
                                Ok(subject) => subject,
                                Err(error) => {
                                    let page = render_auth_result_page(
                                        &request.locale,
                                        identity,
                                        false,
                                        &attempt_id,
                                    )?;
                                    let _ = write_html_response(
                                        &mut stream,
                                        page.as_bytes(),
                                        &attempt_id,
                                    );
                                    return Err(error);
                                }
                            };
                        let completed_at = Utc::now();
                        let subject_hash = sha256_hex(subject.as_bytes());
                        let refresh_token = token_response
                            .refresh_token
                            .as_deref()
                            .ok_or_else(|| {
                                "Browser sign-in did not return a refresh token.".to_owned()
                            })?
                            .to_owned();
                        if let Err(error) = browser_auth_vault::store_refresh_token(
                            identity.credential_vault_namespace,
                            &subject_hash,
                            &refresh_token,
                        ) {
                            let page = render_auth_result_page(
                                &request.locale,
                                identity,
                                false,
                                &attempt_id,
                            )?;
                            let _ = write_html_response(&mut stream, page.as_bytes(), &attempt_id);
                            return Err(error);
                        }
                        return Ok((
                            BrowserAuthSession {
                                protocol_version: AUTH_PROTOCOL_VERSION,
                                edition_id: identity.edition_id,
                                auth_client_id: identity.auth_client_id,
                                access_token: token_response.access_token,
                                attempt_id_hash: sha256_hex(attempt_id.as_bytes()),
                                state_hash: sha256_hex(state.as_bytes()),
                                subject_hash,
                                issued_at: issued_at_text.clone(),
                                completed_at: completed_at.to_rfc3339(),
                            },
                            stream,
                        ));
                    }
                    let _ = write_text_response(
                        &mut stream,
                        404,
                        "Not Found",
                        "text/plain; charset=utf-8",
                        b"Not found.",
                        &attempt_id,
                    );
                }
                Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                    thread::sleep(Duration::from_millis(25));
                }
                Err(error) => {
                    return Err(format!("The local sign-in callback failed: {error}"));
                }
            }
        }
    })();

    let completed_at = outcome
        .as_ref()
        .map(|(session, _stream)| session.completed_at.clone())
        .unwrap_or_else(|_| Utc::now().to_rfc3339());
    let (result, failure_code, subject_hash) = match &outcome {
        Ok((session, _stream)) => ("authorized", None, Some(session.subject_hash.as_str())),
        Err(error) => {
            let code = browser_auth_failure_code(error);
            let result = match code {
                "user_denied" => "denied",
                "cancelled" => "cancelled",
                "timeout" => "timed_out",
                _ => "failed",
            };
            (result, Some(code), None)
        }
    };
    let attempt_id_hash = sha256_hex(attempt_id.as_bytes());
    let state_hash = sha256_hex(state.as_bytes());
    let receipt = browser_auth_audit::BrowserAuthAuditReceipt::new(
        identity.edition_id,
        identity.auth_client_id,
        &attempt_id_hash,
        &state_hash,
        subject_hash,
        result,
        failure_code,
        &issued_at_text,
        &completed_at,
        "loopback-http",
    );
    if let Err(error) = browser_auth_audit::append_browser_auth_audit(&receipt) {
        if let Ok((_session, mut stream)) = outcome {
            let _ = browser_auth_vault::clear_refresh_token(identity.credential_vault_namespace);
            if let Ok(page) = render_auth_result_page(&request.locale, identity, false, &attempt_id)
            {
                let _ = write_html_response(&mut stream, page.as_bytes(), &attempt_id);
            }
        }
        return Err(error);
    }
    match outcome {
        Ok((session, mut stream)) => {
            if let Ok(page) = render_auth_result_page(&request.locale, identity, true, &attempt_id)
            {
                let _ = write_html_response(&mut stream, page.as_bytes(), &attempt_id);
            }
            Ok(session)
        }
        Err(error) => Err(error),
    }
}

fn browser_auth_failure_code(error: &str) -> &'static str {
    let error = error.to_ascii_lowercase();
    if error.contains("denied or cancelled") {
        "user_denied"
    } else if error.contains("cancelled") {
        "cancelled"
    } else if error.contains("timed out") {
        "timeout"
    } else if error.contains("callback is already in use") {
        "callback_in_use"
    } else if error.contains("bundle identity") || error.contains("not registered") {
        "edition_identity_mismatch"
    } else if error.contains("open the system browser") {
        "browser_open_failed"
    } else if error.contains("identity binding") || error.contains("account subject") {
        "account_binding_failed"
    } else if error.contains("credential") {
        "credential_vault_failed"
    } else if error.contains("token") || error.contains("account service") {
        "token_exchange_failed"
    } else if error.contains("callback") || error.contains("sign-in connection") {
        "callback_failed"
    } else {
        "internal_failure"
    }
}

fn random_hex_32() -> String {
    format!("{}{}", Uuid::new_v4().simple(), Uuid::new_v4().simple())
}

fn sha256_hex(value: &[u8]) -> String {
    hex::encode(Sha256::digest(value))
}

fn pkce_challenge(code_verifier: &str) -> String {
    BASE64_URL_SAFE_NO_PAD.encode(Sha256::digest(code_verifier.as_bytes()))
}

fn build_authorize_url(
    identity: DesktopAuthIdentity,
    oauth_client_id: &str,
    state: &str,
    nonce: &str,
    code_challenge: &str,
) -> Result<Url, String> {
    let mut url = Url::parse(OAUTH_AUTHORIZE_URL)
        .map_err(|_| "The approved OAuth authorization URL is invalid.".to_owned())?;
    url.query_pairs_mut()
        .append_pair("response_type", "code")
        .append_pair("client_id", oauth_client_id)
        .append_pair("redirect_uri", identity.redirect_uri)
        .append_pair("state", state)
        .append_pair("code_challenge", code_challenge)
        .append_pair("code_challenge_method", "S256")
        .append_pair("scope", "openid email profile")
        .append_pair("nonce", nonce);
    Ok(url)
}

fn parse_authorization_callback(
    target: &str,
    expected_path: &str,
) -> Result<AuthorizationCallback, String> {
    let url = Url::parse(&format!("http://127.0.0.1{target}"))
        .map_err(|_| "Browser sign-in returned an invalid callback URL.".to_owned())?;
    if url.path() != expected_path || url.fragment().is_some() {
        return Err("Browser sign-in returned to the wrong desktop edition.".to_owned());
    }
    let mut fields = HashMap::new();
    for (name, value) in url.query_pairs() {
        if fields
            .insert(name.into_owned(), value.into_owned())
            .is_some()
        {
            return Err("Browser sign-in callback contained duplicate fields.".to_owned());
        }
    }
    if fields.contains_key("error") {
        if fields.keys().any(|key| {
            !matches!(
                key.as_str(),
                "error" | "error_description" | "error_uri" | "state"
            )
        }) {
            return Err("Browser sign-in denial contained unexpected fields.".to_owned());
        }
        if !fields.contains_key("state") || fields.len() < 2 || fields.len() > 4 {
            return Err("Browser sign-in denial fields are incomplete.".to_owned());
        }
        let state = fields.remove("state").unwrap_or_default();
        if state.is_empty() || state.len() > 256 || state.chars().any(char::is_control) {
            return Err("Browser sign-in denial state is invalid.".to_owned());
        }
        return Ok(AuthorizationCallback::Denied { state });
    }
    if fields.len() != 2 || !fields.contains_key("code") || !fields.contains_key("state") {
        return Err("Browser sign-in callback fields are incomplete.".to_owned());
    }
    let code = fields.remove("code").unwrap_or_default();
    let state = fields.remove("state").unwrap_or_default();
    if code.is_empty()
        || code.len() > MAX_CODE_BYTES
        || code.contains(char::is_whitespace)
        || code.chars().any(char::is_control)
    {
        return Err("Browser sign-in returned an invalid authorization code.".to_owned());
    }
    Ok(AuthorizationCallback::Authorized { code, state })
}

fn exchange_authorization_code(
    oauth_client_id: &str,
    redirect_uri: &str,
    code: &str,
    code_verifier: &str,
) -> Result<OAuthTokenResponse, String> {
    match send_token_request(&[
        ("grant_type", "authorization_code"),
        ("code", code),
        ("client_id", oauth_client_id),
        ("redirect_uri", redirect_uri),
        ("code_verifier", code_verifier),
    ])? {
        TokenHttpOutcome::Accepted(response) => Ok(response),
        TokenHttpOutcome::Rejected => {
            Err("The browser sign-in authorization code was rejected.".to_owned())
        }
    }
}

fn send_token_request(fields: &[(&str, &str)]) -> Result<TokenHttpOutcome, String> {
    let client = Client::builder()
        .connect_timeout(TOKEN_REQUEST_TIMEOUT)
        .timeout(TOKEN_REQUEST_TIMEOUT)
        .redirect(Policy::none())
        .user_agent("DroneDream-Desktop/1.0.0")
        .build()
        .map_err(|_| "The browser sign-in token client could not be created.".to_owned())?;
    let mut response = client
        .post(OAUTH_TOKEN_URL)
        .form(fields)
        .send()
        .map_err(|_| {
            "The browser sign-in code exchange could not reach the account service.".to_owned()
        })?;
    if !response.status().is_success() {
        return if token_status_is_credential_rejection(response.status()) {
            Ok(TokenHttpOutcome::Rejected)
        } else {
            Err("The browser sign-in account service is temporarily unavailable.".to_owned())
        };
    }
    if response
        .content_length()
        .is_some_and(|length| length > MAX_TOKEN_RESPONSE_BYTES as u64)
    {
        return Err("The browser sign-in token response is too large.".to_owned());
    }
    let mut body = Vec::new();
    response
        .by_ref()
        .take(MAX_TOKEN_RESPONSE_BYTES as u64 + 1)
        .read_to_end(&mut body)
        .map_err(|_| "The browser sign-in token response could not be read.".to_owned())?;
    if body.len() > MAX_TOKEN_RESPONSE_BYTES {
        return Err("The browser sign-in token response is too large.".to_owned());
    }
    let parsed = serde_json::from_slice(&body)
        .map_err(|_| "The browser sign-in token response is invalid.".to_owned())?;
    Ok(TokenHttpOutcome::Accepted(parsed))
}

fn jwt_payload(token: &str) -> Result<serde_json::Value, String> {
    validate_token("identity token", token)?;
    let parts = token.split('.').collect::<Vec<_>>();
    if parts.len() != 3 {
        return Err("Browser sign-in returned an invalid identity token.".to_owned());
    }
    let decoded = BASE64_URL_SAFE_NO_PAD
        .decode(parts[1])
        .map_err(|_| "Browser sign-in returned an invalid identity token.".to_owned())?;
    serde_json::from_slice(&decoded)
        .map_err(|_| "Browser sign-in returned invalid identity claims.".to_owned())
}

fn audience_matches(value: &serde_json::Value, expected: &str) -> bool {
    value.as_str() == Some(expected)
        || value
            .as_array()
            .is_some_and(|items| items.iter().any(|item| item.as_str() == Some(expected)))
}

fn validate_token_response(
    response: &OAuthTokenResponse,
    oauth_client_id: &str,
    nonce: &str,
) -> Result<String, String> {
    let access_subject = validate_access_token_response(response, oauth_client_id)?;
    let refresh_token = response
        .refresh_token
        .as_deref()
        .ok_or_else(|| "Browser sign-in did not return a refresh token.".to_owned())?;
    validate_token("refresh token", refresh_token)?;
    let id_token = response
        .id_token
        .as_deref()
        .ok_or_else(|| "Browser sign-in did not return an identity token.".to_owned())?;
    let identity_claims = jwt_payload(id_token)?;
    let identity_subject = identity_claims
        .get("sub")
        .and_then(serde_json::Value::as_str);
    if Some(access_subject.as_str()) != identity_subject
        || identity_claims
            .get("iss")
            .and_then(serde_json::Value::as_str)
            != Some(EXPECTED_ISSUER)
        || !identity_claims
            .get("aud")
            .is_some_and(|audience| audience_matches(audience, oauth_client_id))
        || identity_claims
            .get("nonce")
            .and_then(serde_json::Value::as_str)
            != Some(nonce)
    {
        return Err(
            "Browser sign-in identity binding did not match this desktop edition.".to_owned(),
        );
    }
    validate_claim_expiry(&identity_claims)?;
    Ok(access_subject)
}

fn validate_access_token_response(
    response: &OAuthTokenResponse,
    oauth_client_id: &str,
) -> Result<String, String> {
    validate_token("access token", &response.access_token)?;
    if !response.token_type.eq_ignore_ascii_case("bearer")
        || response.expires_in == 0
        || response.expires_in > 86_400
    {
        return Err("Browser sign-in returned invalid token metadata.".to_owned());
    }
    let access_claims = jwt_payload(&response.access_token)?;
    let access_subject = access_claims
        .get("sub")
        .and_then(serde_json::Value::as_str)
        .ok_or_else(|| "Browser sign-in account subject is missing.".to_owned())?;
    if access_claims.get("iss").and_then(serde_json::Value::as_str) != Some(EXPECTED_ISSUER)
        || access_claims
            .get("client_id")
            .and_then(serde_json::Value::as_str)
            != Some(oauth_client_id)
    {
        return Err(
            "Browser sign-in identity binding did not match this desktop edition.".to_owned(),
        );
    }
    validate_claim_expiry(&access_claims)?;
    Ok(access_subject.to_owned())
}

fn validate_claim_expiry(claims: &serde_json::Value) -> Result<(), String> {
    let expires_at = claims
        .get("exp")
        .and_then(serde_json::Value::as_i64)
        .ok_or_else(|| "Browser sign-in token expiry is missing.".to_owned())?;
    if expires_at <= Utc::now().timestamp() {
        return Err("Browser sign-in returned an expired token.".to_owned());
    }
    Ok(())
}

fn restore_browser_auth_vault_sync() -> Result<Option<BrowserAuthSession>, String> {
    let identity = compiled_desktop_auth_identity()?;
    let attempt_id = random_hex_32();
    let attempt_id_hash = sha256_hex(attempt_id.as_bytes());
    let state_hash = sha256_hex(format!("restore:{attempt_id}").as_bytes());
    let issued_at = Utc::now().to_rfc3339();
    let outcome = (|| -> Result<VaultRestoreOutcome, String> {
        let oauth_client_id = compiled_oauth_client_id()?;
        let Some(stored) =
            browser_auth_vault::load_refresh_token(identity.credential_vault_namespace)?
        else {
            return Ok(VaultRestoreOutcome::NoSavedSession);
        };
        let token_response = match send_token_request(&[
            ("grant_type", "refresh_token"),
            ("refresh_token", &stored.refresh_token),
            ("client_id", oauth_client_id),
        ])? {
            TokenHttpOutcome::Accepted(response) => response,
            TokenHttpOutcome::Rejected => {
                browser_auth_vault::clear_refresh_token(identity.credential_vault_namespace)?;
                return Ok(VaultRestoreOutcome::ReauthorizationRequired);
            }
        };
        let subject = validate_access_token_response(&token_response, oauth_client_id)
            .inspect_err(|_error| {
                let _ =
                    browser_auth_vault::clear_refresh_token(identity.credential_vault_namespace);
            })?;
        let subject_hash = sha256_hex(subject.as_bytes());
        if subject_hash != stored.subject_hash {
            let _ = browser_auth_vault::clear_refresh_token(identity.credential_vault_namespace);
            return Err("The stored desktop session belongs to a different account.".to_owned());
        }
        let refresh_token = token_response
            .refresh_token
            .as_deref()
            .unwrap_or(&stored.refresh_token)
            .to_owned();
        browser_auth_vault::store_refresh_token(
            identity.credential_vault_namespace,
            &subject_hash,
            &refresh_token,
        )?;
        let completed_at = Utc::now().to_rfc3339();
        Ok(VaultRestoreOutcome::Restored(Box::new(
            BrowserAuthSession {
                protocol_version: AUTH_PROTOCOL_VERSION,
                edition_id: identity.edition_id,
                auth_client_id: identity.auth_client_id,
                access_token: token_response.access_token,
                attempt_id_hash: attempt_id_hash.clone(),
                state_hash: state_hash.clone(),
                subject_hash,
                issued_at: issued_at.clone(),
                completed_at,
            },
        )))
    })();
    let completed_at = match &outcome {
        Ok(VaultRestoreOutcome::Restored(session)) => session.completed_at.clone(),
        _ => Utc::now().to_rfc3339(),
    };
    let (result, failure_code, subject_hash) = match &outcome {
        Ok(VaultRestoreOutcome::NoSavedSession) => ("no_saved_session", None, None),
        Ok(VaultRestoreOutcome::ReauthorizationRequired) => {
            ("reauthorization_required", Some("refresh_rejected"), None)
        }
        Ok(VaultRestoreOutcome::Restored(session)) => {
            ("restored", None, Some(session.subject_hash.as_str()))
        }
        Err(error) => (
            "restore_failed",
            Some(browser_auth_failure_code(error)),
            None,
        ),
    };
    let receipt = browser_auth_audit::BrowserAuthAuditReceipt::new(
        identity.edition_id,
        identity.auth_client_id,
        &attempt_id_hash,
        &state_hash,
        subject_hash,
        result,
        failure_code,
        &issued_at,
        &completed_at,
        "credential-vault",
    );
    if let Err(error) = browser_auth_audit::append_browser_auth_audit(&receipt) {
        if matches!(&outcome, Ok(VaultRestoreOutcome::Restored(_))) {
            let _ = browser_auth_vault::clear_refresh_token(identity.credential_vault_namespace);
        }
        return Err(error);
    }
    match outcome? {
        VaultRestoreOutcome::NoSavedSession | VaultRestoreOutcome::ReauthorizationRequired => {
            Ok(None)
        }
        VaultRestoreOutcome::Restored(session) => Ok(Some(*session)),
    }
}

fn render_auth_result_page(
    locale: &str,
    identity: DesktopAuthIdentity,
    success: bool,
    nonce: &str,
) -> Result<String, String> {
    let brand_lockup = format!(
        "data:image/png;base64,{}",
        BASE64_STANDARD.encode(identity.brand_lockup)
    );
    let replacements = [
        ("__DOCUMENT_LANGUAGE__", locale.to_owned()),
        ("__CSP_NONCE__", nonce.to_owned()),
        ("__BRAND_LOCKUP_DATA_URL__", brand_lockup),
        (
            "__DISPLAY_NAME_JSON__",
            serde_json::to_string(identity.display_name)
                .map_err(|error| format!("Could not render edition name: {error}"))?,
        ),
        (
            "__LOCALE_JSON__",
            serde_json::to_string(locale)
                .map_err(|error| format!("Could not render sign-in locale: {error}"))?,
        ),
        (
            "__SUCCESS_JSON__",
            serde_json::to_string(&success)
                .map_err(|error| format!("Could not render sign-in result: {error}"))?,
        ),
        (
            "__HOME_URL_JSON__",
            serde_json::to_string(HOMEPAGE_URL)
                .map_err(|error| format!("Could not render homepage URL: {error}"))?,
        ),
    ];
    let mut page = AUTH_RESULT_TEMPLATE.to_owned();
    for (placeholder, replacement) in replacements {
        page = page.replace(placeholder, &replacement);
    }
    if page.contains("__DOCUMENT_LANGUAGE__")
        || page.contains("__CSP_NONCE__")
        || page.contains("__BRAND_LOCKUP_DATA_URL__")
        || page.contains("__DISPLAY_NAME_JSON__")
        || page.contains("__LOCALE_JSON__")
        || page.contains("__SUCCESS_JSON__")
        || page.contains("__HOME_URL_JSON__")
    {
        return Err("The browser sign-in result page was not rendered completely.".to_owned());
    }
    Ok(page)
}

fn read_http_request(stream: &mut TcpStream) -> Result<HttpRequest, String> {
    let mut received = Vec::with_capacity(4096);
    let mut buffer = [0_u8; 4096];
    let header_end = loop {
        let count = stream
            .read(&mut buffer)
            .map_err(|error| format!("Could not read browser request: {error}"))?;
        if count == 0 {
            return Err("Browser closed the local sign-in request.".to_owned());
        }
        received.extend_from_slice(&buffer[..count]);
        if let Some(index) = find_bytes(&received, b"\r\n\r\n") {
            break index + 4;
        }
        if received.len() > MAX_HEADER_BYTES {
            return Err("Browser sign-in headers are too large.".to_owned());
        }
    };
    let header_text = std::str::from_utf8(&received[..header_end - 4])
        .map_err(|_| "Browser sign-in headers are not valid UTF-8.".to_owned())?;
    let mut lines = header_text.split("\r\n");
    let request_line = lines
        .next()
        .ok_or_else(|| "Browser sign-in request line is missing.".to_owned())?;
    let parts = request_line.split_whitespace().collect::<Vec<_>>();
    if parts.len() != 3 || parts[2] != "HTTP/1.1" {
        return Err("Browser sign-in requires HTTP/1.1.".to_owned());
    }
    let method = parts[0].to_owned();
    if method != "GET" {
        return Err("Browser sign-in callback requires GET.".to_owned());
    }
    let target = parts[1].to_owned();
    if !target.starts_with('/')
        || target.len() > MAX_TARGET_BYTES
        || target.contains(char::is_whitespace)
    {
        return Err("Browser sign-in request target is invalid.".to_owned());
    }
    let mut headers = HashMap::new();
    for line in lines {
        let (name, value) = line
            .split_once(':')
            .ok_or_else(|| "Browser sign-in header is malformed.".to_owned())?;
        let normalized_name = name.trim().to_ascii_lowercase();
        if normalized_name.is_empty()
            || !normalized_name
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || byte == b'-')
        {
            return Err("Browser sign-in header name is invalid.".to_owned());
        }
        if headers
            .insert(normalized_name, value.trim().to_owned())
            .is_some()
        {
            return Err("Browser sign-in request contains a duplicate header.".to_owned());
        }
    }
    if headers.contains_key("transfer-encoding") {
        return Err("Chunked browser sign-in requests are not allowed.".to_owned());
    }
    let content_length = match headers.get("content-length") {
        Some(raw) => raw
            .parse::<usize>()
            .map_err(|_| "Browser sign-in content length is invalid.".to_owned())?,
        None => 0,
    };
    if content_length != 0 {
        return Err("Browser sign-in callbacks must not contain a request body.".to_owned());
    }
    Ok(HttpRequest {
        method,
        target,
        headers,
    })
}

fn host_is_exact(request: &HttpRequest, port: u16) -> bool {
    let expected = format!("127.0.0.1:{port}");
    request.headers.get("host") == Some(&expected)
}

fn validate_token(label: &str, token: &str) -> Result<(), String> {
    if token.is_empty()
        || token.len() > MAX_TOKEN_BYTES
        || token.contains(char::is_whitespace)
        || token.chars().any(char::is_control)
    {
        return Err(format!("Browser sign-in returned an invalid {label}."));
    }
    Ok(())
}

fn constant_time_equal(left: &[u8], right: &[u8]) -> bool {
    let mut difference = left.len() ^ right.len();
    let length = left.len().max(right.len());
    for index in 0..length {
        difference |= usize::from(
            left.get(index).copied().unwrap_or(0) ^ right.get(index).copied().unwrap_or(0),
        );
    }
    difference == 0
}

fn find_bytes(haystack: &[u8], needle: &[u8]) -> Option<usize> {
    haystack
        .windows(needle.len())
        .position(|window| window == needle)
}

fn write_html_response(stream: &mut TcpStream, body: &[u8], nonce: &str) -> Result<(), String> {
    write_text_response(stream, 200, "OK", "text/html; charset=utf-8", body, nonce)
}

fn write_text_response(
    stream: &mut TcpStream,
    status: u16,
    reason: &str,
    content_type: &str,
    body: &[u8],
    nonce: &str,
) -> Result<(), String> {
    let headers = format!(
        "HTTP/1.1 {status} {reason}\r\n\
         Content-Type: {content_type}\r\n\
         Content-Length: {}\r\n\
         Cache-Control: no-store, max-age=0\r\n\
         Pragma: no-cache\r\n\
         Referrer-Policy: no-referrer\r\n\
         X-Content-Type-Options: nosniff\r\n\
         X-Frame-Options: DENY\r\n\
         Cross-Origin-Opener-Policy: same-origin\r\n\
         Content-Security-Policy: default-src 'none'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'; form-action 'none'; connect-src 'none'; script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; img-src data:; font-src 'none'\r\n\
         Connection: close\r\n\r\n",
        body.len(),
    );
    stream
        .write_all(headers.as_bytes())
        .and_then(|_| stream.write_all(body))
        .and_then(|_| stream.flush())
        .map_err(|error| format!("Could not respond to browser sign-in: {error}"))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Cursor;

    fn valid_request() -> BrowserAuthRequest {
        BrowserAuthRequest {
            locale: "en".to_owned(),
        }
    }

    fn fake_jwt(claims: serde_json::Value) -> String {
        let header = BASE64_URL_SAFE_NO_PAD.encode(br#"{"alg":"RS256","typ":"JWT"}"#);
        let payload = BASE64_URL_SAFE_NO_PAD.encode(serde_json::to_vec(&claims).unwrap());
        format!("{header}.{payload}.test-signature")
    }

    fn token_response(client_id: &str, nonce: &str) -> OAuthTokenResponse {
        let expiration = Utc::now().timestamp() + 600;
        OAuthTokenResponse {
            access_token: fake_jwt(serde_json::json!({
                "sub": "account-subject-1",
                "iss": EXPECTED_ISSUER,
                "client_id": client_id,
                "exp": expiration,
            })),
            refresh_token: Some("bounded-refresh-token".to_owned()),
            id_token: Some(fake_jwt(serde_json::json!({
                "sub": "account-subject-1",
                "iss": EXPECTED_ISSUER,
                "aud": client_id,
                "nonce": nonce,
                "exp": expiration,
            }))),
            token_type: "Bearer".to_owned(),
            expires_in: 600,
        }
    }

    #[test]
    fn validates_only_supported_locales() {
        assert!(validate_request(&valid_request()).is_ok());
        let mut chinese = valid_request();
        chinese.locale = "zh-CN".to_owned();
        assert!(validate_request(&chinese).is_ok());
        let mut unsupported = valid_request();
        unsupported.locale = "fr".to_owned();
        assert!(validate_request(&unsupported).is_err());
    }

    #[test]
    fn renders_bilingual_page_without_unresolved_sensitive_placeholders() {
        for locale in ["en", "zh-CN"] {
            let mut request = valid_request();
            request.locale = locale.to_owned();
            let page = render_auth_result_page(
                &request.locale,
                desktop_auth_identity("universal").unwrap(),
                true,
                "nonce-123",
            )
            .unwrap();
            assert!(page.contains("Sign in and enter tuning workspace"));
            assert!(page.contains("登录并进入调优平台"));
            assert!(page.contains("DroneDream"));
            assert!(page.contains("nonce=\"nonce-123\""));
            assert!(page.contains("data:image/png;base64,"));
            assert!(!page.contains("__BRAND_LOCKUP_DATA_URL__"));
            assert!(!page.contains("accessToken"));
            assert!(!page.contains("refreshToken"));
            assert!(!page.contains("Cancel this sign-in"));
        }
    }

    #[test]
    fn rejects_non_get_and_body_requests() {
        let body = br#"{"state":"abc"}"#;
        let raw = format!(
            "POST /desktop-auth/abc/cancel HTTP/1.1\r\nHost: 127.0.0.1:1234\r\nOrigin: http://127.0.0.1:1234\r\nContent-Type: application/json\r\nContent-Length: {}\r\n\r\n{}",
            body.len(),
            std::str::from_utf8(body).unwrap(),
        );
        let mut cursor = Cursor::new(raw.into_bytes());
        let mut received = Vec::new();
        cursor.read_to_end(&mut received).unwrap();
        let listener = TcpListener::bind((Ipv4Addr::LOCALHOST, 0)).unwrap();
        let address = listener.local_addr().unwrap();
        let handle = thread::spawn(move || {
            let mut client = TcpStream::connect(address).unwrap();
            client.write_all(&received).unwrap();
        });
        let (mut server, _) = listener.accept().unwrap();
        let parsed = read_http_request(&mut server);
        handle.join().unwrap();
        assert!(parsed.is_err());
    }

    #[test]
    fn edition_identities_are_unique_and_brand_bound() {
        let identities = ["universal", "sim", "lab", "field", "autonomy"]
            .map(|edition| desktop_auth_identity(edition).unwrap());
        for (index, identity) in identities.iter().enumerate() {
            assert_eq!(identity.callback_port, 49210 + index as u16);
            assert!(identity.redirect_uri.contains(identity.edition_id));
            assert!(identity.bundle_identifier.ends_with(identity.edition_id));
            assert!(identity
                .credential_vault_namespace
                .contains(identity.edition_id));
            assert!(identity.brand_lockup.starts_with(b"\x89PNG\r\n\x1a\n"));
        }
        assert!(desktop_auth_identity("unknown").is_err());
    }

    #[test]
    fn computes_the_rfc7636_s256_challenge() {
        assert_eq!(
            pkce_challenge("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"),
            "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
        );
    }

    #[test]
    fn authorize_url_binds_edition_without_disclosing_verifier() {
        let identity = desktop_auth_identity("sim").unwrap();
        let url = build_authorize_url(
            identity,
            "provider-client-sim",
            "state-123",
            "nonce-123",
            "challenge-123",
        )
        .unwrap();
        let query = url
            .query_pairs()
            .map(|(key, value)| (key.into_owned(), value.into_owned()))
            .collect::<HashMap<_, _>>();
        assert_eq!(url.as_str().split('?').next(), Some(OAUTH_AUTHORIZE_URL));
        assert_eq!(
            query.get("client_id").map(String::as_str),
            Some("provider-client-sim")
        );
        assert_eq!(
            query.get("redirect_uri").map(String::as_str),
            Some(identity.redirect_uri)
        );
        assert_eq!(query.get("state").map(String::as_str), Some("state-123"));
        assert_eq!(query.get("nonce").map(String::as_str), Some("nonce-123"));
        assert_eq!(
            query.get("code_challenge").map(String::as_str),
            Some("challenge-123")
        );
        assert!(!url.as_str().contains("code_verifier"));
    }

    #[test]
    fn callback_accepts_only_code_or_denial_bound_to_state() {
        assert_eq!(
            parse_authorization_callback(
                "/desktop-auth/sim/callback?code=code-1&state=state-1",
                "/desktop-auth/sim/callback",
            )
            .unwrap(),
            AuthorizationCallback::Authorized {
                code: "code-1".to_owned(),
                state: "state-1".to_owned(),
            },
        );
        assert_eq!(
            parse_authorization_callback(
                "/desktop-auth/sim/callback?error=access_denied&state=state-1",
                "/desktop-auth/sim/callback",
            )
            .unwrap(),
            AuthorizationCallback::Denied {
                state: "state-1".to_owned(),
            },
        );
        for target in [
            "/desktop-auth/lab/callback?code=code-1&state=state-1",
            "/desktop-auth/sim/callback?code=a&code=b&state=state-1",
            "/desktop-auth/sim/callback?accessToken=secret&state=state-1",
            "/desktop-auth/sim/callback?error=access_denied",
            "/desktop-auth/sim/callback?code=code-1&state=state-1&extra=true",
        ] {
            assert!(parse_authorization_callback(target, "/desktop-auth/sim/callback").is_err());
        }
    }

    #[test]
    fn token_claims_are_bound_to_client_subject_nonce_and_expiry() {
        let client_id = "provider-client-universal";
        let nonce = "nonce-123";
        let response = token_response(client_id, nonce);
        assert_eq!(
            validate_token_response(&response, client_id, nonce).unwrap(),
            "account-subject-1",
        );
        assert!(validate_token_response(&response, "different-client", nonce).is_err());
        assert!(validate_token_response(&response, client_id, "different-nonce").is_err());

        let mut expired = token_response(client_id, nonce);
        expired.id_token = Some(fake_jwt(serde_json::json!({
            "sub": "account-subject-1",
            "iss": EXPECTED_ISSUER,
            "aud": client_id,
            "nonce": nonce,
            "exp": Utc::now().timestamp() - 1,
        })));
        assert!(validate_token_response(&expired, client_id, nonce).is_err());
    }

    #[test]
    fn oauth_token_response_uses_the_provider_snake_case_contract() {
        let response: OAuthTokenResponse = serde_json::from_value(serde_json::json!({
            "access_token": "access.token.value",
            "refresh_token": "refresh-token-value",
            "id_token": "identity.token.value",
            "token_type": "bearer",
            "expires_in": 3600,
            "scope": "openid email profile"
        }))
        .unwrap();
        assert_eq!(response.access_token, "access.token.value");
        assert_eq!(
            response.refresh_token.as_deref(),
            Some("refresh-token-value")
        );
        assert_eq!(response.id_token.as_deref(), Some("identity.token.value"));
        assert_eq!(response.token_type, "bearer");
        assert_eq!(response.expires_in, 3600);

        assert!(
            serde_json::from_value::<OAuthTokenResponse>(serde_json::json!({
                "accessToken": "access.token.value",
                "refreshToken": "refresh-token-value",
                "idToken": "identity.token.value",
                "tokenType": "bearer",
                "expiresIn": 3600
            }))
            .is_err()
        );
    }

    #[test]
    fn refresh_response_accepts_rotated_or_unchanged_refresh_without_an_id_token() {
        let client_id = "registered-universal-client";
        let mut response = token_response(client_id, "unused-for-refresh");
        response.refresh_token = None;
        response.id_token = None;

        assert_eq!(
            validate_access_token_response(&response, client_id).unwrap(),
            "account-subject-1"
        );
        assert!(validate_token_response(&response, client_id, "unused-for-refresh").is_err());
    }

    #[test]
    fn only_permanent_token_rejections_may_invalidate_a_stored_session() {
        for status in [
            StatusCode::BAD_REQUEST,
            StatusCode::UNAUTHORIZED,
            StatusCode::FORBIDDEN,
        ] {
            assert!(token_status_is_credential_rejection(status));
        }
        for status in [
            StatusCode::NOT_FOUND,
            StatusCode::TOO_MANY_REQUESTS,
            StatusCode::INTERNAL_SERVER_ERROR,
            StatusCode::SERVICE_UNAVAILABLE,
        ] {
            assert!(!token_status_is_credential_rejection(status));
        }
    }

    #[test]
    fn audit_failure_codes_are_stable_and_do_not_embed_error_text() {
        for (message, code) in [
            ("Browser sign-in was denied or cancelled.", "user_denied"),
            ("Browser sign-in was cancelled.", "cancelled"),
            ("Browser sign-in timed out.", "timeout"),
            (
                "The universal browser sign-in callback is already in use.",
                "callback_in_use",
            ),
            (
                "The desktop bundle identity does not match.",
                "edition_identity_mismatch",
            ),
            ("Could not open the system browser.", "browser_open_failed"),
            (
                "The identity binding does not match the account subject.",
                "account_binding_failed",
            ),
            ("Credential vault write failed.", "credential_vault_failed"),
            ("Token endpoint failed.", "token_exchange_failed"),
            ("The local callback failed.", "callback_failed"),
            ("opaque implementation detail", "internal_failure"),
        ] {
            assert_eq!(browser_auth_failure_code(message), code);
            assert!(browser_auth_failure_code(message).bytes().all(|byte| {
                byte.is_ascii_lowercase() || byte.is_ascii_digit() || byte == b'_'
            }));
        }
    }

    #[test]
    fn renders_each_edition_result_without_credentials_or_raw_tokens() {
        for locale in ["en", "zh-CN"] {
            for edition in ["universal", "sim", "lab", "field", "autonomy"] {
                let identity = desktop_auth_identity(edition).unwrap();
                let page = render_auth_result_page(locale, identity, true, "nonce-123").unwrap();
                assert!(page.contains(identity.display_name));
                assert!(page.contains("nonce=\"nonce-123\""));
                assert!(page.contains("data:image/png;base64,"));
                assert!(!page.contains("accessToken"));
                assert!(!page.contains("refreshToken"));
                assert!(!page.contains("password"));
                assert!(!page.contains("Cancel this sign-in"));
            }
        }
    }

    #[test]
    fn constant_time_state_comparison_rejects_length_and_byte_changes() {
        assert!(constant_time_equal(b"same", b"same"));
        assert!(!constant_time_equal(b"same", b"samf"));
        assert!(!constant_time_equal(b"same", b"same-longer"));
    }
}
