import type { ProjectCondition } from "../types";

interface Props {
  conditions: ProjectCondition[];
  onChange: (conditions: ProjectCondition[]) => void;
}

export function ConditionBar({ conditions, onChange }: Props) {
  if (!conditions.length) return null;
  return (
    <div className="condition-bar">
      <span className="condition-title">项目条件</span>
      {conditions.map((condition, index) => (
        <span key={condition.key} className={`condition-item${condition.locked ? " locked" : ""}`}>
          <span className="condition-label">{condition.label}</span>
          <input
            value={condition.value}
            onChange={(event) => {
              const next = [...conditions];
              next[index] = { ...condition, value: event.target.value, locked: true };
              onChange(next);
            }}
          />
          <label className="condition-lock">
            <input
              type="checkbox"
              checked={condition.locked}
              onChange={(event) => {
                const next = [...conditions];
                next[index] = { ...condition, locked: event.target.checked };
                onChange(next);
              }}
            />
            锁定
          </label>
        </span>
      ))}
    </div>
  );
}
