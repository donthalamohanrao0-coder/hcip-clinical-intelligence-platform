import { NextRequest, NextResponse } from "next/server";

const API_URL = process.env.HCIP_API_URL ?? "http://localhost:8000";
const API_KEY = process.env.HCIP_API_KEY ?? "";

export async function POST(req: NextRequest) {
  try {
    const formData = await req.formData();
    const file = formData.get("file") as File | null;
    const knowledge_base_id = (formData.get("knowledge_base_id") as string) ?? "kb-clinical-2024";

    if (!file) {
      return NextResponse.json({ success: false, error: "No file provided" }, { status: 400 });
    }

    // Forward to FastAPI
    const upstream = new FormData();
    upstream.append("file", file, file.name);
    upstream.append("knowledge_base_id", knowledge_base_id);

    const res = await fetch(`${API_URL}/api/v1/ingest/upload`, {
      method: "POST",
      headers: { "X-API-Key": API_KEY },
      body: upstream,
    });

    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    return NextResponse.json(
      { success: false, error: "Upload failed", detail: String(err) },
      { status: 500 },
    );
  }
}
