# dsh run 终态会话登记必须按 attempt 收敛为列表（纯赋值覆盖漏归档）

## 背景

add-dsh-session-title-archive 的 daemon 侧归档链路（core/agent_runner/runner.py `_run_dsh_session_id` 注册 → 终态 `_dsh_session_tidy_on_terminal` 投递）在线上 repair 车道暴露：同 run 多次 attempt（`-a1/-a2/-a3` 重试）各 spawn 独立 dsh 会话，终态只归档末次 attempt 的会话，前序会话堆积 web 未分组。

## 结论

- `_normalize_run_id`（runner.py:1146）把 `-a<n>/-r<n>` 剥到 base run_id——**凡以 base 键登记 per-attempt 资源，纯赋值必然逐 attempt 覆盖**；多 attempt run 的每份资源都要走列表/集合语义登记，终态全量消费。
- 现行事实：`AgentRunner._register_dsh_session_id(run_id, session_id)` 登记值=列表（同 id 幂等、None 尝试不擦既有捕获、首个 None→None 哨兵、str 旧形态并入）；`_dsh_session_tidy_on_terminal` pop 后逐 id 全量按序投递，None/空列表走既有「未捕获」WARN 面。
- 非 repair 特有：一切重试链 run（impl/verify 等）多 attempt 同样漏；repair 高重试率先暴露。

## 证据

- 修复前生产样本（cloud-phone，2026-11-09）：repair-p2p-crossnet-traversal-1794211508 三 attempt dsh-events 流各含独立 session id（8f9bba9d/cad75a42/e7ed3f39），fenixd.log 仅归档 e7ed3f39（a3）；可见 ×2=a1+a2 泄漏，数量精确吻合。repair-m3 同型（f6df70cf/a7596978/59c2de31，仅 59c2de31 归档）。
- 队列空（`/root/cloud-phone/.fenix/dsh_session_tidy/pending.jsonl` 无条目）+ 日志「dsh 会话已归档」成功留痕 → 排除投递失败面，锁定注册覆盖。
- 修复：tests/test_dsh_session_tidy.py 45 passed（含先红用例：多 attempt 全量归档、空列表防御、登记契约 7 例）；4 条泄漏会话经 helper 补归档后 web 复验 repair 残留清零。
