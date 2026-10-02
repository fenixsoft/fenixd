# fix-verify-late-result-terminal-clobber — Design

## Context

2026-09-24 `fix-quality-gates-flat-form-and-explainability` 事故链（日志取证，时间为本地 UTC+8）：

1. 13:27:29 派发 LLM verifier `verify-<spec>-1790227649-a1`（独立 worktree + dev-server，实测 42 分钟 183 轮）；同时进程内机械三阶段车道并行推进。
2. 13:52-13:59 机械车道出结果 → judge 认证 → 13:59:59 SPEC 流转 `testing → verified → done → pushed`（branch SHA 901f3048 上远端）。**a1 未被终止，继续在飞。**
3. 14:09:20 a1 完成；20 日 06:09:20Z 日志：run metrics（duration 2511.9s）→ worktree 清理（其真实结果文件随 worktree 删除）。
4. 14:09:21 结果应用走 `legacy.py` 成功路径：主树结果文件（机械快道产物，无 role 戳）mtime 早于 a1 启动时刻（run_id 内嵌 epoch 13:27:24 基线）→ `_verifier_result_is_stale` 判 True → **直接 `update_spec(status="implemented")` 覆写终态** + infra 记账 + 预算豁免。
5. 14:09:22 recovery 看到 implemented 立即重派 → 场景冻结复用 → 机械重验 11s 全绿 → 全绿快道 mechanical verified → 14:10:25 回到 pushed。

净损害为零（终态未变、同 SHA、预算豁免 0/6），但暴露三缺陷：迟到结果可覆写终态（D6 复核缺口）、终态不回收在飞车道（白烧 10 分钟 tokens）、快道产物缺来源戳（误判土壤）。

## Goals / Non-Goals

- **Goals**：迟到 verifier 结果在任何非 testing 状态下一律丢弃；verified 收敛点回收在飞 verify 车道；快道裁决产物带合法来源戳。
- **Non-Goals**：不改变 testing 内的并发车道与 stale 回退语义；不修 run 历史显示（「完成 13:27」实为派发时刻，属 run-record-readability 族）；不动 `fix-quality-gates-terminal-blindspot`（指纹盲区族，不重叠）。

## Decisions

### D1：D6 复核补在 legacy.py 三个缺口分支，判据与同文件既有分支同构

`_cur != "testing"` → `logger.debug` 丢弃并 return。三处插入位置：

| 分支 | 现位置 | 插入点 |
|---|---|---|
| foreign-role/foreign-stamp | legacy.py ~L137-166 | `if not verifier_result.ok:` 之后、`_verified_gate_refuses` 之前（复核最廉价且终态 SPEC 不再消耗门禁判定） |
| unknown-status + stale | legacy.py ~L171-196 | `_verifier_result_is_stale` 判 True 后、`update_spec` 之前 |
| 成功路径 stale 守卫 | legacy.py ~L283-304 | 同上 |

丢弃时不调 `_record_infra_failure`（终态 SPEC 记 infra 是噪音；且该记账附带预算豁免，对终态无意义）。pipeline.py 仅转口暴露 `_verifier_result_is_stale`（:265 方法表）供 legacy 使用，自身无同款写状态分支，无需改动。

### D2：回收钩子放 `_on_spec_verified` 收敛点，复用既有取消原语

- 选 `engine.py` `_on_spec_verified` 而非各 transition 调用点：它是 legacy（:497）与 pipeline（:1029）双路唯一汇合处，单点收口零遗漏。
- 照搬 `_stop_parallel_planning`（engine.py:1087，planner-plan 车道既有范式）的两段结构：`_remove_queued_entry(spec_name, "verifier")` 摘在队条目 + `cancel_run` 终止在飞 run，外层 try/except 记 WARNING 不抛。
- **取消键形态（评审实测修正，MUST）**：`cancel_run` 的旗标登记键 = 传入 id 经 `_normalize_run_id` 归一（core/agent_runner/runner.py:652，只剥 `-a<n>`/`-r<n>` 后缀，**不剥 epoch**）；消费点（attempt 循环 runner.py:3121、轮询环 runner.py:4094）以**带 epoch 的 run 级 id**（verifier 构造见 runner.py:822 `f"verify-{spec_name}-{int(time.time())}"`）归一后做**精确集合判定**。故 MUST 对活跃 run 按**完整 run 级 id（含 epoch，如 `verify-<spec>-<epoch>`）**调 `cancel_run`，MUST NOT 传裸 `verify-<spec>`——裸键登记后与消费点键不收敛，取消**静默失效**（登记侧按裸前缀 `startswith` 匹配活跃 attempt（runner.py:701-704），仍返回 `cancel_requested` 并留审计，极具迷惑性）。先例 `_stop_parallel_planning` 传裸键 `planner-plan-<spec_name>`（planner run id 同样带 epoch，runner.py:834），其取消旗标同样未真正收敛、长期靠摘队列 + 消费侧校验兜底（engine.py:1027 竞窗注释「run 会照常跑完」互证）——本车道收尾 MUST NOT 照搬裸键。
- **归属复核（MUST）**：登记侧裸前缀匹配会误中同根后代 spec 的 run（如 `verify-fix-a-b-<epoch>` 命中 `verify-fix-a` 前缀；family 谱系 fix-→fix-fix- 派生常见，family.py:283 既有同款「精确前缀归属守卫」教训注释）。收尾须对活跃 attempt 逐个以 `run_spec_part(aid) == spec_name`（core/agent_runner/run_files.py:105，cancel_run 审计同款解析）复核归属，仅对本 spec 的 run 调 `cancel_run`。
- **插入点（MUST）**：`_on_spec_verified` 内 `transition(spec_name, "done")` 成功之后，与 `_evict_spec_serving` 终局驱逐同位置同范式（engine.py ~:1518-1523，try/except 记 WARNING 非阻塞）。MUST NOT 放方法入口：D7 逃生门（验证进度不完整 → 回退 testing 断点续跑，engine.py ~:1493-1509）与「blocker 保持 verified」两路径在入口判据后提前 return——入口回收会拆掉刚被门禁要求续跑的在飞车道，破坏断点续跑语义；改用完整 run id 后旗标按 epoch 键登记，也不会误杀门禁回退后重派的新 epoch verify run 与人工重验 run。
- 外层 try/except 记 WARNING：取消失败由 D1 的 D6 复核兜底丢弃迟到结果（纵深防御），不得影响 done → push 主链。
- 时机选 verified 之后而非 testing 内：testing 内双车道并行是设计行为（机械车道先出结果即采信），只有终态化才该拆车道。

### D3：快道 payload 补 `role: "verifier"`，读侧零改动

`_all_green_fast_path` payload 加一个键即可：`_read_verdict`/`_read_verifier_result` 白名单认 `role=verifier`，`_verifier_result_is_stale` 的 role 门（report_gate.py:154-156）放行，spec 戳与 mtime 判据保持不变。`mechanical: true` 保留，机械来源仍可辨识。只读消费方（verify_report.py:108 等）对多余键天然兼容。

已知取舍：同轮机械快道先写文件、在飞 LLM verifier 后完成时，其 stale 校验将放行并采信快道裁决（verified）——同 spec 同轮、均为验证车道产物，可接受；且 LLM verifier 自身会先写自己的结果文件覆盖之，窗口极窄。

## Risks / Trade-offs

- **[取消语义]** `cancel_run` 是协作式取消（旗标 + 轮询环退出），a1 类长轮次从收到旗标到实际退出有延迟 → 由 D1 兜底：即使退出前写完结果，应用侧也因非 testing 丢弃。测试须覆盖「取消已请求但结果仍到达」的竞态。
- **[取消键收敛]** `cancel_run` 登记键与轮询环消费键必须归一收敛（见 D2）：裸 `verify-<spec>` 键会静默失效且返回值/审计均显成功。测试须断言「cancel 后轮询环视角 `_cancel_is_requested(<带 epoch run id>)` 为真」，MUST NOT 只断言 `cancel_run` 返回值。
- **[回归面]** legacy.py 三分支均有存量用例（tests/test_daemon_lifecycle_races.py:753 附近），改动须保证 testing 状态下行为逐字节不变（含 error 文案、`_cancelled_hold` 复位等字段）。
- **[hidden 依赖]** `_on_spec_verified` 内新增 runner 调用，注意该收敛点在部分测试中以 stub context 调用——须 getattr 防御或保证注入完整（以现有测试跑通为准）。

## Migration Plan

纯代码防御增强，无状态迁移、无配置项、无 schema 变化。生效须 daemon 重启（热加载不覆盖进程内在飞线程语义）。

## Open Questions

无。
