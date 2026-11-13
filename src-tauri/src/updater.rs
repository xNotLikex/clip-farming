use serde_json::{json, Value};
use std::io::Write;
use std::process::Command;

const GITHUB_RELEASE_URL: &str =
    "https://api.github.com/repos/xNotLikex/clip-farming/releases/latest";

fn parse_semver(v: &str) -> (u64, u64, u64) {
    let clean = v.trim().trim_start_matches('v').trim_start_matches('V');
    let parts: Vec<u64> = clean
        .split('.')
        .map(|p| {
            p.split('-')
                .next()
                .unwrap_or("0")
                .parse::<u64>()
                .unwrap_or(0)
        })
        .collect();
    (
        parts.first().copied().unwrap_or(0),
        parts.get(1).copied().unwrap_or(0),
        parts.get(2).copied().unwrap_or(0),
    )
}

pub async fn check_for_update() -> Result<Value, String> {
    let current = env!("CARGO_PKG_VERSION");
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(10))
        .build()
        .map_err(|e| format!("HTTP Client Fehler: {e}"))?;

    let resp = client
        .get(GITHUB_RELEASE_URL)
        .header("User-Agent", "Clip-Farming-Studio")
        .header("Accept", "application/vnd.github+json")
        .send()
        .await
        .map_err(|e| format!("Update-Check fehlgeschlagen: {e}"))?;

    if !resp.status().is_success() {
        return Err(format!("GitHub API Fehler: HTTP {}", resp.status()));
    }

    let data: Value = resp
        .json()
        .await
        .map_err(|e| format!("Ungültige GitHub-Antwort: {e}"))?;

    let tag = data
        .get("tag_name")
        .and_then(|v| v.as_str())
        .unwrap_or(current);
    let latest = tag.trim().trim_start_matches('v').trim_start_matches('V');
    let update_available = parse_semver(latest) > parse_semver(current);

    let mut download_url = String::new();
    let mut asset_name = String::new();
    if let Some(assets) = data.get("assets").and_then(|a| a.as_array()) {
        // Bevorzuge NSIS setup.exe, fallback auf .msi, fallback auf .zip (Portable)
        for ext in [".exe", ".msi", ".zip"] {
            if let Some(found) = assets.iter().find(|a| {
                a.get("name")
                    .and_then(|n| n.as_str())
                    .map(|n| n.to_lowercase().ends_with(ext))
                    .unwrap_or(false)
            }) {
                download_url = found
                    .get("browser_download_url")
                    .and_then(|u| u.as_str())
                    .unwrap_or("")
                    .to_string();
                asset_name = found
                    .get("name")
                    .and_then(|n| n.as_str())
                    .unwrap_or("")
                    .to_string();
                break;
            }
        }
    }

    let release_notes = data
        .get("body")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();

    let html_url = data
        .get("html_url")
        .and_then(|v| v.as_str())
        .unwrap_or("https://github.com/xNotLikex/clip-farming/releases/latest")
        .to_string();

    Ok(json!({
        "update_available": update_available,
        "current_version": current,
        "latest_version": latest,
        "download_url": download_url,
        "asset_name": asset_name,
        "release_notes": release_notes,
        "html_url": html_url
    }))
}

pub async fn download_and_launch_update(download_url: &str) -> Result<Value, String> {
    if download_url.is_empty() || !download_url.starts_with("https://") {
        return Err("Ungültige Download-URL für Update.".to_string());
    }

    let filename = download_url
        .split('/')
        .next_back()
        .filter(|s| s.ends_with(".exe") || s.ends_with(".msi") || s.ends_with(".zip"))
        .unwrap_or("clip-farming-update.exe");

    let target = std::env::temp_dir().join(filename);
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(300))
        .build()
        .map_err(|e| e.to_string())?;

    let mut resp = client
        .get(download_url)
        .header("User-Agent", "Clip-Farming-Studio")
        .send()
        .await
        .map_err(|e| format!("Update-Download fehlgeschlagen: {e}"))?;

    if !resp.status().is_success() {
        return Err(format!("Update-Download HTTP {}", resp.status()));
    }

    let mut file = std::fs::File::create(&target).map_err(|e| e.to_string())?;
    while let Some(chunk) = resp.chunk().await.map_err(|e| e.to_string())? {
        file.write_all(&chunk).map_err(|e| e.to_string())?;
    }
    file.flush().map_err(|e| e.to_string())?;
    drop(file);

    if filename.ends_with(".msi") {
        Command::new("msiexec")
            .arg("/i")
            .arg(&target)
            .spawn()
            .map_err(|e| format!("MSI-Installer konnte nicht gestartet werden: {e}"))?;
    } else if filename.ends_with(".exe") {
        Command::new(&target)
            .spawn()
            .map_err(|e| format!("Setup-Installer konnte nicht gestartet werden: {e}"))?;
    } else {
        let _ = Command::new("explorer").arg(format!("/select,{}", target.display())).spawn();
    }

    tokio::spawn(async {
        tokio::time::sleep(std::time::Duration::from_millis(600)).await;
        std::process::exit(0);
    });

    Ok(json!({
        "ok": true,
        "status": "launching_installer",
        "installer_path": target.to_string_lossy()
    }))
}
