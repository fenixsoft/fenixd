# proposal: reduce-cli-stderr-noise-attribution

## 背景

自省欠账的 unrecognized_model 关联排查已由本轮复核完成（只读，现存 50 个归档 run）：该告警是 claude CLI 启动期对非 Anthropic 模型名的固定 stderr 诊断（每 run 恰 1 条，转录 line 4），出现与否由模型名唯一决定——glm-5.3-flash / deepseek-v4-flash run 全有（48/50），claude-sonnet-5 run 零有。含告警组失败率 2.1%（1/48，94% 成功收尾），与失败/停滞零区分度——定噪。

「升级计数纳入瞬态判据」分支被双重否定：数据上无相关性；设计上 core/agent_runner/runner.py:3058-3066 已刻意对该 stderr 返回 is_transient=False 不进 record_transient_break，provider_circuit.py:71-83 注释明言「把 unrecognized_model 从瞬态中收窄」（add-impl-selfcheck-model-probe 交付）。

## 问题

排查实锤了两个真实消费端缺口——无害噪声正在挤掉真实证据：

- 失败归因污染：core/knowledge_backfill.py:428-430 失败归因取 stderr 尾 400 字符，恰只剩噪声行；kb-adr6/kb-adr7 回填 run 真实死因是 bigmodel 429 限流（stdout「API Error: Request rejected (429)」），被噪声淹没。
- 深扫证据占位：自省中途信号深扫的 first_stderr（core/self_review.py:902-903 取首条）恒被该噪声占位，连续两个窗口的自省条目被同一噪声带偏。

## 目标

- CLI stderr 诊断噪声 pattern 收口为可复用常量（provider_circuit.py:80 UNRECOGNIZED_MODEL_TEXT_PATTERNS 已有基础，导出复用）。
- 深扫 first_stderr 选取跳过噪声行（stderr 计数保留全量）。
- 失败归因文本过滤噪声行，stderr 过滤后为空时回退 stdout 尾部。

## 非目标

- 不改 core/agent_runner/runner.py:3058-3066 的瞬态排除判据（不反向推翻 add-impl-selfcheck-model-probe 的收窄决策）。
- 不改模型链命名与 --model 传参（core/agent_runner/runner.py:4426）。
- 不改熔断阈值（.fenix/config.yaml:143-145 的 5/600s 为生产配置）。
- 不触碰 evo-alert-noise-governance 的 admin 告警链（对象不同，互不侵入）。