## Why

全仓约 398 处 timezone 相关引用中，存储层主流是 `now(timezone.utc)`（192 处），但 72 处裸 `datetime.now()`（naive 本地）混入写侧；读侧为消化由此产生的歧义，演化出 **4 种互相矛盾的 naive 解读策略**（`regression.py` naive→本地、`dashboard/data/timeline.py` 与 `routes/code_review_routes.py` naive→UTC、`evolution.py` naive→本地再转 UTC），且转换轮子重复 ≥8 份（`_iso_to_local_dt` 在 `code_review.py`/`self_review.py` 逐字重复）。两个文件的注释各自引用相反的「项目约定」为自己背书——混乱已被制度化，日志分析与时间展示反复出现 8 小时偏差困惑。

## What Changes

- 新增 `core/timelib.py`：全框架唯一时间原语模块（零第三方依赖），提供 `now_utc` / `now_local` / `parse_ts` / `from_epoch` / `to_storage` / `fmt_display`
- 固化分层约定：存储与计算层一律 aware UTC；本地时区只出现在渲染边界（CLI 展示、knowledge 盖戳、浏览器 dayjs）
- 读侧 naive 解读策略定音：`parse_ts` 对无时区后缀时间戳**统一按本地时区解读**（定调 2026-09-30，依据：存量 naive 数据实测多数产自本地 `now()`）
- 修复 4 处矛盾读侧：`regression.py` / `dashboard/data/timeline.py` / `routes/code_review_routes.py` / `evolution.py` 的时间解析改走 `parse_ts`
- 新增 AST 静态守卫 `tests/test_timelib_guard.py`（套 `test_callsite_arity_guard.py` house style）：禁裸 `datetime.now()` / `datetime.utcnow()` / 裸 `fromtimestamp()` / timelib 之外的 `fromisoformat()`；白名单=上线当日全部存量违例，棘轮式只许收缩
- 删除重复转换轮子：`code_review.py` 与 `self_review.py` 的 `_iso_to_local_dt` 逐字重复副本改走 `parse_ts`

**明确不在本 SPEC 范围**（由后续 SPEC「全仓时间调用点迁移」承接）：存量写侧 72 处裸 `now()` 及其余调用点迁移、`self_review.py` 本地 naive 气泡改造、`.fenix/bin` 展示脚本统一。前端 36 处 dayjs 与 `verify_engine/browser.py` 的 `timezone_id`（playwright 语义）永不在任何批次范围内。

## Capabilities

### New Capabilities
- `timelib-consolidation`: 唯一时间原语模块的 API 契约、分层约定（存储=aware UTC / 渲染=本地）、naive 解读唯一策略、AST 守卫棘轮机制

### Modified Capabilities

（无——归档 spec `2026-09-22-fix-deferred-findings` 只锁 TypeError 排序行为，未将 naive→UTC 定为 requirement 级约束，本 SPEC 推翻该实现注释不构成能力需求变更）

## Impact

- **新文件**：`core/timelib.py`、`tests/test_timelib_guard.py`
- **修改**：`core/regression.py`、`core/dashboard/data/timeline.py`、`core/dashboard/routes/code_review_routes.py`、`core/evolution.py`、`core/code_review.py`、`core/self_review.py`（仅删除重复助手改转发，不动窗口气泡逻辑）、`tests/fenix_guards.py`（共享扫描器扩展）
- **行为变化（有意）**：`timeline.py` 的 fix-deferred-findings D2「naive 补 `tzinfo=utc`」被推翻为 naive→本地——该域 deferred findings 时间戳展示平移 8 小时；实现前 MUST 用真实存量数据验读确认实际写手格式，差异点逐个列清
- **兼容性**：`parse_ts` 失败返回 None（house 容错风格）；`knowledge.py` 本地盖戳行为一字不变（时间源改走 `now_local()`，输出格式不变）
- **无 UI、无数据迁移、无第三方依赖**
