<!-- knowledge: capability=error-attribution-denoise rev=1 sources=spec/archive/2026-09-13-fix-provider-transient-backoff -->

# 错误归因降噪

run 终态 error 消息拼装时的 CLI 诊断噪音过滤：让死因字段不再被与死因无关的 stderr 诊断行误标。

## 现行规则

- runner 在进程非零退出拼装 error 消息（取 stderr 末 5 行拼接）时，先过滤匹配 `^\[claude-code:` 的 stderr 诊断噪音行；过滤后无剩余内容时回退 `Exit code: {returncode}` 形态（returncode 为实际退出码）。
- run 产物 jsonl 中的 stderr 原始事件行保持原样不过滤，取证现场完整。
- 瞬断判定与 dispatch 分类不得依赖降噪后的 error 字符串反推，必须使用原始 stderr 信号或结构化标记。

## 溯源

- [2026-09-13 fix-provider-transient-backoff](spec/archive/2026-09-13-fix-provider-transient-backoff/) — 确立 error 拼装的 CLI 诊断行过滤、全噪音时退出码回退形态，以及「分类不得反推降噪文本」的口径
