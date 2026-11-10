// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::net::{SocketAddr, TcpStream};
use std::path::PathBuf;
use std::process::Command;
use std::time::Duration;

#[cfg(windows)]
use std::os::windows::process::CommandExt;

fn clear_webview_cache() {
    #[cfg(windows)]
    {
        if let Ok(local_appdata) = std::env::var("LOCALAPPDATA") {
            let cache_dir = PathBuf::from(local_appdata).join("com.notlike.clipfarming");
            if cache_dir.exists() {
                let _ = std::fs::remove_dir_all(&cache_dir);
            }
        }
    }
}

fn ensure_backend_running() {
    // Check if worker port 5000 is already active
    if let Ok(addr) = "127.0.0.1:5000".parse::<SocketAddr>() {
        if TcpStream::connect_timeout(&addr, Duration::from_millis(200)).is_ok() {
            return; // Worker already running!
        }
    }

    let mut working_dir = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
    if let Ok(exe_path) = std::env::current_exe() {
        if let Some(exe_dir) = exe_path.parent() {
            if exe_dir.join("src").exists() {
                working_dir = exe_dir.to_path_buf();
            }
        }
    }

    let py_path = if working_dir.join("runtime\\python.exe").exists() {
        working_dir.join("runtime\\python.exe")
    } else if working_dir.join(".venv\\Scripts\\python.exe").exists() {
        working_dir.join(".venv\\Scripts\\python.exe")
    } else if working_dir.join("..\\.venv\\Scripts\\python.exe").exists() {
        working_dir.join("..\\.venv\\Scripts\\python.exe")
    } else {
        PathBuf::from("python")
    };

    #[cfg(windows)]
    {
        const CREATE_NO_WINDOW: u32 = 0x08000000;
        let _ = Command::new(py_path)
            .current_dir(&working_dir)
            .args(["-m", "src.web_studio"])
            .creation_flags(CREATE_NO_WINDOW)
            .spawn();
    }

    #[cfg(not(windows))]
    {
        let _ = Command::new(py_path)
            .current_dir(&working_dir)
            .args(["-m", "src.web_studio"])
            .spawn();
    }

    // Wait up to 10 seconds for backend to become ready
    if let Ok(addr) = "127.0.0.1:5000".parse::<SocketAddr>() {
        for _ in 0..100 {
            if TcpStream::connect_timeout(&addr, Duration::from_millis(100)).is_ok() {
                std::thread::sleep(Duration::from_millis(200));
                break;
            }
            std::thread::sleep(Duration::from_millis(100));
        }
    }
}

fn main() {
    clear_webview_cache();
    if let Ok(exe_path) = std::env::current_exe() {
        if let Some(exe_dir) = exe_path.parent() {
            if exe_dir.join("src").exists() || exe_dir.join("data").exists() {
                let _ = std::env::set_current_dir(exe_dir);
            }
        }
    }
    ensure_backend_running();
    clip_farming_lib::run();
}
