/**
 * Next.js proxy route: POST /api/query/stream
 *
 * Forwards the clinical query to the FastAPI backend's SSE endpoint and
 * pipes the response body straight through to the browser. The API key
 * never reaches the browser — same trust boundary as /api/query.
 */

import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";

const BACKEND_URL = process.env.HCIP_API_URL ?? "http://localhost:8000";
const API_KEY     = process.env.HCIP_API_KEY  ?? "";

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();

    const upstream = await fetch(`${BACKEND_URL}/api/v1/query/stream`, {
      method:  "POST",
      headers: {
        "Content-Type": "application/json",
        "X-API-Key":    API_KEY,
        "X-Request-ID": request.headers.get("x-request-id") ?? crypto.randomUUID(),
      },
      body: JSON.stringify(body),
    });

    if (!upstream.ok || !upstream.body) {
      const detail = await upstream.text().catch(() => "");
      return NextResponse.json(
        { success: false, error: "Backend unreachable", detail },
        { status: upstream.status || 502 },
      );
    }

    return new Response(upstream.body, {
      status:  200,
      headers: {
        "Content-Type":      "text/event-stream",
        "Cache-Control":     "no-cache",
        "Connection":        "keep-alive",
        "X-Accel-Buffering": "no",
      },
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Proxy error";
    return NextResponse.json(
      { success: false, error: "Backend unreachable", detail: message },
      { status: 502 },
    );
  }
}
