/**
 * Next.js proxy route: POST /api/query
 *
 * Forwards the clinical query to the FastAPI backend with the server-side
 * API key. The key never reaches the browser.
 */

import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.HCIP_API_URL ?? "http://localhost:8000";
const API_KEY     = process.env.HCIP_API_KEY  ?? "";

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();

    const upstream = await fetch(`${BACKEND_URL}/api/v1/query`, {
      method:  "POST",
      headers: {
        "Content-Type": "application/json",
        "X-API-Key":    API_KEY,
        "X-Request-ID": request.headers.get("x-request-id") ?? crypto.randomUUID(),
      },
      body: JSON.stringify(body),
      // Generous timeout for full-pipeline queries (cold start can take ~3s)
      signal: AbortSignal.timeout(30_000),
    });

    const data = await upstream.json();
    return NextResponse.json(data, { status: upstream.status });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Proxy error";
    return NextResponse.json(
      { success: false, error: "Backend unreachable", detail: message },
      { status: 502 },
    );
  }
}
