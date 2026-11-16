# Design: add-distill-run-work-summary

## Context

蒸馏批 run 产物是合成事件流（started/heartbeat/round/result，add-distill-run-artifacts D1 备选 B），spawn stdout 保持裸文本。时间轴 run 节点 summary 的数据源是产物末行 `result` 事件的 `result` 字符串字段（`_run_tail_insights`，`core/dashboard/data/runs.py:1060`），蒸馏批终态行缺该字段 → 总结盒零渲染。

蒸馏 spawn 经 `run_one_shot(ClaudeAdapter(), SpawnRequest(output_format=None, ...))`（`core/knowledge.py::_spawn_once`）裸文本执行，`outcome.stdout` 已被捕获，但成功路径只返回 `(ok, err)`，stdout 丢弃。prompt（`agents/knowledge-distill.md` 完成标准第 7 步）要求 stdout 最后一行输出 `KNOWLEDGE_DISTILL_DONE`，daemon 侧无消费方。

## Goals / Non-Goals

**Goals**
- 主蒸馏成功后，agent 的最终消息作为工作总结出现在时间轴 run 节点总结盒
- 读侧与前端零改动

**Non-Goals**
- 折叠子 run 的总结不采集（folded 计数已够；用户定调 2026-11-06）
- 不切换 stream-json 全转录（改动面与诊断契约变动不成比例）
- 失败路径的诊断形态不变（error 行、stdout/stderr 摘要进日志照旧）

## Decisions

- **D1 总结载体 = 既有终态 result 行新增 `result` 字段**。读侧 `_run_tail_insights` 对 `result` 事件既有 `result` 字段的读取自动拾取，前端总结盒既有分支自动渲染。备选「新增 summary 事件类型」被否：读侧不解析未知键，需双端改动；备选「daemon 侧 git show --stat 合成摘要」被否：非 agent 自述（用户定调要 agent 输出工作总结），且无规则语义。
- **D2 文本来源 = 主蒸馏 spawn 成功路径的 stdout**。裸文本模式 stdout 即最终消息；剥离尾部 `KNOWLEDGE_DISTILL_DONE` 标记行后整段作为总结。标记行从「无消费方的提示词契约」转正为剥离锚点；标记缺失不判失败（成功判据仍是退出码 + validate_knowledge，标记仅作剥离锚，fail-open）。
- **D3 返回值扩展 = `_spawn_once`/`_spawn_and_wait` 改三元组 `(ok, err, stdout)`**。折叠调用点同步适配（忽略第三位）；测试注入缝在 Popen 级（`DistillManager(spawn=...)`）不受影响，`test_harness_one_shot_forms.py` 两处二元解包需更新。
- **D4 截断与装配 = 模块常量上限（2000 字符）**，超限尾部截断加「…（截断）」后缀；提取函数纯函数化便于单测。装配点在成功路径 `result["ok"] = True` 旁（`result["summary"] = <文本>`），`_distill_run_artifact_close` 的 ok 分支增加 `"result": result.get("summary")` 字段——空/缺失不写该键（读侧字段缺失按现状渲染）。JSON 字段名必须叫 `result`（读侧契约），dict 内部键名用 `summary` 避免与 dict 自身语义混淆。
- **D5 prompt 契约 = 只改主蒸馏完成段**（`agents/knowledge-distill.md`）：自查通过后先输出简短工作总结（本轮蒸馏了哪些能力页/ADR、新增或修订了哪些规则要点，markdown、建议 ≤20 行），最后单独一行 `KNOWLEDGE_DISTILL_DONE` 收尾。折叠 prompt（`build_inbox_fold_prompt`）不动。
- **D6 字段向后兼容**：历史蒸馏产物无 `result` 字段，读侧按缺失处理（与 origin_request 同口径）；读取 `_run_tail_insights` 对非字符串值有既有防护。

## Risks

- agent 输出的总结过长或含噪声 → 截断常量兜底；总结盒 markdown 渲染与普通 agent 总结同管道，无新增注入面
- stdout 为空（模型未按要求输出）→ fail-open 不写字段，时间轴与现状一致
- `_spawn_and_wait` 三元组遗漏解包点 → 全仓 grep 该方法名与 `_spawn_once`（产品代码 2 处外部调用 + `_spawn_and_wait` 内部 2 处 `_spawn_once` 解包（含 bare-model 重试段）+ 测试 2 处解包），回归测试覆盖

## 界面约束

本 SPEC 无前端改动（读侧/前端零改动是核心设计），不涉及 DESIGN.md 偏离。
