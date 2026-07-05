// POST /api/auth/login { email, password }
// Calls FastAPI POST /api/v1/auth/login
// Returns { user: User, token: string }
import { NextRequest, NextResponse } from 'next/server';

const API_URL = process.env.HCIP_API_URL || 'http://localhost:8000';

export async function POST(req: NextRequest) {
  const body = await req.json();

  try {
    const resp = await fetch(`${API_URL}/api/v1/auth/login`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(body),
      signal:  AbortSignal.timeout(10000),
    });
    const data = await resp.json();
    if (!resp.ok) {
      return NextResponse.json(
        { error: data.detail || 'Invalid credentials' },
        { status: resp.status },
      );
    }
    return NextResponse.json(data);
  } catch {
    return NextResponse.json(
      { error: 'Invalid email or password' },
      { status: 401 },
    );
  }
}
