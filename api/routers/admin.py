"""
Admin user-management endpoints — /api/v1/admin/users.

Backs the frontend's Admin > User Management page. All routes require an
admin-role JWT (require_admin) and are scoped to the caller's own
organization_id — an admin from one org can never see or edit another org's
users, even though this deployment currently only has one org.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from api.dependencies import UserContext, require_admin
from api.services import auth_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["Admin"])


class CreateUserRequest(BaseModel):
    name:           str
    email:          str
    role:           str
    password:       str
    allowed_kb_ids: list[str] = []


class UpdateUserRequest(BaseModel):
    name:           Optional[str]       = None
    email:          Optional[str]       = None
    role:           Optional[str]       = None
    password:       Optional[str]       = None
    allowed_kb_ids: Optional[list[str]] = None
    is_active:      Optional[bool]      = None


def _get_owned_user(user_id: str, admin: UserContext) -> dict:
    user = auth_service.get_user_by_id(user_id)
    if not user or user["organization_id"] != admin.organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@router.get("/users")
async def list_users(admin: UserContext = Depends(require_admin)) -> dict:
    users = auth_service.list_users(admin.organization_id)
    return {"success": True, "users": [auth_service.to_public(u) for u in users]}


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def create_user(
    body:  CreateUserRequest,
    admin: UserContext = Depends(require_admin),
) -> dict:
    if auth_service.get_user_by_email(body.email):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    user = auth_service.create_user(
        organization_id = admin.organization_id,
        email           = body.email,
        password        = body.password,
        name            = body.name,
        role            = body.role,
        allowed_kb_ids  = body.allowed_kb_ids,
    )
    logger.info("Admin %s created user %s (%s)", admin.user_id, user["id"], user["email"])
    return {"success": True, "data": auth_service.to_public(user)}


@router.patch("/users/{user_id}")
async def update_user(
    user_id: str,
    body:    UpdateUserRequest,
    admin:   UserContext = Depends(require_admin),
) -> dict:
    _get_owned_user(user_id, admin)

    updates = body.model_dump(exclude_unset=True)
    if "email" in updates and updates["email"]:
        existing = auth_service.get_user_by_email(updates["email"])
        if existing and existing["id"] != user_id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    updated = auth_service.update_user(user_id, updates)
    logger.info("Admin %s updated user %s", admin.user_id, user_id)
    return {"success": True, "data": auth_service.to_public(updated)}


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: str,
    admin:   UserContext = Depends(require_admin),
) -> None:
    _get_owned_user(user_id, admin)
    auth_service.delete_user(user_id)
    logger.info("Admin %s deleted user %s", admin.user_id, user_id)
