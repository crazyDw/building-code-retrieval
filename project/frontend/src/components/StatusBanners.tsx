import type { DonePayload, Health } from "../types";

interface Props {
  health?: Health | null;
  done?: DonePayload;
  error?: string;
  streaming?: boolean;
}

export function StatusBanners({ health, done, error, streaming }: Props) {
  const banners: { tone: string; text: string }[] = [];
  if (health?.dev_mode) {
    banners.push({ tone: "warn", text: "开发模式（DEV_MODE）：跳过模型与预热，结果不得作为检索质量依据。" });
  }
  if (health && !health.ready) {
    banners.push({ tone: "error", text: `服务未就绪（${health.reason_code ?? "not_ready"}）。` });
  }
  if (error) banners.push({ tone: "error", text: `本轮中断：${error}` });
  if (streaming) banners.push({ tone: "info", text: "正在生成…" });
  if (done?.fallback_flag) {
    banners.push({ tone: "warn", text: "当前未提供归纳解读：以下为检索到的条文原文与适用范围。" });
  }
  if (done?.not_found) {
    banners.push({ tone: "error", text: "未检索到直接依据，已列出最接近的条款。" });
  }
  if (done?.degraded_flag) {
    banners.push({
      tone: "warn",
      text: `检索降级（${done.degraded_reason ?? "unknown"}）：未使用重排，结果为 RRF 排序。`,
    });
  }
  if (done?.broad) {
    banners.push({ tone: "info", text: "这是宽泛问题：这不是完整清单，请补充具体条件。" });
  }
  if (done?.superseded_notice) {
    banners.push({ tone: "warn", text: done.superseded_notice });
  }
  if (!banners.length) return null;
  return (
    <div className="banners">
      {banners.map((banner, index) => (
        <div key={index} className={`banner banner-${banner.tone}`}>
          {banner.text}
        </div>
      ))}
    </div>
  );
}
