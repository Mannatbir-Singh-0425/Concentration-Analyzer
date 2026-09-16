"""
Image Processing, ROI Slicing, Illumination Normalization & Spot Detection
Supports circular wells, rectangular test strips, and automatic white-balance correction.
"""

import cv2
import numpy as np
import base64
from typing import Tuple, Dict, Any, List, Optional


def decode_image(image_bytes: bytes) -> np.ndarray:
    """Decode image bytes into OpenCV BGR numpy array."""
    np_arr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Failed to decode image from buffer.")
    return img


def encode_image_base64(img_bgr: np.ndarray, quality: int = 85) -> str:
    """Encode OpenCV BGR image into base64 JPEG string."""
    encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), quality]
    success, enc = cv2.imencode(".jpg", img_bgr, encode_param)
    if not success:
        raise ValueError("Failed to encode image to base64.")
    return base64.b64encode(enc).decode("utf-8")


def apply_gray_world_normalization(img_bgr: np.ndarray) -> np.ndarray:
    """
    Gray-World Color Constancy algorithm to neutralize ambient lighting shifts
    (e.g., warm fluorescent bulbs vs cool phone flash).
    """
    b, g, r = cv2.split(img_bgr.astype(np.float32))
    mean_b = np.mean(b) + 1e-6
    mean_g = np.mean(g) + 1e-6
    mean_r = np.mean(r) + 1e-6

    gray_avg = (mean_b + mean_g + mean_r) / 3.0

    b_norm = np.clip(b * (gray_avg / mean_b), 0, 255)
    g_norm = np.clip(g * (gray_avg / mean_g), 0, 255)
    r_norm = np.clip(r * (gray_avg / mean_r), 0, 255)

    return cv2.merge([b_norm, g_norm, r_norm]).astype(np.uint8)


def extract_roi(
    img_bgr: np.ndarray,
    roi_data: Optional[Dict[str, Any]] = None
) -> Tuple[np.ndarray, Optional[np.ndarray]]:
    """
    Extract Region of Interest (ROI).
    
    Supports:
    - 'rect': {"type": "rect", "x": int, "y": int, "w": int, "h": int}
    - 'circle': {"type": "circle", "cx": int, "cy": int, "radius": int}
    - None: Full image with central 80% default margin
    
    Returns:
    - cropped_bgr: BGR patch containing the ROI
    - mask: binary mask (255 inside ROI, 0 outside) or None
    """
    h, w, _ = img_bgr.shape

    if roi_data is None:
        # Default: center 70% region
        x1, y1 = int(w * 0.15), int(h * 0.15)
        x2, y2 = int(w * 0.85), int(h * 0.85)
        cropped = img_bgr[y1:y2, x1:x2]
        return cropped, None

    roi_type = roi_data.get("type", "rect")

    if roi_type == "circle":
        cx = int(roi_data.get("cx", w // 2))
        cy = int(roi_data.get("cy", h // 2))
        radius = int(roi_data.get("radius", min(w, h) // 4))

        # Bounding box of the circle
        x1 = max(0, cx - radius)
        y1 = max(0, cy - radius)
        x2 = min(w, cx + radius)
        y2 = min(h, cy + radius)

        cropped = img_bgr[y1:y2, x1:x2].copy()
        ch, cw, _ = cropped.shape

        # Create circle mask inside bounding box
        mask = np.zeros((ch, cw), dtype=np.uint8)
        circle_cx = cx - x1
        circle_cy = cy - y1
        cv2.circle(mask, (circle_cx, circle_cy), radius, 255, -1)

        # Mask pixels outside circle to avoid edge noise
        # Compute mean using only the masked circle pixels
        masked_pixels = cropped[mask == 255]
        if len(masked_pixels) > 0:
            avg_color = np.mean(masked_pixels, axis=0).astype(np.uint8)
            # Create a uniform or masked patch
            patch_clean = np.full_like(cropped, avg_color)
            patch_clean[mask == 255] = cropped[mask == 255]
            return patch_clean, mask
        return cropped, mask

    else:
        # Rectangle ROI
        x = int(roi_data.get("x", 0))
        y = int(roi_data.get("y", 0))
        rw = int(roi_data.get("w", w))
        rh = int(roi_data.get("h", h))

        x1 = max(0, min(x, w - 1))
        y1 = max(0, min(y, h - 1))
        x2 = max(x1 + 1, min(x + rw, w))
        y2 = max(y1 + 1, min(y + rh, h))

        cropped = img_bgr[y1:y2, x1:x2]
        return cropped, None


def auto_detect_spots(img_bgr: np.ndarray, max_spots: int = 12) -> List[Dict[str, int]]:
    """
    Auto-detect circular assay wells (e.g. 96-well plate, petri spots, μPADs)
    using adaptive thresholding and contour circularity filtering.
    """
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (9, 9), 2)
    h, w = gray.shape

    min_dist = min(h, w) // 10
    min_radius = min(h, w) // 30
    max_radius = min(h, w) // 6

    circles = cv2.HoughCircles(
        blurred,
        cv2.HOUGH_GRADIENT,
        dp=1.2,
        minDist=min_dist,
        param1=50,
        param2=30,
        minRadius=min_radius,
        maxRadius=max_radius
    )

    detected = []
    if circles is not None:
        circles = np.round(circles[0, :]).astype("int")
        # Sort top-to-bottom, left-to-right
        sorted_circles = sorted(circles, key=lambda c: (c[1] // (2 * min_radius), c[0]))
        for i, (cx, cy, r) in enumerate(sorted_circles[:max_spots]):
            detected.append({
                "id": i + 1,
                "type": "circle",
                "cx": int(cx),
                "cy": int(cy),
                "radius": int(r)
            })

    return detected
