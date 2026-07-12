use std::path::PathBuf;

fn main() {
    let manifest_dir = PathBuf::from(
        std::env::var("CARGO_MANIFEST_DIR").expect("Cargo must set CARGO_MANIFEST_DIR"),
    );
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
