from __future__ import annotations

import os
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .auth import get_current_user, login_user
from .db import ADMIN_USER, db_ping, init_db, reset_and_seed_demo_data
from .exporters import build_excel_bytes, build_pdf_bytes
from .importer import import_excel_dataset
from .metrics import compare_images
from .ml import MLRuntime
from .models import (
    AuditLogOut,
    CompareMetricsResult,
    ExpertRecommendRequest,
    ExportRequest,
    FeedbackRequest,
    FormulaRecommendation,
    Formula,
    GenerateRequest,
    GenerateFromRgbRequest,
    GenerateResult,
    LoginRequest,
    LoginResponse,
    MatchRequest,
    MatchResult,
    Measurement,
    OrchestrateRequest,
    OrchestrateResult,
    ParsedRequirement,
    ModelStatusResult,
    TrainRequest,
    TrainResult,
    FeedbackOut,
    RenderPreviewRequest,
    RenderPreviewResult,
    RequirementParseRequest,
    TuneRequest,
    TuneResult,
    TrendMatchRequest,
    TrendMatchResult,
    TrendForecastRequest,
    TrendForecastResult,
    TrendTrainRequest,
    TrendTrainResult,
    VisionExtractResult,
    VisionRecommendResult,
)
from .services import ColorEngine, ExpertOrchestrator
from .storage import SQLStore
from .trend_preferences import TrendPreferenceRuntime
from .vision import build_measurement_from_rgb, extract_measurement_from_image

app = FastAPI(title="Smart Paint Color System", version="0.2.1+trends-forecast")
init_db()
store = SQLStore()
engine = ColorEngine(store)
ml_runtime = MLRuntime(model_dir="models")
trend_runtime = TrendPreferenceRuntime(model_dir="models")
expert = ExpertOrchestrator(store, engine, ml_runtime=ml_runtime)
static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")

cors_origins_raw = os.getenv(
    "CORS_ORIGINS",
    "http://127.0.0.1:8000,http://localhost:8000,http://127.0.0.1:5173,http://localhost:5173",
)
cors_origins = [x.strip() for x in cors_origins_raw.split(",") if x.strip()]
# Render 公网部署可设 CORS_ORIGINS=*
allow_all_cors = cors_origins == ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if allow_all_cors else cors_origins,
    allow_credentials=not allow_all_cors,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health(response: Response) -> dict:
    """无需登录；用于确认当前进程是否为本仓库最新代码（含 trends）。"""
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    trend_paths = sorted(
        {getattr(r, "path", "") for r in app.routes if getattr(r, "path", None) and "/trends" in str(r.path)}
    )
    post_forecast_loaded = any(
        getattr(r, "path", "") == "/trends/forecast"
        and ("POST" in (getattr(r, "methods", None) or set()))
        for r in app.routes
    )
    return {
        "status": "ok",
        "db_connected": db_ping(),
        "app_version": app.version,
        "trends_routes_loaded": trend_paths,
        "post_trends_forecast_loaded": post_forecast_loaded,
    }


@app.get("/trends/ping")
def trends_ping() -> JSONResponse:
    """无需登录、不读数据库；仅用于判断当前 uvicorn 是否为本项目带 trends 的版本。"""
    post_forecast_loaded = any(
        getattr(r, "path", "") == "/trends/forecast"
        and ("POST" in (getattr(r, "methods", None) or set()))
        for r in app.routes
    )
    return JSONResponse(
        {
            "trends_api": True,
            "app_version": app.version,
            "post_trends_forecast_loaded": post_forecast_loaded,
            "hint": "打开 /health 查看 app_version 与 post_trends_forecast_loaded。展望流行色需 POST /trends/forecast；若为 false 请关掉旧 uvicorn 后在项目根执行: python -m uvicorn app.main:app --reload --port 8000",
        },
        headers={"Cache-Control": "no-store"},
    )


@app.get("/dashboard/summary")
def dashboard_summary(_: str = Depends(get_current_user)) -> dict:
    return store.get_dashboard_summary()


@app.get("/")
def index() -> FileResponse:
    return FileResponse(static_dir / "index.html")


@app.post("/auth/login", response_model=LoginResponse)
def login(payload: LoginRequest) -> LoginResponse:
    token = login_user(payload)
    return LoginResponse(token=token)


@app.post("/measurements")
def create_measurement(measurement: Measurement, username: str = Depends(get_current_user)) -> dict:
    store.add_measurement(measurement)
    store.add_audit_log(username, "create_measurement", "measurement", measurement.id)
    return {"message": "measurement saved", "id": measurement.id}


@app.post("/formulas")
def create_formula(formula: Formula, username: str = Depends(get_current_user)) -> dict:
    if not store.has_measurement(formula.linked_measurement_id):
        raise HTTPException(status_code=400, detail="linked_measurement_id not found")
    store.add_formula(formula)
    store.add_audit_log(username, "create_formula", "formula", formula.id)
    return {"message": "formula saved", "id": formula.id}


@app.get("/formulas")
def list_formulas(_: str = Depends(get_current_user)) -> list[Formula]:
    return store.list_formulas()


@app.get("/feedbacks", response_model=list[FeedbackOut])
def list_feedbacks(limit: int = 50, _: str = Depends(get_current_user)) -> list[FeedbackOut]:
    return store.list_feedbacks(limit=limit)


@app.get("/knowledge/rgb-primaries")
def rgb_primaries(_: str = Depends(get_current_user)) -> dict:
    return {
        "optical_mapping": {
            "blue": {"wavelength_nm": 400, "measurement_channel": 'angles["45"][wavelength=400]'},
            "green": {"wavelength_nm": 500, "measurement_channel": 'angles["45"][wavelength=500]'},
            "red": {"wavelength_nm": 600, "measurement_channel": 'angles["45"][wavelength=600]'},
        },
        "formula_mapping": {
            "blue": "base_blue",
            "green": "base_green",
            "red": "base_red",
        },
        "code_locations": {
            "feature_extraction": "app/vision.py",
            "formula_generation": "app/services.py",
            "model_training_features": "app/ml.py",
        },
    }


@app.post("/algorithms/match", response_model=list[MatchResult])
def run_match(payload: MatchRequest, username: str = Depends(get_current_user)) -> list[MatchResult]:
    if not store.list_formulas():
        raise HTTPException(status_code=400, detail="no formulas available")
    results = engine.smart_match(payload.measurement, payload.top_k)
    top_score = results[0].score if results else 0.0
    store.add_audit_log(username, "smart_match", "measurement", payload.measurement.id, top_score)
    return results


@app.post("/algorithms/tune", response_model=TuneResult)
def run_tune(payload: TuneRequest, username: str = Depends(get_current_user)) -> TuneResult:
    if not store.has_formula(payload.base_formula_id):
        raise HTTPException(status_code=400, detail="base formula not found")
    base = store.get_formula(payload.base_formula_id)
    result = engine.smart_tune(payload.target_measurement, base)
    store.add_audit_log(username, "smart_tune", "formula", payload.base_formula_id)
    return result


@app.post("/algorithms/generate", response_model=GenerateResult)
def run_generate(payload: GenerateRequest, username: str = Depends(get_current_user)) -> GenerateResult:
    result = engine.smart_generate(payload.measurement, range_ratio=payload.range_ratio)
    store.add_audit_log(username, "smart_generate", "measurement", payload.measurement.id, result.confidence)
    return result


@app.post("/algorithms/generate-from-rgb", response_model=GenerateResult)
def run_generate_from_rgb(payload: GenerateFromRgbRequest, username: str = Depends(get_current_user)) -> GenerateResult:
    """由 RGB 合成测色并生成配方（用于展望色一键下发等）。"""
    measurement, ref_rgb, ref_lab = build_measurement_from_rgb(
        payload.r,
        payload.g,
        payload.b,
        car_model=payload.car_model,
        color_code=payload.color_code,
    )
    store.add_measurement(measurement)
    result = engine.smart_generate(measurement, range_ratio=payload.range_ratio)
    result = result.model_copy(
        update={
            "reference_rgb": dict(ref_rgb),
            "reference_lab": dict(ref_lab),
        }
    )
    store.add_audit_log(
        username,
        "generate_from_rgb",
        "measurement",
        measurement.id,
        result.confidence,
    )
    return result


@app.post("/algorithms/render", response_model=RenderPreviewResult)
def run_render(payload: RenderPreviewRequest, username: str = Depends(get_current_user)) -> RenderPreviewResult:
    if not store.has_formula(payload.formula_id):
        raise HTTPException(status_code=400, detail="formula not found")
    formula = store.get_formula(payload.formula_id)
    result = engine.paint_render_preview(formula, payload.view_angle)
    store.add_audit_log(username, "paint_render_preview", "formula", payload.formula_id, result.flake_intensity)
    return result


@app.get("/audit/logs", response_model=list[AuditLogOut])
def read_audit_logs(limit: int = 50, _: str = Depends(get_current_user)) -> list[AuditLogOut]:
    return store.list_audit_logs(limit=limit)


@app.post("/admin/reset-demo")
def admin_reset_demo_data(username: str = Depends(get_current_user)) -> dict:
    if username != ADMIN_USER:
        raise HTTPException(status_code=403, detail="admin only")
    result = reset_and_seed_demo_data()
    store.add_audit_log(username, "admin_reset_demo", "system", "demo_data")
    return {"message": "demo data reset complete", "result": result}


@app.post("/vision/extract", response_model=VisionExtractResult)
async def vision_extract(
    image: UploadFile = File(...),
    car_model: str = Form(default="Unknown-Car"),
    color_code: str = Form(default="AUTO"),
    roi_left: float = Form(default=0.0),
    roi_top: float = Form(default=0.0),
    roi_width: float = Form(default=1.0),
    roi_height: float = Form(default=1.0),
    username: str = Depends(get_current_user),
) -> VisionExtractResult:
    result = await extract_measurement_from_image(
        image,
        car_model=car_model,
        color_code=color_code,
        roi_left=roi_left,
        roi_top=roi_top,
        roi_width=roi_width,
        roi_height=roi_height,
    )
    store.add_measurement(result.measurement)
    store.add_audit_log(username, "vision_extract", "measurement", result.measurement.id)
    return result


@app.post("/vision/recommend", response_model=VisionRecommendResult)
async def vision_recommend(
    image: UploadFile = File(...),
    car_model: str = Form(default="Unknown-Car"),
    color_code: str = Form(default="AUTO"),
    top_k: int = Form(default=3),
    range_ratio: float = Form(default=0.1),
    roi_left: float = Form(default=0.0),
    roi_top: float = Form(default=0.0),
    roi_width: float = Form(default=1.0),
    roi_height: float = Form(default=1.0),
    username: str = Depends(get_current_user),
) -> VisionRecommendResult:
    extracted = await extract_measurement_from_image(
        image,
        car_model=car_model,
        color_code=color_code,
        roi_left=roi_left,
        roi_top=roi_top,
        roi_width=roi_width,
        roi_height=roi_height,
    )
    store.add_measurement(extracted.measurement)
    matches = engine.smart_match(extracted.measurement, top_k=max(1, min(10, top_k)))
    safe_ratio = max(0.01, min(0.5, range_ratio))
    generated = engine.smart_generate(extracted.measurement, range_ratio=safe_ratio)
    generated = generated.model_copy(
        update={
            "reference_rgb": dict(extracted.avg_rgb),
            "reference_lab": dict(extracted.avg_lab) if extracted.avg_lab else None,
        }
    )
    store.add_audit_log(username, "vision_recommend", "measurement", extracted.measurement.id)
    return VisionRecommendResult(
        measurement=extracted.measurement,
        match_results=matches,
        generated_formula=generated,
        avg_rgb=extracted.avg_rgb,
        avg_lab=extracted.avg_lab,
        roi=extracted.roi,
    )


@app.post("/export/excel")
def export_excel(payload: ExportRequest, username: str = Depends(get_current_user)) -> Response:
    content = build_excel_bytes(payload.report_name, payload.result_type, payload.payload)
    store.add_audit_log(username, "export_excel", "report", payload.report_name)
    headers = {"Content-Disposition": f'attachment; filename="{payload.report_name}.xlsx"'}
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )


@app.post("/export/pdf")
def export_pdf(payload: ExportRequest, username: str = Depends(get_current_user)) -> Response:
    content = build_pdf_bytes(payload.report_name, payload.result_type, payload.payload)
    store.add_audit_log(username, "export_pdf", "report", payload.report_name)
    headers = {"Content-Disposition": f'attachment; filename="{payload.report_name}.pdf"'}
    return Response(content=content, media_type="application/pdf", headers=headers)


@app.post("/import/excel")
async def import_excel(file: UploadFile = File(...), username: str = Depends(get_current_user)) -> dict:
    if not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="only .xlsx file is supported")
    content = await file.read()
    report = import_excel_dataset(content, store)
    score = float(report.get("total_failed", 0))
    store.add_audit_log(username, "import_excel", "dataset", file.filename, score)
    return report


@app.post("/metrics/compare", response_model=CompareMetricsResult)
async def metrics_compare(
    target_image: UploadFile = File(...),
    predicted_image: UploadFile = File(...),
    username: str = Depends(get_current_user),
) -> CompareMetricsResult:
    target_bytes = await target_image.read()
    predicted_bytes = await predicted_image.read()
    metrics = compare_images(target_bytes, predicted_bytes)
    store.add_audit_log(username, "metrics_compare", "metrics", "image_pair", metrics["trust_score"])
    return CompareMetricsResult(**metrics)


@app.post("/expert/parse-requirement", response_model=ParsedRequirement)
def expert_parse_requirement(payload: RequirementParseRequest, username: str = Depends(get_current_user)) -> ParsedRequirement:
    result = expert.parse_requirement(payload)
    store.add_audit_log(username, "expert_parse_requirement", "requirement", "parsed")
    return result


@app.post("/expert/recommend", response_model=list[FormulaRecommendation])
def expert_recommend(payload: ExpertRecommendRequest, username: str = Depends(get_current_user)) -> list[FormulaRecommendation]:
    result = expert.recommend_formulas(payload)
    top = result[0].priority_score if result else 0.0
    store.add_audit_log(username, "expert_recommend", "formula", "topk", top)
    return result


@app.post("/expert/orchestrate", response_model=OrchestrateResult)
def expert_orchestrate(payload: OrchestrateRequest, username: str = Depends(get_current_user)) -> OrchestrateResult:
    result = expert.orchestrate(payload.raw_input, payload.top_k)
    top = result.recommendations[0].priority_score if result.recommendations else 0.0
    store.add_audit_log(username, "expert_orchestrate", "workflow", "full_pipeline", top)
    return result


@app.post("/expert/feedback")
def expert_feedback(payload: FeedbackRequest, username: str = Depends(get_current_user)) -> dict:
    result = expert.feedback(payload)
    store.add_feedback(payload.formula_id, payload.measured_performance, payload.accepted, payload.comment)
    score = float(result.get("measured_avg", 0.0))
    store.add_audit_log(username, "expert_feedback", "formula", payload.formula_id, score)
    return result


@app.post("/expert/train", response_model=TrainResult)
def expert_train(payload: TrainRequest, username: str = Depends(get_current_user)) -> TrainResult:
    metadata = ml_runtime.train(min_samples=payload.min_samples)
    store.add_audit_log(username, "expert_train", "model", metadata["model_version"], float(metadata["perf_r2"]))
    return TrainResult(**metadata)


@app.get("/expert/model-status", response_model=ModelStatusResult)
def expert_model_status(_: str = Depends(get_current_user)) -> ModelStatusResult:
    return ModelStatusResult(**ml_runtime.status())


@app.get("/trends/status", tags=["流行色 trends"])
def trends_status(_: str = Depends(get_current_user)) -> dict:
    return trend_runtime.dataset_status()


@app.post("/trends/train", response_model=TrendTrainResult, tags=["流行色 trends"])
def trends_train(payload: TrendTrainRequest, username: str = Depends(get_current_user)) -> TrendTrainResult:
    try:
        result = trend_runtime.train(min_rows=payload.min_rows, n_clusters=payload.n_clusters)
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    store.add_audit_log(username, "trends_train", "trend_ml", result.model_version, float(result.sample_count))
    return result


@app.post("/trends/match", response_model=TrendMatchResult, tags=["流行色 trends"])
def trends_match(payload: TrendMatchRequest, username: str = Depends(get_current_user)) -> TrendMatchResult:
    try:
        result = trend_runtime.match(
            r=payload.r,
            g=payload.g,
            b=payload.b,
            measurement=payload.measurement,
            top_k=payload.top_k,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    store.add_audit_log(username, "trends_match", "trend_ml", "match", float(result.preference_score))
    return result


@app.post("/trends/forecast", response_model=TrendForecastResult, tags=["流行色 trends"])
def trends_forecast(payload: TrendForecastRequest, username: str = Depends(get_current_user)) -> TrendForecastResult:
    """由提取 RGB / 测色数据，结合趋势簇与年份信息，启发式展望未来流行色（主动开发参考）。"""
    try:
        result = trend_runtime.forecast(
            r=payload.r,
            g=payload.g,
            b=payload.b,
            measurement=payload.measurement,
            horizon_years=payload.horizon_years,
            suggestions_per_horizon=payload.suggestions_per_horizon,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    store.add_audit_log(username, "trends_forecast", "trend_ml", "forecast", float(len(result.forecasts)))
    return result
