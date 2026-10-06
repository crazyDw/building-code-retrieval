interface Props {
  text: string;
  open: boolean;
}

export function ReasoningPanel({ text, open }: Props) {
  if (!text) return null;
  return (
    <details className="reasoning-panel" open={open}>
      <summary>模型推理过程（以下为模型推理过程，非规范内容）</summary>
      <pre>{text}</pre>
    </details>
  );
}
