use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use chrono::Local;
use reqwest::header::HeaderMap;
use rusqlite::Connection;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

const TWITCH_GQL_CLIENT_ID: &str = "kimne78kx3ncx6brgo4mv6wki5h1ko";
const TWITCH_GQL_URL: &str = "https://gql.twitch.tv/gql";

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct DiscoveredClip {
    pub clip_id: String,
    pub streamer: String,
    pub title: String,
    pub url: String,
    pub view_count: i64,
    pub duration: f64,
    pub created_at: String,
    pub thumbnail_url: String,
}

fn get_base_dir() -> PathBuf {
    if Path::new("data").exists() {
        PathBuf::from(".")
    } else if Path::new("../data").exists() {
        PathBuf::from("..")
    } else {
        PathBuf::from(".")
    }
}

pub async fn query_twitch_clips(
    channel_name: &str,
    limit: usize,
    time_filter: &str,
) -> Result<Vec<DiscoveredClip>, String> {
    let client = reqwest::Client::new();
    let mut headers = HeaderMap::new();
    headers.insert("Client-ID", TWITCH_GQL_CLIENT_ID.parse().unwrap());
    headers.insert("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)".parse().unwrap());

    let filter_enum = match time_filter.to_uppercase().as_str() {
        "LAST_WEEK" => "LAST_WEEK",
        "ALL_TIME" => "ALL_TIME",
        _ => "LAST_DAY",
    };

    let query = format!(
        r#"query($login: String!, $limit: Int!) {{
            user(login: $login) {{
                id
                login
                clips(first: $limit, criteria: {{ filter: {} }}) {{
                    edges {{
                        node {{
                            id
                            slug
                            title
                            viewCount
                            durationSeconds
                            createdAt
                            url
                            thumbnailURL
                        }}
                    }}
                }}
            }}
        }}"#,
        filter_enum
    );

    let payload = json!({
        "query": query,
        "variables": {
            "login": channel_name.to_lowercase(),
            "limit": limit
        }
    });

    let resp = client
        .post(TWITCH_GQL_URL)
        .headers(headers)
        .json(&payload)
        .send()
        .await
        .map_err(|e| format!("Twitch GQL HTTP Error: {}", e))?;

    let json_resp: Value = resp
        .json()
        .await
        .map_err(|e| format!("Twitch GQL Parse Error: {}", e))?;

    let mut clips = Vec::new();
    let edges = json_resp
        .pointer("/data/user/clips/edges")
        .and_then(|v| v.as_array());

    if let Some(edge_list) = edges {
        for edge in edge_list {
            if let Some(node) = edge.get("node") {
                let slug = node
                    .get("slug")
                    .and_then(|v| v.as_str())
                    .or_else(|| node.get("id").and_then(|v| v.as_str()))
                    .unwrap_or_default()
                    .to_string();

                if slug.is_empty() {
                    continue;
                }

                let title = node
                    .get("title")
                    .and_then(|v| v.as_str())
                    .unwrap_or("Clip")
                    .to_string();

                let view_count = node
                    .get("viewCount")
                    .and_then(|v| v.as_i64())
                    .unwrap_or(0);

                let duration = node
                    .get("durationSeconds")
                    .and_then(|v| v.as_f64())
                    .unwrap_or(30.0);

                let created_at = node
                    .get("createdAt")
                    .and_then(|v| v.as_str())
                    .unwrap_or_default()
                    .to_string();

                let url = node
                    .get("url")
                    .and_then(|v| v.as_str())
                    .unwrap_or_default()
                    .to_string();

                let thumbnail_url = node
                    .get("thumbnailURL")
                    .and_then(|v| v.as_str())
                    .unwrap_or_default()
                    .to_string();

                clips.push(DiscoveredClip {
                    clip_id: slug,
                    streamer: channel_name.to_string(),
                    title,
                    url,
                    view_count,
                    duration,
                    created_at,
                    thumbnail_url,
                });
            }
        }
    }

    Ok(clips)
}

pub async fn get_direct_mp4_url(slug: &str) -> Option<String> {
    let client = reqwest::Client::new();
    let mut headers = HeaderMap::new();
    headers.insert("Client-ID", TWITCH_GQL_CLIENT_ID.parse().unwrap());
    headers.insert("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)".parse().unwrap());

    let query = r#"query($slug: ID!) {
        clip(slug: $slug) {
            playbackAccessToken(params: { platform: "web", playerType: "site" }) {
                signature
                value
            }
            videoQualities {
                frameRate
                quality
                sourceURL
            }
        }
    }"#;

    let payload = json!({
        "query": query,
        "variables": { "slug": slug }
    });

    let resp = client
        .post(TWITCH_GQL_URL)
        .headers(headers)
        .json(&payload)
        .send()
        .await
        .ok()?;

    let json_resp: Value = resp.json().await.ok()?;
    let clip_data = json_resp.pointer("/data/clip")?;

    let sig = clip_data.pointer("/playbackAccessToken/signature")?.as_str()?;
    let token = clip_data.pointer("/playbackAccessToken/value")?.as_str()?;

    let qualities = clip_data.pointer("/videoQualities")?.as_array()?;
    if let Some(best) = qualities.first() {
        let source_url = best.get("sourceURL")?.as_str()?;
        return Some(format!("{}?sig={}&token={}", source_url, sig, urlencoding_simple(token)));
    }

    None
}

fn urlencoding_simple(s: &str) -> String {
    let mut encoded = String::new();
    for c in s.chars() {
        match c {
            'a'..='z' | 'A'..='Z' | '0'..='9' | '-' | '_' | '.' | '~' => encoded.push(c),
            _ => encoded.push_str(&format!("%{:02X}", c as u32)),
        }
    }
    encoded
}

pub async fn download_clip_file(clip_url: &str, clip_id: &str) -> Result<PathBuf, String> {
    let base = get_base_dir();
    let raw_dir = base.join("downloads").join("raw");
    fs::create_dir_all(&raw_dir).map_err(|e| e.to_string())?;

    let out_path = raw_dir.join(format!("{}.mp4", clip_id));
    if out_path.exists() && fs::metadata(&out_path).map(|m| m.len() > 1000).unwrap_or(false) {
        return Ok(out_path);
    }

    // Try direct GQL stream url first!
    if let Some(direct_url) = get_direct_mp4_url(clip_id).await {
        let client = reqwest::Client::new();
        if let Ok(resp) = client.get(&direct_url).send().await {
            if resp.status().is_success() {
                if let Ok(bytes) = resp.bytes().await {
                    if bytes.len() > 1000 {
                        let mut file = fs::File::create(&out_path).map_err(|e| e.to_string())?;
                        file.write_all(&bytes).map_err(|e| e.to_string())?;
                        return Ok(out_path);
                    }
                }
            }
        }
    }

    // Fallback: yt-dlp CLI
    let yt_dlp_res = std::process::Command::new("yt-dlp")
        .args([
            "-o",
            out_path.to_str().unwrap(),
            "-f",
            "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            clip_url,
        ])
        .output();

    if let Ok(_) = yt_dlp_res {
        if out_path.exists() && fs::metadata(&out_path).map(|m| m.len() > 1000).unwrap_or(false) {
            return Ok(out_path);
        }
    }

    Err(format!("Download failed for clip {}", clip_id))
}

pub fn save_harvested_clip(clip: &DiscoveredClip, raw_path: &Path) -> Result<(), String> {
    let base = get_base_dir();
    let db_path = base.join("data").join("pipeline.db");
    let conn = Connection::open(&db_path).map_err(|e| e.to_string())?;

    let now_iso = Local::now().to_rfc3339();
    let raw_str = raw_path.to_str().unwrap_or_default();

    conn.execute(
        r#"INSERT OR IGNORE INTO clips (
            clip_id, streamer, platform, original_title, url,
            view_count, duration, clip_created_at, harvested_at,
            status, raw_path
        ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, 'harvested', ?10)"#,
        rusqlite::params![
            clip.clip_id,
            clip.streamer,
            "twitch",
            clip.title,
            clip.url,
            clip.view_count,
            clip.duration,
            clip.created_at,
            now_iso,
            raw_str,
        ],
    )
    .map_err(|e| e.to_string())?;

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn test_twitch_gql_query() {
        let clips = query_twitch_clips("trymacs", 5, "LAST_DAY").await;
        assert!(clips.is_ok(), "GQL query failed: {:?}", clips.err());
        let list = clips.unwrap();
        println!("Trymacs clips found: {}", list.len());
        for c in &list {
            println!(" - {} ({} views, {}s)", c.title, c.view_count, c.duration);
        }
    }
}
