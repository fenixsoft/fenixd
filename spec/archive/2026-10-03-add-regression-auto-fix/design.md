## Context

测试回归车道（`core/regression.py`）产出单快照 `.fenix/regression/last-run.json`（failures/error/timeout/long_tests 四类异常），回归页签只读展示 + 手动重跑，无修复入口。code-fix 车道（`core/code_fix.py` `CodeFixOrchestrator`）是成熟的修复机制：从 code-review 台账（`core/code_review.py` `read_items`/`upsert_findings`，fingerprint 去重）选取 open 条目批派 worktree 修复、批验证回归、失败自愈；且 `add-code-fix-manual-trigger` 已建立「dashboard 写文件信号 → daemon 主循环消费 → `checkpoint(override_enabled=True)` → 结果文件回链」的完整先例（`.fenix/code_fix_request.json` / `code_fix_request_result.json` / `_check_code_fix_requests`）。

约束：台账 `upsert_findings` 的 upsert 语义（不覆盖 status/first_seen_at）是共享契约，MUST NOT 为回归场景改动；`checkpoint` 的全部守卫（单飞/无 open 条目/失败保留/回归契约 fail-closed）原样保留；code-fix 批派/验证/合并机制零改动。

## Goals / Non-Goals

**Goals**
- 回归页签一键触发「问题列表 → code-fix 台账条目 → 修复链」的自动修复。
- 受理判定回链（triggered / reason）用户可见。
- 复发问题可再次触发修复（重开语义）。
- 长耗时修复语义（不改通过结果）固化到条目文案，随批派注入修复 Agent。

**Non-Goals**
- 周期性/自动触发回归修复（仅手动按钮）。
- 按用例勾选修复子集。
- 新增修复进度 UI（复用质量页签既有 CodeFixProgressCard）。
- 改动 code-fix 批派、验证、合并、自愈机制与 `upsert_findings`/`fingerprint` 共享语义。
- 对 code-review 来源条目做任何自动重开。

## Decisions

**D1 复用 code-fix 车道，转换发生在 daemon 消费端**：按钮信号 → daemon 读快照 → 转换为 findings → `upsert_findings` → `checkpoint(override_enabled=True)`。备选「前端直接转换上传条目」被否：快照读取与转换属服务端职责，前端不持台账写路径；备选「独立回归修复车道」被否：重做批派/验证/自愈成本高且无隔离收益。手动触发即临时授权沿用 `override_enabled` 既有语义（其余守卫不动）。

**D2 信号与回链文件与 code_fix_request 完全同构**：`.fenix/regression_fix_request.json`（原子写，含 `created`）+ `.fenix/regression_fix_request_result.json`（`request_created/triggered/reason/message/finished_at`）；消费走 `_consume_request_file` 原子模式（先 rename 占位再读，消灭「先读后删」窗口丢请求——code-review item 69fdd0ab526e 的既修形态）。同构降低实现与审查成本，回链契约用户已熟悉。

**D3 转换与重开落 `core/code_fix.py` 纯函数**：`convert_regression_snapshot_to_findings(snapshot)`（快照 dict → findings 列表，映射固化见 spec）与 `reopen_regression_items(project_root, live_fps)`（仅 `regression-` 前缀 category、fingerprint 仍出现在快照且 status 非 open → 重开 open + 刷新 first_seen_at；读-改-写 + flock，与台账写同锁）。纯函数化便于单测，不触碰既有路径。

**D4 整体超时条目的 file 锚点取 `.fenix/verify.yaml`**：`upsert_findings` 跳过无 file 的发现（既有硬规则），而整体超时无逐用例定位；超时处置的真实入口恰是回归硬超时的声明落点 verify.yaml（查套件性能或超时配置），以真实存在文件为锚点而非伪造用例路径。

**D5 消费端读快照以当下为准，不与信号锁定**：触发到消费之间快照可能被新一轮回归覆盖或清理——消费端读不到/损坏即落 `snapshot_missing` 结果，不重试不排队（单快照语义下无历史可回放，用户重按即可）。备选「信号携带快照内联副本」被否：复制一份大 JSON 进信号文件换不来实际收益（重按成本≈0）。

**D6 checkpoint 拒绝不回滚台账**：转换入账成功但 `checkpoint` 以 `already_running` 等拒绝时，条目保留已入账状态——在飞链下一批 `select_batch` 按 first_seen_at 自然吸收新条目；回链如实返回 reason。回滚反而制造「条目消失、用户以为触发失败」的假象。

**D7 `review_kind` 新值 `regression_fix`**：已核实全仓 `review_kind` 仅作元数据透传（`upsert_findings` 存储、进度接口返回），无枚举校验，新值零破坏。`review_id` 取 `regression-fix-<signal created>` 保证可追溯。

**D8 前端按钮可用性由快照机械判定 + 受理回链轮询**：按钮 disabled 条件纯前端可判（快照在手）；点击后 POST → 轮询 `fix-result`（`request_created` 比对本轮触发）→ triggered 弹成功提示并指向质量页签进度、非 triggered 按 reason 分支提示。复用 code-review 手动触发按钮的既有 UX 范式与请求序号守卫。

## Risks / Trade-offs

- [回归条目混入 code-review 台账，台账视图/统计口径变化] → category `regression-` 前缀隔离标识；台账 UI 按既有 category 列渲染新标签，无需改读侧；统计无按 category 硬编码断言（实现时复核，如有则补充枚举）。
- [长耗时优化改坏被测行为] → suggestion 固化「不改变通过结果」约束 + code-fix 批验证既有回归重跑兜底（变失败按批失败语义处置）。
- [信号风暴/重复点击] → 按钮 loading 防重复 + 信号原子消费（rename 占位）天然幂等；重复触发经 fingerprint 去重不产生重复条目。
- [超时条目 file=verify.yaml 被修复 Agent 误读为「改配置了事」] → description 携带 reason/输出摘要并固化处置指引（先查套件性能，确属超时配置不合理才调声明）。
- [enabled 总开关关闭时手动授权绕过引发意外修复] → 与 add-code-fix-manual-trigger 同一语义取舍（手动即授权），非新风险；授权不外溢（链终态清除）由既有机制保证。

## Migration Plan

无数据迁移。合入后：前端经 `npm run build` 产出 dist（运行时重建，不入库）；daemon 重启后新消费方法生效（挂主循环既有车道检查点序列）。回滚：直接回退提交，信号/结果文件为 gitignored 运行时产物，残留无害。

## Open Questions

无——执行模式（full）、执行时机（立即）、修复范围（全部异常用例）、长耗时语义（Agent 自主优化不改行为）已与用户确认。
