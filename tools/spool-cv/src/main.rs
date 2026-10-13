/// spool-cv — Estimate 3D printer filament spool remaining weight from a photo.
///
/// Algorithm:
///   1. Load image, convert to grayscale, resize to work size (512px max)
///   2. Build a radial brightness profile from image center outward
///   3. Smooth the profile, compute gradient to find ring boundaries
///   4. Identify hub radius (bright→dark transition from center) and
///      flange radius (last strong edge near image boundary)
///   5. Measure filament fill radius (dark→bright or color-saturation peak)
///   6. fill_pct = (fill_r² - hub_r²) / (flange_r² - hub_r²)  [area-proportional]
///
/// Outputs JSON to stdout:
///   {"fill_pct":0.72,"estimated_g":720,"confidence":"high","reasoning":"..."}

use clap::Parser;
use image::{DynamicImage, GenericImageView, ImageReader};
use serde::Serialize;
use std::path::PathBuf;

#[derive(Parser)]
#[command(name = "spool-cv", about = "Estimate filament spool fill from image")]
struct Args {
    /// Path to the spool image (JPEG, PNG, or WebP)
    image: PathBuf,

    /// Full spool weight in grams (default: 1000)
    #[arg(long, default_value_t = 1000.0)]
    full_g: f64,

    /// Debug: print radial profile to stderr
    #[arg(long, default_value_t = false)]
    debug: bool,
}

#[derive(Serialize)]
struct Output {
    fill_pct: f64,
    estimated_g: u32,
    confidence: String,
    reasoning: String,
}

fn main() {
    let args = Args::parse();

    match analyze(&args) {
        Ok(result) => {
            println!("{}", serde_json::to_string(&result).unwrap());
        }
        Err(e) => {
            // Do NOT invent fill_pct on geometry failure — report error only
            println!(r#"{{"error":"{}"}}"#, e);
        }
    }
}

fn analyze(args: &Args) -> Result<Output, String> {
    // ── Load & resize ──────────────────────────────────────────────────────
    let img = ImageReader::open(&args.image)
        .map_err(|e| format!("open: {e}"))?
        .decode()
        .map_err(|e| format!("decode: {e}"))?;

    // Resize so longest edge = 512px — faster, enough detail
    let img = resize_max(&img, 512);
    let (w, h) = img.dimensions();
    let cx = w as f64 / 2.0;
    let cy = h as f64 / 2.0;
    let max_r = cx.min(cy) * 0.97; // don't go to the very edge

    // ── Build radial profiles ──────────────────────────────────────────────
    // For each radius r, sample N points around a circle, record mean values
    let steps = 256usize;
    let mut lum_profile = vec![0f64; steps];   // luminance (0-255)
    let mut sat_profile = vec![0f64; steps];   // HSV saturation (0-1)

    for (i, r_norm) in (0..steps).map(|i| (i, i as f64 / steps as f64)) {
        let r = r_norm * max_r;
        let n_samples = (2.0 * std::f64::consts::PI * r).max(8.0) as usize;
        let mut lum_sum = 0f64;
        let mut sat_sum = 0f64;

        for k in 0..n_samples {
            let angle = 2.0 * std::f64::consts::PI * k as f64 / n_samples as f64;
            let px = (cx + r * angle.cos()).round() as u32;
            let py = (cy + r * angle.sin()).round() as u32;
            let px = px.min(w - 1);
            let py = py.min(h - 1);

            let pixel = img.get_pixel(px, py);
            let r8 = pixel[0] as f64;
            let g8 = pixel[1] as f64;
            let b8 = pixel[2] as f64;

            // Luminance (perceptual)
            lum_sum += 0.2126 * r8 + 0.7152 * g8 + 0.0722 * b8;

            // HSV saturation (values are 0-255 range)
            let max_c = r8.max(g8).max(b8);
            let min_c = r8.min(g8).min(b8);
            sat_sum += if max_c > 0.0 { (max_c - min_c) / max_c } else { 0.0 };
        }

        lum_profile[i] = lum_sum / n_samples as f64;
        sat_profile[i] = sat_sum / n_samples as f64;
    }

    // ── Smooth profiles (simple box filter, radius 3) ──────────────────────
    let lum_smooth = smooth(&lum_profile, 3);
    let sat_smooth = smooth(&sat_profile, 3);

    if args.debug {
        for i in 0..steps {
            eprintln!(
                "r={:.3} lum={:.1} sat={:.3}",
                i as f64 / steps as f64,
                lum_smooth[i],
                sat_smooth[i]
            );
        }
    }

    // ── Find hub radius ────────────────────────────────────────────────────
    // Hub = dark plastic center. In most spools the very center (r<0.05) is
    // the hub axle hole (may be bright or dark). The hub body extends from
    // ~0.05 to ~0.25 normalized radius.
    // Strategy: find first local minimum in luminance after the center
    // (the dark hub body), then the first rise after that = inner filament edge.
    let hub_r_norm = find_hub_radius(&lum_smooth, &sat_smooth);
    let flange_r_norm = find_flange_radius(&lum_smooth, steps);
    let fill_r_norm = find_fill_radius(&lum_smooth, &sat_smooth, hub_r_norm, flange_r_norm);

    if args.debug {
        eprintln!(
            "hub_r={:.3} fill_r={:.3} flange_r={:.3}",
            hub_r_norm, fill_r_norm, flange_r_norm
        );
    }

    // ── Sanity checks ──────────────────────────────────────────────────────
    let confidence;
    let reasoning;

    // Geometry must be hub < fill <= flange, and hub shouldn't be > 40% of max_r
    let geom_ok = hub_r_norm < fill_r_norm
        && fill_r_norm <= flange_r_norm
        && hub_r_norm < 0.40
        && flange_r_norm > 0.50
        && (flange_r_norm - hub_r_norm) > 0.15;

    // Saturation check: filament region should have higher saturation than hub
    let sat_hub = mean_range(&sat_smooth, 0, (hub_r_norm * steps as f64) as usize);
    let sat_fill = mean_range(
        &sat_smooth,
        (hub_r_norm * steps as f64) as usize,
        (fill_r_norm * steps as f64) as usize,
    );

    // Check image is likely a spool: should have a dark region + lighter ring
    let lum_center = mean_range(&lum_smooth, 0, (0.15 * steps as f64) as usize);
    let lum_mid = mean_range(
        &lum_smooth,
        (0.2 * steps as f64) as usize,
        (0.7 * steps as f64) as usize,
    );
    let looks_like_spool = lum_center < lum_mid + 30.0; // center not drastically brighter than body

    let fill_pct = if geom_ok {
        let hub2 = hub_r_norm * hub_r_norm;
        let fill2 = fill_r_norm * fill_r_norm;
        let flange2 = flange_r_norm * flange_r_norm;
        ((fill2 - hub2) / (flange2 - hub2)).clamp(0.0, 1.0)
    } else {
        0.5 // fallback
    };

    if !looks_like_spool {
        confidence = "low".to_string();
        reasoning = format!(
            "image may not be a spool face-on (lum_center={lum_center:.0} lum_mid={lum_mid:.0}); estimate unreliable"
        );
    } else if !geom_ok {
        confidence = "low".to_string();
        reasoning = format!(
            "could not resolve ring boundaries (hub={hub_r_norm:.2} fill={fill_r_norm:.2} flange={flange_r_norm:.2}); defaulting to 50%"
        );
    } else if sat_fill < sat_hub - 0.05 || (fill_r_norm - hub_r_norm) < 0.03 {
        confidence = "medium".to_string();
        reasoning = format!(
            "ring detected but low saturation contrast (sat_hub={sat_hub:.2} sat_fill={sat_fill:.2}); fill={:.0}%",
            fill_pct * 100.0
        );
    } else {
        confidence = "high".to_string();
        reasoning = format!(
            "hub={:.0}% flange={:.0}% fill={:.0}% of radius; area ratio={:.0}%",
            hub_r_norm * 100.0,
            flange_r_norm * 100.0,
            fill_r_norm * 100.0,
            fill_pct * 100.0,
        );
    }

    let estimated_g = (fill_pct * args.full_g).round() as u32;

    Ok(Output {
        fill_pct: (fill_pct * 1000.0).round() / 1000.0,
        estimated_g,
        confidence,
        reasoning,
    })
}

// ── Algorithm helpers ──────────────────────────────────────────────────────

/// Find hub outer edge: the point where luminance first rises significantly
/// after the dark hub body (from center outward).
fn find_hub_radius(lum: &[f64], sat: &[f64]) -> f64 {
    let n = lum.len();
    // Skip the very center axle (first 3%)
    let start = (0.03 * n as f64) as usize;
    let end = (0.45 * n as f64) as usize;

    // Find minimum luminance in hub region (the dark hub body)
    let mut min_lum = f64::MAX;
    let mut min_idx = start;
    for i in start..end {
        if lum[i] < min_lum {
            min_lum = lum[i];
            min_idx = i;
        }
    }

    // After the minimum, find where luminance rises by >15 units (filament starts)
    for i in min_idx..end {
        if lum[i] > min_lum + 15.0 || sat[i] > 0.15 {
            return i as f64 / n as f64;
        }
    }

    // Fallback: use saturation onset
    for i in start..end {
        if sat[i] > 0.12 {
            return i as f64 / n as f64;
        }
    }

    0.20 // default hub radius
}

/// Find outer flange: the last strong brightness drop before image edge.
/// Flange is the plastic rim — usually bright (white/grey) then drops to background.
fn find_flange_radius(lum: &[f64], n: usize) -> f64 {
    // Search inward from 95% radius for last bright region
    let outer = (0.95 * n as f64) as usize;
    let inner = (0.50 * n as f64) as usize;

    // Find the last local maximum in luminance (bright flange rim)
    let mut best = inner;
    let mut best_lum = 0f64;
    for i in inner..outer {
        if lum[i] > best_lum {
            best_lum = lum[i];
            best = i;
        }
    }

    // Walk outward from best to find the drop-off
    for i in best..outer {
        if lum[i] < best_lum - 20.0 {
            return (i as f64 - 2.0) / n as f64;
        }
    }

    0.85 // default flange radius
}

/// Find filament fill edge: the outermost point with significant saturation
/// or luminance, between hub and flange.
fn find_fill_radius(lum: &[f64], sat: &[f64], hub_r: f64, flange_r: f64) -> f64 {
    let n = lum.len();
    let hub_i = (hub_r * n as f64) as usize;
    let flange_i = (flange_r * n as f64) as usize;

    if hub_i >= flange_i {
        return flange_r;
    }

    // Strategy: scan outward from hub, find the last index with
    // either high saturation (colored filament) or luminance above hub level
    let hub_lum = mean_range(lum, 0, hub_i.max(1));
    let threshold_lum = hub_lum + 10.0;
    let threshold_sat = 0.10;

    let mut last_filament = hub_i;
    for i in hub_i..flange_i {
        if lum[i] > threshold_lum || sat[i] > threshold_sat {
            last_filament = i;
        }
    }

    (last_filament as f64 / n as f64).clamp(hub_r, flange_r)
}

// ── Image utilities ────────────────────────────────────────────────────────

fn resize_max(img: &DynamicImage, max_px: u32) -> image::ImageBuffer<image::Rgb<u8>, Vec<u8>> {
    let (w, h) = img.dimensions();
    let scale = (max_px as f64 / w.max(h) as f64).min(1.0);
    let nw = (w as f64 * scale) as u32;
    let nh = (h as f64 * scale) as u32;
    img.resize(nw, nh, image::imageops::FilterType::Triangle)
        .to_rgb8()
}

fn smooth(v: &[f64], radius: usize) -> Vec<f64> {
    let n = v.len();
    let mut out = vec![0f64; n];
    for i in 0..n {
        let lo = i.saturating_sub(radius);
        let hi = (i + radius + 1).min(n);
        let sum: f64 = v[lo..hi].iter().sum();
        out[i] = sum / (hi - lo) as f64;
    }
    out
}

fn mean_range(v: &[f64], start: usize, end: usize) -> f64 {
    if start >= end || end > v.len() {
        return 0.0;
    }
    v[start..end].iter().sum::<f64>() / (end - start) as f64
}
