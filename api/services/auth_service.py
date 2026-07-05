"""
Auth service — Supabase-backed user store, password hashing, JWT issuance.

Replaces the frontend's earlier hardcoded demo accounts. All access to the
`users` table goes through here using the Supabase service-role key, which
bypasses RLS by design — this module is the only thing allowed to touch it.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import bcrypt
from jose import jwt
from supabase import Client, create_client

from ingestion.config import get_settings

_USERS = "users"


def _client() -> Client:
    cfg = get_settings()
    return create_client(cfg.supabase_url, cfg.supabase_service_key)


# ── Passwords ──────────────────────────────────────────────────────────────────

def hash_password(raw: str) -> str:
    return bcrypt.hashpw(raw.encode(), bcrypt.gensalt()).decode()


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(raw.encode(), hashed.encode())
    except Exception:
        return False


# ── JWT ────────────────────────────────────────────────────────────────────────

def create_access_token(user: dict[str, Any], expires_hours: int = 8) -> str:
    cfg = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub":   user["id"],
        "org":   user["organization_id"],
        "role":  user["role"],
        "email": user["email"],
        "iat":   now,
        "exp":   now + timedelta(hours=expires_hours),
    }
    return jwt.encode(payload, cfg.jwt_secret, algorithm=cfg.jwt_algorithm)


# ── User CRUD ──────────────────────────────────────────────────────────────────

def get_user_by_email(email: str) -> Optional[dict]:
    db     = _client()
    result = db.table(_USERS).select("*").eq("email", email.strip().lower()).maybe_single().execute()
    return result.data if result and result.data else None


def get_user_by_id(user_id: str) -> Optional[dict]:
    db     = _client()
    result = db.table(_USERS).select("*").eq("id", user_id).maybe_single().execute()
    return result.data if result and result.data else None


def list_users(organization_id: str) -> list[dict]:
    db     = _client()
    result = (
        db.table(_USERS)
        .select("*")
        .eq("organization_id", organization_id)
        .order("created_at", desc=True)
        .execute()
    )
    return result.data or []


def create_user(
    organization_id: str,
    email:           str,
    password:        str,
    name:            str,
    role:            str,
    allowed_kb_ids:  list[str],
) -> dict:
    db  = _client()
    row = {
        "id":              str(uuid.uuid4()),
        "organization_id": organization_id,
        "email":           email.strip().lower(),
        "password_hash":   hash_password(password),
        "name":            name,
        "role":            role,
        "allowed_kb_ids":  allowed_kb_ids,
        "is_active":       True,
        "created_at":      datetime.now(timezone.utc).isoformat(),
    }
    result = db.table(_USERS).insert(row).execute()
    return result.data[0]


def update_user(user_id: str, updates: dict[str, Any]) -> Optional[dict]:
    db = _client()
    updates = dict(updates)

    password = updates.pop("password", None)
    if password:
        updates["password_hash"] = hash_password(password)

    if "email" in updates and updates["email"]:
        updates["email"] = updates["email"].strip().lower()

    if not updates:
        return get_user_by_id(user_id)

    result = db.table(_USERS).update(updates).eq("id", user_id).execute()
    return result.data[0] if result.data else None


def touch_last_login(user_id: str) -> None:
    db = _client()
    db.table(_USERS).update(
        {"last_login": datetime.now(timezone.utc).isoformat()}
    ).eq("id", user_id).execute()


def delete_user(user_id: str) -> None:
    db = _client()
    db.table(_USERS).delete().eq("id", user_id).execute()


def to_public(user: dict) -> dict:
    """Strips password_hash before a user record leaves this module."""
    return {k: v for k, v in user.items() if k != "password_hash"}
