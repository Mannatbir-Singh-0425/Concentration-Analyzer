"""
Feature Extractor for Colorimetric & Spectrophotometric Assay Images
Extracts multi-color space metrics (RGB, CIE-Lab, HSV, Optical Density, Delta-E, Ratios)
with laboratory-grade analytical accuracy.
"""

import cv2
import numpy as np
import math


def rgb_to_hex(r: float, g: float, b: float) -> str:
    """Convert RGB float values [0-255] to hex string."""
    r_int = int(np.clip(round(r), 0, 255))
    g_int = int(np.clip(round(g), 0, 255))
    b_int = int(np.clip(round(b), 0, 255))
    return f"#{r_int:02x}{g_int:02x}{b_int:02x}"


def extract_features_from_bgr(img_bgr: np.ndarray, blank_features: dict = None) -> dict:
    """
    Extract comprehensive analytical features from a cropped BGR image or ROI.
    
    Parameters:
    - img_bgr: np.ndarray (H, W, 3) in BGR format (OpenCV standard)
    - blank_features: optional dict of features from a blank reference sample (0 concentration)
    
    Returns:
    - dict containing named scalar features, dominant channels, hex color, and feature vector.
    """
    if img_bgr is None or img_bgr.size == 0:
        raise ValueError("Invalid or empty image supplied to feature extractor.")

    # Convert color spaces
    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    img_lab = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2LAB)
    img_hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    img_gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)

    # 1. RGB statistics
    r_chan = img_rgb[:, :, 0].astype(np.float64)
    g_chan = img_rgb[:, :, 1].astype(np.float64)
    b_chan = img_rgb[:, :, 2].astype(np.float64)

    mean_r = float(np.mean(r_chan))
    mean_g = float(np.mean(g_chan))
    mean_b = float(np.mean(b_chan))

    std_r = float(np.std(r_chan))
    std_g = float(np.std(g_chan))
    std_b = float(np.std(b_chan))

    median_r = float(np.median(r_chan))
    median_g = float(np.median(g_chan))
    median_b = float(np.median(b_chan))

    # 2. CIE-L*a*b* statistics (OpenCV: L in [0, 255], a in [0, 255], b in [0, 255])
    # Standard CIE L* is [0, 100], a* is [-128, 127], b* is [-128, 127]
    L_raw = img_lab[:, :, 0].astype(np.float64) * (100.0 / 255.0)
    a_raw = img_lab[:, :, 1].astype(np.float64) - 128.0
    b_raw = img_lab[:, :, 2].astype(np.float64) - 128.0

    mean_L = float(np.mean(L_raw))
    mean_a = float(np.mean(a_raw))
    mean_b_lab = float(np.mean(b_raw))
    std_L = float(np.std(L_raw))

    # 3. HSV statistics
    # OpenCV Hue is [0, 180], S is [0, 255], V is [0, 255]
    H_chan = img_hsv[:, :, 0].astype(np.float64) * 2.0  # Scale to [0, 360]
    S_chan = img_hsv[:, :, 1].astype(np.float64) / 255.0  # Scale to [0, 1]
    V_chan = img_hsv[:, :, 2].astype(np.float64) / 255.0

    mean_h = float(np.mean(H_chan))
    mean_s = float(np.mean(S_chan))
    mean_v = float(np.mean(V_chan))

    # 4. Luminance / Gray
    mean_gray = float(np.mean(img_gray))
    std_gray = float(np.std(img_gray))

    # 5. Channel Ratios & Normalized Differences
    eps = 1e-6
    ratio_rg = float(mean_r / (mean_g + eps))
    ratio_bg = float(mean_b / (mean_g + eps))
    ratio_rb = float(mean_r / (mean_b + eps))
    norm_diff_rb = float((mean_r - mean_b) / (mean_r + mean_b + eps))
    norm_diff_gb = float((mean_g - mean_b) / (mean_g + mean_b + eps))

    # 6. Optical Density (OD) calculation
    # If blank is supplied: OD = -log10((I + eps) / (I_blank + eps))
    # Otherwise, reference to full scale 255.0
    if blank_features:
        blank_r = max(blank_features.get("mean_r", 255.0), eps)
        blank_g = max(blank_features.get("mean_g", 255.0), eps)
        blank_b = max(blank_features.get("mean_b", 255.0), eps)
        blank_L = blank_features.get("mean_L", 100.0)
        blank_a = blank_features.get("mean_a", 0.0)
        blank_b_lab = blank_features.get("mean_b_lab", 0.0)

        od_r = float(-np.log10(max(mean_r, eps) / blank_r))
        od_g = float(-np.log10(max(mean_g, eps) / blank_g))
        od_b = float(-np.log10(max(mean_b, eps) / blank_b))
        od_gray = float(-np.log10(max(mean_gray, eps) / max(blank_features.get("mean_gray", 255.0), eps)))

        # Delta E from blank in CIE-Lab
        delta_L = mean_L - blank_L
        delta_a = mean_a - blank_a
        delta_b = mean_b_lab - blank_b_lab
        delta_E = float(math.sqrt(delta_L**2 + delta_a**2 + delta_b**2))
    else:
        # Default reference to 255
        od_r = float(-np.log10(max(mean_r, eps) / 255.0))
        od_g = float(-np.log10(max(mean_g, eps) / 255.0))
        od_b = float(-np.log10(max(mean_b, eps) / 255.0))
        od_gray = float(-np.log10(max(mean_gray, eps) / 255.0))
        delta_E = 0.0

    hex_color = rgb_to_hex(mean_r, mean_g, mean_b)

    # Feature vector for ML algorithms (standardized 18 features)
    feature_vector = [
        mean_r, mean_g, mean_b,
        std_r, std_g, std_b,
        mean_L, mean_a, mean_b_lab,
        mean_h, mean_s, mean_v,
        mean_gray,
        ratio_rg, ratio_bg, ratio_rb,
        od_r, od_g, od_b,
        delta_E
    ]

    return {
        "mean_r": round(mean_r, 3),
        "mean_g": round(mean_g, 3),
        "mean_b": round(mean_b, 3),
        "std_r": round(std_r, 3),
        "std_g": round(std_g, 3),
        "std_b": round(std_b, 3),
        "median_r": round(median_r, 3),
        "median_g": round(median_g, 3),
        "median_b": round(median_b, 3),
        "mean_L": round(mean_L, 3),
        "mean_a": round(mean_a, 3),
        "mean_b_lab": round(mean_b_lab, 3),
        "std_L": round(std_L, 3),
        "mean_h": round(mean_h, 3),
        "mean_s": round(mean_s, 4),
        "mean_v": round(mean_v, 4),
        "mean_gray": round(mean_gray, 3),
        "std_gray": round(std_gray, 3),
        "ratio_rg": round(ratio_rg, 4),
        "ratio_bg": round(ratio_bg, 4),
        "ratio_rb": round(ratio_rb, 4),
        "norm_diff_rb": round(norm_diff_rb, 4),
        "norm_diff_gb": round(norm_diff_gb, 4),
        "od_r": round(od_r, 4),
        "od_g": round(od_g, 4),
        "od_b": round(od_b, 4),
        "od_gray": round(od_gray, 4),
        "delta_E": round(delta_E, 3),
        "hex_color": hex_color,
        "feature_vector": feature_vector
    }


def extract_features_from_bytes(image_bytes: bytes, blank_features: dict = None) -> dict:
    """Decode raw image bytes and extract full features."""
    np_arr = np.frombuffer(image_bytes, np.uint8)
    img_bgr = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    if img_bgr is None:
        raise ValueError("Could not decode image from byte stream.")
    return extract_features_from_bgr(img_bgr, blank_features=blank_features)
