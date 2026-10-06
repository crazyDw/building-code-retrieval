import type { SectionHint } from "../types";

interface Props {
  hint: SectionHint;
  onViewAll: () => void;
}

export function SectionHintBar({ hint, onViewAll }: Props) {
  return (
    <div className="section-hint">
      该节共 {hint.section_clause_count} 条，当前列出 {hint.listed_count} 条。
      <button type="button" onClick={onViewAll}>
        查看该节全部
      </button>
    </div>
  );
}
