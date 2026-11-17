# 立项请求（原话照录）

> 用户（2026-11-10 09:18，消息 m00308，对 lead 事故报告与修复清单的批复）：「4先不动，1、3你手动修改。2立项，full，11:00后执行」

立项对象（lead 事故报告 m00307 修复清单第②项）：

**维护车道接入 provider 退避链（含 429 终局重派按链解析）**——2026-11-09 夜间 glm-5.3 周/月额度耗尽事故暴露的第二处断点：

- 六条 LLM 维护车道（administrator / arbiter / self-review / evolution / code-review / code-fix）在 `core/agent_runner/maintenance_runs.py` 各自由复制同一段模型组装块：`provider, model_override = assignment[0]` 只取链首选直连，`_write_lane_provider_marker` 硬编码 `chain_index=0 / chain_len=1`；车道不经 `runner._execute_agent_inner` 的 attempt 环，没有跨 provider 兜底。
- 实证（2026-11-09 本地夜间，.fenix/runs/archive）：`code-review-1794240196`（16:03:22Z）撞 bigmodel 429 直接终态；`_schedule_ratelimit_redispatch` 于 16:08:27Z 以原 manifest 复跑 `code-review-1794240502`，仍取链首 bigmodel 再撞同一 429，唯一一次重派额度耗尽。同段时间 administrator/arbiter/self-review run 全部 `provider=bigmodel.cn, chain_index=0, chain_len=1`。
- 用户同批批复的其它三项：①切链闸门复用结构化双源信号（lead 已手动修复并补回归测试，`runner._switch_signal_text`）；③回归测试（随①落地）；④「周/月额度类 429 的 300s 冷却不合理」明确推迟不动。

## 执行时机

用户指定「11:00后执行」：`start_after = 2026-11-10T03:00:00+00:00`（Asia/Shanghai 2026-11-10 11:00）。

## 明确不在本 SPEC 范围

- ④ 429 冷却时长 / 配额类错误分级策略：用户明确推迟（m00308「4先不动」）。
- 普通 agent 车道的 attempt 环切链闸门：已由①手动修复，本 SPEC 只复用其判定原语，不重复改造。
- `run_impl_ocr`（外部二进制 `bin/ocr_review.py` 车道，复用 implementer assignment 写 OCR 配置）不纳入链 failover；如需要另立。
- provider 熔断语义（`PROVIDER_CIRCUIT_4XX`）、每日 provider 派发计数、配置/凭据 UI 不变。
