from __future__ import annotations

from typing import Dict, List

from pydantic import BaseModel, Field


class SpectrumPoint(BaseModel):
    wavelength: int = Field(..., ge=380, le=780)
    value: float = Field(..., ge=0.0, le=1.0)


class Measurement(BaseModel):
    id: str
    car_model: str
    color_code: str
    angles: Dict[str, List[SpectrumPoint]]
    texture: Dict[str, float] = Field(default_factory=dict)


class Formula(BaseModel):
    id: str
    name: str
    pigments: Dict[str, float]
    linked_measurement_id: str


class MatchRequest(BaseModel):
    measurement: Measurement
    top_k: int = Field(default=3, ge=1, le=10)


class MatchResult(BaseModel):
    formula_id: str
    score: float
    reason: str


class TuneRequest(BaseModel):
    target_measurement: Measurement
    base_formula_id: str


class TuneResult(BaseModel):
    formula_id: str
    adjustment: Dict[str, float]
    advice: List[str]


class GenerateRequest(BaseModel):
    measurement: Measurement
    range_ratio: float = Field(default=0.1, ge=0.01, le=0.5)


class GenerateFromRgbRequest(BaseModel):
    """由 RGB（如流行色展望结果）合成测色特征并走与图像一致的生成管线。"""

    r: int = Field(..., ge=0, le=255)
    g: int = Field(..., ge=0, le=255)
    b: int = Field(..., ge=0, le=255)
    range_ratio: float = Field(default=0.1, ge=0.01, le=0.5)
    car_model: str = Field(default="Trend-Forecast", max_length=160)
    color_code: str = Field(default="FCST", max_length=48)
    source_label: str = Field(default="", max_length=240, description="前端展示用，如展望色标签")


class FillerSpec(BaseModel):
    """填料或功能粉体在成品中的建议添加（质量分数，%）。"""

    name: str
    content_pct: float = Field(..., ge=0.0, le=100.0)


class GenerateResult(BaseModel):
    formula_name: str
    pigments: Dict[str, float]
    confidence: float = Field(..., ge=0.0, le=1.0)
    pigments_range: Dict[str, "PigmentRange"] = Field(default_factory=dict)
    limit_color_previews: List["ColorPreviewPoint"] = Field(default_factory=list)
    process_parameters: Dict[str, float | str] = Field(default_factory=dict)
    operation_advice: List[str] = Field(default_factory=list)
    fillers: List[FillerSpec] = Field(
        default_factory=list,
        description="填料/助粉体种类及建议含量（占成品 %）",
    )
    masterbatch_ratio_pct: Dict[str, float] = Field(
        default_factory=dict,
        description="七支色母在色浆中的相对质量占比（合计约 100%）",
    )
    base_material_formula_pct: Dict[str, float] = Field(
        default_factory=dict,
        description="基料（树脂/溶剂/助剂）建议配比（占基料体系 %，合计约 100%）",
    )
    reference_rgb: Dict[str, int] | None = Field(
        default=None,
        description="可选：图像/ROI 参考色，与 limit_color_previews 对照",
    )
    reference_lab: Dict[str, float] | None = Field(
        default=None,
        description="可选：参考色在 CIE Lab（D65，与 skimage rgb2lab 一致）",
    )


class PigmentRange(BaseModel):
    lower: float = Field(..., ge=0.0, le=1.0)
    mid: float = Field(..., ge=0.0, le=1.0)
    upper: float = Field(..., ge=0.0, le=1.0)


class ColorPreviewPoint(BaseModel):
    level: str
    rgb: Dict[str, int]
    hex: str


class RenderPreviewRequest(BaseModel):
    formula_id: str
    view_angle: int = Field(default=45, ge=0, le=180)


class RenderPreviewResult(BaseModel):
    formula_id: str
    rgb_hint: str
    roughness: float
    flake_intensity: float


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str


class AuditLogOut(BaseModel):
    id: int
    username: str
    action: str
    target_type: str
    target_id: str
    score: float
    created_at: str


class VisionExtractResult(BaseModel):
    measurement: Measurement
    avg_rgb: Dict[str, int]
    avg_lab: Dict[str, float] = Field(default_factory=dict)
    roi: Dict[str, float] = Field(
        default_factory=dict,
        description="使用的 ROI：left, top, width, height，均为相对整图 0~1",
    )
    suggestion: str


class VisionRecommendResult(BaseModel):
    measurement: Measurement
    match_results: List[MatchResult]
    generated_formula: GenerateResult
    avg_rgb: Dict[str, int] = Field(
        default_factory=dict,
        description="与识图相同的 ROI/全图平均 RGB（0–255），便于与配方色母区分",
    )
    avg_lab: Dict[str, float] = Field(default_factory=dict)
    roi: Dict[str, float] = Field(default_factory=dict)


class ExportRequest(BaseModel):
    report_name: str = "color_report"
    result_type: str = "generic"
    payload: Dict = Field(default_factory=dict)


class CompareMetricsResult(BaseModel):
    delta_e_00: float
    rgb_rmse: float
    rgb_mae: float
    ssim: float
    trust_score: float
    level: str


class RequirementParseRequest(BaseModel):
    raw_input: str


class ParsedRequirement(BaseModel):
    hard_constraints: Dict[str, float] = Field(default_factory=dict)
    soft_constraints: Dict[str, float] = Field(default_factory=dict)
    notes: List[str] = Field(default_factory=list)


class ExpertRecommendRequest(BaseModel):
    requirement: ParsedRequirement
    top_k: int = Field(default=5, ge=5, le=10)


class FormulaRecommendation(BaseModel):
    formula_id: str
    priority_score: float
    predicted_performance: Dict[str, float]
    pass_hard_constraints: bool
    process_parameters: Dict[str, float | str]
    reasoning: str


class OrchestrateRequest(BaseModel):
    raw_input: str
    top_k: int = Field(default=5, ge=5, le=10)


class OrchestrateResult(BaseModel):
    parsed_requirement: ParsedRequirement
    recommendations: List[FormulaRecommendation]
    generated_formula: GenerateResult
    workflow_steps: List[str]


class FeedbackRequest(BaseModel):
    formula_id: str
    measured_performance: Dict[str, float]
    accepted: bool
    comment: str = ""


class TrainRequest(BaseModel):
    min_samples: int = Field(default=20, ge=1)


class TrainResult(BaseModel):
    trained_at: str
    sample_count: int
    perf_mae: float
    perf_r2: float
    rank_mae: float
    model_version: str


class ModelStatusResult(BaseModel):
    ready: bool
    model_dir: str
    metadata: Dict = Field(default_factory=dict)


class TrendNeighbor(BaseModel):
    tcx_code: str
    color_name: str
    hex: str
    r: int
    g: int
    b: int
    lab_l: float
    lab_a: float
    lab_b: float
    trend_year: int = 0
    book_group: str = ""
    distance: float
    image_rel_path: str = ""


class TrendMatchRequest(BaseModel):
    r: int | None = None
    g: int | None = None
    b: int | None = None
    measurement: Measurement | None = None
    top_k: int = Field(default=5, ge=1, le=30)


class TrendMatchResult(BaseModel):
    query_lab: Dict[str, float]
    preference_score: float
    trend_cluster: int
    neighbors: List[TrendNeighbor]
    mean_delta_e_lab: float = 0.0


class TrendTrainRequest(BaseModel):
    min_rows: int = Field(default=16, ge=8)
    n_clusters: int | None = Field(default=None, ge=2, le=32)


class TrendTrainResult(BaseModel):
    trained_at: str
    sample_count: int
    n_clusters: int
    model_version: str


class TrendForecastRequest(BaseModel):
    """由提取色 / RGB 结合已训练趋势模型，给出未来若干年的启发式色展望（非物理预测）。"""

    r: int | None = None
    g: int | None = None
    b: int | None = None
    measurement: Measurement | None = None
    horizon_years: int = Field(default=2, ge=1, le=5, description="展望年数，例如 2 表示未来两年")
    suggestions_per_horizon: int = Field(default=3, ge=1, le=8, description="每个展望年生成的候选色数量")


class TrendForecastColor(BaseModel):
    horizon_offset: int = Field(..., ge=1, description="相对锚点年的第几年（1=下一年度方向）")
    forecast_calendar_year: int = Field(..., ge=1900, le=2100)
    label: str = ""
    hex: str = "#000000"
    r: int = Field(..., ge=0, le=255)
    g: int = Field(..., ge=0, le=255)
    b: int = Field(..., ge=0, le=255)
    lab_l: float = 0.0
    lab_a: float = 0.0
    lab_b: float = 0.0
    rationale: str = ""


class TrendForecastResult(BaseModel):
    query_lab: Dict[str, float]
    trend_cluster: int
    anchor_trend_year: int = Field(0, description="用于外推的参考年（数据集中簇内或全局最大 trend_year）")
    temporal_signal: str = Field(
        "",
        description="cluster_temporal_regression | global_temporal | palette_evolution_heuristic",
    )
    forecasts: List[TrendForecastColor] = Field(default_factory=list)
    methodology_note: str = Field(
        default="",
        description="说明算法边界：启发式外推，需持续用真实市场/检测数据校准",
    )


class FeedbackOut(BaseModel):
    id: int
    formula_id: str
    measured_performance: Dict[str, float]
    accepted: bool
    comment: str
    created_at: str
