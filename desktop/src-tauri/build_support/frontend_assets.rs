use std::path::{Path, PathBuf};

// 功能：
//   1. 要求桌面前端以相对目录嵌入，拒绝可能被 Tauri 优先解析成 URL 的盘符路径。
//   2. 禁止外部网址、UNC 路径和文件列表代替产品页面；目录必须包含 index.html。
// 输入：
//   frontend_dist：合并配置中的前端目录字符串。
//   config_dir：规范 tauri.conf.json 所在目录，不是临时覆盖配置所在目录。
// 输出：
//   result：有效前端目录，或阻止生成错误 EXE 的明确错误信息。
pub fn validate_embedded_frontend(frontend_dist: &str, config_dir: &Path) -> Result<PathBuf, String> {
    if frontend_dist.is_empty()
        || frontend_dist.trim() != frontend_dist
        || frontend_dist.contains(':')
        || frontend_dist.starts_with(['/', '\\'])
    {
        return Err("frontendDist must be a relative asset directory, not a URL or absolute path; Windows drive prefixes can be interpreted as URL schemes".into());
    }
    let directory = config_dir.join(frontend_dist);
    if !directory.join("index.html").is_file() {
        return Err(format!("frontendDist has no index.html: {}", directory.display()));
    }
    Ok(directory)
}

#[cfg(test)]
mod tests {
    use super::*;

    // 功能：
    //   复现盘符被当作 URL 的配置，并覆盖网页、文件 URL、UNC、空路径边界。
    // 输入：
    //   无；不安全路径集在测试内部给出。
    // 输出：
    //   无；任一不安全路径未被拒绝时测试失败。
    #[test]
    fn rejects_nonembedded_destinations() {
        for path in ["Q:/Build/frontend", "Q:\\Build\\frontend", "https://example.com", "file:///Q:/Build", "//server/share", "\\\\server\\share", "/tmp/frontend", "", " ../frontend"] {
            assert!(validate_embedded_frontend(path, Path::new(".")).is_err(), "accepted {path}");
        }
    }

    // 功能：
    //   证明相对目录需要真实入口文件，不会把不存在的页面误判为已嵌入。
    // 输入：
    //   无；使用系统临时目录中的独立测试目录及测试入口。
    // 输出：
    //   无；入口存在时通过，入口缺失时拒绝。
    #[test]
    fn requires_an_actual_relative_entrypoint() {
        let root = std::env::temp_dir().join(format!("dronedream-frontend-guard-{}", std::process::id()));
        std::fs::create_dir(&root).unwrap();
        let dist = root.join("dist");
        std::fs::create_dir(&dist).unwrap();
        assert!(validate_embedded_frontend("dist", &root).is_err());
        let entry = dist.join("index.html");
        std::fs::write(&entry, "<html></html>").unwrap();
        assert_eq!(validate_embedded_frontend("dist", &root).unwrap(), dist);
        std::fs::remove_file(entry).unwrap();
        std::fs::remove_dir(dist).unwrap();
        std::fs::remove_dir(root).unwrap();
    }
}
