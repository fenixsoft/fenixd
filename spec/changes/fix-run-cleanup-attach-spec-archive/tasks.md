# Tasks: fix-run-cleanup-attach-spec-archive

## Deliverables

```yaml
- path: core/agent_runner/run_files.py
  kind: modify
- path: core/dashboard/data/runs.py
  kind: modify
- path: core/dashboard/data/config_admin.py
  kind: modify
- path: core/dashboard/watcher.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: core/dashboard/data/timeline.py
  kind: modify
- path: docs/help/10-artifacts.md
  kind: modify
```

## 1. archive_spec_runs 升级为清理（挂靠 SPEC 归档）

- [ ] 1.1 `core/agent_runner/run_files.py`：`archive_spec_runs` 语义从
  「顶层移入 archive/」改为「该 SPEC 的 `*.jsonl` 从顶层与 `archive/`
  归档副本一并删除」——两处 glob 同名匹配（`run_spec_part` 全等）、逐文件
  删除记 INFO 日志、单文件 OSError 记 WARNING 继续其余、返回值改为清理
  文件数；模块 docstring 的产物保留语义段同步改写（清理绑定 SPEC 生命周期 +
  无主产物天龄兜底，详见 2.x）
- [ ] 1.2 单测（tests/ 下 run_files 归档清理相关用例）：顶层与归档副本两处
  均删除；其他 SPEC 产物零影响；单文件删除失败不阻断且日志可查；返回计数
  正确；`runs_dir` 不存在返回 0 的既有行为保持

## 2. 清扫器第 2 步替换为无主产物天龄兜底

- [ ] 2.1 `core/dashboard/data/runs.py`：删除 `_RETENTION_KEEP_DEFAULT`、
  `_resolve_runs_keep` 及 `runs_retention_check` 第 2 步的 keep 上限删除段；
  替换为：`_LANE_RUN_RETENTION_DAYS = 14` 常量，每周期扫描 `spec/changes/`
  目录名集合（现算不缓存），`archive/*.jsonl` 中 `run_spec_part(stem)` 不在
  活跃集且 mtime 超天龄者删除——活跃集扫描失败 fail-closed 跳过本轮兜底
  仅记 WARNING（防误删）；每周期删除量沿用批次上限；逐文件记日志
- [ ] 2.2 `runs_retention_check` docstring 与 runs.py:985-1000 模块注释的
  keep 语义改写为新语义（终态移入归档不变 + SPEC 归档清理 + 无主兜底）
- [ ] 2.3 单测：无主超龄删除、无主未超龄保留、活跃 SPEC 超龄产物保留、
  `spec/changes/` 扫描失败 fail-closed 不删任何文件、「终态 run 移入归档」
  行为不变、config 残留 `runs.keep` 键对行为零影响

## 3. config_admin 拆除 runs 受管键

- [ ] 3.1 `core/dashboard/data/config_admin.py`：`_MANAGED_KEYS` 去除
  `"runs"`；删除缺省展示（约 :426 `{"runs": {"keep": 50}}`）、读取回显
  分支（约 :653-662）、生效回显分支（约 :894-899）、写入分支
  （约 :1042-1050）四处 runs 键处理
- [ ] 3.2 单测：配置补丁含 `runs` 键被忽略不落盘不回显；其余受管键正常
  应用与回显；回显结果不含 `runs` 键

## 4. 注释与文档语义更正

- [ ] 4.1 语义引用点注释更正：`core/dashboard/watcher.py:35/307`、
  `core/admin_monitor.py:3510`、`core/dashboard/data/timeline.py:340`
  （「旧 spec 的 run 产物被清理后时间轴仍可回看」改为「SPEC 归档后运行
  节点随产物清理消失，归档前全程可回看」口径）
- [ ] 4.2 `docs/help/10-artifacts.md`「.fenix/runs/ 运行记录」章节的归档
  保留语义更正为新语义；grep docs/help 全域确认无 `runs.keep` 残留记载

## 5. 回归防护

- [ ] 5.1 grep 全仓测试代码与替身中 `runs.keep`、`_RETENTION_KEEP_DEFAULT`、
  `_resolve_runs_keep` 旧键残留并清理（memory 先例：配置单源迁移必须查
  测试替身旧键）
- [ ] 5.2 相关测试套件全绿：runs/spec_archive/config_admin/run_files 归档
  清理相关测试 + 受影响面冒烟（`archive_spec` 调用链）
