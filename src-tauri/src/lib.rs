pub mod commands;
pub mod config;
pub mod db;
pub mod gpu;
pub mod layout;
pub mod models;
pub mod pipeline;
pub mod state;
pub mod sticker;
pub mod subtitles;
pub mod twitch;
pub mod updater;
pub mod whisper;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            let _ = db::open_connection();
            let handle = app.handle().clone();
            state::status_manager().set_app_handle(handle.clone());
            pipeline::start_autopilot_loop(handle);
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::get_dashboard_data,
            commands::get_app_version,
            commands::get_data_root_path,
            commands::open_folder,
            commands::delete_queue_clip,
            commands::save_clip_crop,
            commands::trigger_twitch_run,
            commands::detect_hardware_gpus,
            commands::get_available_encoders,
            commands::select_hardware_encoder,
            commands::api_proxy,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
