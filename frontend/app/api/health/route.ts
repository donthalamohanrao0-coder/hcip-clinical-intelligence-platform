/**
 * Next.js proxy route: GET /api/health
 * Proxies the readiness check to the FastAPI backend.
 */

import { NextResponse } from "next/server";

const BACKEND_URL = process.env.HCIP_API_URL ?? "http://localhost:8000";
const API_KEY     = process.env.HCIP_API_KEY  ?? "";

export async function GET() {
  try {
    const upstream = await fetch(`${BACKEND_URL}/health/ready`, {
      headers: { "X-API-Key": API_KEY },
      signal:  AbortSignal.timeout(5_000),
    });
    const data = await upstream.json();
    return NextResponse.json(data, { status: upstream.status });
  } catch {
    return NextResponse.json(
      { status: "degraded", checks: { backend: "error: unreachable" } },
      { status: 503 },
    );
  }
}
