## Context

全仓约 398 处 timezone 相关引用。存储层主流为 `now(timezone.utc)`（192 处），jsonl/STATE 时间戳带 `Z` 后缀（336 处）；但 72 处裸 `datetime.now()`（naive 本地）混入写侧（重灾区 `self_review.py` 19 处、`code_review.py` 6 处），读侧为消化歧义演化出 4 种矛盾 naive 解读策略（`regression.py` naive→本地；`dashboard/data/timeline.py`、`routes/code_review_routes.py` naive→UTC；`evolution.py` naive→本地→UTC），另有 aware→naive 本地的剥时区写入（`code_review.py:674`）。转换轮子重复 ≥8 份，`_iso_to_local_dt` 两份逐字重复。守卫基建已有先例：`tests/test_callsite_arity_guard.py` AST 扫描 + `tests/fenix_guards.py` 共享扫描器 + 白名单机制。本地时区展示是合法需求（knowledge 盖戳用户定调 2026-09-30 用本地；浏览器 dayjs 本地渲染正确）。

## Goals / Non-Goals

**Goals:**
- 单一时间原语模块 `core/timelib.py`，API 契约冻结后供 SPEC-B（全仓迁移）消费
- naive 解读唯一策略定音（按本地），消除 4 处矛盾
- AST 守卫棘轮上线：违例只能减不能增
- 重复解析轮子收拢为单源

**Non-Goals:**
- 存量写侧 72 处裸 `now()` 迁移（SPEC-B）
- `self_review.py` 本地 naive 气泡改造（SPEC-B；本 SPEC 仅收拢其解析助手，气泡语义不动）
- `.fenix/bin` 展示脚本统一（SPEC-B）
- 前端 36 处 dayjs、`verify_engine/browser.py` `timezone_id`（永不在范围）
- `.astimezone()` 禁用（首批不入守卫，dashboard 展示路由合法在用）
- 数据迁移脚本（本 SPEC 无数据迁移；timeline 域仅验读）

## Decisions

### D1 naive 按本地解读（推翻 timeline.py D2 的 naive→UTC）
理由：存量 naive 数据实测多数产自本地 `now()`（`self_review` 字段、外部/人工 marker，`regression.py` 注释已实证观察）；迁移完成后唯一 naive-UTC 生产者（`code_review.py` 剥时区写入）在 SPEC-B 迁改名单内，消亡后 naive=本地与实际数据分布一致。机器时区固定 Asia/Shanghai 无 DST，无换算陷阱。
备选「naive→UTC」：与「全链 UTC」字面一致，但 self_review 字段、外部 marker 会被错读 8 小时，需随每批迁移修数据——否决。
备选「严格拒绝 naive」：迁移脚本工作量翻倍且外部人工文件无法自动改写——否决。
**影响**：timeline 域 deferred findings 时间戳展示平移 8h；实现前以真实存量数据验读，差异清单留痕（spec Scenario 锁定）。

### D2 守卫为 AST 扫描测试而非 lint 工具链
项目无 ruff/flake8 配置；`test_callsite_arity_guard.py` 已确立 AST 扫描 + 白名单 + 共享扫描器 house style。扩展 `tests/fenix_guards.py`，新增 `tests/test_timelib_guard.py`。首批禁用模式从窄（4 类），`.astimezone()` 缓入——避免首日白名单过大导致棘轮失焦。
备选「引入 ruff 自定义规则」：引入新工具链依赖，违反 YAGNI——否决。

### D3 白名单僵尸条目检测
守卫对「白名单条目已无对应违例」报失败（不是警告）：无失败信号的收缩会被遗忘，名单虚胖后棘轮退化为摆设。每批迁移的收尾动作=收缩白名单+守卫通过。

### D4 parse_ts 失败返回 None 而非抛异常
与 dashboard 容错契约及现有 8 份私有解析器的多数行为（`_iso_to_local_dt`、`_parse_iso` 均返回 None）一致；需要异常语义的调用方极少且可 `parse_ts(x) if ... else raise` 包装。
备选「抛 ValueError + parse_ts_or 变体」：API 面翻倍，YAGNI——否决。

### D5 knowledge 盖戳助手留在 knowledge.py
盖戳格式（`(naive 串, "UTC+8" 后缀)` 元组、`> 最后更新：` 行格式）是知识域领域格式，不是通用原语；仅时间源改走 `timelib.now_local()`，输出逐字不变（spec Scenario 锁定）。
备选「把 local_now_stamp 移入 timelib」：领域格式污染通用模块——否决。

## Risks / Trade-offs

- [timeline D2 翻转改变该域展示时刻（平移 8h）] → 实现前真实数据验读 + 差异清单留痕 + spec Scenario 锁定验读动作；若验读发现该域写手实为 naive UTC 存量，升级为「该域数据先修正再切策略」，在 run 记录中申报
- [读侧统一后，依赖旧解读的下游隐式行为变化] → 4 处修改各自补 characterization 测试（同一输入新旧期望对照）后切换
- [`self_review` 气泡在收拢后与新 `parse_ts` 语义不一致（它内部 aware→naive 本地）] → 本 SPEC 只收拢解析、不动气泡；`_iso_to_local_dt` 转发实现保持逐字行为等价（spec Scenario 锁定等价性），气泡迁移留给 SPEC-B
- [守卫白名单基线统计口径与实际违例有出入（如 `datetime` 别名导入）] → AST 扫描按 `ast.Attribute` 链（`datetime.now`/`dt.now` 等接收者别名通配）判定，参考 arity-guard 的接收者表达式处理；上线首跑人工核对违例总数与 grep 口径（398 处大数内的裸 now 计数 72）一致性
- [timelib API 在 SPEC-B 迁移中发现缺口] → SPEC-B 以 ADDITIONAL requirement 扩展 timelib，不破坏本 SPEC 冻结的 6 函数契约

## Migration Plan

1. 落地 `core/timelib.py` + 单测（无消费方，零风险）
2. 守卫上线（白名单=当日存量违例全量，棘轮生效）
3. timeline 域真实数据验读 → 4 处读侧切 `parse_ts` + characterization 测试
4. 重复轮子收拢（`_iso_to_local_dt` ×2、`escalation._parse_ts`、`recovery._parse_event_timestamp`）
5. 守卫白名单首轮收缩（上述步骤消除的违例）
回滚：步骤 1-2 纯增量可直接 revert；步骤 3-4 每步独立提交，可单步回退。

## Open Questions

（无——naive 策略与分批节奏已于 2026-09-30 由用户定调；执行模式 full、立即调度）
