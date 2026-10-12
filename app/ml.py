from __future__ import annotations

import json
import os
import pickle
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.metrics import mean_absolute_error, r2_score

from .db import FeedbackRow, FormulaRow, MeasurementRow, SessionLocal


def _safe_float(v: Any) -> float:
    try:
        return float(v)
    except Exception:
        return 0.0


def _extract_feature(pigments: dict, measurement: dict) -> list[float]:
    p = pigments or {}
    a = (measurement or {}).get("angles", {})
    t = (measurement or {}).get("texture", {})
    vals_45 = a.get("45", [])
    band = {int(x.get("wavelength", 0)): _safe_float(x.get("value", 0.0)) for x in vals_45 if isinstance(x, dict)}
    return [
        _safe_float(p.get("base_white", 0.0)),
        _safe_float(p.get("base_black", 0.0)),
        _safe_float(p.get("base_red", 0.0)),
        _safe_float(p.get("base_green", 0.0)),
        _safe_float(p.get("base_blue", 0.0)),
        _safe_float(p.get("al_silver", 0.0)),
        _safe_float(p.get("pearl", 0.0)),
        _safe_float(band.get(400, 0.0)),
        _safe_float(band.get(500, 0.0)),
        _safe_float(band.get(600, 0.0)),
        _safe_float(t.get("flake_intensity", 0.0)),
        _safe_float(t.get("sparkle", 0.0)),
        _safe_float(t.get("grain", 0.0)),
    ]


def _pseudo_performance(pigments: dict) -> dict:
    white = _safe_float(pigments.get("base_white", 0.0))
    black = _safe_float(pigments.get("base_black", 0.0))
    red = _safe_float(pigments.get("base_red", 0.0))
    green = _safe_float(pigments.get("base_green", 0.0))
    blue = _safe_float(pigments.get("base_blue", 0.0))
    silver = _safe_float(pigments.get("al_silver", 0.0))
    pearl = _safe_float(pigments.get("pearl", 0.0))
    chromatic = red + green + blue
    adhesion = 6.5 + 2.2 * min(1.0, white + chromatic) + 0.6 * pearl
    gloss = 65.0 + 25.0 * min(1.0, pearl + silver + 0.5 * white)
    impact = 35.0 + 25.0 * min(1.0, chromatic + 0.5 * white) - 6.0 * black
    voc = 180.0 - 60.0 * min(1.0, white + chromatic) + 20.0 * silver
    return {"adhesion": adhesion, "gloss": gloss, "impact": impact, "voc": voc}


@dataclass
class ModelArtifacts:
    perf_model: Any
    rank_model: Any
    metadata: dict


class MLRuntime:
    def __init__(self, model_dir: str = "models") -> None:
        self.model_dir = Path(model_dir)
        self.model_dir.mkdir(parents=True, exist_ok=True)
        self.perf_path = self.model_dir / "perf_model.pkl"
        self.rank_path = self.model_dir / "rank_model.pkl"
        self.meta_path = self.model_dir / "metadata.json"
        self.perf_model: Any = None
        self.rank_model: Any = None
        self.metadata: dict = {}
        self.load()

    def has_model(self) -> bool:
        return self.perf_model is not None and self.rank_model is not None

    def load(self) -> None:
        if not (self.perf_path.exists() and self.rank_path.exists()):
            return
        try:
            with open(self.perf_path, "rb") as f:
                self.perf_model = pickle.load(f)
            with open(self.rank_path, "rb") as f:
                self.rank_model = pickle.load(f)
            if self.meta_path.exists():
                self.metadata = json.loads(self.meta_path.read_text(encoding="utf-8"))
        except Exception as exc:
            # sklearn 版本与旧 pickle 不兼容时（如 _loss）不阻断服务启动
            self.perf_model = None
            self.rank_model = None
            self.metadata = {
                "load_error": str(exc),
                "hint": "retrain via POST /expert/train or pin scikit-learn to the training version",
            }

    def train(self, min_samples: int = 20) -> dict:
        x_rows: list[list[float]] = []
        y_perf: list[list[float]] = []
        y_rank: list[float] = []

        with SessionLocal() as session:
            formulas = session.query(FormulaRow).all()
            measurements = {m.id: m for m in session.query(MeasurementRow).all()}
            feedbacks = session.query(FeedbackRow).all()
            feedback_by_formula: dict[str, list[FeedbackRow]] = {}
            for fb in feedbacks:
                feedback_by_formula.setdefault(fb.formula_id, []).append(fb)

            for f in formulas:
                m = measurements.get(f.linked_measurement_id)
                if m is None:
                    continue
                feat = _extract_feature(f.pigments, {"angles": m.angles, "texture": m.texture})
                base_perf = _pseudo_performance(f.pigments)
                fb_list = feedback_by_formula.get(f.id, [])
                if fb_list:
                    avg = {"adhesion": 0.0, "gloss": 0.0, "impact": 0.0, "voc": 0.0}
                    for fb in fb_list:
                        mp = fb.measured_performance or {}
                        avg["adhesion"] += _safe_float(mp.get("adhesion", base_perf["adhesion"]))
                        avg["gloss"] += _safe_float(mp.get("gloss", base_perf["gloss"]))
                        avg["impact"] += _safe_float(mp.get("impact", base_perf["impact"]))
                        avg["voc"] += _safe_float(mp.get("voc", base_perf["voc"]))
                    n = len(fb_list)
                    perf = [avg["adhesion"] / n, avg["gloss"] / n, avg["impact"] / n, avg["voc"] / n]
                    rank_target = sum(fb.accepted for fb in fb_list) / n
                else:
                    perf = [base_perf["adhesion"], base_perf["gloss"], base_perf["impact"], base_perf["voc"]]
                    rank_target = 0.5
                x_rows.append(feat)
                y_perf.append(perf)
                y_rank.append(rank_target)

        if len(x_rows) < min_samples:
            raise ValueError(f"insufficient samples: {len(x_rows)} < {min_samples}")

        x = np.asarray(x_rows, dtype=np.float32)
        y_perf_arr = np.asarray(y_perf, dtype=np.float32)
        y_rank_arr = np.asarray(y_rank, dtype=np.float32)

        perf = RandomForestRegressor(n_estimators=200, random_state=42)
        rank = GradientBoostingRegressor(random_state=42)
        perf.fit(x, y_perf_arr)
        rank.fit(x, y_rank_arr)

        perf_pred = perf.predict(x)
        rank_pred = rank.predict(x)
        mae = float(mean_absolute_error(y_perf_arr, perf_pred))
        if len(x_rows) < 2:
            r2 = 0.0
        else:
            r2 = float(r2_score(y_perf_arr, perf_pred))
            if not np.isfinite(r2):
                r2 = 0.0
        rank_mae = float(mean_absolute_error(y_rank_arr, rank_pred))

        with open(self.perf_path, "wb") as f:
            pickle.dump(perf, f)
        with open(self.rank_path, "wb") as f:
            pickle.dump(rank, f)

        meta = {
            "trained_at": datetime.utcnow().isoformat(),
            "sample_count": int(len(x_rows)),
            "perf_mae": round(mae, 6),
            "perf_r2": round(r2, 6),
            "rank_mae": round(rank_mae, 6),
            "model_version": datetime.utcnow().strftime("v%Y%m%d%H%M%S"),
        }
        self.meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        self.load()
        return meta

    def predict_performance(self, pigments: dict, measurement: dict) -> dict:
        if self.perf_model is None:
            raise RuntimeError("model not loaded")
        x = np.asarray([_extract_feature(pigments, measurement)], dtype=np.float32)
        pred = self.perf_model.predict(x)[0]
        return {
            "adhesion": round(float(pred[0]), 3),
            "gloss": round(float(pred[1]), 3),
            "impact": round(float(pred[2]), 3),
            "voc": round(float(pred[3]), 3),
        }

    def predict_rank(self, pigments: dict, measurement: dict) -> float:
        if self.rank_model is None:
            raise RuntimeError("model not loaded")
        x = np.asarray([_extract_feature(pigments, measurement)], dtype=np.float32)
        val = float(self.rank_model.predict(x)[0])
        return max(0.0, min(1.0, val))

    def status(self) -> dict:
        exists = self.has_model()
        return {
            "ready": exists,
            "model_dir": str(self.model_dir.resolve()),
            "metadata": self.metadata if exists else {},
        }

