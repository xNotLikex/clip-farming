// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::net::{SocketAddr, TcpStream};
use std::path::Path;
use std::process::Command;
use std::time::Duration;

#[cfg(windows)]
use std::os::windows::process::CommandExt;

fn ensure_backend_running() {
    // Check if worker port 5000 is already active
    if let Ok(addr) = "127.0.0.1:5000".parse::<SocketAddr>() {
        if TcpStream::connect_timeout(&addr, Duration::from_millis(200)).is_ok() {
            return; // Worker already running!
        }
    }

    // Determine python interpreter path
    let py_path = if Path::new(".venv\\Scripts\\python.exe").exists() {
        ".venv\\Scripts\\python.exe"
    } else if Path::new("..\\.venv\\Scripts\\python.exe").exists() {
        "..\\.venv\\Scripts\\python.exe"
    } else {
        "python"
    };

    #[cfg(windows)]
    {
        const CREATE_NO_WINDOW: u32 = 0x08000000;
        let _ = Command::new(py_path)
            .args(["-m", "src.web_studio"])
            .creation_flags(CREATE_NO_WINDOW)
            .spawn();
    }

    #[cfg(not(windows))]
    {
        let _ = Command::new(py_path)
            .args(["-m", "src.web_studio"])
            .spawn();
    }
}

fn main() {
    ensure_backend_running();
    clip_farming_lib::run();
}
