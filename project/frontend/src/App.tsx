import { useCallback, useEffect, useRef, useState } from "react";
import { getClause, getClauses, getHealth, searchClause, streamChat } from "./api";
import { AnswerBlocks } from "./components/AnswerBlocks";
import { CitationSidebar, fullPathOf } from "./components/CitationSidebar";
import { ConditionBar } from "./components/ConditionBar";
import { ReasoningPanel } from "./components/ReasoningPanel";
import { SectionHintBar } from "./components/SectionHintBar";
import { StatusBanners } from "./components/StatusBanners";
import { TableView } from "./components/TableView";
import type {
  Citation,
  ClauseListItem,
  ClausePayload,
  DonePayload,
  Health,
  Message,
  ProjectCondition,
} from "./types";

interface SidebarState {
  open: boolean;
  citations: Citation[];
  clause: ClausePayload | null;
  sectionItems: ClauseListItem[] | null;
}

function citationOf(clause: ClausePayload): Citation {
  return {
    clause_id: clause.clause_id,
    clause_no: clause.clause_no,
    standard_id: clause.standard_id,
    standard_name: "",
    path: clause.path,
    chapter_no: clause.chapter_no,
    section_id: clause.section_id,
    matched_kuan: null,
    is_reference: false,
  };
}

function mergeConditions(
  previous: ProjectCondition[],
  incoming: ProjectCondition[],
): ProjectCondition[] {
  const locked = previous.filter((condition) => condition.locked);
  const merged = incoming.map(
    (condition) => locked.find((item) => item.key === condition.key) ?? condition,
  );
  for (const condition of locked) {
    if (!merged.some((item) => item.key === condition.key)) merged.push(condition);
  }
  return merged;
}

export default function App() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [deep, setDeep] = useState(false);
  const [conditions, setConditions] = useState<ProjectCondition[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [lookup, setLookup] = useState("");
  const [lookupResults, setLookupResults] = useState<ClausePayload[] | null>(null);
  const [sidebar, setSidebar] = useState<SidebarState>({
    open: false,
    citations: [],
    clause: null,
    sectionItems: null,
  });
  const referencedRef = useRef<string[]>([]);
  const nextId = useRef(1);

  useEffect(() => {
    void getHealth()
      .then(setHealth)
      .catch(() => setHealth(null));
  }, []);

  const patchMessage = useCallback(
    (id: number, patch: Partial<Message> | ((message: Message) => Partial<Message>)) => {
      setMessages((previous) =>
        previous.map((message) =>
          message.id === id
            ? { ...message, ...(typeof patch === "function" ? patch(message) : patch) }
            : message,
        ),
      );
    },
    [],
  );

  const resolveReferenced = useCallback(async (text: string): Promise<string[]> => {
    const ids = new Set(referencedRef.current);
    const numbers = [...new Set(text.match(/\d+\.\d+\.\d+/g) ?? [])];
    for (const clauseNo of numbers) {
      try {
        const result = await searchClause(clauseNo);
        result.items.forEach((item) => ids.add(item.clause_id));
      } catch {
        // 解析失败不影响本轮提问
      }
    }
    referencedRef.current = [...ids];
    return [...ids];
  }, []);

  const openCitation = useCallback(async (citation: Citation) => {
    if (!referencedRef.current.includes(citation.clause_id)) {
      referencedRef.current = [...referencedRef.current, citation.clause_id];
    }
    setSidebar((previous) => ({ ...previous, open: true, clause: null }));
    try {
      const clause = await getClause(citation.clause_id);
      setSidebar((previous) => ({ ...previous, open: true, clause }));
    } catch {
      // 条文不存在时保持侧栏打开
    }
  }, []);

  const openCitationById = useCallback(
    (clauseId: string) => {
      const known =
        messages
          .flatMap((message) => message.done?.citations ?? [])
          .find((citation) => citation.clause_id === clauseId) ??
        sidebar.citations.find((citation) => citation.clause_id === clauseId);
      const citation: Citation =
        known ?? {
          clause_id: clauseId,
          clause_no: clauseId.slice(clauseId.indexOf("_") + 1),
          standard_id: clauseId.slice(0, clauseId.indexOf("_")),
          standard_name: "",
          path: [],
          chapter_no: null,
          section_id: null,
          matched_kuan: null,
          is_reference: false,
        };
      void openCitation(citation);
    },
    [messages, openCitation, sidebar.citations],
  );

  const viewSection = useCallback(
    async (done: DonePayload) => {
      const hint = done.section_hint;
      const citation = done.citations[0];
      if (!hint || !citation) return;
      try {
        const result = await getClauses(citation.standard_id, hint.section_id);
        setSidebar((previous) => ({
          ...previous,
          open: true,
          sectionItems: result.items,
          clause: null,
        }));
      } catch {
        // 忽略网络错误
      }
    },
    [],
  );

  const copyClause = useCallback(async (clause: ClausePayload) => {
    const path = fullPathOf(clause);
    const text = `> 依据：${clause.standard_id} ${clause.clause_no}（${path}）\n> ${clause.text}`;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      window.prompt("复制以下引用文本：", text);
    }
  }, []);

  const send = useCallback(async () => {
    const text = input.trim();
    if (!text || busy) return;
    setBusy(true);
    setInput("");
    setLookupResults(null);
    const userMessage: Message = {
      id: nextId.current++,
      role: "user",
      text,
      derivation: "",
      original: "",
      reasoning: "",
      streaming: false,
      deep,
    };
    const assistantId = nextId.current++;
    setMessages((previous) => [
      ...previous,
      userMessage,
      {
        id: assistantId,
        role: "assistant",
        text: "",
        derivation: "",
        original: "",
        reasoning: "",
        streaming: true,
        deep,
      },
    ]);
    const referenced = await resolveReferenced(text);
    let completed = false;
    try {
      for await (const streamEvent of streamChat({
        message: text,
        deep_analysis: deep,
        project_conditions: conditions,
        referenced_clause_ids: referenced,
      })) {
        const data = streamEvent.data;
        if (streamEvent.event === "meta") {
          const metaConditions = data.project_conditions as ProjectCondition[] | undefined;
          if (metaConditions?.length) {
            setConditions((previous) => mergeConditions(previous, metaConditions));
          }
        } else if (streamEvent.event === "reasoning") {
          patchMessage(assistantId, (message) => ({
            reasoning: message.reasoning + String(data.delta ?? ""),
          }));
        } else if (streamEvent.event === "answer") {
          const block = String(data.block ?? "derivation");
          const delta = String(data.delta ?? "");
          patchMessage(assistantId, (message) =>
            block === "original"
              ? { original: message.original + delta }
              : { derivation: message.derivation + delta },
          );
        } else if (streamEvent.event === "reset") {
          patchMessage(assistantId, { derivation: "" });
        } else if (streamEvent.event === "error") {
          patchMessage(assistantId, {
            error: `${String(data.code ?? "error")}: ${String(data.message ?? "")}`,
          });
        } else if (streamEvent.event === "done") {
          const done = data as unknown as DonePayload;
          completed = true;
          patchMessage(assistantId, { done, streaming: false });
          setConditions((previous) => mergeConditions(previous, done.project_conditions));
          setSidebar((previous) => ({ ...previous, citations: done.citations }));
        }
      }
    } catch (error) {
      patchMessage(assistantId, {
        error: error instanceof Error ? error.message : String(error),
      });
    } finally {
      patchMessage(assistantId, (message) =>
        message.streaming
          ? { streaming: false, error: message.error ?? (completed ? undefined : "连接中断，未收到完成事件") }
          : {},
      );
      setBusy(false);
    }
  }, [busy, conditions, deep, input, patchMessage, resolveReferenced]);

  const runLookup = useCallback(async () => {
    const query = lookup.trim();
    if (!query) return;
    try {
      const result = await searchClause(query);
      setLookupResults(result.items);
      if (result.items.length === 1) {
        const clause = result.items[0];
        setSidebar((previous) => ({
          ...previous,
          open: true,
          citations: previous.citations.length
            ? previous.citations
            : [citationOf(clause)],
          clause,
        }));
      } else if (result.items.length > 1) {
        setSidebar((previous) => ({
          ...previous,
          open: true,
          citations: result.items.map(citationOf),
        }));
      }
    } catch {
      setLookupResults([]);
    }
  }, [lookup]);

  const selectSectionItem = useCallback(async (clauseId: string) => {
    try {
      const clause = await getClause(clauseId);
      setSidebar((previous) => ({ ...previous, open: true, clause }));
    } catch {
      // 忽略
    }
  }, []);

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <strong>建筑规范检索助手</strong>
          <span className="subtitle">只依据条文作答 · 允许条件性推导 · 禁止合规结论</span>
        </div>
        <div className="topbar-right">
          {health && (
            <span className={`health-badge ${health.ready ? "ok" : "bad"}`}>
              {health.ready ? "服务就绪" : "未就绪"} · {health.device}
              {health.dev_mode ? " · DEV" : ""}
            </span>
          )}
          <span className="lookup">
            <input
              value={lookup}
              onChange={(event) => setLookup(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") void runLookup();
              }}
              placeholder="条款号直查，如 5.3.9"
            />
            <button type="button" onClick={() => void runLookup()}>
              查询
            </button>
          </span>
        </div>
      </header>

      <StatusBanners health={health} />

      {lookupResults && lookupResults.length > 1 && (
        <div className="lookup-candidates">
          跨标准重号，请选择：
          {lookupResults.map((item) => (
            <button key={item.clause_id} type="button" onClick={() => void openCitation(citationOf(item))}>
              {item.standard_id} {item.clause_no}
            </button>
          ))}
        </div>
      )}

      <div className="layout">
        <main className="chat">
          <div className="messages">
            {messages.map((message) => (
              <div key={message.id} className={`message message-${message.role}`}>
                {message.role === "user" ? (
                  <div className="user-bubble">{message.text}</div>
                ) : (
                  <div className="assistant-card">
                    <ReasoningPanel
                      text={message.reasoning}
                      open={message.streaming && message.deep}
                    />
                    <AnswerBlocks
                      derivation={message.derivation}
                      original={message.original}
                      onCitation={openCitationById}
                    />
                    {message.done?.tables.map((table) => (
                      <TableView key={`${table.table_id}-${table.clause_id}`} table={table} />
                    ))}
                    {message.done?.section_hint && (
                      <SectionHintBar
                        hint={message.done.section_hint}
                        onViewAll={() => void viewSection(message.done as DonePayload)}
                      />
                    )}
                    <StatusBanners
                      done={message.done}
                      error={message.error}
                      streaming={message.streaming}
                    />
                  </div>
                )}
              </div>
            ))}
            {!messages.length && (
              <div className="empty-hint">
                描述设计场景（如“6 层住宅，层高 3.0m，楼梯踏步宽度怎么定？”），
                或直接输入条款号（如“5.3.9”）。
              </div>
            )}
          </div>

          <div className="composer">
            <ConditionBar conditions={conditions} onChange={setConditions} />
            <div className="composer-row">
              <label className="deep-toggle">
                <input
                  type="checkbox"
                  checked={deep}
                  onChange={(event) => setDeep(event.target.checked)}
                />
                深度分析
              </label>
              <textarea
                value={input}
                onChange={(event) => setInput(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    void send();
                  }
                }}
                placeholder="Enter 发送，Shift+Enter 换行"
                rows={3}
              />
              <button type="button" onClick={() => void send()} disabled={busy || !input.trim()}>
                {busy ? "生成中…" : "发送"}
              </button>
            </div>
          </div>
        </main>

        {sidebar.open && (
          <CitationSidebar
            citations={sidebar.citations}
            clause={sidebar.clause}
            sectionItems={sidebar.sectionItems}
            copied={copied}
            onSelect={(citation) => void openCitation(citation)}
            onSelectItem={(clauseId) => void selectSectionItem(clauseId)}
            onViewSection={() => {
              const lastDone = [...messages].reverse().find((message) => message.done)?.done;
              if (lastDone) void viewSection(lastDone);
            }}
            onCopy={(clause) => void copyClause(clause)}
            onClose={() => setSidebar((previous) => ({ ...previous, open: false }))}
          />
        )}
      </div>
    </div>
  );
}
