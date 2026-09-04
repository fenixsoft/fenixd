# Tasks: fix-dispatch-orphan

## 1. 状态机读取防御（design D3，先复现再修）

- [x] 1.1 编写最小复现用例：构造含字符串形条目/半写内容的 STATE.md 调用 `state_machine.read_all()`，证实 `string indices must be integers` 崩溃点位（或证实根因另有其处并记录实际点位）；用例入库 tests/test_core.py
- [x] 1.2 在 read_all() 解析层规范化条目：非法条目跳过并记 warning；1.1 用例转绿后确保既有解析用例无回归

## 2. bug_found 重发无害化（design D2）

- [x] 2.1 pm_engine spec_bug_found 处理器扩展幂等守卫：fix 子 SPEC 处于 implementing/testing/implemented/verified/done/pushed 时仅记日志不动状态；全路径禁止向 implementer_run/tester_run 写空值；补单元测试三例（implemented 存活两轮扫描 / ready 无历史正常 reset 且不清字段 / done 完全跳过）
- [x] 2.2 全局 grep implementer_run/tester_run 消费点确认「保留历史 run id」语义兼容（dashboard 与排队去重），结论写入 PR 描述

## 3. 同状态行动性重置补发（design D1）

- [x] 3.1 定位 spec_bug_found 处理器内所有同状态重置写回点（含"already exists (status=ready) — resetting to ready"路径），写回后直调 `_on_spec_ready(spec)`；复用 pm_engine.py L105 启动路径先例；补测试：同状态重置周期内派发被触发、与真实事件序列不双重排队
- [x] 3.2 排查其他产生行动性同状态更新的处理器（error 更新后可重新派发的 ready 场景），逐点接入补发并列清单到 PR 描述；确认无遗漏点后进入下一任务

## 4. full_scan 单条隔离与统计（spec-full-scan-resilience）

- [x] 4.1 event_bus.full_scan 中 recovery 循环逐条 try/except（单条失败记 error 含 spec 名），check_blockers 同样包裹；扫描末尾输出 handled/failed 统计日志；补测试：注入单条毒条目时其余 SPEC 的 recovery 全部完成且统计可见

## 5. 孤儿 ready 白名单恢复（design D4）

- [x] 5.1 实现 ready 存活判定：优先调用 improve-run-lifecycle-governance 已落地的 has_live_attempt/refresh_locks 接口（若未合入则用兜底实现——pgrep 匹配 `.claude/worktrees/{impl,verify}-<spec>-*` claude 进程 + 对应最新 run 文件 mtime < 120s），接口选型写在 PR 描述
- [x] 5.2 改写 full_scan recovery 的 ready 分支为白名单判定（存活才 skip 并记「skip: live child present」），重派发前清 error、保留 implementer_run；补测试四例：带 error 孤儿重派发 / 带 implementer_run 无活跃运行重派发 / 有存活进程跳过 / 锁表在册跳过

## 6. 回归与核验

- [x] 6.1 全量 pytest 通过（重点 tests/test_core.py 及新增用例），无既有用例回归
- [x] 6.2 对照三个 capability spec 的全部 Scenario 逐条核对实现覆盖并记录结论

---

### 附：PR 描述所需的审计结论

**2.2 implementer_run/tester_run 消费点兼容性结论**
全局 grep 所有消费点，确认字段语义均为「最后已知 run id」（可为 null 的透传），
保留历史值不影响任何消费逻辑：
- `core/event_bus.py:97 / :90`：recovery 守卫 `if entry.get("implementer_run")`
  （有历史 run 则跳过 re-dispatch）——保留历史值与白名单判定（5.2）配合，孤儿仍
  可被重派发（D4 白名单反转了原黑名单跳过逻辑）。
- `core/dashboard/data.py:898`：`cleanup_runs` 用 run id 保护历史 run 文件不被淘汰
  ——保留历史 id 反而增强保护，无害。
- `core/dashboard/data.py:1163-1164`：详情页透传展示，`None` 安全。
- `core/pm_engine.py:949/1423/...`：均为成功路径写入 run id，无消费重建逻辑。
结论：**保留历史 run id 完全兼容，dashboard 与排队去重不受影响**。

**3.2 行动性同状态更新处理器排查清单**
逐点排查 `core/pm_engine.py` 所有写回点，确认是否存在「状态未变却需行动」的遗漏点：
1. `spec_bug_found` 重置（ready→ready / bug-found→ready）：**已接 D1 补发**
   （`_do_spec_bug_found` 重置后直调 `_on_spec_ready`，3.1）。
2. `check_blockers` auto-recovery（L1850/1860）：implementing/testing→ready 属**状态变更**，
   已 `_enqueue` 派发，无遗漏。
3. `_rollback_failed_dispatch`（L1088/1087）：失败落回 ready/implemented 属**状态变更**，
   已 `_enqueue`，无遗漏。
4. `implementer` 失败 retry 耗尽（L1031-1040）：implementing→ready **状态变更**，
   原依赖事件总线 checksum 重排；**已补强** `_enqueue` 立即重排（3.2），消除 daemon 重启间隙孤儿。
5. verifier `_on_spec_verified` error 写入（L159）：verified 终态保持，由 full_scan 周期
   重触发 `spec_verified` 门禁，非同状态重置，无遗漏。
结论：**唯一真正的同状态行动性更新是 spec_bug_found 重置（3.1 已覆盖），其余写回点均为**
**状态变更或已有显式 `_enqueue`，无遗漏点。**

**5.1 存活判定接口选型结论**
姊妹变更 `improve-run-lifecycle-governance` 的 `has_live_attempt` 接口**当前尚未合入**
（`core/agent_runner.py` 中不存在），按 design D4 兜底实现：
- `_ready_has_live_child` 优先探测 `agent_runner.has_live_attempt`（若未来合入自动复用）。
- 兜底：pgrep 匹配 `.claude/worktrees/{impl,verify}-<spec>-*` 进程 + `implementer_run`
  指向最新 run 文件 mtime < 120s。
- 不重复造锁机制（锁归姊妹变更），仅做轻量存活探测，语义一致即满足白名单需求。
# tasks.md 追加块（第二轮实施内容）

## 7. verifier 判定完整性（design D5–D8，specs/verifier-judgment-integrity）

- [x] 7.1 agent_runner `_run_claude` rc==0 路径增加 last_result.is_error/subtype 终态校验（字段缺失维持现行为）；补单元测试三例：rc0+is_error 假成功拒绝 / rc0+503 文本样例 fixture / 正常完成不受影响
- [x] 7.2 pm_engine verifier 成功分支前置进度核对：testing→verified 前 done>=total 才晋级，不完整走既有失败重试并写 error 摘要；done 门禁 fail-open 语义不变；补单元测试（半程假阳性不晋级 / 完整通过照常）
- [x] 7.3 VALID_TRANSITIONS 增加 VERIFIED→TESTING 回退通道（仅门禁自动路径暴露），回退保留 implementer_run 与断点；transition 表单测覆盖（允许/人工路径仍拒）
- [ ] 7.4 排查 verify-fix-add-dashboard-spec-doc-tabs-and-info-clear-1787803666-a1.jsonl 证据消失事件：审计 runs 目录读写与清理路径定位丢失原因，落实产物生命周期保障（结算前禁删+删除留痕）并记录结论于 PR 描述
- [ ] 7.5 全量 pytest 通过且对照四个 capability spec 的 Scenario 逐条核对覆盖情况

