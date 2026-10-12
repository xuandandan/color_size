"""
Pantone / fashion trend color preference module.

Loads metadata.csv (+ optional images folder) from TREND_DATASET_ROOT
(default: ./data/pantone_fashion_trends). Uses Lab space + scikit-learn
(StandardScaler, KMeans, NearestNeighbors) for trend clustering and similarity.
"""

from __future__ import annotations

import csv
import json
import math
import os
import pickle
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.cluster import KMeans
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import StandardScaler
from skimage.color import lab2rgb, rgb2lab

from .models import (
    Measurement,
    TrendForecastColor,
    TrendForecastResult,
    TrendMatchResult,
    TrendNeighbor,
    TrendTrainResult,
)


def _default_data_root() -> Path:
    env = os.getenv("TREND_DATASET_ROOT", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return (Path(__file__).resolve().parent.parent / "data" / "pantone_fashion_trends").resolve()


def _rgb_to_lab(r: float, g: float, b: float) -> tuple[float, float, float]:
    arr = np.array([[[r / 255.0, g / 255.0, b / 255.0]]], dtype=np.float64)
    lab = rgb2lab(arr)[0, 0]
    return float(lab[0]), float(lab[1]), float(lab[2])


def _lab_to_rgb_hex(L: float, a: float, b: float) -> tuple[int, int, int, str]:
    arr = np.array([[[L, a, b]]], dtype=np.float64)
    rgb = lab2rgb(arr)[0, 0]
    r = int(round(float(np.clip(rgb[0], 0.0, 1.0)) * 255))
    g = int(round(float(np.clip(rgb[1], 0.0, 1.0)) * 255))
    b = int(round(float(np.clip(rgb[2], 0.0, 1.0)) * 255))
    hx = f"#{r:02x}{g:02x}{b:02x}"
    return r, g, b, hx


def _clamp_lab_vec(lab: np.ndarray) -> np.ndarray:
    out = lab.astype(np.float64).copy()
    out[0] = float(np.clip(out[0], 2.0, 98.0))
    out[1] = float(np.clip(out[1], -90.0, 90.0))
    out[2] = float(np.clip(out[2], -90.0, 90.0))
    return out


def measurement_to_lab(m: Measurement) -> tuple[float, float, float]:
    pts = m.angles.get("45", [])
    ch = {int(p.wavelength): float(p.value) for p in pts}
    r = int(min(255, max(0, round(ch.get(600, 0.0) * 255))))
    g = int(min(255, max(0, round(ch.get(500, 0.0) * 255))))
    b = int(min(255, max(0, round(ch.get(400, 0.0) * 255))))
    return _rgb_to_lab(float(r), float(g), float(b))


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        if v is None or str(v).strip() == "":
            return default
        return int(float(v))
    except (TypeError, ValueError):
        return default


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or str(v).strip() == "":
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def load_trend_rows(csv_path: Path) -> tuple[list[dict[str, Any]], np.ndarray]:
    if not csv_path.is_file():
        raise FileNotFoundError(f"metadata.csv not found: {csv_path}")
    rows: list[dict[str, Any]] = []
    labs: list[list[float]] = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            r = _safe_int(row.get("r"), -1)
            g = _safe_int(row.get("g"), -1)
            b = _safe_int(row.get("b"), -1)
            if r < 0 or g < 0 or b < 0:
                continue
            ll = _safe_float(row.get("lab_l"), 0.0)
            la = _safe_float(row.get("lab_a"), 0.0)
            lb = _safe_float(row.get("lab_b"), 0.0)
            if str(row.get("lab_l", "")).strip() == "":
                ll, la, lb = _rgb_to_lab(float(r), float(g), float(b))
            meta = {
                "image_rel_path": str(row.get("image_rel_path", "") or ""),
                "trend_year": _safe_int(row.get("trend_year"), 0),
                "tcx_code": str(row.get("tcx_code", "") or ""),
                "color_name": str(row.get("color_name", "") or ""),
                "hex": str(row.get("hex", "") or ""),
                "r": r,
                "g": g,
                "b": b,
                "lab_l": ll,
                "lab_a": la,
                "lab_b": lb,
                "book_group": str(row.get("book_group", "") or ""),
                "book_title": str(row.get("book_title", "") or ""),
            }
            rows.append(meta)
            labs.append([ll, la, lb])
    if not rows:
        raise ValueError("no valid color rows in CSV (check r,g,b columns)")
    return rows, np.asarray(labs, dtype=np.float64)


@dataclass
class TrendArtifacts:
    scaler: StandardScaler | None = None
    kmeans: KMeans | None = None
    nn: NearestNeighbors | None = None
    labs: np.ndarray | None = None
    meta_rows: list[dict[str, Any]] = field(default_factory=list)
    train_meta: dict[str, Any] = field(default_factory=dict)


class TrendPreferenceRuntime:
    def __init__(self, model_dir: str = "models") -> None:
        self.model_dir = Path(model_dir)
        self.model_dir.mkdir(parents=True, exist_ok=True)
        self.bundle_path = self.model_dir / "trend_preference_bundle.pkl"
        self.meta_path = self.model_dir / "trend_preference_meta.json"
        self.data_root = _default_data_root()
        self.art = TrendArtifacts()
        self._load_bundle()

    def _csv_path(self) -> Path:
        return self.data_root / "metadata.csv"

    def _load_bundle(self) -> None:
        if not self.bundle_path.exists():
            return
        try:
            with open(self.bundle_path, "rb") as f:
                data = pickle.load(f)
            self.art.scaler = data.get("scaler")
            self.art.kmeans = data.get("kmeans")
            self.art.nn = data.get("nn")
            self.art.labs = data.get("labs")
            self.art.meta_rows = data.get("meta_rows", [])
            if self.meta_path.exists():
                self.art.train_meta = json.loads(self.meta_path.read_text(encoding="utf-8"))
        except Exception as exc:
            # 旧 pickle 与当前 sklearn 不兼容时跳过，服务仍可启动
            self.art = TrendArtifacts()
            self.art.train_meta = {"load_error": str(exc)}

    def dataset_status(self) -> dict[str, Any]:
        csv_p = self._csv_path()
        n = 0
        years: set[int] = set()
        err = ""
        if csv_p.is_file():
            try:
                rows, _ = load_trend_rows(csv_p)
                n = len(rows)
                for r in rows:
                    y = int(r.get("trend_year") or 0)
                    if y:
                        years.add(y)
            except Exception as e:
                err = str(e)
        return {
            "data_root": str(self.data_root),
            "metadata_csv": str(csv_p),
            "csv_exists": csv_p.is_file(),
            "row_count": n,
            "trend_years": sorted(years),
            "model_ready": self.art.nn is not None and self.art.scaler is not None,
            "error": err,
        }

    def train(self, min_rows: int = 16, n_clusters: int | None = None) -> TrendTrainResult:
        csv_p = self._csv_path()
        rows, labs = load_trend_rows(csv_p)
        n = len(rows)
        if n < min_rows:
            raise ValueError(f"insufficient trend colors: {n} < {min_rows}")

        scaler = StandardScaler()
        x_scaled = scaler.fit_transform(labs)

        k = n_clusters if n_clusters is not None else min(16, max(4, n // 6))
        k = max(2, min(int(k), n - 1))
        kmeans = KMeans(n_clusters=k, random_state=42, n_init=10)
        kmeans.fit(x_scaled)

        nn_k = min(15, n)
        nn = NearestNeighbors(n_neighbors=nn_k, metric="euclidean")
        nn.fit(x_scaled)

        bundle = {
            "scaler": scaler,
            "kmeans": kmeans,
            "nn": nn,
            "labs": labs,
            "meta_rows": rows,
        }
        with open(self.bundle_path, "wb") as f:
            pickle.dump(bundle, f)

        meta = {
            "trained_at": datetime.utcnow().isoformat(),
            "sample_count": n,
            "n_clusters": k,
            "data_root": str(self.data_root),
            "model_version": datetime.utcnow().strftime("trend_v%Y%m%d%H%M%S"),
        }
        self.meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        self._load_bundle()
        return TrendTrainResult(
            trained_at=meta["trained_at"],
            sample_count=n,
            n_clusters=k,
            model_version=meta["model_version"],
        )

    def match(
        self,
        *,
        r: int | None,
        g: int | None,
        b: int | None,
        measurement: Measurement | None,
        top_k: int,
    ) -> TrendMatchResult:
        if self.art.scaler is None or self.art.nn is None or self.art.labs is None:
            raise RuntimeError("trend model not trained; POST /trends/train first")

        if measurement is not None:
            L, a, bb = measurement_to_lab(measurement)
        elif r is not None and g is not None and b is not None:
            L, a, bb = _rgb_to_lab(float(r), float(g), float(b))
        else:
            raise ValueError("provide rgb or measurement")

        q_lab = np.array([[L, a, bb]], dtype=np.float64)
        q_scaled = self.art.scaler.transform(q_lab)

        cluster_id = 0
        if self.art.kmeans is not None:
            cluster_id = int(self.art.kmeans.predict(q_scaled)[0])

        k = min(top_k, len(self.art.meta_rows))
        dists_scaled, idx = self.art.nn.kneighbors(q_scaled, n_neighbors=k)

        neighbors: list[TrendNeighbor] = []
        de_list: list[float] = []
        for j, i in enumerate(idx[0]):
            i = int(i)
            row = self.art.meta_rows[i]
            nl = self.art.labs[i]
            d_lab = float(np.linalg.norm(q_lab[0] - nl))
            de_list.append(d_lab)
            neighbors.append(
                TrendNeighbor(
                    tcx_code=row["tcx_code"],
                    color_name=row["color_name"],
                    hex=row["hex"],
                    r=int(row["r"]),
                    g=int(row["g"]),
                    b=int(row["b"]),
                    lab_l=float(nl[0]),
                    lab_a=float(nl[1]),
                    lab_b=float(nl[2]),
                    trend_year=int(row.get("trend_year") or 0),
                    book_group=row.get("book_group", "") or "",
                    distance=round(float(dists_scaled[0][j]), 6),
                    image_rel_path=row.get("image_rel_path", "") or "",
                )
            )

        mean_de = float(np.mean(de_list)) if de_list else 50.0
        preference = float(min(100.0, max(0.0, 100.0 * np.exp(-mean_de / 18.0))))

        return TrendMatchResult(
            query_lab={"L": round(L, 4), "a": round(a, 4), "b": round(bb, 4)},
            preference_score=round(preference, 2),
            trend_cluster=cluster_id,
            neighbors=neighbors,
            mean_delta_e_lab=round(mean_de, 4),
        )

    def forecast(
        self,
        *,
        r: int | None,
        g: int | None,
        b: int | None,
        measurement: Measurement | None,
        horizon_years: int,
        suggestions_per_horizon: int,
    ) -> TrendForecastResult:
        """结合提取色与趋势簇（及 trend_year 若存在）做未来若干年的 Lab 外推，供主动开发参考。"""
        if self.art.scaler is None or self.art.kmeans is None or self.art.labs is None:
            raise RuntimeError("trend model not trained; POST /trends/train first")

        if measurement is not None:
            L, a, bb = measurement_to_lab(measurement)
        elif r is not None and g is not None and b is not None:
            L, a, bb = _rgb_to_lab(float(r), float(g), float(b))
        else:
            raise ValueError("provide rgb or measurement")

        user = np.array([L, a, bb], dtype=np.float64)
        q_scaled = self.art.scaler.transform(user.reshape(1, -1))
        cluster_id = int(self.art.kmeans.predict(q_scaled)[0])

        labs = self.art.labs
        rows = self.art.meta_rows
        all_labels = self.art.kmeans.predict(self.art.scaler.transform(labs))
        cluster_mask = all_labels == cluster_id
        cluster_idx = np.where(cluster_mask)[0]

        def max_year_for_indices(idxs: np.ndarray) -> int:
            ys = [int(rows[int(i)].get("trend_year") or 0) for i in idxs.flatten()]
            ys = [y for y in ys if y > 0]
            return int(max(ys)) if ys else 0

        anchor_cluster = max_year_for_indices(cluster_idx)
        anchor_global = max_year_for_indices(np.arange(len(rows), dtype=int))
        anchor = max(anchor_cluster, anchor_global)
        if anchor == 0:
            anchor = datetime.utcnow().year

        mean_by_year_cluster: dict[int, list[np.ndarray]] = {}
        for i in cluster_idx:
            i = int(i)
            y = int(rows[i].get("trend_year") or 0)
            if y <= 0:
                continue
            mean_by_year_cluster.setdefault(y, []).append(labs[i].copy())

        year_means_c: dict[int, np.ndarray] = {}
        for y, lst in mean_by_year_cluster.items():
            year_means_c[y] = np.mean(np.stack(lst, axis=0), axis=0)

        velocity = np.zeros(3, dtype=np.float64)
        temporal_signal = "palette_evolution_heuristic"

        years_sorted = sorted(year_means_c.keys())
        if len(years_sorted) >= 2:
            Y = np.array(years_sorted, dtype=np.float64)
            M = np.stack([year_means_c[y] for y in years_sorted], axis=0)
            for dim in range(3):
                coef = np.polyfit(Y, M[:, dim], 1)
                velocity[dim] = float(coef[0])
            temporal_signal = "cluster_temporal_regression"
        else:
            mean_by_year_global: dict[int, list[np.ndarray]] = {}
            for i in range(len(rows)):
                y = int(rows[i].get("trend_year") or 0)
                if y <= 0:
                    continue
                mean_by_year_global.setdefault(y, []).append(labs[i].copy())
            year_means_g: dict[int, np.ndarray] = {}
            for y, lst in mean_by_year_global.items():
                year_means_g[y] = np.mean(np.stack(lst, axis=0), axis=0)
            gy = sorted(year_means_g.keys())
            if len(gy) >= 2:
                Y = np.array(gy, dtype=np.float64)
                M = np.stack([year_means_g[y] for y in gy], axis=0)
                for dim in range(3):
                    coef = np.polyfit(Y, M[:, dim], 1)
                    velocity[dim] = float(coef[0])
                temporal_signal = "global_temporal"
            else:
                if len(cluster_idx) > 0:
                    centroid = np.mean(labs[cluster_idx], axis=0)
                else:
                    centroid = np.mean(labs, axis=0)
                delta = centroid - user
                nrm = float(np.linalg.norm(delta)) + 1e-6
                velocity = (delta / nrm) * 1.8

        if len(cluster_idx) > 0:
            centroid_c = np.mean(labs[cluster_idx], axis=0)
        else:
            centroid_c = np.mean(labs, axis=0)

        methodology_note = (
            "本结果为启发式外推：优先使用「与您颜色同一趋势簇」内按 metadata 中 trend_year 汇总的 Lab 年均值，"
            "对 L/a/b 分别做一元线性回归得到「每年沿趋势库的移动方向」；再与您提取的 Lab、簇心加权融合。"
            "同一年度的多条候选：主要在同一亮度附近沿 a*b* 平面扇形散开（并带轻微 L 扰动），便于看色相微差；"
            "不同年度之间会叠加趋势速度 × 年数，故 Y+1 与 Y+2 整体会拉开。"
            "非市场调研结论；请用真实流行色复盘持续校准。"
        )

        forecasts: list[TrendForecastColor] = []
        w_user = 0.42
        for h in range(1, horizon_years + 1):
            trend_point = _clamp_lab_vec(user + velocity * float(h))
            blended = w_user * user + (1.0 - w_user) * (0.55 * trend_point + 0.45 * centroid_c)
            blended = _clamp_lab_vec(blended)
            cal_year = int(anchor + h)
            for k in range(suggestions_per_horizon):
                theta = (2.0 * math.pi * k) / max(suggestions_per_horizon, 1)
                # 略加大 ab 扇形，并在 L* 上给每条候选微小差异，避免「同年三条亮度完全一样」
                ab_scale = 3.0 + 0.5 * k + 0.35 * h
                l_jitter = (0.55 + 0.15 * k + 0.08 * h) * math.sin(theta * 2.0 + 0.3 * k)
                pert = np.array(
                    [l_jitter, ab_scale * math.cos(theta), ab_scale * math.sin(theta)],
                    dtype=np.float64,
                )
                lab_k = _clamp_lab_vec(blended + pert)
                rr, gg, bb2, hx = _lab_to_rgb_hex(float(lab_k[0]), float(lab_k[1]), float(lab_k[2]))
                sig_zh = {
                    "cluster_temporal_regression": "簇内按年回归",
                    "global_temporal": "全库按年回归",
                    "palette_evolution_heuristic": "簇向演变",
                }.get(temporal_signal, temporal_signal)
                rationale = (
                    f"簇 {cluster_id}，锚点年 {anchor}，Y+{h} 候选 {k + 1}/{suggestions_per_horizon}；"
                    f"趋势信号：{sig_zh}（{temporal_signal}）"
                )
                forecasts.append(
                    TrendForecastColor(
                        horizon_offset=h,
                        forecast_calendar_year=cal_year,
                        label=f"Y+{h} 展望 #{k + 1}",
                        hex=hx,
                        r=rr,
                        g=gg,
                        b=bb2,
                        lab_l=round(float(lab_k[0]), 4),
                        lab_a=round(float(lab_k[1]), 4),
                        lab_b=round(float(lab_k[2]), 4),
                        rationale=rationale,
                    )
                )

        return TrendForecastResult(
            query_lab={"L": round(L, 4), "a": round(a, 4), "b": round(bb, 4)},
            trend_cluster=cluster_id,
            anchor_trend_year=int(anchor),
            temporal_signal=temporal_signal,
            forecasts=forecasts,
            methodology_note=methodology_note,
        )
