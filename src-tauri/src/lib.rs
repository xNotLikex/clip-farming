use tauri::Manager;

pub mod commands;
pub mod db;
pub mod gpu;
pub mod models;
pub mod setup;
pub mod twitch;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            if let Some(window) = app.get_webview_window("main") {
                if setup::is_environment_ready() {
                    let url = tauri::Url::parse("http://127.0.0.1:5000").unwrap();
                    let _ = window.navigate(url);
                } else {
                    // Load local setup.html
                    let _ = window.navigate(tauri::Url::parse("tauri://localhost/setup.html").unwrap_or_else(|_| {
                        tauri::Url::parse("http://tauri.localhost/setup.html").unwrap()
                    }));
                }
            }
            Ok(())
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
            setup::run_automated_setup,
            setup::launch_studio_after_setup,
        ])
        .run(tauri::generate_context!())
        .expect("error while building tauri application");
}
