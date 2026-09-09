# Tasks: fix-verdict-read-failclosed

## Deliverables

```yaml
- path: core/agent_runner/runner.py
  kind: modify
- path: core/pm_engine/verification.py
  kind: modify
- path: core/agent_runner/prompt_builder.py
  kind: modify
- path: agents/planner-judge.md
  kind: modify
- path: tests/test_agent_runner_gate.py
  kind: modify
- path: tests/test_verdict_read_failclosed.py
  kind: new
```

## 1. runner 硬门：时序、新鲜度、白名单（spec：硬门校验本轮实际产出 / 新鲜度 / status 白名单）

- [ ] 1.1 拷回前置：把根 result 复制与 `_copyback_verify_progress(wt_path, spec_name)` 移到 `_check_agent_result_artifact` 门检调用**之前**（成功路径内、`_run_claude` 返回后），原位置（原 runner.py:2115-2133）代码移除不留双份；拷回幂等性保持（mtime 守卫不动）
- [ ] 1.2 `_check_agent_result_artifact` 增 `run_started_at: float` 参数，校验结果文件 mtime ≥ run_started_at，早于则归因「结果文件早于本轮启动（陈旧残留）」；attempt 循环传入本轮启动时刻
- [ ] 1.3 白名单常量 `planner_result_status_whitelist = ("verified", "bug-found", "plan-ready", "scenario-repaired")` 落地 `prompt_builder.py`（紧邻 `planner_result_path`）；runner 门检 `json.loads` 成功后校验顶层 `status ∈` 白名单，白名单外归因文案含实际 status 值
- [ ] 1.4 `tests/test_agent_runner_gate.py` 新增用例：① worktree 侧写非法 JSON（裸换行复刻）→ 拷回后门检拦截（瞬态重试路径）；② 主树残留上一轮合法文件 + 本轮零产出 → 新鲜度拦截；③ 顶层 status="success" → 白名单拦截；④ 合法 verified / bug-found → 通过且 run 判 success

## 2. pm_engine 读侧 fail-closed（spec：读侧裁决 fail-closed / legacy 路径同门）

- [ ] 2.1 `_read_verifier_result` / `_read_planner_result` 返回结构化三态（status 或 unreadable(reason, detail)，reason ∈ missing/parse/unknown-status/foreign-stamp，detail=解析错误原文）；内联白名单改引共享常量；`engine.py:2438-2442` 委托签名同步；全库调用点适配
- [ ] 2.2 三阶段裁决采纳处（verification.py:1497 读后）：unreadable → 重派 judge 一次（复用 `_verify_verdict_evidence` 的 run_planner 重试形态）→ 复读；二次仍 unreadable → `update_spec(status="blocked", error=…)` + `_send_human_escalation_alert(signal_type="verdict_result_unreadable", severity="critical", description/evidence/recommended_action 含解析错误原文与结果文件完整路径)`；重试前复用入口状态判据（非 testing 丢弃，与 D6 stale-result 防护同构）；不推进 bug-found、不派生 fix
- [ ] 2.3 legacy 采纳处（verification.py:2006 读后）：unreadable → blocked + 同款 verdict_result_unreadable 告警；不重派整轮 verifier、不发生任何 → verified 转换
- [ ] 2.4 语义反转清账：`_read_verifier_result` docstring 删「视为 verified」改述三态 fail-closed；`_all_green_fast_path` 注释同步（写回失败不得静默 verified，快道产物读侧 unreadable 时走常规 judge 或 blocked）；全库 grep `视为 verified`、`按 verified 兜底`、`treating as verified` 命中的注释/日志文案一并更新为 fail-closed 表述
- [ ] 2.5 `tests/test_verdict_read_failclosed.py` 新建：① 裸换行非法 JSON（复刻事故签名 Invalid control character line 25 col 402）→ 重试 judge 一次 → 二次仍坏 → blocked + 告警（断言错误原文入告警、无 verified 转换、无 fix 派生）；② status="success" 白名单外同路径；③ 首次 unreadable、重试后合法 bug-found → 正常走 fix 链；④ legacy unreadable → blocked + 告警；⑤ 合法 verified / bug-found / scenario-repaired 路由不回归；⑥ 全绿快道机械写回 → 读侧 ok → verified 不回归

## 3. judge prompt 契约加固（design D7）

- [ ] 3.1 `agents/planner-judge.md` 结果文件写入步骤（步骤 6 及 scenario-repaired 分支步骤 4 若有写文件处）追加：结果文件必须为**合法 JSON**——字符串内换行/引号/控制字符必须转义，建议以代码 `json.dump` 生成而非手工拼接文本
- [ ] 3.2 `prompt_builder.py` 动态契约段若复述结果文件写入契约则同步一句（与模板双落点一致）；未复述则仅以 1.3 的常量落点为该文件改动依据

## 4. 回归与收尾

- [ ] 4.1 全绿快道回归验证：0 失败 0 警告 → 机械写回 → 读侧 ok → verified（既有行为不变）
- [ ] 4.2 既有相关测试全绿：test_agent_runner_gate.py、test_verdict_evidence_taxonomy.py、test_verify_report_gate.py、test_verdict_visibility.py、test_verdict_fast_track.py 及 pm_engine/verification 相关既有用例
- [ ] 4.3 终检：全库 grep 确认无残留 fail-open 语义注释；`python3 -m pytest tests/ -x -q` 全量绿
