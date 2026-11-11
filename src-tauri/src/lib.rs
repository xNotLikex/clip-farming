// L1 Audit-Fix: tauri::Manager unused import entfernt

pub mod commands;
pub mod db;
pub mod gpu;
pub mod models;
pub mod setup;
pub mod twitch;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .setup(|_app| {
            // The window naturally loads index.html (Setup Wizard & Launcher).
            // It automatically checks if the environment is ready, launches
            // Python Web Studio in the background, and navigates when ready.
            Ok(())
        })
        .on_window_event(|_window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                #[cfg(windows)]
                {
                    use std::os::windows::process::CommandExt;
                    let _ = std::process::Command::new("powershell")
                        .args(["-NoProfile", "-Command", "Get-NetTCPConnection -LocalPort 5000 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"])
                        .creation_flags(0x08000000)
                        .spawn();
                }
            }
        })
        .invoke_handler(tauri::generate_handler![
            commands::get_dashboard_data,
            commands::get_app_version,
            commands::open_folder,
            commands::delete_queue_clip,
            commands::save_clip_crop,
            commands::trigger_twitch_run,
            commands::detect_hardware_gpus,
            commands::get_available_encoders,
            commands::select_hardware_encoder,
            commands::api_proxy,
            setup::get_setup_info,
            setup::get_setup_progress,
            setup::run_automated_setup,
            setup::launch_studio_after_setup,
        ])
        .run(tauri::generate_context!())
        .expect("error while building tauri application");
}
