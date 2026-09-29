## Deliverables

```yaml
- path: core/state_machine.py
  kind: modify
- path: core/dashboard/data/state.py
  kind: modify
- path: core/dashboard/data/spec_archive.py
  kind: modify
- path: core/dashboard/routes/spec_routes.py
  kind: modify
- path: core/evolution.py
  kind: modify
- path: bin/fenix_archive.py
  kind: modify
- path: tests/test_archive_state_migration.py
  kind: new
```

## 1. 迁出原语与清单解析

- [x] 1.1 `core/state_machine.py` 新增 `evict_spec(name, archived_by) -> dict`：在 `.STATE.md.lock` 的 flock 内重读校验（条目在且终态），先追加写入 `.fenix/STATE.archive.md`（条目 + `archived_at` UTC ISO + `archived_by`，清单同名条目已存在时整体重写覆盖不产生重复小节，写入含 fsync），再经 `_write_all_locked` 重写 STATE.md 移除该条目；清单写入失败返回失败且 STATE.md 不动，条目不存在返回 `found: False` 幂等（design D2）
- [x] 1.2 `core/dashboard/data/state.py` 抽取 STATE.md 条目解析公共循环，新增 `parse_archived_state(project_root) -> dict`（同格式解析 `.fenix/STATE.archive.md`，文件缺失返回空 dict），`parse_state` 改为复用公共循环且行为不变
- [x] 1.3 单测（`tests/test_archive_state_migration.py`）：迁出后活跃条目消失且清单含溯源字段；清单写入失败（monkeypatch 抛 OSError）条目保留在 STATE.md；重复迁出幂等；清单缺失时首迁创建、解析返回空；活跃状态流转（update_spec）不触碰清单文件内容与 mtime

## 2. 三条归档路径收口

- [x] 2.1 `core/dashboard/data/spec_archive.py` 的 `archive_spec` 增加 `archived_by` 参数（缺省 `ui`），目录移动成功后调用 `evict_spec`，迁出失败在返回 dict 追加 `evict_warning` 字段（不回滚移动、不改 ok 语义）；`auto_archive_check` 调用处传 `archived_by="auto"`，跳过/成功日志含迁出结果
- [x] 2.2 `core/dashboard/routes/spec_routes.py` 归档 API 响应透传 `evict_warning`（存在时）；归档成功日志含迁出结果
- [x] 2.3 `bin/fenix_archive.py` 目录移动成功后 import StateMachine 调用 `evict_spec(name, "cli")`：STATE 无条目时输出说明性字段（如 `state_evicted: false`），迁出异常 fail-open 为输出告警字段不报错退出（与既有 `commit_archive_move` 同风格）
- [x] 2.4 单测：三条路径归档成功后 STATE.md 无该条目且清单含对应 `archived_by`（`auto`/`ui`/`cli`）；归档被拒（目标已存在/非终态）不迁出；`bin/fenix_archive.py` 对 STATE 无条目的 change 归档成功不报错

## 3. 读侧双源口径

- [x] 3.1 `core/dashboard/data/spec_archive.py` 的 `is_spec_archived` 改为「活跃目录不存在 且（`parse_state` 或 `parse_archived_state` 有条目）」，保持「目录存在短路返回 False」的性能路径
- [x] 3.2 `core/dashboard/routes/spec_routes.py` 的 `_api_specs` 合并 `parse_archived_state` 条目（同名单活跃侧优先，清单条目 `archived=true` 并透传 `archived_at`/`archived_by`），清单条目复用既有 `spec_summary` 组装（文档/进度经 `resolve_spec_dir` 归档回退）
- [x] 3.3 `core/evolution.py` 候选名撞名检查（约 1130 行 `candidate in read_all()`）并入 `parse_archived_state` 键集
- [x] 3.4 单测：迁出条目 `is_spec_archived` 仍为 True；`/api/specs` 已归档视图含迁出条目且字段齐全、未归档视图不含、双源同名单不重复行；evo 候选名与清单条目同名时触发改名后缀

## 4. 存量回填与软删除兼容

- [x] 4.1 `core/dashboard/data/spec_archive.py` 新增 `backfill_archived_entries(project_root, logger) -> dict`：扫描活跃 STATE 中「终态 + 活跃目录不存在」条目逐个 `evict_spec(name, "backfill")`，单条失败跳过记日志返回计数；非终态孤儿条目跳过并记日志
- [x] 4.2 把回填挂到 `auto_archive_check` 的既有周期触发处（先回填后阈值归档），不受 `auto_threshold` 开关约束（阈值 0 仍回填）
- [x] 4.3 `soft_delete_spec` 的 `found` 判定改为活跃 STATE 或清单有条目；条目仅在清单时清理清单小节，双源并存时两处都清，归档目录移除逻辑不变；清单小节移除在 `.STATE.md.lock` 的 flock 内执行（与迁出/回填写侧同锁，避免并发竞态）
- [x] 4.4 单测：回填批量迁出 archived_by=backfill、重复执行第二轮零迁出、非终态孤儿保留；阈值 0 时回填仍执行；软删除对仅清单条目与双源条目的清理行为

## 5. 既有用例修订与全量验证

- [x] 5.1 修订 `tests/test_spec_archive.py`、`tests/test_state_machine.py` 中断言「归档后条目保留/STATE.md 不变」的既有用例至新行为（迁出语义）
- [x] 5.2 全量 `pytest` 通过（注意 basetemp/工作区隔离既有约定，禁读构建产物）
- [x] 5.3 dashboard 假项目 fixture 端到端验证：伪造含已归档条目的项目（活跃目录缺失 + STATE 条目）→ 触发回填 → `/api/specs` 已归档视图可见迁出条目、详情文档可读、Overview 统计仅含活跃条目（截图与响应体取证存 `.history`）

## 验证修复（原地打回第 1 轮）

- [ ] 先复核失败有效性：逐条核对 `spec/changes/add-archive-state-migration/verification-report.md` 中失败场景的期望断言（状态字面量/选择器/前置数据）与产品实际行为是否相符——断言与产品不符属场景缺陷，修场景文件；确属产品行为不符才修产品代码
- [ ] 按复核结论修复：场景缺陷改场景文件，真实产品 Bug 改产品代码
- [ ] 修复后重跑验证确认通过
