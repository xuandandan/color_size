from __future__ import annotations

from io import BytesIO

import numpy as np
from PIL import Image
from skimage.color import deltaE_ciede2000, rgb2lab
from skimage.metrics import structural_similarity


def _load_and_align_images(a_bytes: bytes, b_bytes: bytes) -> tuple[np.ndarray, np.ndarray]:
    img_a = Image.open(BytesIO(a_bytes)).convert("RGB")
    img_b = Image.open(BytesIO(b_bytes)).convert("RGB")
    if img_a.size != img_b.size:
        img_b = img_b.resize(img_a.size, Image.Resampling.BILINEAR)
    arr_a = np.asarray(img_a, dtype=np.float32) / 255.0
    arr_b = np.asarray(img_b, dtype=np.float32) / 255.0
    return arr_a, arr_b


def compare_images(a_bytes: bytes, b_bytes: bytes) -> dict:
    arr_a, arr_b = _load_and_align_images(a_bytes, b_bytes)

    diff = arr_a - arr_b
    rgb_rmse = float(np.sqrt(np.mean(diff**2)) * 255.0)
    rgb_mae = float(np.mean(np.abs(diff)) * 255.0)

    lab_a = rgb2lab(arr_a)
    lab_b = rgb2lab(arr_b)
    delta_e_map = deltaE_ciede2000(lab_a, lab_b)
    delta_e_00 = float(np.mean(delta_e_map))

    ssim_score = float(structural_similarity(arr_a, arr_b, channel_axis=2, data_range=1.0))

    # Trust score from 0-100, weighted by perceptual color error and structure.
    de_component = max(0.0, 100.0 - min(100.0, delta_e_00 * 20.0))
    rmse_component = max(0.0, 100.0 - min(100.0, rgb_rmse * 2.0))
    ssim_component = max(0.0, min(100.0, ssim_score * 100.0))
    trust_score = 0.5 * de_component + 0.2 * rmse_component + 0.3 * ssim_component

    if delta_e_00 < 1.5 and ssim_score > 0.98:
        level = "excellent"
    elif delta_e_00 < 2.5 and ssim_score > 0.95:
        level = "good"
    elif delta_e_00 < 4.0 and ssim_score > 0.90:
        level = "acceptable"
    else:
        level = "needs_tuning"

    return {
        "delta_e_00": round(delta_e_00, 4),
        "rgb_rmse": round(rgb_rmse, 4),
        "rgb_mae": round(rgb_mae, 4),
        "ssim": round(ssim_score, 4),
        "trust_score": round(float(trust_score), 2),
        "level": level,
    }
