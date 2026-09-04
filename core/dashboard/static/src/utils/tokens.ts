// Token 展示格式化（spec 详情页「项目信息」卡片使用）。
// 口径：tokens_in 已含缓存写入+命中（分项 cache 入 input，与 STATE 累计一致）。

export const fmtMillions = (tokens: number) => {
  const m = (tokens || 0) / 1e6;
  return m >= 1000 ? (m / 1000).toFixed(2) + 'G' : m.toFixed(1) + 'M';
};

// 输入 Token 展示：主数值为缓存未命中量（tokens_in − cache_read，含缓存写入与
// 未入缓存部分）；括号内保留缓存命中与命中率，命中率分母仍为含缓存的输入总量
// （口径与 STATE 累计一致）。分项为 null（历史 spec 未记录）时不显示括号，避免伪 0%
export interface TokenUsageLike {
  tokens_in: number;
  cache_read_input_tokens?: number | null;
}

export const fmtInputTokens = (usage: TokenUsageLike) => {
  const cacheRead = usage.cache_read_input_tokens;
  if (cacheRead == null || !usage.tokens_in) return fmtMillions(usage.tokens_in);
  const pct = ((cacheRead / usage.tokens_in) * 100).toFixed(1);
  return `${fmtMillions(usage.tokens_in - cacheRead)}（缓存命中 ${fmtMillions(cacheRead)}，命中率 ${pct}%）`;
};
