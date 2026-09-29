<!-- knowledge: capability=artifact-path-autofill rev=1 sources=spec/archive/2026-09-23-fix-artifact-paths-hardcoded-default -->

# 构建产物路径自动探测与起草

产物路径配置的自动化闭环：setup 探测预填、运行期未裁决信号、Administrator 起草收口，保证判定器两键总可被裁决。

## 现行规则

- setup 预填：`fenix-setup` 初始化流程探测项目构建产物路径并写入 `.fenix/config.yaml` 的 `worktree.has_build_artifacts` 与 `worktree.build_artifact_paths`。探测信息源至少含 `package.json` 的 `scripts`、`pyproject.toml`、项目目录结构（`dist/`/`build/`/`public/`/`static/` 等）。
- setup 幂等与降级：探测信息不足或失败不阻塞后续步骤，两键留空（交运行期兜底起草）；`worktree.has_build_artifacts` 已在配置中显式存在时跳过（不覆盖人工设置）；写入经 `.fenix/config.yaml` 合并（存在则更新对应键，不存在则跳过）。
- 运行期起草信号：merge-back 的 WIP 重叠闸门（`_wip_overlap_gate`）检测到产物配置未裁决（见 `artifact-path-declaration` 的三态语义）时，写信号 `build_artifact_paths_missing` 呼叫 Administrator 起草。触发点在该方法「无重叠即早退」分支**之前**（主树干净是常态，判定不得被早退跳过）；信号带 `spec` 字段，evidence 另附「项目名=<name>」冗余证据，摄取侧对无 spec 形态支持从 evidence 解析；已裁决（`false` 或路径非空）时不写；同项目同 signal_type 的未消费信号在途去重。信号不改变闸门判定，只呼叫起草。
- 信号摄取：`build_artifact_paths_missing` 登记进 `admin_monitor` 的管理信号表（`STORED_SIGNAL_TYPES`），严重度 `major`；处置建议登记在 `_SIGNAL_RECOMMENDATIONS`；摄取时无关联 spec 则从 evidence「项目名=」解析；摄取后先 `mark_escalated` 再唤起 Administrator（防重复唤起），已 escalated 的记录后续巡检跳过。
- Administrator 起草手册（`agents/administrator.md`）：输入源含项目构建配置与 `.fenix/config.yaml` 的 `project.type`；流程与验证契约起草同构——探测 → 写草稿 → 机械校验（路径合法性经 `validate_build_artifact_paths` 同口径）→ 落位 `.fenix/config.yaml` → git 提交；确无产物的项目写 `has_build_artifacts=false` 结案（不得用「路径留空」冒充已裁决）；处置动作在处置记录 `actions_taken` 留痕。

## 溯源

- [2026-09-23 2026-09-23-fix-artifact-paths-hardcoded-default](spec/archive/2026-09-23-fix-artifact-paths-hardcoded-default/) — 建立 setup LLM 探测预填、`_wip_overlap_gate` 未裁决信号、admin 摄取唤起与 Administrator 起草手册的闭环
