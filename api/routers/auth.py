"""
Auth endpoint — POST /api/v1/auth/login.

Verifies email + password against the Supabase `users` table and issues a
JWT carrying sub/org/role claims, consumed by api/dependencies.py's
_validate_jwt() on every subsequent authenticated request.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from api.services import auth_service

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Auth"])


class LoginRequest(BaseModel):
    email:    str
    password: str


class LoginResponse(BaseModel):
    user:  dict
    token: str


@router.post("/auth/login", response_model=LoginResponse)
async def login(body: LoginRequest) -> LoginResponse:
    user = auth_service.get_user_by_email(body.email)
    if not user or not user.get("is_active", True):
        raise HTTPException(
            status_code = status.HTTP_401_UNAUTHORIZED,
            detail      = "Invalid email or password",
        )

    if not auth_service.verify_password(body.password, user["password_hash"]):
        raise HTTPException(
            status_code = status.HTTP_401_UNAUTHORIZED,
            detail      = "Invalid email or password",
        )

    token = auth_service.create_access_token(user)
    auth_service.touch_last_login(user["id"])

    logger.info("Login | user=%s org=%s role=%s", user["id"], user["organization_id"], user["role"])

    return LoginResponse(user=auth_service.to_public(user), token=token)
