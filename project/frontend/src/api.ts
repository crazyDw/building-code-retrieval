import type {
  ClauseListItem,
  ClausePayload,
  Health,
  ProjectCondition,
  StreamEvent,
} from "./types";

export interface ChatRequest {
  message: string;
  deep_analysis: boolean;
  project_conditions: ProjectCondition[];
  referenced_clause_ids: string[];
}

async function getJson<T>(url: string): Promise<T> {
  const response = await fetch(url);
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new Error(detail?.detail?.code ?? `HTTP ${response.status}`);
  }
  return (await response.json()) as T;
}

export function getHealth(): Promise<Health> {
  return getJson<Health>("/api/health");
}

export function getClause(clauseId: string): Promise<ClausePayload> {
  return getJson<ClausePayload>(`/api/clause/${encodeURIComponent(clauseId)}`);
}

export function searchClause(
  clauseNo: string,
  standardId?: string,
): Promise<{ count: number; items: ClausePayload[] }> {
  const params = new URLSearchParams({ clause_no: clauseNo });
  if (standardId) params.set("standard_id", standardId);
  return getJson(`/api/search?${params.toString()}`);
}

export function getClauses(
  standardId: string,
  sectionNo: string,
): Promise<{ count: number; items: ClauseListItem[] }> {
  const params = new URLSearchParams({
    standard_id: standardId,
    section_no: sectionNo,
  });
  return getJson(`/api/clauses?${params.toString()}`);
}

function parseEventChunk(chunk: string): StreamEvent | null {
  let event = "message";
  const dataLines: string[] = [];
  for (const rawLine of chunk.split("\n")) {
    const line = rawLine.trimEnd();
    if (line.startsWith("event: ")) event = line.slice(7);
    else if (line.startsWith("data: ")) dataLines.push(line.slice(6));
  }
  if (!dataLines.length) return null;
  try {
    return { event, data: JSON.parse(dataLines.join("\n")) };
  } catch {
    return null;
  }
}

/** SSE 客户端：按空行切分事件，缓冲区保证被拆包的标记也能拼回。 */
export async function* streamChat(
  payload: ChatRequest,
  signal?: AbortSignal,
): AsyncGenerator<StreamEvent> {
  const response = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal,
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new Error(detail?.detail?.code ?? `HTTP ${response.status}`);
  }
  if (!response.body) throw new Error("no_stream");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let index = buffer.indexOf("\n\n");
    while (index >= 0) {
      const chunk = buffer.slice(0, index);
      buffer = buffer.slice(index + 2);
      const event = parseEventChunk(chunk);
      if (event) yield event;
      index = buffer.indexOf("\n\n");
    }
  }
  buffer += decoder.decode();
  const tail = parseEventChunk(buffer);
  if (tail) yield tail;
}
