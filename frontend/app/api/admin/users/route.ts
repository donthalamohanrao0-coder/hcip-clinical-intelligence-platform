// GET: list all users  POST: create user
// Admin-only — forwards the caller's JWT so the backend's require_admin
// dependency can verify the role itself; this proxy makes no trust decisions.
import { NextRequest, NextResponse } from 'next/server';

const API_URL = process.env.HCIP_API_URL || 'http://localhost:8000';

export async function GET(req: NextRequest) {
  const token = req.headers.get('x-api-token') || '';

  try {
    const resp = await fetch(`${API_URL}/api/v1/admin/users`, {
      headers: { Authorization: `Bearer ${token}` },
      signal:  AbortSignal.timeout(10000),
    });
    const data = await resp.json();
    return NextResponse.json(data, { status: resp.status });
  } catch (err) {
    return NextResponse.json(
      { success: false, error: 'Backend unreachable', detail: String(err) },
      { status: 502 },
    );
  }
}

export async function POST(req: NextRequest) {
  const token = req.headers.get('x-api-token') || '';
  const body  = await req.json();

  try {
    const resp = await fetch(`${API_URL}/api/v1/admin/users`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body:    JSON.stringify(body),
      signal:  AbortSignal.timeout(10000),
    });
    const data = await resp.json();
    return NextResponse.json(data, { status: resp.status });
  } catch (err) {
    return NextResponse.json(
      { success: false, error: 'Backend unreachable', detail: String(err) },
      { status: 502 },
    );
  }
}
