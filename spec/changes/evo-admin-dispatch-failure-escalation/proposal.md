# admin-dispatch-failure-escalation — admin 派发失败专用升级信号

## Why

2026-09-14 20:26 stash_pop_conflict 信号派发 Administrator 时因提示词构造 replace() 报错（{evidence} 为 dict 穿透 str.replace，prompt_builder.py:204）无法派发；升级记录虽已落（admin_alerts.json 4079b0d022a3「Administrator 唤起失败」），但：① 沿用原 signal_type（stash_pop_conflict），无「派发期编程错误」专用类型，无法归类统计；② 升级记录缺结构化归因（异常类型/调用点），人工无法一眼判断根因；③ 派发失败不重试，自动处置链路单点即断（靠孤儿检测延迟 1.5h 才升级 critical）。add-control-plane-silent-failure-guards 防线三只覆盖 _reset_env_blocked_after_disposition 复位路径，派发链空白。另：_str_field 序列化修复与防回退单测已在工作树但未提交（66f815db 为 verifier 分支 merge，未触及 prompt_builder.py），须纳入版本化。

## What Changes

- admin 派发失败落专用升级信号：signal_type=admin_dispatch_programming_error、severity=critical、evidence 含异常类型/消息/调用点/原信号（signal_type/spec/severity）。
- 派发失败重试语义：冷却（escalation_cooldown_minutes）后自动重试一次原信号，仍失败保持升级记录（retry_count 上限 1），不无限重试。
- _str_field 修复 + 防回退单测纳入版本化（提交现有工作树改动并补派发链用例）。

## 验收

- 回放 stash_pop_conflict dict evidence → 派发失败 → 恰好 1 条 admin_dispatch_programming_error critical 升级记录（含异常类型与调用点）；冷却后重试一次；恢复后原信号可正常派发。