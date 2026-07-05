/**
 * HCIP API client — browser-side.
 *
 * All clinical query requests are proxied through Next.js API routes
 * (/api/query) so the backend API key never reaches the browser.
 */

import type { APIResponse, Citation, ErrorResponse, QueryResult, SafetyFlag } from "./types";

export class HCIPApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public detail?: string,
  ) {
    super(message);
    this.name = "HCIPApiError";
  }
}

async function handleResponse<T>(res: Response): Promise<T> {
  const json = await res.json();
  if (!res.ok || json.success === false) {
    const err = json as ErrorResponse;
    throw new HCIPApiError(err.error ?? "Request failed", res.status, err.detail);
  }
  return (json as APIResponse<T>).data;
}

export async function submitQuery(params: {
  query:              string;
  knowledge_base_id:  string;
  organization_id?:   string;
  token?:             string;
}): Promise<QueryResult> {
  const { token, ...body } = params;

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };

  if (token) {
    headers["X-API-Token"] = token;
  }

  const res = await fetch("/api/query", {
    method:  "POST",
    headers,
    body:    JSON.stringify(body),
  });
  return handleResponse<QueryResult>(res);
}

export async function fetchReadiness(): Promise<{
  status: string;
  checks: Record<string, string>;
}> {
  const res = await fetch("/api/health");
  return res.json();
}

// ─── Streaming query (SSE) ─────────────────────────────────────────────────

export type QueryMeta = Omit<QueryResult, "final_response" | "query_text">;

export type StreamEvent =
  | { type: "stage"; stage: string; label: string }
  | { type: "token"; text: string }
  | ({ type: "meta" } & QueryMeta)
  | { type: "error"; message: string }
  | { type: "done" };

/**
 * Streams a clinical query via SSE, invoking `onEvent` for every event as it
 * arrives (stage progress, individual answer tokens, final metadata, or an
 * error) so the caller can render the answer as it's generated.
 *
 * Throws HCIPApiError if the initial request itself fails (auth, network,
 * backend down) — mid-stream failures instead surface as a `type: "error"`
 * event so partially-streamed text isn't silently discarded.
 */
export async function streamQuery(
  params: {
    query:              string;
    knowledge_base_id:  string;
    organization_id?:   string;
    token?:             string;
  },
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const { token, ...body } = params;

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (token) {
    headers["X-API-Token"] = token;
  }

  const res = await fetch("/api/query/stream", {
    method:  "POST",
    headers,
    body:    JSON.stringify(body),
    signal,
  });

  if (!res.ok || !res.body) {
    const json = await res.json().catch(() => ({}) as Partial<ErrorResponse>);
    throw new HCIPApiError(json.error ?? "Request failed", res.status, json.detail);
  }

  const reader  = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer    = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let sepIndex: number;
    while ((sepIndex = buffer.indexOf("\n\n")) !== -1) {
      const rawEvent = buffer.slice(0, sepIndex);
      buffer = buffer.slice(sepIndex + 2);

      const dataLine = rawEvent
        .split("\n")
        .find((line) => line.startsWith("data:"));
      if (!dataLine) continue;

      const jsonStr = dataLine.slice(5).trim();
      if (!jsonStr) continue;

      try {
        onEvent(JSON.parse(jsonStr) as StreamEvent);
      } catch {
        // Malformed chunk — skip it rather than aborting the whole stream.
      }
    }
  }
}

// Re-exported so callers building a QueryResult from streamed events (for
// history persistence, etc.) don't need a separate import.
export type { Citation, SafetyFlag };
