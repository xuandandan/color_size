from __future__ import annotations

import hashlib
import os
from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, String, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./paint_system.db")
ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "demo-token")


def _normalize_database_url(url: str) -> str:
    if url.startswith("mysql://"):
        # SQLAlchemy 2 requires explicit DBAPI driver.
        return url.replace("mysql://", "mysql+pymysql://", 1)
    return url


DB_URL = _normalize_database_url(DATABASE_URL)
engine_kwargs = {"future": True, "pool_pre_ping": True}
if DB_URL.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    engine_kwargs["pool_recycle"] = 3600
engine = create_engine(DB_URL, **engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


class MeasurementRow(Base):
    __tablename__ = "measurements"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    car_model: Mapped[str] = mapped_column(String(120), index=True)
    color_code: Mapped[str] = mapped_column(String(64), index=True)
    angles: Mapped[dict] = mapped_column(JSON)
    texture: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class FormulaRow(Base):
    __tablename__ = "formulas"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    pigments: Mapped[dict] = mapped_column(JSON)
    linked_measurement_id: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class UserRow(Base):
    __tablename__ = "users"
    username: Mapped[str] = mapped_column(String(64), primary_key=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    token: Mapped[str] = mapped_column(String(128), unique=True, index=True)


class AuditLogRow(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), index=True)
    action: Mapped[str] = mapped_column(String(200))
    target_type: Mapped[str] = mapped_column(String(50))
    target_id: Mapped[str] = mapped_column(String(80))
    score: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class FeedbackRow(Base):
    __tablename__ = "feedbacks"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    formula_id: Mapped[str] = mapped_column(String(64), index=True)
    measured_performance: Mapped[dict] = mapped_column(JSON)
    accepted: Mapped[float] = mapped_column(Float, default=0.0)
    comment: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def db_ping() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    with Session(engine) as session:
        admin = session.get(UserRow, ADMIN_USER)
        if admin is None:
            session.add(
                UserRow(
                    username=ADMIN_USER,
                    password_hash=hash_password(ADMIN_PASSWORD),
                    token=ADMIN_TOKEN,
                )
            )
            session.commit()
        existing_measurement = session.get(MeasurementRow, "m001")
        if existing_measurement is None:
            session.add(
                MeasurementRow(
                    id="m001",
                    car_model="Model-X",
                    color_code="PX-100",
                    angles={
                        "15": [
                            {"wavelength": 400, "value": 0.3},
                            {"wavelength": 500, "value": 0.4},
                            {"wavelength": 600, "value": 0.2},
                        ],
                        "45": [
                            {"wavelength": 400, "value": 0.35},
                            {"wavelength": 500, "value": 0.45},
                            {"wavelength": 600, "value": 0.25},
                        ],
                        "110": [
                            {"wavelength": 400, "value": 0.4},
                            {"wavelength": 500, "value": 0.3},
                            {"wavelength": 600, "value": 0.2},
                        ],
                    },
                    texture={"flake_intensity": 0.6, "sparkle": 0.4, "grain": 0.3},
                )
            )
        existing_formula = session.get(FormulaRow, "f001")
        if existing_formula is None:
            session.add(
                FormulaRow(
                    id="f001",
                    name="Metal Blue Base",
                    pigments={"base_white": 0.2, "base_black": 0.1, "al_silver": 0.18, "pearl": 0.06},
                    linked_measurement_id="m001",
                )
            )
        session.commit()


def reset_and_seed_demo_data() -> dict:
    with Session(engine) as session:
        deleted_logs = session.query(AuditLogRow).delete()
        deleted_formulas = session.query(FormulaRow).delete()
        deleted_measurements = session.query(MeasurementRow).delete()
        session.add(
            MeasurementRow(
                id="m001",
                car_model="Model-X",
                color_code="PX-100",
                angles={
                    "15": [
                        {"wavelength": 400, "value": 0.3},
                        {"wavelength": 500, "value": 0.4},
                        {"wavelength": 600, "value": 0.2},
                    ],
                    "45": [
                        {"wavelength": 400, "value": 0.35},
                        {"wavelength": 500, "value": 0.45},
                        {"wavelength": 600, "value": 0.25},
                    ],
                    "110": [
                        {"wavelength": 400, "value": 0.4},
                        {"wavelength": 500, "value": 0.3},
                        {"wavelength": 600, "value": 0.2},
                    ],
                },
                texture={"flake_intensity": 0.6, "sparkle": 0.4, "grain": 0.3},
            )
        )
        session.add(
            FormulaRow(
                id="f001",
                name="Metal Blue Base",
                pigments={"base_white": 0.2, "base_black": 0.1, "al_silver": 0.18, "pearl": 0.06},
                linked_measurement_id="m001",
            )
        )
        session.commit()
        return {
            "deleted_measurements": deleted_measurements,
            "deleted_formulas": deleted_formulas,
            "deleted_audit_logs": deleted_logs,
            "seeded_measurements": 1,
            "seeded_formulas": 1,
        }
