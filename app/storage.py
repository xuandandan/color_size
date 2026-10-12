from __future__ import annotations

from datetime import datetime
from typing import List

from sqlalchemy import desc, select

from .db import AuditLogRow, FeedbackRow, FormulaRow, MeasurementRow, SessionLocal
from .models import AuditLogOut, FeedbackOut, Formula, Measurement


class SQLStore:
    def get_dashboard_summary(self) -> dict:
        with SessionLocal() as session:
            measurement_count = session.query(MeasurementRow).count()
            formula_count = session.query(FormulaRow).count()
            audit_count = session.query(AuditLogRow).count()
            return {
                "measurement_count": measurement_count,
                "formula_count": formula_count,
                "audit_count": audit_count,
            }

    def add_measurement(self, measurement: Measurement) -> None:
        with SessionLocal() as session:
            row = MeasurementRow(
                id=measurement.id,
                car_model=measurement.car_model,
                color_code=measurement.color_code,
                angles=measurement.model_dump(mode="json")["angles"],
                texture=measurement.texture,
            )
            session.merge(row)
            session.commit()

    def add_formula(self, formula: Formula) -> None:
        with SessionLocal() as session:
            row = FormulaRow(
                id=formula.id,
                name=formula.name,
                pigments=formula.pigments,
                linked_measurement_id=formula.linked_measurement_id,
            )
            session.merge(row)
            session.commit()

    def list_formulas(self) -> List[Formula]:
        with SessionLocal() as session:
            rows = session.scalars(select(FormulaRow).order_by(FormulaRow.created_at.desc())).all()
            return [
                Formula(
                    id=row.id,
                    name=row.name,
                    pigments=row.pigments,
                    linked_measurement_id=row.linked_measurement_id,
                )
                for row in rows
            ]

    def has_formula(self, formula_id: str) -> bool:
        with SessionLocal() as session:
            return session.get(FormulaRow, formula_id) is not None

    def get_formula(self, formula_id: str) -> Formula:
        with SessionLocal() as session:
            row = session.get(FormulaRow, formula_id)
            if row is None:
                raise KeyError(formula_id)
            return Formula(
                id=row.id,
                name=row.name,
                pigments=row.pigments,
                linked_measurement_id=row.linked_measurement_id,
            )

    def has_measurement(self, measurement_id: str) -> bool:
        with SessionLocal() as session:
            return session.get(MeasurementRow, measurement_id) is not None

    def get_measurement(self, measurement_id: str) -> Measurement:
        with SessionLocal() as session:
            row = session.get(MeasurementRow, measurement_id)
            if row is None:
                raise KeyError(measurement_id)
            return Measurement(
                id=row.id,
                car_model=row.car_model,
                color_code=row.color_code,
                angles=row.angles,
                texture=row.texture,
            )

    def add_audit_log(
        self,
        username: str,
        action: str,
        target_type: str,
        target_id: str,
        score: float = 0.0,
    ) -> None:
        with SessionLocal() as session:
            session.add(
                AuditLogRow(
                    username=username,
                    action=action,
                    target_type=target_type,
                    target_id=target_id,
                    score=score,
                )
            )
            session.commit()

    def list_audit_logs(self, limit: int = 50) -> List[AuditLogOut]:
        with SessionLocal() as session:
            rows = session.scalars(select(AuditLogRow).order_by(desc(AuditLogRow.id)).limit(limit)).all()
            return [
                AuditLogOut(
                    id=row.id,
                    username=row.username,
                    action=row.action,
                    target_type=row.target_type,
                    target_id=row.target_id,
                    score=row.score,
                    created_at=row.created_at.isoformat() if isinstance(row.created_at, datetime) else "",
                )
                for row in rows
            ]

    def add_feedback(self, formula_id: str, measured_performance: dict, accepted: bool, comment: str) -> None:
        with SessionLocal() as session:
            session.add(
                FeedbackRow(
                    formula_id=formula_id,
                    measured_performance=measured_performance,
                    accepted=1.0 if accepted else 0.0,
                    comment=comment,
                )
            )
            session.commit()

    def list_feedbacks(self, limit: int = 50) -> List[FeedbackOut]:
        with SessionLocal() as session:
            rows = session.scalars(select(FeedbackRow).order_by(desc(FeedbackRow.id)).limit(limit)).all()
            return [
                FeedbackOut(
                    id=row.id,
                    formula_id=row.formula_id,
                    measured_performance=row.measured_performance or {},
                    accepted=bool(row.accepted >= 0.5),
                    comment=row.comment or "",
                    created_at=row.created_at.isoformat() if isinstance(row.created_at, datetime) else "",
                )
                for row in rows
            ]
