import { NextRequest, NextResponse } from 'next/server';

const API_URL = process.env.HCIP_API_URL || 'http://localhost:8000';

export async function PATCH(
  req: NextRequest,
  { params }: { params: { userId: string } },
) {
  const token = req.headers.get('x-api-token') || '';
  const body  = await req.json();

  try {
    const resp = await fetch(`${API_URL}/api/v1/admin/users/${params.userId}`, {
      method:  'PATCH',
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

export async function DELETE(
  req: NextRequest,
  { params }: { params: { userId: string } },
) {
  const token = req.headers.get('x-api-token') || '';

  try {
    const resp = await fetch(`${API_URL}/api/v1/admin/users/${params.userId}`, {
      method:  'DELETE',
      headers: { Authorization: `Bearer ${token}` },
      signal:  AbortSignal.timeout(10000),
    });
    if (resp.status === 204) return new NextResponse(null, { status: 204 });
    const data = await resp.json();
    return NextResponse.json(data, { status: resp.status });
  } catch (err) {
    return NextResponse.json(
      { success: false, error: 'Backend unreachable', detail: String(err) },
      { status: 502 },
    );
  }
}
