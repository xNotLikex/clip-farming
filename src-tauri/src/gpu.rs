use serde::{Deserialize, Serialize};
use std::process::Command;

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct GpuInfo {
    pub name: String,
    pub vendor: String,
    pub is_onboard: bool,
    pub ram_mb: u64,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct EncoderProfile {
    pub id: String,
    pub name: String,
    pub codec: String,
    pub description: String,
    pub ffmpeg_args: Vec<String>,
    pub is_supported: bool,
}

pub fn test_ffmpeg_encoder(codec: &str) -> bool {
    let output = Command::new("ffmpeg")
        .args([
            "-y",
            "-f", "lavfi",
            "-i", "testsrc=duration=0.1:size=320x240:rate=10",
            "-c:v", codec,
            "-f", "null", "-",
        ])
        .output();

    match output {
        Ok(out) => out.status.success(),
        Err(_) => false,
    }
}

pub fn detect_gpus() -> Vec<GpuInfo> {
    let mut gpus = Vec::new();

    #[cfg(target_os = "windows")]
    {
        let ps_cmd = "Get-CimInstance Win32_VideoController | Select-Object Name, AdapterRAM | ConvertTo-Json -Compress";
        if let Ok(out) = Command::new("powershell").args(["-NoProfile", "-Command", ps_cmd]).output() {
            if out.status.success() {
                let stdout = String::from_utf8_lossy(&out.stdout);
                if let Ok(val) = serde_json::from_str::<serde_json::Value>(&stdout) {
                    let items = if let Some(arr) = val.as_array() {
                        arr.clone()
                    } else if val.is_object() {
                        vec![val]
                    } else {
                        vec![]
                    };

                    for item in items {
                        let name = item.get("Name").and_then(|v| v.as_str()).unwrap_or("Unbekannte GPU").to_string();
                        let ram_bytes = item.get("AdapterRAM").and_then(|v| v.as_u64()).unwrap_or(0);
                        let ram_mb = ram_bytes / (1024 * 1024);

                        let name_lower = name.to_lowercase();
                        let is_nvidia = name_lower.contains("nvidia") || name_lower.contains("geforce") || name_lower.contains("rtx") || name_lower.contains("gtx");
                        let is_amd = name_lower.contains("amd") || name_lower.contains("radeon");
                        let is_intel = name_lower.contains("intel") || name_lower.contains("arc") || name_lower.contains("iris") || name_lower.contains("uhd");

                        let is_onboard = (name_lower.contains("graphics") && !name_lower.contains("rx")) || ram_mb < 1500;

                        let vendor = if is_nvidia {
                            "nvidia"
                        } else if is_amd {
                            "amd"
                        } else if is_intel {
                            "intel"
                        } else {
                            "other"
                        };

                        gpus.push(GpuInfo {
                            name,
                            vendor: vendor.to_string(),
                            is_onboard,
                            ram_mb,
                        });
                    }
                }
            }
        }
    }

    gpus
}

pub fn get_encoder_catalog() -> Vec<EncoderProfile> {
    vec![
        EncoderProfile {
            id: "nvenc".to_string(),
            name: "NVIDIA NVENC".to_string(),
            codec: "h264_nvenc".to_string(),
            description: "NVIDIA GeForce / RTX dedizierte GPU".to_string(),
            ffmpeg_args: vec!["-c:v".to_string(), "h264_nvenc".to_string(), "-preset".to_string(), "p4".to_string(), "-cq".to_string(), "23".to_string()],
            is_supported: test_ffmpeg_encoder("h264_nvenc"),
        },
        EncoderProfile {
            id: "amf".to_string(),
            name: "AMD AMF".to_string(),
            codec: "h264_amf".to_string(),
            description: "AMD Radeon dedizierte GPU & Onboard APU".to_string(),
            ffmpeg_args: vec!["-c:v".to_string(), "h264_amf".to_string(), "-quality".to_string(), "speed".to_string(), "-b:v".to_string(), "6M".to_string()],
            is_supported: test_ffmpeg_encoder("h264_amf"),
        },
        EncoderProfile {
            id: "qsv".to_string(),
            name: "Intel QuickSync".to_string(),
            codec: "h264_qsv".to_string(),
            description: "Intel Arc & Core iGPU QuickSync".to_string(),
            ffmpeg_args: vec!["-c:v".to_string(), "h264_qsv".to_string(), "-preset".to_string(), "medium".to_string(), "-global_quality".to_string(), "23".to_string()],
            is_supported: test_ffmpeg_encoder("h264_qsv"),
        },
        EncoderProfile {
            id: "mf".to_string(),
            name: "Windows Media Foundation".to_string(),
            codec: "h264_mf".to_string(),
            description: "Universelle Hardware-Beschleunigung (AMD Onboard, Intel & NVIDIA)".to_string(),
            ffmpeg_args: vec!["-c:v".to_string(), "h264_mf".to_string(), "-b:v".to_string(), "6M".to_string()],
            is_supported: test_ffmpeg_encoder("h264_mf"),
        },
        EncoderProfile {
            id: "cpu".to_string(),
            name: "CPU (x264)".to_string(),
            codec: "libx264".to_string(),
            description: "Multi-Core CPU Software-Encoding (Maximale Kompatibilität)".to_string(),
            ffmpeg_args: vec!["-c:v".to_string(), "libx264".to_string(), "-preset".to_string(), "fast".to_string(), "-crf".to_string(), "22".to_string(), "-threads".to_string(), "0".to_string()],
            is_supported: true,
        },
    ]
}

pub fn select_best_encoder(preferred: &str) -> EncoderProfile {
    let catalog = get_encoder_catalog();

    if preferred != "auto" {
        if let Some(prof) = catalog.iter().find(|p| p.id == preferred && p.is_supported) {
            return prof.clone();
        }
    }

    // Auto-selection based on detected GPUs & verified FFmpeg capabilities
    let gpus = detect_gpus();
    let has_nvidia = gpus.iter().any(|g| g.vendor == "nvidia");
    let has_amd = gpus.iter().any(|g| g.vendor == "amd");
    let has_intel = gpus.iter().any(|g| g.vendor == "intel");

    if has_nvidia {
        if let Some(prof) = catalog.iter().find(|p| p.id == "nvenc" && p.is_supported) {
            return prof.clone();
        }
    }

    if has_amd {
        if let Some(prof) = catalog.iter().find(|p| p.id == "amf" && p.is_supported) {
            return prof.clone();
        }
    }

    if has_intel {
        if let Some(prof) = catalog.iter().find(|p| p.id == "qsv" && p.is_supported) {
            return prof.clone();
        }
    }

    // Windows Media Foundation fallback (works with AMD Onboard, Intel, etc.)
    if let Some(prof) = catalog.iter().find(|p| p.id == "mf" && p.is_supported) {
        return prof.clone();
    }

    // Absolute fallback: CPU
    catalog.iter().find(|p| p.id == "cpu").unwrap().clone()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_gpu_detection() {
        let gpus = detect_gpus();
        println!("Detected GPUs: {:?}", gpus);
        assert!(!gpus.is_empty(), "Should detect at least one GPU on Windows");
    }

    #[test]
    fn test_best_encoder_selection() {
        let best = select_best_encoder("auto");
        println!("Best Encoder Selected: {} ({})", best.name, best.codec);
        assert!(best.is_supported, "Selected encoder must be supported");
    }
}
