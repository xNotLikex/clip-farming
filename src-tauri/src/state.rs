use chrono::Local;
use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet};
use std::sync::{Arc, Mutex, OnceLock};
use tauri::{AppHandle, Emitter};

const MAX_LOG_LINES: usize = 80;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StatusState {
    pub is_running: bool,
    pub phase: String,
    pub status: String,
    pub message: String,
    pub current_task: String,
    pub clip_title: String,
    pub streamer: String,
    pub percent: i32,
    pub progress_percent: i32,
    pub eta_seconds: i64,
    pub speed: String,
    pub clip_id: String,
    pub last_run: Option<String>,
    pub logs: Vec<String>,
}

impl Default for StatusState {
    fn default() -> Self {
        Self {
            is_running: false,
            phase: "idle".to_string(),
            status: "idle".to_string(),
            message: "Bereit".to_string(),
            current_task: "Bereit zur Ausführung".to_string(),
            clip_title: String::new(),
            streamer: String::new(),
            percent: 0,
            progress_percent: 0,
            eta_seconds: 0,
            speed: String::new(),
            clip_id: String::new(),
            last_run: None,
            logs: Vec::new(),
        }
    }
}

pub struct StatusManager {
    inner: Mutex<StatusState>,
    app_handle: Mutex<Option<AppHandle>>,
}

impl StatusManager {
    fn new() -> Self {
        Self {
            inner: Mutex::new(StatusState::default()),
            app_handle: Mutex::new(None),
        }
    }

    pub fn set_app_handle(&self, app: AppHandle) {
        if let Ok(mut guard) = self.app_handle.lock() {
            *guard = Some(app);
        }
    }

    fn emit_state(&self, snapshot: &StatusState) {
        if let Ok(guard) = self.app_handle.lock() {
            if let Some(app) = guard.as_ref() {
                let _ = app.emit("status-update", snapshot);
            }
        }
    }

    pub fn get_state(&self) -> StatusState {
        self.inner.lock().map(|g| g.clone()).unwrap_or_default()
    }

    pub fn set_task(&self, phase: &str, message: &str, clip_title: &str, streamer: &str) {
        let snapshot = {
            let mut st = self.inner.lock().unwrap();
            let is_running = !matches!(phase, "idle" | "error");
            st.is_running = is_running;
            st.phase = phase.to_string();
            st.status = phase.to_string();
            st.message = message.to_string();
            st.current_task = message.to_string();
            st.clip_title = clip_title.to_string();
            st.streamer = streamer.to_string();
            if !is_running {
                st.percent = 0;
                st.progress_percent = 0;
                st.eta_seconds = 0;
                st.speed.clear();
                st.clip_id.clear();
                st.last_run = Some(Local::now().format("%d.%m.%Y %H:%M").to_string());
            }
            let ts = Local::now().format("%H:%M:%S").to_string();
            st.logs.push(format!("[{}] [{}] {}", ts, phase.to_uppercase(), message));
            if st.logs.len() > MAX_LOG_LINES {
                let excess = st.logs.len() - MAX_LOG_LINES;
                st.logs.drain(0..excess);
            }
            st.clone()
        };
        self.emit_state(&snapshot);
    }

    pub fn set_progress(&self, percent: i32, eta_seconds: i64, speed: &str, phase: Option<&str>, clip_id: Option<&str>) {
        let snapshot = {
            let mut st = self.inner.lock().unwrap();
            st.percent = percent.clamp(0, 100);
            st.progress_percent = st.percent;
            st.eta_seconds = eta_seconds.max(0);
            st.speed = speed.to_string();
            if let Some(p) = phase {
                st.phase = p.to_string();
                st.status = p.to_string();
            }
            if let Some(cid) = clip_id {
                st.clip_id = cid.to_string();
            }
            st.clone()
        };
        self.emit_state(&snapshot);
    }

    pub fn log(&self, msg: &str) {
        let snapshot = {
            let mut st = self.inner.lock().unwrap();
            let ts = Local::now().format("%H:%M:%S").to_string();
            st.logs.push(format!("[{}] {}", ts, msg));
            if st.logs.len() > MAX_LOG_LINES {
                let excess = st.logs.len() - MAX_LOG_LINES;
                st.logs.drain(0..excess);
            }
            st.clone()
        };
        self.emit_state(&snapshot);
    }
}

pub fn status_manager() -> &'static StatusManager {
    static INSTANCE: OnceLock<StatusManager> = OnceLock::new();
    INSTANCE.get_or_init(StatusManager::new)
}

pub fn worker_lock() -> &'static Arc<tokio::sync::Mutex<()>> {
    static LOCK: OnceLock<Arc<tokio::sync::Mutex<()>>> = OnceLock::new();
    LOCK.get_or_init(|| Arc::new(tokio::sync::Mutex::new(())))
}

#[derive(Default)]
struct RenderRegistry {
    active_pids: HashMap<String, u32>,
    cancelled: HashSet<String>,
}

fn render_registry() -> &'static Mutex<RenderRegistry> {
    static REG: OnceLock<Mutex<RenderRegistry>> = OnceLock::new();
    REG.get_or_init(|| Mutex::new(RenderRegistry::default()))
}

pub fn register_active_render(clip_id: &str, pid: u32) {
    if let Ok(mut reg) = render_registry().lock() {
        reg.cancelled.remove(clip_id);
        reg.active_pids.insert(clip_id.to_string(), pid);
    }
}

pub fn clear_active_render(clip_id: &str) {
    if let Ok(mut reg) = render_registry().lock() {
        reg.active_pids.remove(clip_id);
    }
}

pub fn is_render_cancelled(clip_id: &str) -> bool {
    render_registry()
        .lock()
        .map(|reg| reg.cancelled.contains(clip_id))
        .unwrap_or(false)
}

pub fn consume_render_cancelled(clip_id: &str) -> bool {
    if let Ok(mut reg) = render_registry().lock() {
        reg.active_pids.remove(clip_id);
        return reg.cancelled.remove(clip_id);
    }
    false
}

static GLOBAL_CANCEL: std::sync::atomic::AtomicBool = std::sync::atomic::AtomicBool::new(false);

pub fn request_global_cancel() {
    GLOBAL_CANCEL.store(true, std::sync::atomic::Ordering::SeqCst);
}

pub fn is_global_cancel_requested() -> bool {
    GLOBAL_CANCEL.load(std::sync::atomic::Ordering::SeqCst)
}

pub fn clear_global_cancel() {
    GLOBAL_CANCEL.store(false, std::sync::atomic::Ordering::SeqCst);
}

pub fn cancel_all_active_tasks() -> usize {
    request_global_cancel();

    let pids = {
        let mut reg = match render_registry().lock() {
            Ok(guard) => guard,
            Err(poisoned) => poisoned.into_inner(),
        };
        let drained: Vec<_> = reg.active_pids.drain().collect();
        let mut pids = Vec::with_capacity(drained.len());
        for (cid, pid) in drained {
            reg.cancelled.insert(cid);
            pids.push(pid);
        }
        pids
    };

    let count = pids.len();
    for pid in pids {
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            let _ = std::process::Command::new("taskkill")
                .args(["/PID", &pid.to_string(), "/T", "/F"])
                .creation_flags(0x08000000)
                .output();
        }
        #[cfg(not(windows))]
        {
            let _ = std::process::Command::new("kill")
                .args(["-9", &pid.to_string()])
                .output();
        }
    }

    status_manager().set_task("idle", "Aufgabe durch Benutzer abgebrochen.", "", "");
    count
}

pub fn cancel_active_render(clip_id: &str) -> bool {
    let pid_opt = {
        let mut reg = render_registry().lock().unwrap();
        reg.cancelled.insert(clip_id.to_string());
        reg.active_pids.remove(clip_id)
    };

    if let Some(pid) = pid_opt {
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            let _ = std::process::Command::new("taskkill")
                .args(["/PID", &pid.to_string(), "/T", "/F"])
                .creation_flags(0x08000000)
                .output();
        }
        #[cfg(not(windows))]
        {
            let _ = std::process::Command::new("kill")
                .args(["-9", &pid.to_string()])
                .output();
        }
        return true;
    }
    false
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_progress_clamping_and_log_limit() {
        let mgr = StatusManager::new();
        mgr.set_task("rendering", "Rendere...", "Clip", "Streamer");
        mgr.set_progress(150, -5, "2.1x", Some("rendering"), Some("c1"));
        let st = mgr.get_state();
        assert_eq!(st.percent, 100);
        assert_eq!(st.eta_seconds, 0);
        assert!(st.is_running);

        for i in 0..100 {
            mgr.log(&format!("Log {}", i));
        }
        assert_eq!(mgr.get_state().logs.len(), MAX_LOG_LINES);
    }

    #[test]
    fn test_render_cancellation_tracking() {
        register_active_render("clip_x", 999_999);
        assert!(!is_render_cancelled("clip_x"));
        assert!(cancel_active_render("clip_x"));
        assert!(is_render_cancelled("clip_x"));
        assert!(consume_render_cancelled("clip_x"));
        assert!(!is_render_cancelled("clip_x"));
    }

    #[test]
    fn test_cancel_all_active_tasks() {
        clear_global_cancel();
        assert!(!is_global_cancel_requested());
        register_active_render("clip_multi_1", 999_998);
        register_active_render("clip_multi_2", 999_997);
        let count = cancel_all_active_tasks();
        assert_eq!(count, 2);
        assert!(is_global_cancel_requested());
        assert!(is_render_cancelled("clip_multi_1"));
        assert!(is_render_cancelled("clip_multi_2"));
        clear_global_cancel();
        assert!(!is_global_cancel_requested());
    }
}
