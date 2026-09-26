## Deliverables

```yaml
- path: core/dashboard/routes/architecture_routes.py
  kind: modify
- path: tests/test_dashboard_architecture_api.py
  kind: modify
```

## 1. 阶段 prompt 与 evidence 基础设施

- [ ] 1.1 新增 `_build_explore_prompt(proot, project_name)`：~1KB 探索 prompt——四项取证维度（核心组件/主链路/外部依赖/信任边界）、evidence.md 写盘绝对路径（`.fenix/architecture/evidence.md`）、`ARCHIFY_EVIDENCE_DONE` marker 契约；不注入 archify SKILL.md 全文
- [ ] 1.2 新增 `_build_author_prompt(proot, project_name)`：~2KB 出图 prompt——以包根绝对路径引用 `vendor/archify/SKILL.md`（指示先读再开工，不内嵌全文）、evidence.md 绝对路径、五项形态约束（8–16 组件/单主路径/外部依赖与信任边界/说明卡片/中文）、候选 JSON 分段小步写纪律（先骨架后逐段 Edit，禁单次巨量 Write）、`ARCHIFY_DONE <组件数>` marker 契约
- [ ] 1.3 新增 evidence HEAD 指纹 helper：写入 evidence.md 头部（HEAD sha + UTC 时间戳）、读取比对当前 repo HEAD（**以目标项目根 `proot` 为 cwd** 执行 `git rev-parse HEAD`——daemon 进程 cwd 与 proot 不同，禁止用进程 cwd 取 HEAD；容错 detached/非 git 项目/命令异常一律返回不匹配）、evidence 缺失/损坏/无指纹头一律判不匹配

## 2. 两阶段生成编排

- [ ] 2.1 `_run_generation` 改顺序两阶段：**vendored archify 包完整性检查保留在编排最前（先于阶段1 spawn，两段共用一次检查，既有失败文案不变）**；refresh 受理时 evidence 存在且 HEAD 一致则跳过阶段1；否则 spawn 阶段1（`_build_explore_prompt`），阶段1 判定（returncode==0 且 evidence 非空）通过后 spawn 阶段2（`_build_author_prompt`）；阶段1 失败直接 failed 短路，不 spawn 阶段2
- [ ] 2.2 超时拆分：新增 `_EXPLORE_TIMEOUT_SECONDS = 720` / 保留 1800s 总额改阶段2 `_AUTHOR_TIMEOUT_SECONDS = 1080`；每段独立 `communicate(timeout=...)` + 超时进程组 SIGKILL 击杀（既有 killpg 范式）；error 文案区分阶段（「阶段1 探索超时（>720s 未完成）…」/「阶段2 出图超时（>1080s 未完成）…」）
- [ ] 2.3 status `stage` 键：`_status_payload` 增可选键 `stage`（阶段1 运行中 `"exploring"`、阶段2 运行中 `"authoring"`、终态 null），沿用 tmp+os.replace 原子写；存量六键字段名与语义不变
- [ ] 2.4 移除旧单体 `_build_prompt` 或收敛为阶段2 builder 的内部复用，确保仓库内无残留调用（含本文件与测试引用点）

## 3. 测试改造与回归

- [ ] 3.1 存量用例改造：fake spawn 按 prompt 内容区分阶段（prompt 含 `ARCHIFY_EVIDENCE_DONE` 即阶段1、含 `ARCHIFY_DONE` marker 契约即阶段2）；`test_invocation_shape_and_env` / `test_timeout_kills_process_group` / `test_artifact_missing_claimed_done_failed` / `test_component_count_out_of_range_failed` / `test_retry_after_failure_overwrites_error` / `test_prompt_contains_skill_md_fulltext_and_package_root`（改为断言「不内嵌全文+含绝对路径引用」）等适配两段语义
- [ ] 3.2 新增用例：HEAD 一致跳过阶段1（只 spawn 一次）/ HEAD 变化重探索（spawn 两次）/ evidence 缺失·损坏·无指纹头重探索 / 阶段1 非零退出或 evidence 空文件短路 failed 且不 spawn 阶段2 / 阶段1 与阶段2 各自超时击杀且 error 文案含阶段前缀 / stage 字段两段运行时取值与终态 null
- [ ] 3.3 `pytest tests/test_dashboard_architecture_api.py` 全绿（含存量 16 例改造后语义等价），并跑通交付物守卫的声明 lint 预检（Deliverables 声明路径与本仓库布局 `core/`、`tests/` 一致）
