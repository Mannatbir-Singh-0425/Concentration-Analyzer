"""
Demo Assay & Synthetic Colorimetric Standard Generator
Generates realistic photographic calibration standards and unknown validation samples
for immediate testing (Bradford Protein, Nitrate Water Quality, Glucose Dipstick).
"""

import cv2
import numpy as np
import base64
from typing import Dict, Any, List, Tuple
from core.feature_extractor import extract_features_from_bgr


def _create_well_image(
    base_bgr: Tuple[int, int, int],
    target_bgr: Tuple[int, int, int],
    fraction: float,
    size: int = 240,
    is_strip: bool = False
) -> np.ndarray:
    """
    Synthesizes a high-fidelity photographic well or strip patch with:
    - Non-linear color absorption
    - Subtle Gaussian noise & texture
    - Radial meniscus vignette
    - Specular glass highlight reflection
    """
    img = np.ones((size, size, 3), dtype=np.float32)

    # Interpolate color according to fraction (sigmoidal/Beer-Lambert response)
    # fraction in [0, 1]
    f = float(np.clip(fraction, 0.0, 1.0))
    # Beer-Lambert optical density simulation:
    # Color absorbance increases nonlinearly
    color = [
        base_bgr[0] * (1.0 - f) + target_bgr[0] * f,
        base_bgr[1] * (1.0 - f) + target_bgr[1] * f,
        base_bgr[2] * (1.0 - f) + target_bgr[2] * f,
    ]

    # Background plate / tray color (neutral dark lab plastic or white tile)
    if is_strip:
        # White nitrocellulose strip pad on plastic backing
        img[:] = [240, 240, 240]  # Off-white plastic
        pad_margin = int(size * 0.15)
        # Test pad
        for c in range(3):
            img[pad_margin:-pad_margin, pad_margin:-pad_margin, c] = color[c]
    else:
        # Circular microtiter well in a black/translucent plate
        img[:] = [30, 32, 38]  # Laboratory dark plate background
        cy, cx = size // 2, size // 2
        radius = int(size * 0.42)

        # Coordinate grids for radial effects
        y, x = np.ogrid[:size, :size]
        dist_from_center = np.sqrt((x - cx)**2 + (y - cy)**2)
        well_mask = dist_from_center <= radius

        # Fill well with solution color
        for c in range(3):
            chan = img[:, :, c]
            # Meniscus darkening towards well edge
            vignette = 1.0 - 0.25 * (dist_from_center / radius)**2
            vignette = np.clip(vignette, 0.7, 1.0)
            chan[well_mask] = color[c] * vignette[well_mask]
            img[:, :, c] = chan

        # Add subtle glass ring border
        ring_mask = (dist_from_center >= radius - 3) & (dist_from_center <= radius + 2)
        img[ring_mask] = img[ring_mask] * 0.5 + 40

        # Subtle specular glint reflection on upper-left quadrant
        glint_dist = np.sqrt((x - (cx - radius * 0.45))**2 + (y - (cy - radius * 0.45))**2)
        glint_mask = (glint_dist < radius * 0.18) & well_mask
        glint_factor = np.clip(1.0 - (glint_dist / (radius * 0.18)), 0, 1)
        for c in range(3):
            chan = img[:, :, c]
            chan[glint_mask] = chan[glint_mask] * (1.0 - glint_factor[glint_mask]) + 250.0 * glint_factor[glint_mask]
            img[:, :, c] = chan

    # Add realistic sensor noise (Gaussian ± 2.5 levels)
    noise = np.random.normal(0, 2.5, img.shape).astype(np.float32)
    img = np.clip(img + noise, 0, 255).astype(np.uint8)

    # Slight blur to mimic camera optical anti-aliasing
    img = cv2.GaussianBlur(img, (3, 3), 0.5)
    return img


def get_preset_datasets() -> Dict[str, Any]:
    """
    Returns dictionary of all available pre-configured benchmark assays.
    """
    return {
        "bradford": {
            "id": "bradford",
            "title": "Bradford Protein Assay (BSA)",
            "analyte": "Bovine Serum Albumin",
            "unit": "µg/mL",
            "description": "Colorimetric Coomassie Brilliant Blue G-250 assay for protein quantitation at 595 nm. Color transitions from reddish-amber (0 µg/mL) to intense royal blue (1000 µg/mL).",
            "is_strip": False,
            "standards": [
                {"conc": 0.0, "label": "Standard 0 (Blank)"},
                {"conc": 125.0, "label": "Standard 1"},
                {"conc": 250.0, "label": "Standard 2"},
                {"conc": 500.0, "label": "Standard 3"},
                {"conc": 750.0, "label": "Standard 4"},
                {"conc": 1000.0, "label": "Standard 5"}
            ],
            "unknowns": [
                {"true_conc": 340.0, "label": "Cell Lysate Sample A"},
                {"true_conc": 680.0, "label": "Purified Fraction B"},
                {"true_conc": 75.0, "label": "Diluted Wash Fraction C"}
            ],
            "colors": {
                "base": (40, 85, 195),    # Reddish-brown / amber in BGR
                "target": (185, 75, 25)    # Intense Royal Blue in BGR
            }
        },
        "nitrate": {
            "id": "nitrate",
            "title": "Nitrate (NO₃⁻) Water Quality Assay",
            "analyte": "Nitrate (NO₃⁻)",
            "unit": "mg/L (ppm)",
            "description": "Griess diazotization reaction for environmental water testing. Converts from clear/pale straw (0 ppm) to deep magenta-pink azo dye (50 ppm).",
            "is_strip": False,
            "standards": [
                {"conc": 0.0, "label": "Deionized Blank"},
                {"conc": 5.0, "label": "Standard 5 ppm"},
                {"conc": 10.0, "label": "Standard 10 ppm"},
                {"conc": 20.0, "label": "Standard 20 ppm"},
                {"conc": 35.0, "label": "Standard 35 ppm"},
                {"conc": 50.0, "label": "Standard 50 ppm"}
            ],
            "unknowns": [
                {"true_conc": 14.5, "label": "Municipal Tap Water"},
                {"true_conc": 38.0, "label": "Agricultural Runoff Sample"}
            ],
            "colors": {
                "base": (195, 215, 220),  # Pale straw / clear in BGR
                "target": (130, 20, 205)   # Vivid magenta / pink in BGR
            }
        },
        "glucose": {
            "id": "glucose",
            "title": "Glucose Enzymatic Dipstick Assay",
            "analyte": "D-Glucose",
            "unit": "mg/dL",
            "description": "Glucose oxidase / peroxidase test strip pad. Color changes from bright golden yellow (0 mg/dL) through lime to deep teal-emerald (300 mg/dL).",
            "is_strip": True,
            "standards": [
                {"conc": 0.0, "label": "Negative Control (0 mg/dL)"},
                {"conc": 50.0, "label": "Standard 50 mg/dL"},
                {"conc": 100.0, "label": "Standard 100 mg/dL"},
                {"conc": 175.0, "label": "Standard 175 mg/dL"},
                {"conc": 250.0, "label": "Standard 250 mg/dL"},
                {"conc": 300.0, "label": "Standard 300 mg/dL"}
            ],
            "unknowns": [
                {"true_conc": 92.0, "label": "Fasting Specimen (Normal)"},
                {"true_conc": 215.0, "label": "Postprandial Specimen"}
            ],
            "colors": {
                "base": (45, 215, 245),   # Golden Yellow in BGR
                "target": (145, 115, 15)  # Dark Teal-Green in BGR
            }
        }
    }


def generate_preset_assay(preset_id: str = "bradford") -> Dict[str, Any]:
    """
    Generate standard curve images, extract features, and generate validation samples.
    """
    presets = get_preset_datasets()
    if preset_id not in presets:
        preset_id = "bradford"

    cfg = presets[preset_id]
    base_bgr = cfg["colors"]["base"]
    target_bgr = cfg["colors"]["target"]
    is_strip = cfg["is_strip"]

    standards_data = []
    blank_features = None

    max_conc = max([s["conc"] for s in cfg["standards"]])

    for std in cfg["standards"]:
        conc = std["conc"]
        fraction = (conc / max_conc) if max_conc > 0 else 0.0
        # Realistic slight non-linear response
        f_effective = 1.0 - np.exp(-1.8 * fraction) / (1.0 - np.exp(-1.8) + 1e-6)
        f_effective = float(np.clip(f_effective, 0.0, 1.0))

        img_bgr = _create_well_image(base_bgr, target_bgr, f_effective, is_strip=is_strip)
        success, enc = cv2.imencode(".jpg", img_bgr, [cv2.IMWRITE_JPEG_QUALITY, 90])
        img_bytes = enc.tobytes()
        img_b64 = base64.b64encode(img_bytes).decode("utf-8")

        features = extract_features_from_bgr(img_bgr, blank_features=blank_features)
        if conc == 0.0:
            blank_features = features

        standards_data.append({
            "concentration": float(conc),
            "label": std["label"],
            "image_base64": f"data:image/jpeg;base64,{img_b64}",
            "features": features
        })

    unknowns_data = []
    for unk in cfg["unknowns"]:
        true_c = unk["true_conc"]
        fraction = (true_c / max_conc) if max_conc > 0 else 0.0
        f_effective = 1.0 - np.exp(-1.8 * fraction) / (1.0 - np.exp(-1.8) + 1e-6)
        f_effective = float(np.clip(f_effective, 0.0, 1.0))

        img_bgr = _create_well_image(base_bgr, target_bgr, f_effective, is_strip=is_strip)
        success, enc = cv2.imencode(".jpg", img_bgr, [cv2.IMWRITE_JPEG_QUALITY, 90])
        img_bytes = enc.tobytes()
        img_b64 = base64.b64encode(img_bytes).decode("utf-8")
        features = extract_features_from_bgr(img_bgr, blank_features=blank_features)

        unknowns_data.append({
            "label": unk["label"],
            "true_conc": float(true_c),
            "image_base64": f"data:image/jpeg;base64,{img_b64}",
            "features": features
        })

    return {
        "preset_id": preset_id,
        "title": cfg["title"],
        "analyte": cfg["analyte"],
        "unit": cfg["unit"],
        "description": cfg["description"],
        "standards": standards_data,
        "unknowns": unknowns_data
    }
