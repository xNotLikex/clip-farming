use serde::{Deserialize, Serialize};

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct Counts {
    pub harvested: i64,
    pub ready: i64,
    pub scheduled: i64,
    pub published: i64,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct QueueClip {
    pub clip_id: String,
    pub streamer: String,
    pub original_title: String,
    pub view_count: i64,
    pub duration: f64,
    pub harvested_at: Option<String>,
    pub clip_created_at: Option<String>,
    pub created_ago: String,
    pub created_full: String,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct ReadyClip {
    pub clip_id: String,
    pub streamer: String,
    pub title: String,
    pub sticker_text: String,
    pub sub_position: String,
    pub transcript: String,
    pub view_count: i64,
    pub layout_mode: String,
    pub cam_filter: String,
    pub is_manually_published: bool,
    pub has_video: bool,
    pub created_ago: String,
    pub created_full: String,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct ScheduledClip {
    pub clip_id: String,
    pub streamer: String,
    pub original_title: String,
    pub ai_title: Option<String>,
    pub scheduled_publish_at: Option<String>,
    pub view_count: i64,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct PublishedClip {
    pub clip_id: String,
    pub streamer: String,
    pub original_title: String,
    pub ai_title: Option<String>,
    pub published_at: Option<String>,
    pub youtube_video_id: Option<String>,
    pub tiktok_publish_id: Option<String>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct StreamerConfig {
    pub name: String,
    pub platform: String,
    pub enabled: bool,
    pub min_clip_views: i64,
    pub max_clips_per_run: i64,
    pub layout: String,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct AccountStatus {
    pub youtube_connected: bool,
    pub youtube_channel: String,
    pub tiktok_connected: bool,
    pub tiktok_user: String,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct DashboardData {
    pub counts: Counts,
    pub older_queue_count: i64,
    pub queue_clips: Vec<QueueClip>,
    pub ready_clips: Vec<ReadyClip>,
    pub scheduled_clips: Vec<ScheduledClip>,
    pub published_clips: Vec<PublishedClip>,
    pub streamers: Vec<StreamerConfig>,
    pub streamer_counts: std::collections::HashMap<String, usize>,
    pub account_status: AccountStatus,
}
