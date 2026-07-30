use base64::{
    engine::general_purpose::{
        STANDARD as BASE64_STANDARD, URL_SAFE_NO_PAD as BASE64_URL_SAFE_NO_PAD,
    },
    Engine as _,
};
use serde::{Deserialize, Serialize};
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

const AUTH_PAGE_TEMPLATE: &str = include_str!("../browser-auth.html");
const BRAND_LOCKUP: &[u8] =
    include_bytes!("../../../frontend/src/assets/drone-dream-lockup-compact.png");
const EXPECTED_SUPABASE_URL: &str = "https://yggabfynndpzymlqvnim.supabase.co";
const HOMEPAGE_URL: &str = "http://getdronedream.com/";
const AUTH_TIMEOUT: Duration = Duration::from_secs(10 * 60);
const MAX_HEADER_BYTES: usize = 32 * 1024;
const MAX_BODY_BYTES: usize = 48 * 1024;
const MAX_TOKEN_BYTES: usize = 16 * 1024;

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
    supabase_url: String,
    publishable_key: String,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct BrowserAuthSession {
    access_token: String,
    refresh_token: String,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct BrowserAuthPayload {
    state: String,
    access_token: String,
    refresh_token: String,
}

#[derive(Deserialize)]
struct BrowserAuthCancelPayload {
    state: String,
}

struct HttpRequest {
    method: String,
    target: String,
    headers: HashMap<String, String>,
    body: Vec<u8>,
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

fn validate_request(request: &BrowserAuthRequest) -> Result<(), String> {
    if request.locale != "en" && request.locale != "zh-CN" {
        return Err("Browser sign-in locale must be en or zh-CN.".to_owned());
    }
    if request.supabase_url.trim_end_matches('/') != EXPECTED_SUPABASE_URL {
        return Err("Browser sign-in is not bound to the approved account service.".to_owned());
    }
    let key = request.publishable_key.as_str();
    if key.len() < 20
        || key.len() > 4096
        || key.contains(char::is_whitespace)
        || key.chars().any(char::is_control)
        || key.to_ascii_lowercase().contains("placeholder")
        || key.to_ascii_lowercase().contains("desktop_only")
        || key.to_ascii_lowercase().contains("change_me")
        || key.starts_with("sb_secret_")
        || jwt_role(key).as_deref() == Some("service_role")
    {
        return Err("Browser sign-in requires the real public account configuration.".to_owned());
    }
    Ok(())
}

fn jwt_role(token: &str) -> Option<String> {
    let payload = token.split('.').nth(1)?;
    let decoded = BASE64_URL_SAFE_NO_PAD.decode(payload).ok()?;
    let value: serde_json::Value = serde_json::from_slice(&decoded).ok()?;
    value.get("role")?.as_str().map(ToOwned::to_owned)
}

fn run_browser_auth(
    app: AppHandle,
    request: BrowserAuthRequest,
    cancelled: Arc<AtomicBool>,
) -> Result<BrowserAuthSession, String> {
    let listener = TcpListener::bind((Ipv4Addr::LOCALHOST, 0))
        .map_err(|error| format!("Could not start the local sign-in callback: {error}"))?;
    listener
        .set_nonblocking(true)
        .map_err(|error| format!("Could not configure the local sign-in callback: {error}"))?;
    let port = listener
        .local_addr()
        .map_err(|error| format!("Could not read the local sign-in address: {error}"))?
        .port();
    let state = format!("{}{}", Uuid::new_v4().simple(), Uuid::new_v4().simple());
    let nonce = Uuid::new_v4().simple().to_string();
    let page_path = format!("/desktop-auth/{state}");
    let complete_path = format!("{page_path}/complete");
    let cancel_path = format!("{page_path}/cancel");
    let origin = format!("http://127.0.0.1:{port}");
    let page_url = format!("{origin}{page_path}");
    let page = render_auth_page(&request, &state, &nonce, &complete_path, &cancel_path)?;

    app.opener()
        .open_url(page_url, None::<&str>)
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
                    .map_err(|error| format!("Could not secure the sign-in connection: {error}"))?;
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
                if !host_is_exact(&request_message, port) {
                    let _ = write_text_response(
                        &mut stream,
                        421,
                        "Misdirected Request",
                        "text/plain; charset=utf-8",
                        b"Invalid local sign-in host.",
                        &nonce,
                    );
                    continue;
                }
                if request_message.method == "GET" && request_message.target == page_path {
                    let _ = write_html_response(&mut stream, page.as_bytes(), &nonce);
                    continue;
                }
                if request_message.method == "GET"
                    && request_message.target.starts_with("/favicon.ico")
                {
                    let _ = write_empty_response(&mut stream, 204, "No Content", &nonce);
                    continue;
                }
                if request_message.method == "POST" && request_message.target == complete_path {
                    if require_same_origin(&request_message, &origin).is_err() {
                        let _ = write_text_response(
                            &mut stream,
                            403,
                            "Forbidden",
                            "text/plain; charset=utf-8",
                            b"Invalid local sign-in origin.",
                            &nonce,
                        );
                        continue;
                    }
                    let payload: BrowserAuthPayload =
                        match serde_json::from_slice(&request_message.body) {
                            Ok(payload) => payload,
                            Err(_) => {
                                let _ = write_text_response(
                                    &mut stream,
                                    400,
                                    "Bad Request",
                                    "text/plain; charset=utf-8",
                                    b"Invalid sign-in result.",
                                    &nonce,
                                );
                                continue;
                            }
                        };
                    if !constant_time_equal(payload.state.as_bytes(), state.as_bytes()) {
                        let _ = write_text_response(
                            &mut stream,
                            403,
                            "Forbidden",
                            "text/plain; charset=utf-8",
                            b"Invalid sign-in state.",
                            &nonce,
                        );
                        continue;
                    }
                    if validate_token("access token", &payload.access_token).is_err()
                        || validate_token("refresh token", &payload.refresh_token).is_err()
                    {
                        let _ = write_text_response(
                            &mut stream,
                            400,
                            "Bad Request",
                            "text/plain; charset=utf-8",
                            b"Invalid sign-in tokens.",
                            &nonce,
                        );
                        continue;
                    }
                    let _ = write_json_response(
                        &mut stream,
                        200,
                        "OK",
                        br#"{"accepted":true}"#,
                        &nonce,
                    );
                    return Ok(BrowserAuthSession {
                        access_token: payload.access_token,
                        refresh_token: payload.refresh_token,
                    });
                }
                if request_message.method == "POST" && request_message.target == cancel_path {
                    if require_same_origin(&request_message, &origin).is_err() {
                        let _ = write_text_response(
                            &mut stream,
                            403,
                            "Forbidden",
                            "text/plain; charset=utf-8",
                            b"Invalid local sign-in origin.",
                            &nonce,
                        );
                        continue;
                    }
                    let payload: BrowserAuthCancelPayload =
                        match serde_json::from_slice(&request_message.body) {
                            Ok(payload) => payload,
                            Err(_) => {
                                let _ = write_text_response(
                                    &mut stream,
                                    400,
                                    "Bad Request",
                                    "text/plain; charset=utf-8",
                                    b"Invalid sign-in cancellation.",
                                    &nonce,
                                );
                                continue;
                            }
                        };
                    if constant_time_equal(payload.state.as_bytes(), state.as_bytes()) {
                        let _ = write_json_response(
                            &mut stream,
                            200,
                            "OK",
                            br#"{"cancelled":true}"#,
                            &nonce,
                        );
                        return Err("Browser sign-in was cancelled.".to_owned());
                    }
                    let _ = write_text_response(
                        &mut stream,
                        403,
                        "Forbidden",
                        "text/plain; charset=utf-8",
                        b"Invalid sign-in state.",
                        &nonce,
                    );
                    continue;
                }
                let _ = write_text_response(
                    &mut stream,
                    404,
                    "Not Found",
                    "text/plain; charset=utf-8",
                    b"Not found.",
                    &nonce,
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
}

fn render_auth_page(
    request: &BrowserAuthRequest,
    state: &str,
    nonce: &str,
    complete_path: &str,
    cancel_path: &str,
) -> Result<String, String> {
    let replacements = [
        ("__DOCUMENT_LANGUAGE__", request.locale.as_str().to_owned()),
        ("__CSP_NONCE__", nonce.to_owned()),
        (
            "__BRAND_LOCKUP_DATA_URL__",
            format!(
                "data:image/png;base64,{}",
                BASE64_STANDARD.encode(BRAND_LOCKUP)
            ),
        ),
        (
            "__LOCALE_JSON__",
            serde_json::to_string(&request.locale)
                .map_err(|error| format!("Could not render sign-in locale: {error}"))?,
        ),
        (
            "__STATE_JSON__",
            serde_json::to_string(state)
                .map_err(|error| format!("Could not render sign-in state: {error}"))?,
        ),
        (
            "__SUPABASE_URL_JSON__",
            serde_json::to_string(EXPECTED_SUPABASE_URL)
                .map_err(|error| format!("Could not render account URL: {error}"))?,
        ),
        (
            "__PUBLISHABLE_KEY_JSON__",
            serde_json::to_string(&request.publishable_key)
                .map_err(|error| format!("Could not render account configuration: {error}"))?,
        ),
        (
            "__COMPLETE_PATH_JSON__",
            serde_json::to_string(complete_path)
                .map_err(|error| format!("Could not render sign-in callback: {error}"))?,
        ),
        (
            "__CANCEL_PATH_JSON__",
            serde_json::to_string(cancel_path)
                .map_err(|error| format!("Could not render sign-in cancellation: {error}"))?,
        ),
        (
            "__HOME_URL_JSON__",
            serde_json::to_string(HOMEPAGE_URL)
                .map_err(|error| format!("Could not render homepage URL: {error}"))?,
        ),
    ];
    let mut page = AUTH_PAGE_TEMPLATE.to_owned();
    for (placeholder, replacement) in replacements {
        page = page.replace(placeholder, &replacement);
    }
    if page.contains("__CSP_NONCE__")
        || page.contains("__STATE_JSON__")
        || page.contains("__PUBLISHABLE_KEY_JSON__")
        || page.contains("__BRAND_LOCKUP_DATA_URL__")
    {
        return Err("The browser sign-in page was not rendered completely.".to_owned());
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
        if received.len() > MAX_HEADER_BYTES + MAX_BODY_BYTES {
            return Err("Browser sign-in request is too large.".to_owned());
        }
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
    if method != "GET" && method != "POST" {
        return Err("Browser sign-in request method is not allowed.".to_owned());
    }
    let target = parts[1].to_owned();
    if !target.starts_with('/') || target.len() > 512 || target.contains(char::is_whitespace) {
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
    if content_length > MAX_BODY_BYTES {
        return Err("Browser sign-in request body is too large.".to_owned());
    }
    if method == "POST"
        && headers
            .get("content-type")
            .map(|value| !value.eq_ignore_ascii_case("application/json"))
            .unwrap_or(true)
    {
        return Err("Browser sign-in POST must contain JSON.".to_owned());
    }
    while received.len() - header_end < content_length {
        let count = stream
            .read(&mut buffer)
            .map_err(|error| format!("Could not read browser request body: {error}"))?;
        if count == 0 {
            return Err("Browser sign-in request body ended early.".to_owned());
        }
        received.extend_from_slice(&buffer[..count]);
        if received.len() - header_end > MAX_BODY_BYTES {
            return Err("Browser sign-in request body is too large.".to_owned());
        }
    }
    Ok(HttpRequest {
        method,
        target,
        headers,
        body: received[header_end..header_end + content_length].to_vec(),
    })
}

fn require_same_origin(request: &HttpRequest, origin: &str) -> Result<(), String> {
    if request.headers.get("origin").map(String::as_str) != Some(origin) {
        return Err("Browser sign-in request did not come from the local page.".to_owned());
    }
    Ok(())
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

fn write_json_response(
    stream: &mut TcpStream,
    status: u16,
    reason: &str,
    body: &[u8],
    nonce: &str,
) -> Result<(), String> {
    write_text_response(
        stream,
        status,
        reason,
        "application/json; charset=utf-8",
        body,
        nonce,
    )
}

fn write_empty_response(
    stream: &mut TcpStream,
    status: u16,
    reason: &str,
    nonce: &str,
) -> Result<(), String> {
    write_text_response(
        stream,
        status,
        reason,
        "text/plain; charset=utf-8",
        &[],
        nonce,
    )
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
         Content-Security-Policy: default-src 'none'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'; form-action 'self'; connect-src 'self' {EXPECTED_SUPABASE_URL}; script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; img-src data:; font-src 'none'\r\n\
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
            supabase_url: EXPECTED_SUPABASE_URL.to_owned(),
            publishable_key: "sb_publishable_browser_auth_contract_20260730".to_owned(),
        }
    }

    #[test]
    fn validates_exact_account_project_and_real_public_configuration() {
        assert!(validate_request(&valid_request()).is_ok());
        let mut wrong_origin = valid_request();
        wrong_origin.supabase_url = "https://example.supabase.co".to_owned();
        assert!(validate_request(&wrong_origin).is_err());
        let mut placeholder = valid_request();
        placeholder.publishable_key = "sb_publishable_ci_desktop_only".to_owned();
        assert!(validate_request(&placeholder).is_err());
        let mut secret = valid_request();
        secret.publishable_key =
            "eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoic2VydmljZV9yb2xlIn0.signature".to_owned();
        assert!(validate_request(&secret).is_err());
    }

    #[test]
    fn renders_bilingual_page_without_unresolved_sensitive_placeholders() {
        for locale in ["en", "zh-CN"] {
            let mut request = valid_request();
            request.locale = locale.to_owned();
            let page = render_auth_page(&request, "state-123", "nonce-123", "/complete", "/cancel")
                .unwrap();
            assert!(page.contains("Sign in and enter tuning workspace"));
            assert!(page.contains("登录并进入调优平台"));
            assert!(page.contains("state-123"));
            assert!(page.contains("nonce=\"nonce-123\""));
            assert!(page.contains("data:image/png;base64,"));
            assert!(!page.contains("__PUBLISHABLE_KEY_JSON__"));
            assert!(!page.contains("service_role"));
        }
    }

    #[test]
    fn parses_only_bounded_non_chunked_json_requests() {
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
        let parsed = read_http_request(&mut server).unwrap();
        handle.join().unwrap();
        assert_eq!(parsed.method, "POST");
        assert_eq!(parsed.target, "/desktop-auth/abc/cancel");
        assert_eq!(parsed.body, body);
    }

    #[test]
    fn constant_time_state_comparison_rejects_length_and_byte_changes() {
        assert!(constant_time_equal(b"same", b"same"));
        assert!(!constant_time_equal(b"same", b"samf"));
        assert!(!constant_time_equal(b"same", b"same-longer"));
    }
}
