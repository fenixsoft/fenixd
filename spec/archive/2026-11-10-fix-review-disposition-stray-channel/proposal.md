# 评审处置留痕落点治理与散件 gitignore 草案误伤交付物目录

## Why

两条机制链在同一点交汇成害：

1. **spec/changes 内的成文/留痕产物会滞留 untracked**。arbiter 物化的提案目录在提交缺口窗口（物化 best-effort 失败、或 daemon 版本代差期旧代码无提交逻辑）会成为 untracked 散件——现场实证：`spec/changes/fix-arbiter-proposal-materialize-spec-dir/` 自 2026-11-01 起仅含 proposal.md 滞留 untracked，触发 `maintree_untracked_stray_first_sight` 告警（`.fenix/admin_alerts.json` 告警 id `d9a10915ced6`）。spec-review 车道同样在主树 `spec/changes/<name>/` 内成文/修补（评审 agent 的写权限边界即该目录），修补产物若滞留 untracked 同样触发散件告警。
2. **散件首现提示的 gitignore 草案把 spec/changes 交付物目录归类为「运行时产物目录」**。`core/worktree_manager/stray_wip.py` `_write_first_sight_alert` 的成因注释为硬编码措辞「运行时产物目录，N 个未跟踪 entry 滞留，预防性 ignore 后不再产生散件告警」（stray_wip.py:1536-1540），对任何 untracked 目录统一如此标注——上揭告警 `d9a10915ced6` 的 evidence 即携带 `spec/changes/fix-arbiter-proposal-materialize-spec-dir/` 的 ignore 草案行。若人工按 recommended_action 采纳（把草案行追加至 .gitignore），将永久遮蔽 spec 交付物目录，后续该目录下的正常 SPEC 成文全部隐身于 git 与散件盘点。

评审结果文件本身无此风险（落 `.fenix/spec-review/<spec>/`，已被 `.gitignore:26` `.fenix/*` 覆盖，不入散件面）。风险面集中在：①散件草案生成器不区分交付物目录；②spec/changes 内成文产物缺少与 `_materialize_proposal` 同款的收尾提交兜底。

## What Changes

- **散件首现 gitignore 草案的交付物豁免**：`_write_first_sight_alert` 对 `spec/` 前缀目录不再生成 gitignore 草案行，成因注释改为交付物定性（建议提交而非 ignore）；首现提示本身保留（提醒人工提交的信号价值仍在）。非 spec 路径行为不变。
- **spec-review 车道成文留痕收尾提交**：spec-review run 收尾时对本 run 写过的 `spec/changes/<name>/` 目录执行 best-effort 单目录 add+commit（对齐 `core/pm_engine/arbiter.py` `_materialize_proposal` 的先例），提交失败仅 WARNING 不阻断评审结果交付；无文档改动不产生空提交。
- **不做落点迁移**：评审处置留痕的 SPEC 成文落点保持 `spec/changes/<name>/` 不变（STATE、晋升 lint、实现车道、归档均锚定该目录；`.fenix/` 为 gitignored 运行时区，SPEC 文档迁入即脱离生命周期）。

## Capabilities

### New Capabilities

- `stray-gitignore-deliverable-guard`: 散件首现提示对交付物目录的 gitignore 草案豁免，与 spec-review 车道成文留痕的收尾提交兜底（见 specs/stray-gitignore-deliverable-guard/spec.md）。

### Modified Capabilities

（无——worktree capability 的既有散件升级流不改，本变更只收窄首现草案生成面。）

## Impact

- `core/worktree_manager/stray_wip.py`：`_write_first_sight_alert` 草案生成分支。
- `core/agent_runner/`（spec-review 车道收尾路径）：新增收尾提交钩子。
- `tests/`：豁免行为与收尾提交的回归测试。
- 不改：散件告警存在性、升级时钟、AdminStore 写入协议、arbiter 物化先例。

---

- 立项来源：Arbiter 调查（run_id=None，signature=fix-arbiter-proposal-materialize-spec-dir::spec-review-rejected，source=escalation-alert）
- 立项时间：2026-11-01T01:22:50.719598+00:00
- 评审修补：2026-11-01 spec-review 复评就地补全（Why 证据换实证、What Changes/Capabilities/Impact 成文、新增 design/tasks/specs；原稿「3bf67a 实证」经查无此提交，已替换为可验证证据）
