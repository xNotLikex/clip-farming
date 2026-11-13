use std::fs;
use std::path::Path;
use std::sync::{Mutex, OnceLock};
use clip_farming_lib::{commands, config, db, gpu, layout, state, sticker, subtitles, twitch, whisper};

fn env_lock() -> &'static Mutex<()> {
    static LOCK: OnceLock<Mutex<()>> = OnceLock::new();
    LOCK.get_or_init(|| Mutex::new(()))
}

#[test]
fn test_config_roundtrip_and_streamer_crud() {
    let _guard = env_lock().lock().unwrap();
    let tmp = std::env::temp_dir().join(format!("cf_cfg_test_{}", std::process::id()));
    let _ = fs::remove_dir_all(&tmp);
    fs::create_dir_all(&tmp).unwrap();
    unsafe {
        std::env::set_var("CLIP_FARMING_DATA_DIR", &tmp);
    }

    assert!(config::add_streamer("Trymacs", 100, 3, "auto").unwrap());
    assert!(config::update_streamer("trymacs", Some(250), None, Some("top_right"), None, None).unwrap());

    let cfg = config::load_config();
    assert_eq!(cfg.streamers.len(), 1);
    assert_eq!(cfg.streamers[0].min_clip_views, 250);
    assert_eq!(cfg.streamers[0].layout, "top_right");
    assert!(cfg.streamers[0].custom_crops.is_some());

    assert_eq!(config::update_all_streamers_min_views(500).unwrap(), 1);
    assert_eq!(config::load_config().streamers[0].min_clip_views, 500);

    assert!(config::remove_streamer("trymacs").unwrap());
    assert!(config::load_config().streamers.is_empty());

    unsafe {
        std::env::remove_var("CLIP_FARMING_DATA_DIR");
    }
    let _ = fs::remove_dir_all(&tmp);
}

#[test]
fn test_db_init_insert_and_fetch_dashboard_isolated() {
    let _guard = env_lock().lock().unwrap();
    let tmp = std::env::temp_dir().join(format!("cf_db_test_{}", std::process::id()));
    let _ = fs::remove_dir_all(&tmp);
    fs::create_dir_all(&tmp).unwrap();
    unsafe {
        std::env::set_var("CLIP_FARMING_DATA_DIR", &tmp);
    }

    let conn = db::open_connection().unwrap();
    conn.execute(
        "INSERT INTO clips (clip_id, streamer, original_title, view_count, duration, status) VALUES ('c1', 'trymacs', 'Test Clip', 150, 25.0, 'harvested')",
        [],
    )
    .unwrap();
    drop(conn);

    let dash = db::fetch_dashboard_data().unwrap();
    assert_eq!(dash.counts.harvested, 1);
    assert_eq!(dash.queue_clips.len(), 1);
    assert_eq!(dash.queue_clips[0].clip_id, "c1");

    assert!(db::toggle_manually_published("c1").unwrap());
    assert!(!db::toggle_manually_published("c1").unwrap());

    unsafe {
        std::env::remove_var("CLIP_FARMING_DATA_DIR");
    }
    let _ = fs::remove_dir_all(&tmp);
}

#[test]
fn test_runtime_fallback_chain_order() {
    let qsv = gpu::EncoderProfile {
        id: "qsv".to_string(),
        name: "Intel QuickSync".to_string(),
        codec: "h264_qsv".to_string(),
        description: String::new(),
        ffmpeg_args: vec![],
        is_supported: true,
    };
    let chain = gpu::build_runtime_fallback_chain(&qsv);
    let codecs: Vec<&str> = chain.iter().map(|p| p.codec.as_str()).collect();
    assert_eq!(codecs, vec!["h264_qsv", "h264_mf", "libx264"]);
}

#[test]
fn test_state_progress_and_cancellation() {
    let mgr = state::status_manager();
    mgr.set_task("rendering", "Rendere...", "Clip", "Streamer");
    mgr.set_progress(150, -5, "2.1x", Some("rendering"), Some("c1"));
    let st = mgr.get_state();
    assert_eq!(st.percent, 100);
    assert_eq!(st.eta_seconds, 0);
    assert!(st.is_running);

    state::register_active_render("clip_x", 999_999);
    assert!(!state::is_render_cancelled("clip_x"));
    assert!(state::cancel_active_render("clip_x"));
    assert!(state::is_render_cancelled("clip_x"));
    assert!(state::consume_render_cancelled("clip_x"));
    assert!(!state::is_render_cancelled("clip_x"));
}

#[test]
fn test_twitch_time_filter_normalization() {
    assert_eq!(twitch::normalize_gql_time_filter("last_month"), "LAST_MONTH");
    assert_eq!(twitch::normalize_gql_time_filter("last_week"), "LAST_WEEK");
    assert_eq!(twitch::normalize_gql_time_filter("all_time"), "ALL_TIME");
    assert_eq!(twitch::normalize_gql_time_filter("unknown"), "LAST_DAY");
}

#[test]
fn test_escape_ffmpeg_filter_path() {
    let p = Path::new(r"C:\Users\Test User\Clip's\sub_1.ass");
    let escaped = layout::escape_ffmpeg_filter_path(p);
    assert_eq!(escaped, r"C\:/Users/Test User/Clip\'s/sub_1.ass");
}

#[test]
fn test_build_filter_graph_layouts() {
    let raw = Path::new("raw_clip.mp4");
    let info = layout::VideoInfo {
        width: 1920,
        height: 1080,
        duration: 20.0,
        fps: 60.0,
        has_audio: true,
    };

    let fg_single = layout::build_filter_graph(raw, &info, "single_916", None, None, None, None);
    assert!(fg_single.filter_complex.contains("crop=606:1080:656:0,scale=1080:1920[base]"));
    assert_eq!(fg_single.sticker_y, 480);

    let crops = serde_json::json!({
        "enabled": true,
        "cam": {"x": 0.0, "y": 0.0, "w": 0.25, "h": 0.25},
        "game": {"x": 0.2, "y": 0.0, "w": 0.6, "h": 1.0}
    });
    let fg_crops = layout::build_filter_graph(raw, &info, "custom", Some(&crops), None, None, None);
    assert!(fg_crops.filter_complex.contains("vstack=inputs=2[base]"));
    assert_eq!(fg_crops.sticker_y, 620);

    let fg_blur = layout::build_filter_graph(raw, &info, "auto", None, None, None, None);
    assert!(fg_blur.filter_complex.contains("boxblur=6:2"));
    assert_eq!(fg_blur.sticker_y, 520);
}

#[test]
fn test_create_tiktok_sticker_png() {
    let tmp = std::env::temp_dir().join(format!("cf_sticker_test_{}.png", std::process::id()));
    let _ = fs::remove_file(&tmp);
    let res = sticker::create_tiktok_sticker("KRASSER CLUTCH! 🔥", &tmp).unwrap();
    assert!(res.exists());
    let bytes = fs::read(&res).unwrap();
    assert!(bytes.len() > 500);
    assert_eq!(&bytes[0..8], b"\x89PNG\r\n\x1a\n");
    let _ = fs::remove_file(&res);
}

#[test]
fn test_subtitles_ass_and_alignment() {
    assert_eq!(subtitles::format_ass_time(65.25), "0:01:05.25");

    let orig = vec![subtitles::TranscriptSegment {
        start: 0.0,
        end: 2.0,
        text: "Hallo Welt heute".to_string(),
        words: vec![
            subtitles::WordSegment { word: "Hallo".into(), start: 0.1, end: 0.5, probability: 1.0 },
            subtitles::WordSegment { word: "Welt".into(), start: 0.6, end: 1.0, probability: 1.0 },
            subtitles::WordSegment { word: "heute".into(), start: 1.1, end: 1.6, probability: 1.0 },
        ],
    }];

    let aligned = subtitles::align_words_with_edited_text(&orig, "Hallo liebe Welt heute!", 3.0);
    assert_eq!(aligned.len(), 1);
    assert_eq!(aligned[0].words.len(), 4);
    assert!((aligned[0].words[0].start - 0.1).abs() < 0.01);
    assert!((aligned[0].words[2].start - 0.6).abs() < 0.01);

    let tmp = std::env::temp_dir().join(format!("cf_sub_test_{}.ass", std::process::id()));
    let _ = fs::remove_file(&tmp);
    subtitles::generate_ass(&aligned, &tmp, "center", "cyan").unwrap();
    let content = fs::read_to_string(&tmp).unwrap();
    assert!(content.contains("PlayResX: 1080"));
    assert!(content.contains(",820,1"));
    assert!(content.contains("&H00FFFF00"));
    assert!(content.contains("Dialogue: 0,"));
    let _ = fs::remove_file(&tmp);
}

#[test]
fn test_whisper_json_parsing_with_subword_merge() {
    let sample = r#"{
        "transcription": [
            {
                "offsets": { "from": 100, "to": 1400 },
                "text": " Krasser Clutch!",
                "tokens": [
                    { "text": "[_BEG_]", "offsets": { "from": 100, "to": 100 }, "p": 1.0 },
                    { "text": " Kras", "offsets": { "from": 150, "to": 400 }, "p": 0.9 },
                    { "text": "ser", "offsets": { "from": 400, "to": 650 }, "p": 0.95 },
                    { "text": " Clutch!", "offsets": { "from": 700, "to": 1300 }, "p": 0.98 }
                ]
            },
            {
                "offsets": { "from": 1500, "to": 2000 },
                "text": "[BLANK_AUDIO]",
                "tokens": []
            }
        ]
    }"#;

    let segs = whisper::parse_whisper_json(sample).unwrap();
    assert_eq!(segs.len(), 1);
    assert_eq!(segs[0].words.len(), 2);
    assert_eq!(segs[0].words[0].word, "Krasser");
    assert!((segs[0].words[0].start - 0.15).abs() < 0.001);
    assert!((segs[0].words[0].end - 0.65).abs() < 0.001);
    assert_eq!(segs[0].words[1].word, "Clutch!");
}

#[test]
fn test_delete_older_queue_clips_isolated() {
    let _guard = env_lock().lock().unwrap();
    let tmp = std::env::temp_dir().join(format!("cf_del_older_test_{}", std::process::id()));
    let _ = fs::remove_dir_all(&tmp);
    fs::create_dir_all(&tmp).unwrap();
    unsafe {
        std::env::set_var("CLIP_FARMING_DATA_DIR", &tmp);
    }

    let conn = db::open_connection().unwrap();
    conn.execute(
        "INSERT INTO clips (clip_id, streamer, original_title, view_count, duration, clip_created_at, status) VALUES ('c_old', 'trymacs', 'Old Clip', 150, 25.0, '2020-01-01T12:00:00Z', 'harvested')",
        [],
    ).unwrap();
    conn.execute(
        "INSERT INTO clips (clip_id, streamer, original_title, view_count, duration, clip_created_at, status) VALUES ('c_new', 'trymacs', 'New Clip', 200, 25.0, '2099-01-01T12:00:00Z', 'harvested')",
        [],
    ).unwrap();

    let raw_dir = config::get_raw_clips_dir();
    fs::create_dir_all(&raw_dir).unwrap();
    let old_raw = raw_dir.join("c_old.mp4");
    let new_raw = raw_dir.join("c_new.mp4");
    fs::write(&old_raw, b"dummy old").unwrap();
    fs::write(&new_raw, b"dummy new").unwrap();

    let ids: Vec<String> = {
        let mut stmt = conn
            .prepare("SELECT clip_id FROM clips WHERE status = 'harvested' AND date(COALESCE(clip_created_at, harvested_at), 'localtime') < date('now', 'localtime')")
            .unwrap();
        let rows = stmt.query_map([], |row| row.get(0)).unwrap();
        rows.filter_map(Result::ok).collect()
    };
    assert_eq!(ids, vec!["c_old".to_string()]);

    for cid in ids {
        commands::delete_queue_clip(cid).unwrap();
    }

    assert!(!old_raw.exists());
    assert!(new_raw.exists());

    let remaining: i64 = conn.query_row("SELECT COUNT(*) FROM clips", [], |r| r.get(0)).unwrap();
    assert_eq!(remaining, 1);

    unsafe {
        std::env::remove_var("CLIP_FARMING_DATA_DIR");
    }
    let _ = fs::remove_dir_all(&tmp);
}
