"""User authentication: registration, login, session cookies."""

from __future__ import annotations

import os
from typing import Annotated

import bcrypt
from fastapi import Depends, HTTPException, Request, Response

from src.lib.registry.models import UserRecord
from src.lib.registry.repository import (
    create_session,
    create_user,
    delete_session,
    get_user_by_email,
    get_user_by_id,
    get_user_id_for_session,
)

SESSION_COOKIE = "d2t_session"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except Exception:
        return False


def register_user(email: str, password: str, *, name: str | None = None) -> UserRecord:
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters")
    if get_user_by_email(email):
        raise ValueError("Email already registered")
    return create_user(email, hash_password(password), name=name)


def authenticate_user(email: str, password: str) -> UserRecord | None:
    user = get_user_by_email(email)
    if not user or not verify_password(password, user.password_hash):
        return None
    return user


def start_session(response: Response, user_id: str) -> None:
    token = create_session(user_id)
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 7,
        path="/",
    )


def end_session(response: Response, request: Request) -> None:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        delete_session(token)
    response.delete_cookie(SESSION_COOKIE, path="/")


def get_current_user_optional(request: Request) -> UserRecord | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    user_id = get_user_id_for_session(token)
    if not user_id:
        return None
    return get_user_by_id(user_id)


def get_current_user(request: Request) -> UserRecord:
    user = get_current_user_optional(request)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


OptionalUser = Annotated[UserRecord | None, Depends(get_current_user_optional)]
CurrentUser = Annotated[UserRecord, Depends(get_current_user)]


def bootstrap_admin_if_configured() -> None:
    email = os.environ.get("D2T_BOOTSTRAP_EMAIL", "").strip()
    password = os.environ.get("D2T_BOOTSTRAP_PASSWORD", "").strip()
    if not email or not password:
        return
    if get_user_by_email(email):
        return
    create_user(email, hash_password(password), name="Admin")
