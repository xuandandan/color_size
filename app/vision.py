from __future__ import annotations

from datetime import datetime
from io import BytesIO
from statistics import pstdev
import numpy as np
from fastapi import UploadFile
from PIL import Image
from skimage.color import rgb2lab

from .models import Measurement, SpectrumPoint, VisionExtractResult


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _normalize_roi(left: float, top: float, width: float, height: float) -> tuple[float, float, float, float]:
    left = max(0.0, min(1.0, float(left)))
    top = max(0.0, min(1.0, float(top)))
    width = max(1e-6, min(1.0, float(width)))
    height = max(1e-6, min(1.0, float(height)))
    if left + width > 1.0:
        width = 1.0 - left
    if top + height > 1.0:
        height = 1.0 - top
    return left, top, width, height


def _rgb_int_to_lab_dict(r: int, g: int, b: int) -> dict[str, float]:
    arr = np.array([[[r / 255.0, g / 255.0, b / 255.0]]], dtype=np.float64)
    lab = rgb2lab(arr)[0, 0]
    return {"L": round(float(lab[0]), 2), "a": round(float(lab[1]), 2), "b": round(float(lab[2]), 2)}


def build_measurement_from_rgb(
    r: int,
    g: int,
    b: int,
    *,
    car_model: str = "Trend-Forecast",
    color_code: str = "FCST",
    measurement_id: str | None = None,
) -> tuple[Measurement, dict[str, int], dict[str, float]]:
    """将单点 RGB 转为与识图一致的简化光谱 + 纹理，供 smart_generate 等算法使用。"""
    r = max(0, min(255, int(r)))
    g = max(0, min(255, int(g)))
    b = max(0, min(255, int(b)))
    glitter = _clamp01(max(abs(r - g), abs(g - b), abs(r - b)) / 255.0 * 0.15)
    sparkle = _clamp01(abs(r - b) / 255.0)
    grain = _clamp01(abs(r - g) / 255.0)
    points = [
        SpectrumPoint(wavelength=400, value=_clamp01(b / 255.0)),
        SpectrumPoint(wavelength=500, value=_clamp01(g / 255.0)),
        SpectrumPoint(wavelength=600, value=_clamp01(r / 255.0)),
    ]
    mid = measurement_id or f"fcst-{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}"
    measurement = Measurement(
        id=mid,
        car_model=car_model,
        color_code=color_code,
        angles={"15": points, "45": points, "110": points},
        texture={"flake_intensity": glitter, "sparkle": sparkle, "grain": grain},
    )
    avg_rgb = {"r": r, "g": g, "b": b}
    avg_lab = _rgb_int_to_lab_dict(r, g, b)
    return measurement, avg_rgb, avg_lab


async def extract_measurement_from_image(
    image_file: UploadFile,
    car_model: str = "Unknown-Car",
    color_code: str = "AUTO",
    roi_left: float = 0.0,
    roi_top: float = 0.0,
    roi_width: float = 1.0,
    roi_height: float = 1.0,
) -> VisionExtractResult:
    raw = await image_file.read()
    image = Image.open(BytesIO(raw)).convert("RGB")
    w, h = image.size
    left_n, top_n, rw_n, rh_n = _normalize_roi(roi_left, roi_top, roi_width, roi_height)
    left = int(left_n * w)
    top = int(top_n * h)
    right = min(w, left + max(1, int(rw_n * w)))
    bottom = min(h, top + max(1, int(rh_n * h)))
    crop = image.crop((left, top, right, bottom))
    pixels = list(crop.getdata())
    total = max(1, len(pixels))

    r_avg = int(sum(p[0] for p in pixels) / total)
    g_avg = int(sum(p[1] for p in pixels) / total)
    b_avg = int(sum(p[2] for p in pixels) / total)

    brightness = (r_avg + g_avg + b_avg) / (255 * 3)
    glitter = _clamp01(pstdev([(p[0] + p[1] + p[2]) / 3 for p in pixels]) / 100)
    sparkle = _clamp01(abs(r_avg - b_avg) / 255)
    grain = _clamp01(abs(r_avg - g_avg) / 255)

    points = [
        SpectrumPoint(wavelength=400, value=_clamp01(b_avg / 255)),
        SpectrumPoint(wavelength=500, value=_clamp01(g_avg / 255)),
        SpectrumPoint(wavelength=600, value=_clamp01(r_avg / 255)),
    ]
    measurement_id = f"img-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
    measurement = Measurement(
        id=measurement_id,
        car_model=car_model,
        color_code=color_code,
        angles={"15": points, "45": points, "110": points},
        texture={"flake_intensity": glitter, "sparkle": sparkle, "grain": grain},
    )
    roi_dict = {"left": left_n, "top": top_n, "width": rw_n, "height": rh_n}
    avg_lab = _rgb_int_to_lab_dict(r_avg, g_avg, b_avg)
    suggestion = "Image features extracted. You can run match/generate directly."
    return VisionExtractResult(
        measurement=measurement,
        avg_rgb={"r": r_avg, "g": g_avg, "b": b_avg},
        avg_lab=avg_lab,
        roi=roi_dict,
        suggestion=suggestion,
    )
