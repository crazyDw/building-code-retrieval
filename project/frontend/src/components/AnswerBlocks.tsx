import type { ReactNode } from "react";

interface Props {
  derivation: string;
  original: string;
  onCitation: (clauseId: string) => void;
}

const CITATION_RE = /\[\[clause:([^\]]+)\]\]/g;

function renderInline(text: string, onCitation: (id: string) => void): ReactNode[] {
  const nodes: ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  CITATION_RE.lastIndex = 0;
  while ((match = CITATION_RE.exec(text)) !== null) {
    if (match.index > lastIndex) nodes.push(text.slice(lastIndex, match.index));
    const clauseId = match[1];
    nodes.push(
      <button
        key={`${clauseId}-${match.index}`}
        type="button"
        className="citation-chip"
        onClick={() => onCitation(clauseId)}
        title={clauseId}
      >
        {clauseId}
      </button>,
    );
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < text.length) nodes.push(text.slice(lastIndex));
  return nodes;
}

function renderRich(text: string, onCitation: (id: string) => void): ReactNode {
  const lines = text.split("\n");
  const blocks: ReactNode[] = [];
  let bullets: string[] = [];
  const flush = (key: string) => {
    if (bullets.length) {
      blocks.push(
        <ul key={key}>
          {bullets.map((item, index) => (
            <li key={index}>{renderInline(item, onCitation)}</li>
          ))}
        </ul>,
      );
      bullets = [];
    }
  };
  lines.forEach((line, index) => {
    const trimmed = line.trim();
    if (trimmed.startsWith("- ")) {
      bullets.push(trimmed.slice(2));
      return;
    }
    flush(`list-${index}`);
    if (trimmed) blocks.push(<p key={index}>{renderInline(line, onCitation)}</p>);
  });
  flush("list-end");
  return blocks;
}

export function AnswerBlocks({ derivation, original, onCitation }: Props) {
  return (
    <div className="answer-blocks">
      {derivation && (
        <section className="block block-derivation">
          <h4>条件性推导</h4>
          <div className="block-body">{renderRich(derivation, onCitation)}</div>
        </section>
      )}
      {original && (
        <section className="block block-original">
          <h4>条文原文与适用范围</h4>
          <div className="block-body">{renderRich(original, onCitation)}</div>
        </section>
      )}
    </div>
  );
}
