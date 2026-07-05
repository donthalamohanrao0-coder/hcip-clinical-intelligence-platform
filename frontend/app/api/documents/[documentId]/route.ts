import { NextRequest, NextResponse } from "next/server";

const API_URL = process.env.HCIP_API_URL ?? "http://localhost:8000";
const API_KEY = process.env.HCIP_API_KEY ?? "";

export async function DELETE(
  _req: NextRequest,
  { params }: { params: { documentId: string } },
) {
  try {
    const res = await fetch(
      `${API_URL}/api/v1/ingest/documents/${params.documentId}`,
      { method: "DELETE", headers: { "X-API-Key": API_KEY } },
    );
    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    return NextResponse.json(
      { success: false, error: "Delete failed", detail: String(err) },
      { status: 500 },
    );
  }
}
