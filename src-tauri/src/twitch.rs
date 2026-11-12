use std::collections::HashMap;
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use chrono::Local;
use reqwest::header::HeaderMap;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

use crate::config::{get_data_root, get_raw_clips_dir, StreamerEntry};
use crate::db::{get_processed_ids, open_connection};

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

pub fn normalize_gql_time_filter(time_filter: &str) -> &'static str {
    match time_filter.trim().to_uppercase().as_str() {
        "LAST_WEEK" => "LAST_WEEK",
        "LAST_MONTH" => "LAST_MONTH",
        "ALL_TIME" => "ALL_TIME",
        _ => "LAST_DAY",
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

    let filter_enum = normalize_gql_time_filter(time_filter);

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
    let mut encoded = String::with_capacity(s.len());
    for &b in s.as_bytes() {
        match b {
            b'a'..=b'z' | b'A'..=b'Z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => {
                encoded.push(b as char);
            }
            _ => encoded.push_str(&format!("%{:02X}", b)),
        }
    }
    encoded
}

pub async fn download_clip_file(_clip_url: &str, clip_id: &str) -> Result<PathBuf, String> {
    let raw_dir = get_raw_clips_dir();
    fs::create_dir_all(&raw_dir).map_err(|e| e.to_string())?;

    let out_path = raw_dir.join(format!("{}.mp4", clip_id));
    if out_path.exists() && fs::metadata(&out_path).map(|m| m.len() > 1000).unwrap_or(false) {
        return Ok(out_path);
    }

    let direct_url = get_direct_mp4_url(clip_id)
        .await
        .ok_or_else(|| format!("Konnte direkte MP4-URL für Clip {} nicht ermitteln", clip_id))?;

    let client = reqwest::Client::new();
    let resp = client
        .get(&direct_url)
        .send()
        .await
        .map_err(|e| format!("Download-Fehler für Clip {}: {}", clip_id, e))?;

    if !resp.status().is_success() {
        return Err(format!("HTTP {} beim Laden von Clip {}", resp.status(), clip_id));
    }

    let bytes = resp
        .bytes()
        .await
        .map_err(|e| format!("Stream-Fehler für Clip {}: {}", clip_id, e))?;

    if bytes.len() <= 1000 {
        return Err(format!("Clip-Datei {} ist zu klein ({} Bytes)", clip_id, bytes.len()));
    }

    let tmp_path = out_path.with_extension("mp4.part");
    {
        let mut file = fs::File::create(&tmp_path).map_err(|e| e.to_string())?;
        file.write_all(&bytes).map_err(|e| e.to_string())?;
    }
    fs::rename(&tmp_path, &out_path).map_err(|e| e.to_string())?;
    Ok(out_path)
}

pub fn save_harvested_clip(clip: &DiscoveredClip, raw_path: &Path) -> Result<(), String> {
    let conn = open_connection()?;
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

pub async fn harvest_channel(
    streamer: &StreamerEntry,
    time_filter: &str,
    fallback_to_week: bool,
) -> Result<usize, String> {
    let mut discovered = query_twitch_clips(&streamer.name, 30, time_filter).await?;
    let ids: Vec<String> = discovered.iter().map(|c| c.clip_id.clone()).collect();
    let mut processed = get_processed_ids(&ids)?;

    let mut eligible: Vec<DiscoveredClip> = discovered
        .into_iter()
        .filter(|c| !processed.contains(&c.clip_id) && c.view_count >= streamer.min_clip_views)
        .collect();

    if eligible.is_empty() && fallback_to_week && time_filter.eq_ignore_ascii_case("LAST_DAY") {
        discovered = query_twitch_clips(&streamer.name, 30, "LAST_WEEK").await?;
        let week_ids: Vec<String> = discovered.iter().map(|c| c.clip_id.clone()).collect();
        processed = get_processed_ids(&week_ids)?;
        eligible = discovered
            .into_iter()
            .filter(|c| !processed.contains(&c.clip_id) && c.view_count >= streamer.min_clip_views)
            .collect();
    }

    let mut saved = 0usize;
    for clip in eligible.into_iter().take(streamer.max_clips_per_run.max(1) as usize) {
        if let Ok(raw_path) = download_clip_file(&clip.url, &clip.clip_id).await {
            if save_harvested_clip(&clip, &raw_path).is_ok() {
                saved += 1;
            }
        }
    }

    if let Ok(conn) = open_connection() {
        let now_iso = Local::now().to_rfc3339();
        let _ = conn.execute(
            "INSERT OR REPLACE INTO streamer_checks (streamer, last_checked_at, clips_found) VALUES (?1, ?2, ?3)",
            rusqlite::params![streamer.name.to_lowercase(), now_iso, saved as i64],
        );
    }

    Ok(saved)
}

pub async fn refresh_streamer_avatars(logins: &[String]) -> Result<(), String> {
    if logins.is_empty() {
        return Ok(());
    }
    let client = reqwest::Client::new();
    let mut headers = HeaderMap::new();
    headers.insert("Client-ID", TWITCH_GQL_CLIENT_ID.parse().unwrap());
    headers.insert("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)".parse().unwrap());

    let cache_path = get_data_root().join("data").join("streamer_avatars.json");
    let mut cache: HashMap<String, Value> = if cache_path.exists() {
        fs::read_to_string(&cache_path)
            .ok()
            .and_then(|c| serde_json::from_str(&c).ok())
            .unwrap_or_default()
    } else {
        HashMap::new()
    };

    for login in logins {
        let clean = login.trim().to_lowercase();
        if clean.is_empty() {
            continue;
        }
        let query = r#"query($login: String!) {
            user(login: $login) {
                login
                displayName
                profileImageURL(width: 300)
                stream {
                    id
                    viewersCount
                    game { name }
                    title
                }
            }
        }"#;
        let payload = json!({ "query": query, "variables": { "login": clean } });
        if let Ok(resp) = client.post(TWITCH_GQL_URL).headers(headers.clone()).json(&payload).send().await {
            if let Ok(val) = resp.json::<Value>().await {
                if let Some(u) = val.pointer("/data/user") {
                    if !u.is_null() {
                        let is_live = u.get("stream").map(|s| !s.is_null()).unwrap_or(false);
                        cache.insert(
                            clean.clone(),
                            json!({
                                "avatar_url": u.get("profileImageURL").and_then(|v| v.as_str()).unwrap_or(""),
                                "display_name": u.get("displayName").and_then(|v| v.as_str()).unwrap_or(&clean),
                                "is_live": is_live,
                                "game": u.pointer("/stream/game/name").and_then(|v| v.as_str()),
                                "viewers": u.pointer("/stream/viewersCount").and_then(|v| v.as_i64()).unwrap_or(0),
                            }),
                        );
                    }
                }
            }
        }
    }

    if let Some(parent) = cache_path.parent() {
        let _ = fs::create_dir_all(parent);
    }
    if let Ok(json_str) = serde_json::to_string_pretty(&cache) {
        let _ = fs::write(&cache_path, json_str);
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_urlencoding_utf8_and_time_filters() {
        assert_eq!(urlencoding_simple("a+b c"), "a%2Bb%20c");
        assert_eq!(normalize_gql_time_filter("last_month"), "LAST_MONTH");
        assert_eq!(normalize_gql_time_filter("last_week"), "LAST_WEEK");
        assert_eq!(normalize_gql_time_filter("all_time"), "ALL_TIME");
        assert_eq!(normalize_gql_time_filter("unknown"), "LAST_DAY");
    }

    #[tokio::test]
    #[ignore = "Live Twitch GQL network test"]
    async fn test_twitch_gql_query() {
        let clips = query_twitch_clips("trymacs", 5, "LAST_DAY").await;
        assert!(clips.is_ok(), "GQL query failed: {:?}", clips.err());
    }
}
