from __future__ import annotations

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select

from .db import SessionLocal, UserRow, hash_password
from .models import LoginRequest


def login_user(payload: LoginRequest) -> str:
    with SessionLocal() as session:
        user = session.get(UserRow, payload.username)
        if user is None or user.password_hash != hash_password(payload.password):
            raise HTTPException(status_code=401, detail="invalid credentials")
        return user.token


def get_current_user(x_token: str = Header(default="")) -> str:
    if not x_token:
        raise HTTPException(status_code=401, detail="missing x-token")
    with SessionLocal() as session:
        row = session.scalar(select(UserRow).where(UserRow.token == x_token))
        if row is None:
            raise HTTPException(status_code=401, detail="invalid x-token")
        return row.username
