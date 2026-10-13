// 迁移自 claudecodeui src/components/chat/utils/chatFormatting.ts（取渲染所需子集）
// 注：normalizeInlineCodeFences / formatUsageLimitText 中的 try/catch 与恒真判断无实际触发路径（replace 配合法正则不抛、parseInt 入参已被 \d{10,13} 限定），保留系为对齐上游 diff。

// thinking 折叠头文案（add-run-record-readability 3.1）：「已思考 N 秒 · <预览>」。
// 时长缺失/非正数回退「已思考数秒」（含下一事件缺失、时间戳缺失、负值差场景）；
// 预览缺失只出时长段。
export function formatThinkingLabel(
  staticDuration?: number | null,
  preview?: string,
): string {
  const durationPart =
    typeof staticDuration === 'number' && Number.isFinite(staticDuration) && staticDuration > 0
      ? `已思考 ${Math.round(staticDuration)} 秒`
      : '已思考数秒';
  const trimmed = (preview || '').trim();
  return trimmed ? `${durationPart} · ${trimmed}` : durationPart;
}

export function normalizeInlineCodeFences(text: string) {
  if (!text || typeof text !== 'string') return text;
  // [fenix-ignore:17ccbc5089fe] 本处 try/catch 与 formatUsageLimitText 的恒真判断均为对齐上游 claudecodeui diff 的有意保留（见文件头注释），无可触发路径
  try {
    return text.replace(/```[ \t]*([^\n\r]+?)[ \t]*```/g, '`$1`');
  } catch {
    return text;
  }
}

export function formatUsageLimitText(text: string) {
  try {
    if (typeof text !== 'string') return text;
    return text.replace(/Claude AI usage limit reached\|(\d{10,13})/g, (match, ts) => {
      let timestampMs = parseInt(ts, 10);
      if (!Number.isFinite(timestampMs)) return match;
      if (timestampMs < 1e12) timestampMs *= 1000;
      const reset = new Date(timestampMs);

      const timeStr = new Intl.DateTimeFormat(undefined, {
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
      }).format(reset);

      const offsetMinutesLocal = -reset.getTimezoneOffset();
      const sign = offsetMinutesLocal >= 0 ? '+' : '-';
      const abs = Math.abs(offsetMinutesLocal);
      const offH = Math.floor(abs / 60);
      const offM = abs % 60;
      const gmt = `GMT${sign}${offH}${offM ? ':' + String(offM).padStart(2, '0') : ''}`;
      const tzId = Intl.DateTimeFormat().resolvedOptions().timeZone || '';
      const cityRaw = tzId.split('/').pop() || '';
      const city = cityRaw
        .replace(/_/g, ' ')
        .toLowerCase()
        .replace(/\b\w/g, (char) => char.toUpperCase());
      const tzHuman = city ? `${gmt} (${city})` : gmt;

      // 日期改中文年月日（code-review item 00af222d4b2c）：不再用硬编码英文月份缩写
      const dateReadable = `${reset.getFullYear()} 年 ${reset.getMonth() + 1} 月 ${reset.getDate()} 日`;

      // 文案中文化（code-review item 00af222d4b2c）：与同文件 formatThinkingLabel 的
      // 中文口径一致；上方触发正则仍匹配上游英文原文（该文本由上游产生，本控件不改写）
      return `Claude 用量已达上限，将于 **${timeStr} ${tzHuman}**（${dateReadable}）重置`;
    });
  } catch {
    return text;
  }
}
