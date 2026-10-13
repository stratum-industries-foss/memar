/// print-cv — Detect 3D print failures from webcam frames.
///
/// Checks:
///   A. frame_diff      — sudden large change or zero motion (layer shift / stall)
///   B. edge_density    — Sobel edge fraction (spaghetti = high chaotic edges)
///   C. brightness      — global mean (lens blocked, blob, whiteout)
///   D. texture_variance — center crop variance (adhesion failure = featureless)
///
/// Usage:
///   print-cv <current.jpg> [--prev <prev.jpg>]
///   stdout: JSON {anomaly, score, type, confidence, reasoning, checks}

use clap::Parser;
use image::{ImageReader};
use serde::Serialize;
use std::path::PathBuf;

#[derive(Parser)]
#[command(name = "print-cv", about = "Detect 3D print anomalies from webcam frame")]
struct Args {
    /// Current frame image path
    frame: PathBuf,
    /// Previous frame path for motion diff
    #[arg(long)]
    prev: Option<PathBuf>,
}

#[derive(Serialize, Clone)]
struct CheckResult {
    score: f64,
    anomaly: bool,
    #[serde(rename = "type")]
    anomaly_type: String,
}

#[derive(Serialize)]
struct Checks {
    frame_diff: CheckResult,
    edge_density: CheckResult,
    brightness: CheckResult,
    texture_variance: CheckResult,
}

#[derive(Serialize)]
struct Output {
    anomaly: bool,
    score: f64,
    #[serde(rename = "type")]
    anomaly_type: String,
    confidence: String,
    reasoning: String,
    checks: Checks,
}

fn main() {
    let (output, exit_code) = match run() {
        Ok(o) => (serde_json::to_string(&o).unwrap_or_else(|e| format!(r#"{{"anomaly":true,"type":"cv_error","error":"{}"}}"#, e)), 0),
        Err(e) => (format!(r#"{{"anomaly":true,"type":"cv_error","error":"{}"}}"#, e), 2),
    };
    println!("{}", output);
    std::process::exit(exit_code);
}

fn run() -> Result<Output, String> {
    let args = Args::parse();

    let cur_img = load_gray(&args.frame, 320, 240)?;
    let w: u32 = 320; let h: u32 = 240;
    if w < 3 || h < 3 { return Err("image too small".into()); }

    // ── A. Frame diff ────────────────────────────────────────────────────────
    let frame_diff = if let Some(prev_path) = &args.prev {
        let prev_img = load_gray(prev_path, 320, 240)?;
        let diff: f64 = cur_img.iter().zip(prev_img.iter())
            .map(|(&a, &b)| (a as i32 - b as i32).unsigned_abs() as f64)
            .sum::<f64>() / (cur_img.len() as f64 * 255.0);

        let (anom, atype) = if diff > 0.35 {
            (true, "layer_shift")
        } else if diff < 0.0005 {
            (true, "print_stall")
        } else {
            (false, "ok")
        };
        CheckResult { score: round3(diff), anomaly: anom, anomaly_type: atype.into() }
    } else {
        CheckResult { score: 0.0, anomaly: false, anomaly_type: "ok".into() }
    };

    // ── B. Edge density (Sobel) ──────────────────────────────────────────────
    let gx_kernel: [[i32; 3]; 3] = [[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]];
    let gy_kernel: [[i32; 3]; 3] = [[-1, -2, -1], [0, 0, 0], [1, 2, 1]];
    let mut edge_count = 0u32;
    let total_inner = ((w - 2) * (h - 2)) as f64;

    for y in 1..(h - 1) {
        for x in 1..(w - 1) {
            let mut gx = 0i32;
            let mut gy = 0i32;
            for ky in 0..3usize {
                for kx in 0..3usize {
                    let px = (x as i32 + kx as i32 - 1) as usize;
                    let py = (y as i32 + ky as i32 - 1) as usize;
                    let v = cur_img[py * w as usize + px] as i32;
                    gx += gx_kernel[ky][kx] * v;
                    gy += gy_kernel[ky][kx] * v;
                }
            }
            let mag = ((gx * gx + gy * gy) as f64).sqrt();
            if mag > 30.0 {
                edge_count += 1;
            }
        }
    }
    let edge_frac = edge_count as f64 / total_inner;
    let edge_density = CheckResult {
        score: round3(edge_frac),
        anomaly: edge_frac > 0.25,
        anomaly_type: if edge_frac > 0.25 { "spaghetti".into() } else { "ok".into() },
    };

    // ── C. Brightness ────────────────────────────────────────────────────────
    let mean_brightness = cur_img.iter().map(|&v| v as f64).sum::<f64>()
        / (cur_img.len() as f64 * 255.0);
    let brightness = CheckResult {
        score: round3(mean_brightness),
        anomaly: mean_brightness < 0.08 || mean_brightness >= 0.99,
        anomaly_type: if mean_brightness < 0.08 || mean_brightness >= 0.99 {
            "brightness".into()
        } else {
            "ok".into()
        },
    };

    // ── D. Texture variance (center 60% crop) ────────────────────────────────
    let x0 = (w as f64 * 0.2) as usize;
    let x1 = (w as f64 * 0.8) as usize;
    let y0 = (h as f64 * 0.2) as usize;
    let y1 = (h as f64 * 0.8) as usize;
    let mut crop_vals: Vec<f64> = Vec::new();
    for y in y0..y1 {
        for x in x0..x1 {
            crop_vals.push(cur_img[y * w as usize + x] as f64);
        }
    }
    let n = crop_vals.len() as f64;
    let mean_c = crop_vals.iter().sum::<f64>() / n;
    let variance = crop_vals.iter().map(|&v| (v - mean_c).powi(2)).sum::<f64>() / n;
    let norm_var = (variance / (255.0 * 255.0)).clamp(0.0, 1.0);
    let texture_variance = CheckResult {
        score: round3(norm_var),
        anomaly: norm_var < 0.0002,
        anomaly_type: if norm_var < 0.0002 { "adhesion_failure".into() } else { "ok".into() },
    };

    // ── Aggregate ────────────────────────────────────────────────────────────
    let triggered: Vec<&CheckResult> = [&frame_diff, &edge_density, &brightness, &texture_variance]
        .iter().filter(|c| c.anomaly).copied().collect();

    let anomaly = !triggered.is_empty();
    let priority: &[&CheckResult] = &[&frame_diff, &edge_density, &brightness, &texture_variance];
    let worst = priority.iter().copied().find(|c| c.anomaly);

    let (score, anomaly_type, confidence) = if let Some(w) = worst {
        let conf = if triggered.len() >= 2 { "high" }
                   else if w.score > 0.2 { "high" }
                   else { "medium" };
        (w.score, w.anomaly_type.clone(), conf.to_string())
    } else {
        (0.0, "ok".to_string(), "high".to_string())
    };

    let reasoning = if anomaly {
        let parts: Vec<String> = triggered.iter()
            .map(|c| format!("{} ({:.0}%)", c.anomaly_type, c.score * 100.0))
            .collect();
        parts.join("; ")
    } else {
        format!("all checks ok (edge={:.0}% bright={:.0}%)",
            edge_density.score * 100.0, brightness.score * 100.0)
    };

    Ok(Output {
        anomaly,
        score: round3(score),
        anomaly_type,
        confidence,
        reasoning,
        checks: Checks { frame_diff, edge_density, brightness, texture_variance },
    })
}

// ── Helpers ──────────────────────────────────────────────────────────────────

fn load_gray(path: &PathBuf, w: u32, h: u32) -> Result<Vec<u8>, String> {
    let img = ImageReader::open(path)
        .map_err(|e| format!("open {:?}: {e}", path))?
        .decode()
        .map_err(|e| format!("decode {:?}: {e}", path))?;
    let resized = img.resize_exact(w, h, image::imageops::FilterType::Triangle);
    let gray = resized.grayscale().to_luma8();
    let raw = gray.into_raw(); // Vec<u8>, row-major
    Ok(raw)
}

fn round3(v: f64) -> f64 {
    (v * 1000.0).round() / 1000.0
}
