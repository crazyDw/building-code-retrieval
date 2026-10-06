import type { Citation, ClauseListItem, ClausePayload } from "../types";
import { TableView } from "./TableView";

interface Props {
  citations: Citation[];
  clause: ClausePayload | null;
  sectionItems: ClauseListItem[] | null;
  onSelect: (citation: Citation) => void;
  onSelectItem: (clauseId: string) => void;
  onViewSection: () => void;
  onCopy: (clause: ClausePayload) => void;
  copied: boolean;
  onClose: () => void;
}

export function displayPath(citation: Citation): string {
  const parts: string[] = [];
  if (citation.path[0]) {
    parts.push(
      citation.chapter_no != null ? `第${citation.chapter_no}章 ${citation.path[0]}` : citation.path[0],
    );
  }
  if (citation.path[1]) {
    parts.push(citation.section_id ? `${citation.section_id} ${citation.path[1]}` : citation.path[1]);
  }
  parts.push(...citation.path.slice(2));
  if (citation.clause_no) parts.push(citation.clause_no);
  return parts.join(" › ");
}

export function fullPathOf(clause: ClausePayload): string {
  const parts: string[] = [];
  if (clause.path[0]) parts.push(`第${clause.chapter_no}章 ${clause.path[0]}`);
  if (clause.path[1]) parts.push(`${clause.section_id} ${clause.path[1]}`);
  parts.push(...clause.path.slice(2), clause.clause_no);
  return parts.filter(Boolean).join(" › ");
}

export function CitationSidebar({
  citations,
  clause,
  sectionItems,
  onSelect,
  onSelectItem,
  onViewSection,
  onCopy,
  copied,
  onClose,
}: Props) {
  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <strong>引用与条文</strong>
        <button type="button" onClick={onClose}>
          收起
        </button>
      </div>
      <div className="sidebar-section">
        <div className="sidebar-title">本轮检索条款（{citations.length}）</div>
        {citations.map((citation) => (
          <button
            key={citation.clause_id}
            type="button"
            className="citation-card"
            onClick={() => onSelect(citation)}
          >
            <span className="citation-standard">{citation.standard_name || citation.standard_id}</span>
            <span className="citation-path">
              {displayPath(citation)}
              {citation.is_reference ? "（关联参考）" : ""}
              {citation.matched_kuan ? `（命中第 ${citation.matched_kuan} 款）` : ""}
            </span>
          </button>
        ))}
      </div>
      {sectionItems && (
        <div className="sidebar-section">
          <div className="sidebar-title">该节全部条文（{sectionItems.length}）</div>
          <button type="button" className="link-button" onClick={onViewSection}>
            刷新
          </button>
          {sectionItems.map((item) => (
            <button
              key={item.clause_id}
              type="button"
              className="clause-link"
              onClick={() => onSelectItem(item.clause_id)}
            >
              {item.clause_no} {item.text.slice(0, 40)}
            </button>
          ))}
        </div>
      )}
      {clause && (
        <div className="sidebar-section clause-detail">
          <div className="sidebar-title">
            {clause.standard_id} {clause.clause_no}
          </div>
          <div className="clause-path">{fullPathOf(clause)}</div>
          <pre className="clause-text">{clause.text}</pre>
          {clause.tables.map((table) => (
            <TableView
              key={table.table_id}
              table={{ ...table, clause_id: clause.clause_id, highlight_rows: [] }}
            />
          ))}
          <button type="button" onClick={() => onCopy(clause)}>
            {copied ? "已复制" : "复制带出处 Markdown"}
          </button>
        </div>
      )}
    </aside>
  );
}
