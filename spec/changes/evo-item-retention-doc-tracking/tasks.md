# 实现任务

## Deliverables

```yaml
- path: core/evolution.py
  kind: modify
- path: fenixd.py
  kind: modify
- path: core/dashboard/data.py
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: core/dashboard/static/src/pages/settings/components/SuggestedImprovementsPanel.tsx
  kind: modify
- path: tests/test_evolution_prune.py
  kind: new
- path: tests/test_dashboard_evolution_api.py
  kind: modify
- path: tests/test_self_evolution.py
  kind: modify
- path: core/dashboard/static/dist/index.html
  kind: reference
```

## 1. 条目保留与自动清理（core/evolution.py + fenixd.py）

- [ ] 1.1 `core/evolution.py`：新增模块级常量 `ITEM_RETENTION_DAYS = 7` 与 `ITEM_RETENTION_MIN = 100`，注释说明「保留最近 N 天 ∪ 最近 M 条，取较多数者」。
- [ ] 1.2 `core/evolution.py`：新增 `prune_items(project_root, now=None) -> dict`。用 `read_items` 取全量；按 `(created_at or "", id)` 倒序排序；保留集 = 前 100 名 ∪ 所有 `_parse_iso(created_at) >= now-7天` 的条目 ∪ `_parse_iso` 解析失败（含缺失）的条目；受害条目逐个调用既有 `delete_item(item_id, project_root)` 完成硬删。返回 `{"total", "kept", "deleted", "failed", "details"}`；无受害者时 MUST 直接返回、不触发任何写。**计数口径**：`delete_item` 以返回值（非异常）表达预期失败——`ok=False`（条目已被并发删除 / 草稿路径越界 / 草稿删除 `OSError`）时该记录 MUST NOT 计入 `deleted`，MUST 计入 `failed` 与 `details`，且 MUST NOT 从 `kept` 中移除（记录仍在 `items.jsonl`）。
- [ ] 1.3 `core/evolution.py`：`prune_items` 逐条删除各自 try/except（单条异常计入 `failed` 与 `details`，不中断其余）；同时按 1.2 的计数口径把 `delete_item` 返回的 `ok=False` 计入 `failed`；调用方传入的 `now` 为时区感知 datetime，缺省 `datetime.now(timezone.utc)`。
- [ ] 1.4 `fenixd.py`：在 `_check_evolution_checkpoint` 的宿主守卫（`PROJECT_ROOT.resolve() != FRAMEWORK_ROOT` 早退）**之后**、`_evolution_in_flight` 在途判定**之前**，调用 `prune_items(PROJECT_ROOT)`；调用自身 try/except 包裹，异常仅 `self.logger.error`，不得影响后续派发与主循环。
- [ ] 1.5 `fenixd.py`：清理结果 `deleted > 0 or failed > 0` 时记一条 INFO（含 `total` / `kept` / `deleted` / `failed` 与 `failed` 详情），仅 `deleted == 0 and failed == 0` 时不刷日志（满足 spec「失败 MUST 计数并记录可观测日志」——失败全部发生时不得因 `deleted == 0` 而被静默吞掉）；同步更新 `_check_evolution_checkpoint` docstring（补第 0 步「周期保留清理」）。
- [ ] 1.6 `tests/test_evolution_prune.py`（新建）：覆盖保留并集边界（>7 天且超出 100 名被删 / 7 天内多于 100 条时旧的被删 / 阈值内零删除）、`created_at` 缺失或非法时保留、未决状态（`pending`）同样被删、草稿目录随删除清理、单条删除异常不中断其余。
- [ ] 1.7 `tests/test_self_evolution.py`（扩展，复用既有 daemon 桩，见 `TestEvolutionWorkerFailureSemantics`）：新增检查点接入点回归——(a) `_evolution_in_flight = True` 时调用 `_check_evolution_checkpoint`，已过期受害条目仍被清理（对齐 spec 场景「清理不因分析 run 在途而跳过」）；(b) `PROJECT_ROOT != FRAMEWORK_ROOT` 时调用检查点，不触发任何清理（对齐 D4「非自托管部署自进化整套不启用」）。

## 2. SPEC 位置解析与文档回退（core/evolution.py + core/dashboard/data.py）

- [ ] 2.1 `core/evolution.py`：新增 `resolve_accepted_spec_dir(project_root, spec_name) -> Optional[Path]`。`spec_name` 不满足 `_KEBAB_RE` → `None`；`spec/changes/<spec_name>/` 是目录 → 返回活跃目录；否则遍历 `spec/archive/`，对每个目录名生成归一化候选集合（原样、剥 `^\d{4}-\d{2}-\d{2}-` 前缀、剥 `-\d+$` 后缀、两者都剥）并判定 `spec_name` **全等**命中，命中多个取 `sorted()[-1]`；无命中返回 `None`。MUST NOT 使用前缀匹配（防互为前缀的 spec 名误归属）。
- [ ] 2.2 `core/dashboard/data.py`：改造 `read_evolution_draft`——保持白名单校验与 404/400 分支不变；先按既有逻辑查草稿目录内目标文件，命中即读（既有行为不变）；未命中且 `rec.spec_name` 非空时调用 `resolve_accepted_spec_dir` 解析 SPEC 目录，按同一 `doc` 映射读取（`proposal`/`design`/`tasks` → 同名 `.md`；`spec` → `specs/<capability>/spec.md`，`capability` 取 `rec.spec.capability`，缺失或目录不存在时回退到唯一的能力子目录）。解析后目标路径 MUST 校验仍位于所解析目录内（`is_relative_to`），越界视为 `invalid_doc`；两条路径均无文件 → `{"found": False}`。
- [ ] 2.3 `core/dashboard/data.py`：更新 `read_evolution_draft` docstring，写明「草稿优先、SPEC 位置回退」与越界拒绝。
- [ ] 2.4 `tests/test_dashboard_evolution_api.py`（扩展）：新增用例——接受成功后草稿被删但 `spec/changes/<spec_name>/` 存在时四个 `doc` 均 `found: true` 且内容取自 SPEC 目录；归档到 `spec/archive/YYYY-MM-DD-<name>/`、`spec/archive/YYYY-MM-DD-<name>-<n>/`、`spec/archive/<name>-<epoch>/` 三形态均能命中（对齐 spec「归档后仍可跟踪文档位置」Scenario 枚举的三类命名）；`spec_name` 为另一条目 `spec_name` 的前缀时不相混（`found: false`）；既无草稿又无可解析 SPEC 时 `found: false`。

## 3. 列表摘要与前端渲染（core/dashboard/data.py + 前端）

- [ ] 3.1 `core/dashboard/data.py`：`read_evolution_items` 摘要新增 `doc_source` 字段——草稿目录存在 → `"draft"`；否则 `rec.spec_name` 能解析出 SPEC 目录 → `"spec"`；否则 `None`。保持既有字段（含 `has_draft`）不变。
- [ ] 3.2 `core/dashboard/static/src/services/dashboard.ts`：`EvolutionItem` 接口新增 `doc_source?: 'draft' | 'spec' | null;`（附注释说明来源）。
- [ ] 3.3 `core/dashboard/static/src/pages/settings/components/SuggestedImprovementsPanel.tsx`：文档页签渲染条件由 `hasDraft` 改为 `has_draft || doc_source !== null && doc_source !== undefined`（`doc_source === 'spec'` 时页签同样渲染）；空态文案按来源区分——`doc_source === 'spec'` 时文案说明读自 SPEC 位置，否则沿用既有草稿空态文案。分析结论页签行为不变。
- [ ] 3.4 `tests/test_dashboard_evolution_api.py`：断言列表摘要含 `doc_source`，且未接受条目（有草稿）为 `"draft"`、无草稿无 spec 的 `analyzed` 条目为 `null`（或键存在且为 `null`）。

## 4. 构建与验收

- [ ] 4.1 `python3 -m pytest tests/test_evolution_prune.py tests/test_dashboard_evolution_api.py -q` 全绿；`python3 -m pytest tests/test_dashboard_data.py -q` 无回归（`resolve_spec_dir` 语义未被改动）。
- [ ] 4.2 在 `core/dashboard/static` 执行 `npm install --no-audit --no-fund` 与 `npm run build` 成功，产物 `dist/` 可被既有静态服务加载（该目录为 gitignored 运行时产物，不入库）。
- [ ] 4.3 端到端实测：`GET /api/evolution/items` 的已接受条目 `doc_source` 为 `"spec"`，`GET /api/evolution/draft?item_id=<accepted-id>&doc=proposal` 返回 `found: true`（内容取自 `spec/changes/<spec_name>/proposal.md`）。
