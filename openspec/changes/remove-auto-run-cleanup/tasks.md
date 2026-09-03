# Tasks — remove-auto-run-cleanup

## Deliverables

```yaml
- path: core/agent_runner/run_files.py
  kind: modify
- path: core/agent_runner/__init__.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: core/agent_runner/liveness.py
  kind: modify
- path: core/dashboard/data.py
  kind: modify
- path: bin/fenix_archive.py
  kind: modify
- path: core/dashboard/static/src/pages/settings/components/MiscSettingsPanel.tsx
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: core/dashboard/static/dist/index.html
  kind: modify
- path: tests/test_dashboard_index.py
  kind: modify
- path: tests/test_run_artifact_retention.py
  kind: new
```

## 1. 后端：run_files.py 新增归档原语

- [x] 1.1 将 `core/dashboard/data.py` 的 `_run_spec_part` 迁至 `core/agent_runner/run_files.py`，公开名 `run_spec_part(run_id) -> str`（逻辑逐行保持：前缀剥离表 `-a<n>`/时间戳正则不变）；data.py 删除原实现并改为 `from core.agent_runner.run_files import run_spec_part`，原 `_run_spec_part` 调用点全部改用新名
- [x] 1.2 在 `run_files.py` 新增 `archive_spec_runs(runs_dir: Path, spec_name: str) -> int`：仅 glob 顶层 `*.jsonl`，`run_spec_part(p.stem) == spec_name` 的文件移入 `runs_dir/archive/<同名>`（archive 先 `mkdir(parents=True, exist_ok=True)`）；目标同名已存在时删除顶层副本（归档侧为准）；单文件 OSError 记 warning 继续，返回成功移动数；`runs_dir` 不存在返回 0；不删除任何其他文件
- [x] 1.3 删除 `run_files.py` 的 `clean_old_runs` 与 `RUNS_KEEP` 常量；`core/agent_runner/__init__.py` 导出、`runner.py` 门面转导同步（`clean_old_runs`/`RUNS_KEEP` 移除，新增 `run_spec_part`/`archive_spec_runs`）；`liveness.py` 删除未使用的 `clean_old_runs`/`RUNS_KEEP` import

## 2. 后端：移除自动清理链路

- [x] 2.1 删除 `core/dashboard/data.py` 的 `cleanup_runs`、`_CLEANUP_RUNS_INTERVAL`/`_CLEANUP_RUNS_LAST` 节流常量、模块级 `RUNS_KEEP`（~29 行）及 `from core.agent_runner import clean_old_runs` import；删除 `project_summary` 内唯一调用点（~1679 行 `cleanup_runs(proot)`）
- [x] 2.2 删除 `data.py` 中 `runs.keep` 的配置读取与溯源映射（`ConfigLoader.get(effective, "runs.keep", ...)` 残段、`sources["runs.keep"]`、~2377 行 `"runs.keep"]` 引用）；确认全库无 `cleanup_runs` 生产引用残留

## 3. 后端：spec 归档挂钩

- [x] 3.1 `bin/fenix_archive.py` 的 `archive_change()`：change 目录 `shutil.move` 成功后，`sys.path.insert(0, str(project_root))` 并 `from core.agent_runner.run_files import archive_spec_runs`，对 `project_root/.fenix/runs` 执行 `archive_spec_runs(runs_dir, <name>)`；成功时返回 dict 追加 `"runs_archived": <n>`，OSError/ImportError 时追加 `"runs_archive_warning": "<msg>"` 且不改变归档成功语义（fail-open，design D4）

## 4. 配置 UI 下线

- [x] 4.1 `core/dashboard/static/src/pages/settings/components/MiscSettingsPanel.tsx`：删除「运行产物保留数量（runs.keep）」输入项及其 state/提交字段；`core/dashboard/static/src/services/dashboard.ts` 同步删除 runs.keep 类型/注释（~499 行）
- [x] 4.2 重建前端产物并提交：`cd core/dashboard/static && npm run build`（输出 `static/dist/`），确认 dist 内 bundle 已无 `runs.keep` 字样（中文在 bundle 中为 \uXXXX 转义，用 `runs.keep` ASCII 串 grep 验证）

## 5. 测试

- [x] 5.1 `tests/test_dashboard_index.py`：删除 `cleanup_runs` 相关 4 处用例（~234-249 行附近）；全库 grep（排除 `.claude/worktrees/`、`openspec/changes/archive/`、`node_modules/`、`dist/`、`__pycache__/`）确认 `clean_old_runs`/`RUNS_KEEP`/`cleanup_runs` 在 core/、bin/、tests/ 零残留
- [x] 5.2 新增 `tests/test_run_artifact_retention.py`：① `run_spec_part` 对 `impl-<spec>-<ts>-a1`/`planner-plan-<spec>-<ts>`/`admin-<spec>-<ts>` 等格式还原 spec 名（与原 data.py 测试期望一致）；② `archive_spec_runs` 只移匹配文件、不匹配的留顶层、返回移动数、runs_dir 不存在返回 0；③ `archive_change` 集成：归档带 3 个该 spec runs 的假项目后 runs 进 archive、change 目录进 archive/YYYY-MM-DD-<name>、返回 dict 含 `runs_archived`
- [x] 5.3 全量 `python3 -m pytest tests/ -x -q` 通过（daemon 端口占用的环境性失败可跳过并注明）

## 6. 验证（真实环境）

- [x] 6.1 哨兵存活：临时向 `.fenix/runs/` 放 3 个 mtime 较早的假 `z-verify-*.jsonl` 使总数远超 50，连续触发 8787 的 `/api/projects`、overview、spec 详情 API ≥3 轮，确认哨兵与既有文件全部存活、目录零变化；验证后移除哨兵
- [x] 6.2 设置页 UI：浏览器打开 8787 设置页「其他」分类，确认无「运行产物保留数量」输入项、页面无 console error（截图存 `.history/`）
- [x] 6.3 归档联动真实验证：造一个含 run 产物的临时假 spec（假项目或测试沙箱），执行 `fenix_archive.py` 归档，浏览器确认该 spec 时间轴数据仍可读、runs 顶层文件已移入 archive/

> 验证备注（2026-09-03 fast-track）：6.1/6.2/6.3 的聚合 API 与 UI 验证在 worktree 自起实例 :18901 + 沙箱夹具项目执行，未打主树 :8787——常驻实例为旧码，会执行已删除的 cleanup 逻辑污染/破坏哨兵（见 2026-09-03 runs 删空事故）。哨兵置于沙箱而非真实项目，验证后随沙箱移除，真实项目 runs 零触碰。
