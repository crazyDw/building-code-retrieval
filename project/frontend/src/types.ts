export interface ProjectCondition {
  key: string;
  label: string;
  value: string;
  locked: boolean;
}

export interface Citation {
  clause_id: string;
  clause_no: string;
  standard_id: string;
  standard_name: string;
  path: string[];
  chapter_no: number | null;
  section_id: string | null;
  matched_kuan: number | null;
  is_reference: boolean;
}

export interface TablePayload {
  table_id: string;
  caption: string;
  notes: string[];
  rows: string[][];
  clause_id: string;
  highlight_rows: number[];
  source_line: number;
}

export interface SectionHint {
  section_id: string;
  section_clause_count: number;
  listed_count: number;
}

export interface DonePayload {
  citations: Citation[];
  tables: TablePayload[];
  section_hint: SectionHint | null;
  fallback_flag: boolean;
  degraded_flag: boolean;
  degraded_reason: string | null;
  rerank_used: boolean;
  not_found: boolean;
  broad: boolean;
  superseded_notice: string | null;
  project_conditions: ProjectCondition[];
  numbers: string[];
  mode: string;
  dev_mode: boolean;
  attempts: number;
  timings: Record<string, number>;
}

export interface MetaPayload {
  mode: string;
  dev_mode: boolean;
  not_found: boolean;
  broad: boolean;
  rerank_used: boolean;
  degraded_flag: boolean;
  degraded_reason: string | null;
  numbers: string[];
  project_conditions?: ProjectCondition[];
}

export interface Health {
  ready: boolean;
  warmup_done: boolean;
  device: string;
  gpu_available: boolean;
  rerank_enabled: boolean;
  milvus_connected: boolean;
  dev_mode: boolean;
  version: string;
  status: string;
  reason_code: string | null;
}

export interface KuanItem {
  item_no: number;
  text: string;
}

export interface Kuan {
  kuan_no: number;
  text: string;
  items: KuanItem[];
}

export interface ClauseTable {
  table_id: string;
  caption: string;
  notes: string[];
  rows: string[][];
  source_line: number;
}

export interface ClausePayload {
  clause_id: string;
  clause_no: string;
  standard_id: string;
  section_id: string;
  chapter_no: number;
  path: string[];
  text: string;
  intro: string;
  kuans: Kuan[];
  has_table: boolean;
  source_line: number;
  tables: ClauseTable[];
}

export interface ClauseListItem {
  clause_id: string;
  clause_no: string;
  text: string;
  has_table: boolean;
}

export interface Message {
  id: number;
  role: "user" | "assistant";
  text: string;
  derivation: string;
  original: string;
  reasoning: string;
  done?: DonePayload;
  error?: string;
  streaming: boolean;
  deep: boolean;
  closedByServer?: boolean;
}

export interface StreamEvent {
  event: string;
  data: Record<string, unknown>;
}
