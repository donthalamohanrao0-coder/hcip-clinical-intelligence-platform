"""
One-off script: create the first real admin user in Supabase.

Run from the project root (needs the venv that has `supabase`/`bcrypt`
installed, and a working .env with SUPABASE_URL / SUPABASE_SERVICE_KEY):

    python create_admin_user.py <email> [name]

Requires supabase/migrations/002_users.sql to have been applied first.
"""

from __future__ import annotations

import secrets
import string
import sys

from api.services import auth_service

ALL_KB_IDS = [
    "kb-clinical-2024",
    "kb-pharmacology",
    "kb-cardiology",
    "kb-oncology",
    "kb-emergency",
]


def generate_password(length: int = 16) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python create_admin_user.py <email> [name]")
        sys.exit(1)

    email = sys.argv[1].strip().lower()
    name  = sys.argv[2] if len(sys.argv) > 2 else email.split("@")[0].replace(".", " ").title()

    if auth_service.get_user_by_email(email):
        print(f"A user with email {email} already exists — nothing to do.")
        sys.exit(1)

    password = generate_password()
    user = auth_service.create_user(
        organization_id = "org-dev",
        email           = email,
        password        = password,
        name            = name,
        role            = "admin",
        allowed_kb_ids  = ALL_KB_IDS,
    )

    print("Admin user created.")
    print(f"  Email:    {user['email']}")
    print(f"  Password: {password}")
    print("Save this password now — it will not be shown again.")


if __name__ == "__main__":
    main()
