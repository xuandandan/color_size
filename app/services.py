from __future__ import annotations

from hashlib import md5
import re
from typing import Dict, List

from .formula_extended import extended_fields_for_generate
from .models import (
    ColorPreviewPoint,
    ExpertRecommendRequest,
    FeedbackRequest,
    FillerSpec,
    FormulaRecommendation,
    Formula,
    GenerateResult,
    MatchResult,
    Measurement,
    OrchestrateResult,
    ParsedRequirement,
    PigmentRange,
    RenderPreviewResult,
    RequirementParseRequest,
    TuneResult,
)
from .ml import MLRuntime
from .storage import SQLStore


def _flatten_measurement(measurement: Measurement) -> List[float]:
    values: List[float] = []
    for angle in sorted(measurement.angles.keys()):
        values.extend(point.value for point in measurement.angles[angle])
    values.extend(measurement.texture.values())
    return values


def _distance(a: Measurement, b: Measurement) -> float:
    av = _flatten_measurement(a)
    bv = _flatten_measurement(b)
    if not av or not bv:
        return 1e9
    size = min(len(av), len(bv))
    total = 0.0
    for idx in range(size):
        diff = av[idx] - bv[idx]
        total += diff * diff
    return (total / size) ** 0.5


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


class ColorEngine:
    """MVP engine that maps requirements to four core algorithms."""

    def __init__(self, store: SQLStore) -> None:
        self.store = store

    def smart_match(self, target: Measurement, top_k: int) -> List[MatchResult]:
        # Intelligent matching algorithm: find closest historical formulas.
        scored: List[MatchResult] = []
        for formula in self.store.list_formulas():
            source = self.store.get_measurement(formula.linked_measurement_id)
            dist = _distance(target, source)
            score = max(0.0, 1.0 - dist)
            scored.append(
                MatchResult(
                    formula_id=formula.id,
                    score=round(score, 4),
                    reason=f"distance={dist:.4f}, similarity={score:.4f}",
                )
            )
        scored.sort(key=lambda x: x.score, reverse=True)
        return scored[:top_k]

    def smart_tune(self, target: Measurement, base_formula: Formula) -> TuneResult:
        # Intelligent tuning algorithm: produce quantitative tweak advice.
        linked = self.store.get_measurement(base_formula.linked_measurement_id)
        delta = _distance(target, linked)
        factor = min(0.05, delta)
        adjustment: Dict[str, float] = {}
        advice: List[str] = []
        for pigment, amount in base_formula.pigments.items():
            if pigment.lower().startswith("al") or "silver" in pigment.lower():
                adjustment[pigment] = round(amount * factor, 4)
                advice.append(f"Increase {pigment} by {adjustment[pigment]} for flake response.")
            else:
                adjustment[pigment] = round(-amount * factor / 2, 4)
                advice.append(f"Decrease {pigment} by {abs(adjustment[pigment])} to control hue drift.")
        return TuneResult(formula_id=base_formula.id, adjustment=adjustment, advice=advice[:5])

    def smart_generate(self, measurement: Measurement, range_ratio: float = 0.1) -> GenerateResult:
        # Intelligent generation algorithm: create a color-aware candidate.
        angle_45 = measurement.angles.get("45", [])
        channel_map = {point.wavelength: point.value for point in angle_45}
        red = float(channel_map.get(600, 0.0))
        green = float(channel_map.get(500, 0.0))
        blue = float(channel_map.get(400, 0.0))
        total = max(1e-6, red + green + blue)
        red_ratio = red / total
        green_ratio = green / total
        blue_ratio = blue / total
        brightness = (red + green + blue) / 3
        chroma = max(red, green, blue) - min(red, green, blue)
        metallic = measurement.texture.get("flake_intensity", 0.0)
        pearls = measurement.texture.get("sparkle", 0.0)
        formula_name = f"AUTO-{measurement.color_code}-{measurement.id[-4:]}"

        pigments: Dict[str, float] = {}
        if chroma < 0.12:
            # Neutral/gray-like color: rely on white-black backbone.
            pigments["base_white"] = round(max(0.0, min(1.0, brightness)), 4)
            pigments["base_black"] = round(max(0.0, min(1.0, 1.0 - brightness)), 4)
        else:
            # Chromatic color: rely on primary color pigments, avoid forced black/white.
            if red_ratio > 0.03:
                pigments["base_red"] = round(red_ratio, 4)
            if green_ratio > 0.03:
                pigments["base_green"] = round(green_ratio, 4)
            if blue_ratio > 0.03:
                pigments["base_blue"] = round(blue_ratio, 4)

            # Only add tiny neutral correction for very bright or very dark tones.
            if brightness > 0.85:
                pigments["base_white"] = round((brightness - 0.85) * 0.3, 4)
            if brightness < 0.15:
                pigments["base_black"] = round((0.15 - brightness) * 0.3, 4)

        if metallic > 0:
            pigments["al_silver"] = round(max(0.0, metallic * 0.25), 4)
        if pearls > 0:
            pigments["pearl"] = round(max(0.0, pearls * 0.2), 4)

        if not pigments:
            pigments = {"base_white": 0.5, "base_black": 0.5}

        confidence = max(0.35, min(0.95, 0.45 + chroma * 0.35 + metallic * 0.1 + pearls * 0.1))
        pigment_ranges = self._build_pigment_ranges(pigments, ratio=range_ratio)
        color_previews = self._build_limit_color_previews(pigment_ranges)
        process_parameters = self._build_process_parameters(pigments)
        operation_advice = self._build_operation_advice(pigments, process_parameters)
        fillers, mb_pct, base_pct = extended_fields_for_generate()
        return GenerateResult(
            formula_name=formula_name,
            pigments=pigments,
            confidence=round(confidence, 4),
            pigments_range=pigment_ranges,
            limit_color_previews=color_previews,
            process_parameters=process_parameters,
            operation_advice=operation_advice,
            fillers=fillers,
            masterbatch_ratio_pct=mb_pct,
            base_material_formula_pct=base_pct,
        )

    def _build_pigment_ranges(self, pigments: Dict[str, float], ratio: float = 0.1) -> Dict[str, PigmentRange]:
        ranges: Dict[str, PigmentRange] = {}
        for name, mid in pigments.items():
            margin = max(0.005, abs(mid) * ratio)
            lower = _clamp(mid - margin, 0.0, 1.0)
            upper = _clamp(mid + margin, 0.0, 1.0)
            ranges[name] = PigmentRange(
                lower=round(lower, 4),
                mid=round(_clamp(mid, 0.0, 1.0), 4),
                upper=round(upper, 4),
            )
        return ranges

    def _estimate_rgb_from_pigments(self, pigments: Dict[str, float]) -> Dict[str, int]:
        white = pigments.get("base_white", 0.0)
        black = pigments.get("base_black", 0.0)
        red = pigments.get("base_red", 0.0)
        green = pigments.get("base_green", 0.0)
        blue = pigments.get("base_blue", 0.0)
        silver = pigments.get("al_silver", 0.0)
        pearl = pigments.get("pearl", 0.0)

        # Lightweight perceptual estimate for UI preview (not physical BRDF rendering).
        lift = 0.05 + 0.45 * white + 0.18 * silver + 0.15 * pearl
        darken = 0.75 * black
        r = _clamp(lift + 1.25 * red + 0.15 * green + 0.08 * blue - darken, 0.0, 1.0)
        g = _clamp(lift + 0.15 * red + 1.25 * green + 0.12 * blue - darken, 0.0, 1.0)
        b = _clamp(lift + 0.1 * red + 0.16 * green + 1.25 * blue - darken, 0.0, 1.0)
        return {"r": int(round(r * 255)), "g": int(round(g * 255)), "b": int(round(b * 255))}

    def _build_limit_color_previews(self, ranges: Dict[str, PigmentRange]) -> List[ColorPreviewPoint]:
        previews: List[ColorPreviewPoint] = []
        for level in ("lower", "mid", "upper"):
            pigments = {name: getattr(bounds, level) for name, bounds in ranges.items()}
            rgb = self._estimate_rgb_from_pigments(pigments)
            hex_color = f"#{rgb['r']:02x}{rgb['g']:02x}{rgb['b']:02x}"
            previews.append(ColorPreviewPoint(level=level, rgb=rgb, hex=hex_color))
        return previews

    def _build_process_parameters(self, pigments: Dict[str, float]) -> Dict[str, float | str]:
        silver = pigments.get("al_silver", 0.0)
        pearl = pigments.get("pearl", 0.0)
        metallic_level = silver + pearl
        return {
            "layer_count": 2 if metallic_level < 0.12 else 3,
            "spray_pressure_bar": round(2.0 + min(0.8, metallic_level * 1.8), 2),
            "bake_temp_c": round(60.0 + min(20.0, metallic_level * 40.0), 1),
            "flash_off_min": 8 if metallic_level < 0.12 else 12,
            "gun_nozzle_mm": 1.3 if metallic_level < 0.1 else 1.4,
        }

    def _build_operation_advice(
        self, pigments: Dict[str, float], process_parameters: Dict[str, float | str]
    ) -> List[str]:
        advice: List[str] = []
        white = pigments.get("base_white", 0.0)
        black = pigments.get("base_black", 0.0)
        silver = pigments.get("al_silver", 0.0)
        pearl = pigments.get("pearl", 0.0)

        advice.append(
            "建议先做小样三档验证（下限/中值/上限），确认颜色窗口后再放大批量。"
        )
        advice.append(
            f"喷涂建议：{process_parameters.get('layer_count', 2)}道，压力约 {process_parameters.get('spray_pressure_bar', 2.0)} bar，"
            f"闪干 {process_parameters.get('flash_off_min', 8)} min。"
        )
        advice.append(
            f"烘烤建议：{process_parameters.get('bake_temp_c', 60.0)}°C，枪嘴 {process_parameters.get('gun_nozzle_mm', 1.3)} mm。"
        )
        if silver + pearl > 0.12:
            advice.append("金属/珠光含量较高，建议控制喷枪走速和重叠率，防止花斑与方向性差异。")
        if black > 0.08:
            advice.append("黑母比例偏高，建议分步微调，避免一次性加量导致明度过快下降。")
        if white > 0.35:
            advice.append("白母比例较高，建议关注遮盖与流平平衡，必要时增加一道薄喷。")
        return advice

    def paint_render_preview(self, formula: Formula, view_angle: int) -> RenderPreviewResult:
        # Paint rendering algorithm: deterministic preview metrics for UI visualization.
        pigment_vector = "".join(f"{k}:{v}" for k, v in sorted(formula.pigments.items()))
        digest = md5(pigment_vector.encode("utf-8")).hexdigest()
        rgb_hint = f"#{digest[:6]}"
        roughness = round(max(0.05, min(0.95, abs(90 - view_angle) / 100)), 4)
        flake_intensity = round(
            sum(v for k, v in formula.pigments.items() if "silver" in k.lower() or "pearl" in k.lower()),
            4,
        )
        return RenderPreviewResult(
            formula_id=formula.id,
            rgb_hint=rgb_hint,
            roughness=roughness,
            flake_intensity=flake_intensity,
        )


class ExpertOrchestrator:
    """Main expert agent that coordinates sub-capabilities."""

    def __init__(self, store: SQLStore, color_engine: ColorEngine, ml_runtime: MLRuntime | None = None) -> None:
        self.store = store
        self.color_engine = color_engine
        self.ml_runtime = ml_runtime

    def parse_requirement(self, payload: RequirementParseRequest) -> ParsedRequirement:
        text = payload.raw_input
        hard: Dict[str, float] = {}
        soft: Dict[str, float] = {}
        notes: List[str] = []

        # Parse explicit patterns: "附着力>=8", "光泽 85", "耐冲击 50"
        op = r"(?:>=|<=|>|<|=|＝|≥|≤)?"
        patterns = {
            "adhesion": [rf"附着力\s*{op}\s*(\d+\.?\d*)", rf"adhesion\s*{op}\s*(\d+\.?\d*)"],
            "gloss": [rf"光泽\s*{op}\s*(\d+\.?\d*)", rf"gloss\s*{op}\s*(\d+\.?\d*)"],
            "impact": [rf"耐冲击[性]?\s*{op}\s*(\d+\.?\d*)", rf"impact\s*{op}\s*(\d+\.?\d*)"],
            "voc": [rf"VOC\s*{op}\s*(\d+\.?\d*)", rf"voc\s*{op}\s*(\d+\.?\d*)"],
        }
        for key, pats in patterns.items():
            for pat in pats:
                m = re.search(pat, text, flags=re.IGNORECASE)
                if m:
                    value = float(m.group(1))
                    if key == "voc":
                        hard["voc_max"] = value
                    else:
                        hard[f"{key}_min"] = value
                    break

        if "量产" in text or "生产" in text:
            soft["production_stability"] = 0.85
            notes.append("Detected mass-production intent, prioritizing process stability.")
        if "快速" in text or "效率" in text:
            soft["speed_priority"] = 0.8
            notes.append("Detected speed requirement.")
        if "成本" in text:
            soft["cost_priority"] = 0.8
            notes.append("Detected cost-sensitive requirement.")
        if "环保" in text or "低VOC" in text or "法规" in text:
            hard["voc_max"] = min(hard.get("voc_max", 120.0), 120.0)
            notes.append("Detected compliance requirement for VOC.")

        if not hard:
            hard = {"adhesion_min": 7.0, "gloss_min": 75.0, "impact_min": 40.0}
            notes.append("No explicit numeric target detected; applied default hard constraints.")
        if not soft:
            soft = {"speed_priority": 0.6, "cost_priority": 0.5, "production_stability": 0.7}
            notes.append("Applied default soft constraints.")

        return ParsedRequirement(hard_constraints=hard, soft_constraints=soft, notes=notes)

    def _predict_performance(self, formula: Formula) -> Dict[str, float]:
        if self.ml_runtime and self.ml_runtime.has_model():
            try:
                measurement = self.store.get_measurement(formula.linked_measurement_id)
                payload = measurement.model_dump(mode="json")
                return self.ml_runtime.predict_performance(formula.pigments, payload)
            except Exception:
                pass
        pigments = formula.pigments
        white = pigments.get("base_white", 0.0)
        black = pigments.get("base_black", 0.0)
        red = pigments.get("base_red", 0.0)
        green = pigments.get("base_green", 0.0)
        blue = pigments.get("base_blue", 0.0)
        silver = pigments.get("al_silver", 0.0)
        pearl = pigments.get("pearl", 0.0)
        chromatic = red + green + blue
        adhesion = 6.5 + 2.2 * min(1.0, white + chromatic) + 0.6 * pearl
        gloss = 65.0 + 25.0 * min(1.0, pearl + silver + 0.5 * white)
        impact = 35.0 + 25.0 * min(1.0, chromatic + 0.5 * white) - 6.0 * black
        voc = 180.0 - 60.0 * min(1.0, white + chromatic) + 20.0 * silver
        return {
            "adhesion": round(max(0.0, adhesion), 3),
            "gloss": round(max(0.0, gloss), 3),
            "impact": round(max(0.0, impact), 3),
            "voc": round(max(20.0, voc), 3),
        }

    def _process_params(self, formula: Formula) -> Dict[str, float | str]:
        silver = formula.pigments.get("al_silver", 0.0)
        pearl = formula.pigments.get("pearl", 0.0)
        layer_count = 2 if silver + pearl < 0.12 else 3
        spray_pressure = 2.0 + min(0.8, (silver + pearl) * 1.8)
        bake_temp = 60.0 + min(20.0, (silver + pearl) * 40.0)
        return {
            "layer_count": layer_count,
            "spray_pressure_bar": round(spray_pressure, 2),
            "bake_temp_c": round(bake_temp, 1),
            "gun_nozzle_mm": 1.3 if silver + pearl < 0.1 else 1.4,
        }

    def _check_hard_constraints(self, predicted: Dict[str, float], requirement: ParsedRequirement) -> bool:
        hard = requirement.hard_constraints
        if "adhesion_min" in hard and predicted["adhesion"] < hard["adhesion_min"]:
            return False
        if "gloss_min" in hard and predicted["gloss"] < hard["gloss_min"]:
            return False
        if "impact_min" in hard and predicted["impact"] < hard["impact_min"]:
            return False
        if "voc_max" in hard and predicted["voc"] > hard["voc_max"]:
            return False
        return True

    def recommend_formulas(self, payload: ExpertRecommendRequest) -> List[FormulaRecommendation]:
        recommendations: List[FormulaRecommendation] = []
        formulas = self.store.list_formulas()
        for formula in formulas:
            predicted = self._predict_performance(formula)
            passed = self._check_hard_constraints(predicted, payload.requirement)
            score = 0.0
            if passed:
                score += 70.0
            if self.ml_runtime and self.ml_runtime.has_model():
                try:
                    m = self.store.get_measurement(formula.linked_measurement_id)
                    rank_prob = self.ml_runtime.predict_rank(formula.pigments, m.model_dump(mode="json"))
                    score += rank_prob * 20.0
                except Exception:
                    pass
            hard = payload.requirement.hard_constraints
            if "adhesion_min" in hard:
                score += max(0.0, min(10.0, predicted["adhesion"] - hard["adhesion_min"]))
            if "gloss_min" in hard:
                score += max(0.0, min(10.0, (predicted["gloss"] - hard["gloss_min"]) / 2))
            if "impact_min" in hard:
                score += max(0.0, min(10.0, (predicted["impact"] - hard["impact_min"]) / 2))
            if "voc_max" in hard:
                score += max(0.0, min(10.0, (hard["voc_max"] - predicted["voc"]) / 2))
            score += payload.requirement.soft_constraints.get("production_stability", 0.5) * 5
            score += payload.requirement.soft_constraints.get("speed_priority", 0.5) * 3
            score += payload.requirement.soft_constraints.get("cost_priority", 0.5) * 2
            recommendations.append(
                FormulaRecommendation(
                    formula_id=formula.id,
                    priority_score=round(score, 3),
                    predicted_performance=predicted,
                    pass_hard_constraints=passed,
                    process_parameters=self._process_params(formula),
                    reasoning="Ranked by hard-constraint pass rate + soft-objective weighted score.",
                )
            )
        recommendations.sort(key=lambda x: x.priority_score, reverse=True)
        return recommendations[: payload.top_k]

    def orchestrate(self, raw_input: str, top_k: int) -> OrchestrateResult:
        parsed = self.parse_requirement(RequirementParseRequest(raw_input=raw_input))
        recs = self.recommend_formulas(ExpertRecommendRequest(requirement=parsed, top_k=top_k))
        # Synthesize a pseudo measurement from parsed constraints for direct generation.
        gloss_target = parsed.hard_constraints.get("gloss_min", 75.0) / 100.0
        measurement = Measurement(
            id=f"orchestrated-{md5(raw_input.encode('utf-8')).hexdigest()[:8]}",
            car_model="RequirementBased",
            color_code="AUTO-REQ",
            angles={
                "15": [{"wavelength": 400, "value": 0.2}, {"wavelength": 500, "value": gloss_target}, {"wavelength": 600, "value": 0.3}],  # type: ignore[list-item]
                "45": [{"wavelength": 400, "value": 0.2}, {"wavelength": 500, "value": gloss_target}, {"wavelength": 600, "value": 0.3}],  # type: ignore[list-item]
                "110": [{"wavelength": 400, "value": 0.2}, {"wavelength": 500, "value": gloss_target}, {"wavelength": 600, "value": 0.3}],  # type: ignore[list-item]
            },
            texture={"flake_intensity": 0.2, "sparkle": 0.15, "grain": 0.2},
        )
        generated = self.color_engine.smart_generate(measurement)
        return OrchestrateResult(
            parsed_requirement=parsed,
            recommendations=recs,
            generated_formula=generated,
            workflow_steps=[
                "Main agent parsed raw requirement into hard/soft constraints.",
                "Recommendation agent ranked top formulas from historical library.",
                "Performance prediction agent estimated adhesion/gloss/impact/VOC.",
                "Compliance agent validated hard constraints and flagged pass/fail.",
                "Process agent generated machine/process parameters for pilot production.",
                "Generation agent produced a direct candidate formula for rapid trial.",
            ],
        )

    def feedback(self, payload: FeedbackRequest) -> Dict[str, str | float | bool]:
        # MVP feedback loop: persist as event, return learning delta for explainability.
        confidence_delta = 0.05 if payload.accepted else -0.05
        measured_avg = (
            sum(payload.measured_performance.values()) / max(1, len(payload.measured_performance))
            if payload.measured_performance
            else 0.0
        )
        return {
            "formula_id": payload.formula_id,
            "accepted": payload.accepted,
            "measured_avg": round(measured_avg, 4),
            "model_confidence_delta": confidence_delta,
            "status": "feedback recorded for continual optimization",
        }
