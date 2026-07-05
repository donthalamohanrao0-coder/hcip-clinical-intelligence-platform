-- HCIP — real user accounts (replaces the frontend's hardcoded demo logins)

create table if not exists users (
    id                uuid primary key default gen_random_uuid(),
    organization_id   text not null,
    email             text not null unique,
    password_hash     text not null,
    name              text not null,
    role              text not null default 'physician',
    allowed_kb_ids    text[] not null default '{}',
    is_active         boolean not null default true,
    created_at        timestamptz not null default now(),
    last_login        timestamptz
);

create index if not exists idx_users_organization_id on users (organization_id);
create index if not exists idx_users_email on users (email);

alter table users enable row level security;

-- All access goes through the FastAPI backend using the Supabase service-role
-- key, which bypasses RLS by design. No public/anon policies are defined —
-- this table is never queried directly from the browser.
