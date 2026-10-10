# 自进化子代理等待上限
<!-- knowledge: capability=evolution-subagent-wait-ceiling rev=1 sources=spec/archive/2026-10-11-evo-add-evolution-subagent-wait-ceiling -->

自进化复核 run 派出的核查子代理不受 Claude Code CLI 后台等待上限击杀，「派子代理-等待-汇总」工作流可完整收尾落盘。

## 规则

- evolution 车道派发 CLI 时在该车道 env 中设置 `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0`（无限等待后台任务），注入点在 run_evolution 的 env_overrides 组装处，仅作用于 evolution 车道；runner 层全局默认保持 CLI 缺省（600 秒）。其他维护车道（self_review / code_review 等）的 env 不含该变量，run 超时行为不变——code_review 的「派子代理等汇总」形态由其「禁 async 等待收工」守卫与分片直写纪律兜底，不依赖等待上限放宽。
- 进化提示词（agents/evolution.md 执行模式节）明确约束：核查子代理 MUST 前台派发（同一回合内等待结论返回再继续），收齐全部子代理结论前 MUST NOT 结束回合，每条分片写完立即并入产物文件——env 注入失效或 CLI 行为变化时的第二道防线。
- 击杀归因：evolution 收尾在产物契约缺失判失败时嗅探本 run 转录（`.fenix/runs/<run_id>.jsonl`）的全部 `type: stderr` 行，命中「Background tasks still running after 600s」签名（大小写不敏感子串匹配）则失败 reason 追加 CLI 后台等待 600 秒上限（含变量名）的归因说明；无签名维持现状文案，转录不可读静默跳过嗅探、不影响原失败路径。
- 嗅探只扫 `type: stderr` 行、不做全文件 grep：签名文本会以引用形态大量出现在 assistant/user 转录记录中，全文件 grep 会把引用误判为击杀。
- 子代理真挂死时 run 由 run_timeout 兜底杀死，水位不推进、下一检查点自然重派。

## 溯源

- 2026-10-11 evo-add-evolution-subagent-wait-ceiling（spec/archive/2026-10-11-evo-add-evolution-subagent-wait-ceiling） — 新增本页全部规则：evolution 车道 env 无限等待注入、提示词前台派发兜底、600 秒击杀归因嗅探（仅扫 stderr 行）
