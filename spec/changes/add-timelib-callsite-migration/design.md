## Context

SPEC-A `add-timelib-consolidation-layer`（2026-09-30 立项）交付 `core/timelib.py` 六函数 API、分层约定、AST 守卫棘轮（白名单=上线当日存量违例）与读侧四处 naive 策略统一（naive→本地）。本 SPEC 承接其明确划出的遗留面：存量调用点迁移。探索盘点（2026-09-30）：写侧裸 `datetime.now()` 41 处/13 文件、裸 `fromtimestamp()` 16 处/11 文件、绕过收拢层的 `fromisoformat()` 13 文件、CLI `_local_ts` 私有助手 2 份。`.fenix/bin` 为未跟踪部署副本（`bin/` 为跟踪真身，当前内容同步）。

## Goals / Non-Goals

**Goals:**
- 守卫白名单清零，棘轮进入「零豁免」稳态
- 写侧零 naive 产出（持久化字段全 aware UTC）
- `self_review` naive 气泡迁 aware UTC，窗口/调度判定等价
- CLI 展示脚本时间原语统一

**Non-Goals:**
- 前端 dayjs、`verify_engine/browser.py` `timezone_id`（永不在范围）
- `.astimezone()` 渲染边界转换（未列入禁用模式，dashboard 展示路由保留）
- 存量 naive 数据的批量改写（历史 jsonl/台账按 naive→本地策略兼容读取，不做数据迁移；个别域如发现旧数据错读，另行立项）
- knowledge 盖戳时间源（SPEC-A 已迁，输出格式不变）
- 任何行为变化（窗口阈值/超时/边界/字段名）——发现即申报，另行走 SPEC

## Decisions

### D1 分五批迁移，每批独立提交可回滚
批序按风险与依赖排：① self_review 气泡（最重、语义最敏感、用户级配置敏感测试区）→ ② agent_runner 域 + `fenixd.py`（runner/liveness/provider_circuit/prompt_builder/latency）→ ③ pm_engine + admin/store 域（engine/backoff/pipeline/admin_store/state_machine/admin_monitor/tui_format/alert_routes）→ ④ dashboard data + 散点收尾（summary/spec_archive/runs/artifacts/code_review/evolution/regression/worktree_manager）→ ⑤ bin CLI 展示 + 白名单清零。
备选「单批大爆炸」：20 文件一次合入，回归窗口长且难定位——否决（与 SPEC-A 同理由，用户已定调分批）。

### D2 调度语义边界：本地墙钟解析后立即转 aware UTC
`HH:MM` 配置是人类时刻（用户在 UTC+8 语境下写 `23:00` 期望本地 23 点触发）。解析处（`_parse_run_at` 等）按本地墙钟构造后立刻 `.astimezone(timezone.utc)` 或直接用 `now_local()` 对齐，窗口计算全 aware UTC。配置字面值不变，SPEC Scenario 锁定等价性。
备选「窗口计算保持 naive 本地」：与全层 aware UTC 约定冲突，且下次时间运算仍需换算——否决。

### D3 `.fenix/bin` 部署副本刷新走人工登记
`.fenix/bin/` 未跟踪（`git ls-files` 空）且非 gitignored——worktree 内改动不随 merge-back 落地，属「主树专属写操作」，Agent 不可交付。真身 `bin/*.py` 修改后，刷新步骤登记 `.fenix/todo.md`（或 docs help 人工步骤节）。符合声明 lint 的 reference 语义与 §3.2.1 任务粒度规则。
备选「把 .fenix/bin 纳入跟踪」：改变框架部署模型，超出本 SPEC 职权——否决。

### D4 白名单清零是机械验收口径，不是估算口径
迁移完成性以守卫白名单空集 + 僵尸检测全绿为唯一机械判据；本 SPEC 的文件清单是 2026-09-30 盘点快照，激活时以守卫白名单实际内容为准（若 SPEC-A 期间有新增违例，一并迁移）。任务分配按域不按计数，避免与白名单漂移打架。

### D5 测试同步逐域核对，警惕用户级配置敏感区
自省窗口/调度测试为用户级配置敏感区（`daily_self_review`/billing 空表同源教训）；每批迁移 MUST 同步 grep 该域测试替身的旧时间戳格式（naive 串、`ts[:19]` 切片、`fromtimestamp` 构造），替身与生产同批迁移，防「替身没跟着改」的假失败/假通过。

## Risks / Trade-offs

- [self_review 气泡迁移触碰窗口判定回归（自省报告错误聚合窗口）] → 等价性 Scenario 锁定（同数据同配置命中集合相同）+ characterization 测试先行（迁移前固化现行为）+ 单批独立提交
- [aware UTC 落盘后，外部消费方（人读日志、脚本切片）看到后缀变化] → `parse_ts`/`fmt_display` 已兼容；人读场景靠 CLI `fmt_display` 兜底；对话转述规则已有记忆约定（先转本地再展示）
- [SPEC-A 实现期 timelib API 微调导致本 SPEC 任务措辞漂移] → 激活前以 SPEC-A 归档态为准刷新本 SPEC tasks（`--modify`）；设计按域分批不绑具体函数签名
- [ bin 展示输出格式回退事故复现（2026-09-03 a78215d 同类）] → Scenario 锁定三形态输入输出逐字一致；`_local_ts` 退役前先并行跑一轮对照
- [20 文件迁移横跨多域，review 面大] → 五批独立提交，每批 diff 自含域内；批间无共享文件（self_review 除外，已单列批①）

## Migration Plan

1. 批① self_review 气泡：characterization 测试固化现行为 → 迁 aware UTC → 测试同步 → 白名单收缩
2. 批②~④ 按域重复「迁移→域测试→白名单收缩」循环
3. 批⑤ bin CLI 统一 + 白名单清零 + 僵尸检测全绿 + 全量回归
4. 人工步骤：`.fenix/bin` 部署副本刷新（登记 todo.md）
回滚：每批独立提交可单批 revert；白名单收缩与迁移同批提交，revert 一并还原。

## Open Questions

（无——分批节奏 2026-09-30 用户定调；激活前置 = SPEC-A 归档，调度档=手工激活）
