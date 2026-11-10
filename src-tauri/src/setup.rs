use serde::{Deserialize, Serialize};
use std::io::{BufRead, BufReader};
use std::net::{SocketAddr, TcpStream};
use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::time::Duration;
use tauri::{AppHandle, Emitter, WebviewWindow};

use crate::gpu;

#[cfg(windows)]
use std::os::windows::process::CommandExt;

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct SetupProgressEvent {
    pub percent: u32,
    pub step: u32,
    pub total_steps: u32,
    pub message: String,
    pub log: String,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct SetupInfo {
    pub gpu_name: String,
    pub vram_mb: u64,
    pub recommended_encoder: String,
    pub whisper_device: String,
    pub is_ready: bool,
    pub app_dir: String,
}

pub fn get_app_dir() -> PathBuf {
    if let Ok(exe_path) = std::env::current_exe() {
        if let Some(parent) = exe_path.parent() {
            if parent.join("src").exists() || parent.join("scripts").exists() {
                return parent.to_path_buf();
            }
        }
    }
    std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."))
}

pub fn is_environment_ready() -> bool {
    let base_dir = get_app_dir();

    // 1. Check for Python runtime
    let has_python = base_dir.join("runtime\\python.exe").exists()
        || base_dir.join(".venv\\Scripts\\python.exe").exists();

    if !has_python {
        return false;
    }

    // 2. Check for FFmpeg
    let has_ffmpeg = base_dir.join("bin\\ffmpeg.exe").exists()
        || Command::new("ffmpeg").arg("-version").output().is_ok();

    if !has_ffmpeg {
        return false;
    }

    // 3. Quick test if backend file exists
    if !base_dir.join("src\\web_studio.py").exists() {
        return false;
    }

    true
}

#[tauri::command]
pub fn get_setup_info() -> SetupInfo {
    let app_dir = get_app_dir();
    let gpus = gpu::detect_gpus();

    let mut gpu_name = "Standard Prozessor (CPU)".to_string();
    let mut vram_mb = 0;
    let mut recommended_encoder = "cpu".to_string();
    let mut whisper_device = "cpu".to_string();

    for g in &gpus {
        if g.vendor == "nvidia" {
            gpu_name = g.name.clone();
            vram_mb = g.ram_mb;
            recommended_encoder = "nvenc".to_string();
            whisper_device = "cuda".to_string();
            break;
        } else if g.vendor == "amd" && recommended_encoder == "cpu" {
            gpu_name = g.name.clone();
            vram_mb = g.ram_mb;
            recommended_encoder = "amf".to_string();
        } else if g.vendor == "intel" && recommended_encoder == "cpu" {
            gpu_name = g.name.clone();
            vram_mb = g.ram_mb;
            recommended_encoder = "qsv".to_string();
        }
    }

    if gpu_name == "Standard Prozessor (CPU)" && !gpus.is_empty() {
        gpu_name = gpus[0].name.clone();
        vram_mb = gpus[0].ram_mb;
    }

    SetupInfo {
        gpu_name,
        vram_mb,
        recommended_encoder,
        whisper_device,
        is_ready: is_environment_ready(),
        app_dir: app_dir.to_string_lossy().to_string(),
    }
}

#[tauri::command]
pub async fn run_automated_setup(app: AppHandle) -> Result<bool, String> {
    let app_dir = get_app_dir();
    let script_path = app_dir.join("scripts\\setup_pc.ps1");

    if !script_path.exists() {
        return Err(format!("Setup-Skript nicht gefunden: {:?}", script_path));
    }

    #[cfg(windows)]
    const CREATE_NO_WINDOW: u32 = 0x08000000;

    let mut cmd = Command::new("powershell.exe");
    cmd.args([
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        &script_path.to_string_lossy(),
    ])
    .current_dir(&app_dir)
    .stdout(Stdio::piped())
    .stderr(Stdio::piped());

    #[cfg(windows)]
    cmd.creation_flags(CREATE_NO_WINDOW);

    let mut child = cmd.spawn().map_err(|e| format!("Fehler beim Starten von PowerShell: {}", e))?;

    if let Some(stdout) = child.stdout.take() {
        let reader = BufReader::new(stdout);
        for line in reader.lines().flatten() {
            let trimmed = line.trim();
            if let Some(progress_json) = trimmed.strip_prefix("PROGRESS:") {
                if let Ok(evt) = serde_json::from_str::<SetupProgressEvent>(progress_json) {
                    let _ = app.emit("setup-progress", evt);
                }
            } else if !trimmed.is_empty() {
                let evt = SetupProgressEvent {
                    percent: 50,
                    step: 4,
                    total_steps: 5,
                    message: "Installation wird ausgeführt...".to_string(),
                    log: trimmed.to_string(),
                };
                let _ = app.emit("setup-progress", evt);
            }
        }
    }

    let status = child.wait().map_err(|e| format!("Fehler beim Warten auf Setup: {}", e))?;
    Ok(status.success())
}

#[tauri::command]
pub async fn launch_studio_after_setup(window: WebviewWindow) -> Result<bool, String> {
    let app_dir = get_app_dir();

    // Check if port 5000 is open
    let addr: SocketAddr = "127.0.0.1:5000".parse().unwrap();
    let is_running = TcpStream::connect_timeout(&addr, Duration::from_millis(200)).is_ok();

    if !is_running {
        let py_path = if app_dir.join("runtime\\python.exe").exists() {
            app_dir.join("runtime\\python.exe")
        } else if app_dir.join(".venv\\Scripts\\python.exe").exists() {
            app_dir.join(".venv\\Scripts\\python.exe")
        } else {
            PathBuf::from("python")
        };

        #[cfg(windows)]
        {
            const CREATE_NO_WINDOW: u32 = 0x08000000;
            let _ = Command::new(py_path)
                .current_dir(&app_dir)
                .args(["-m", "src.web_studio"])
                .creation_flags(CREATE_NO_WINDOW)
                .spawn();
        }

        #[cfg(not(windows))]
        {
            let _ = Command::new(py_path)
                .current_dir(&app_dir)
                .args(["-m", "src.web_studio"])
                .spawn();
        }

        // Wait up to 12 seconds for Flask to respond
        for _ in 0..120 {
            if TcpStream::connect_timeout(&addr, Duration::from_millis(100)).is_ok() {
                std::thread::sleep(Duration::from_millis(300));
                break;
            }
            std::thread::sleep(Duration::from_millis(100));
        }
    }

    // Navigate to Studio
    if let Ok(url) = tauri::Url::parse("http://127.0.0.1:5000") {
        let _ = window.navigate(url);
    }

    Ok(true)
}
