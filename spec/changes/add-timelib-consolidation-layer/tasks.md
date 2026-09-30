## Deliverables

```yaml
- path: core/timelib.py
  kind: new
- path: tests/test_timelib.py
  kind: new
- path: tests/test_timelib_guard.py
  kind: new
- path: tests/fenix_guards.py
  kind: modify
- path: core/regression.py
  kind: modify
- path: core/dashboard/data/timeline.py
  kind: modify
- path: core/dashboard/routes/code_review_routes.py
  kind: modify
- path: core/evolution.py
  kind: modify
- path: core/code_review.py
  kind: modify
- path: core/self_review.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: core/pm_engine/verification/escalation.py
  kind: modify
- path: core/pm_engine/recovery.py
  kind: modify
- path: core/knowledge.py
  kind: modify
- path: core/knowledge_backfill.py
  kind: modify
```

## 1. timelib 模块与单测

- [x] 1.1 新建 `core/timelib.py`：实现 `now_utc` / `now_local` / `parse_ts` / `from_epoch` / `to_storage` / `fmt_display` 六函数，零第三方依赖，模块 docstring 写明分层约定（存储/计算=aware UTC，渲染边界=本地）与 naive 唯一策略（按本地解读，定调 2026-09-30）
- [x] 1.2 新建 `tests/test_timelib.py`：覆盖 spec 全部场景——now_utc tzinfo 断言、to_storage Z 后缀与本地输入换算（`2026-09-30 10:33 +08:00` → `2026-09-30T02:33:00Z` 形态）、fmt_display 本地换算、parse_ts 的 naive→本地 / `Z` 与 `+00:00` 等价 / 纯日期串 / 非法串与 `None` 与空串返回 `None`

## 2. AST 守卫棘轮上线

- [x] 2.1 扩展 `tests/fenix_guards.py`：新增时间禁用模式扫描器（按 `ast.Attribute` 链判定，兼容 `datetime`/`dt` 等接收者别名）：零参 `datetime.now()`、`datetime.utcnow()`、零/单参 `datetime.fromtimestamp()`、`datetime.utcfromtimestamp()`、timelib 之外的 `datetime.fromisoformat()`；排除 `tests/` 与 vendored 目录
- [x] 2.2 新建 `tests/test_timelib_guard.py`：白名单机制（最小粒度语义键，不含行号，套 arity-guard 先例）、`core/timelib.py` 全豁免、僵尸条目检测（白名单条目无对应违例即失败）、白名单基线=扫描当日全部存量违例
- [x] 2.3 守卫首跑核对：AST 扫描违例总数与 grep 口径（全仓裸 `datetime.now()` 72 处量级）交叉比对，偏差条目逐个归因后把核对结论写入守卫测试 docstring

## 3. 读侧四处切换与验读

- [x] 3.1 timeline 域写手格式验读：从 `code_review.py` 剥时区写入链（`_iso_to_local_dt` 消费方）与 timeline 写手代码提取实际序列化格式，构造覆盖 naive 本地 / naive UTC / `Z` / `+00:00` 四形态的数据集，新旧解析逐条对照，差异清单写入测试注释
- [x] 3.2 `core/dashboard/data/timeline.py` `_parse_iso_ts` 改走 `timelib.parse_ts`（推翻 D2 naive 补 `tzinfo=utc` 为 naive→本地），下游排序/展示行为以 characterization 测试锁定前后对照
- [x] 3.3 `core/regression.py` 守卫解析（`started.astimezone()` 两处）改走 `timelib.parse_ts`，替换后 stale 判定行为以测试锁定
- [x] 3.4 `core/dashboard/routes/code_review_routes.py` naive 补 `tzinfo=utc` 分支改走 `timelib.parse_ts`，路由解析行为以测试锁定
- [x] 3.5 `core/evolution.py` `_parse_iso` 改走 `timelib.parse_ts`（内部 naive 附本地 tzinfo 逻辑删除），归一化行为以测试锁定

## 4. 重复轮子收拢与盖戳时间源

- [x] 4.1 删除 `core/code_review.py` 与 `core/self_review.py` 的逐字重复 `_iso_to_local_dt`，解析内核改走 `timelib.parse_ts` 并保留 naive 本地收尾（`parse_ts(x).astimezone().replace(tzinfo=None)` 或等价薄包装——现状返回 naive 本地，窗口边界为 naive `datetime.now()`，MUST NOT 把 aware 值直接接入比较）；`self_review.py` 窗口比较气泡语义不动
- [x] 4.2 `core/pm_engine/verification/escalation.py` `_parse_ts` 与 `core/pm_engine/recovery.py` `_parse_event_timestamp`、`core/agent_runner/runner.py` `_parse_event_timestamp`（recovery 注释锁定的同口径副本）的 ISO 解析内核改走 `timelib.parse_ts`：epoch 数值分支与 bool 排除保留（`parse_ts` 不收数值）；aware 输入行为不变，naive 输入按新策略（本地）解读为**有意行为变化**（推翻 escalation「朴素→UTC 与 AdminStore 一致」及 runner/recovery fc528d7216ed 注释，同步更新注释）；实现时核查 admin_store 信号/处置记录与 run 事件是否实际含 naive 时间戳并留痕（admin_store 写侧 `now(timezone.utc).isoformat()` 恒为 aware，naive 仅可能来自人工修补/外部工具）；既有测试若锁定 naive→UTC 需随策略更新
- [x] 4.3 `core/knowledge.py` `local_now_stamp` 与 `core/knowledge_backfill.py` `_now_local_parts` 时间源改走 `timelib.now_local()`，输出格式逐字不变（盖戳行格式断言测试锁定）

## 5. 白名单收缩与全量回归

- [x] 5.1 守卫白名单首轮收缩：清除步骤 3/4 消除的全部违例条目，僵尸条目检测通过
- [x] 5.2 全量单测回归（`python3 -m pytest tests/ -x -q`）通过，重点确认 timeline 排序、regression stale 守卫、escalation/recovery 解析、knowledge 盖戳四域测试绿
