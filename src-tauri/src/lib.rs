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
        .setup(|_app| {
            // The window naturally loads index.html (Setup Wizard & Launcher).
            // It automatically checks if the environment is ready, launches
            // Python Web Studio in the background, and navigates when ready.
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
            setup::get_setup_progress,
            setup::run_automated_setup,
            setup::launch_studio_after_setup,
        ])
        .run(tauri::generate_context!())
        .expect("error while building tauri application");
}
