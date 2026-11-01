# design — 评审处置留痕落点治理与散件 gitignore 草案误伤交付物目录

## 1. 实证与根因

| 断言 | 证据 |
| --- | --- |
| spec/changes 内产物滞留 untracked 会触发散件首现告警 | `.fenix/admin_alerts.json` 告警 `d9a10915ced6`（2026-11-01T01:08:13Z，`maintree_untracked_stray_first_sight`，对象 `spec/changes/fix-arbiter-proposal-materialize-spec-dir/`，1 entry / 2594 字节） |
| 草案生成器把任何 untracked 目录标注为「运行时产物目录」 | `core/worktree_manager/stray_wip.py:1535-1540`：`draft_line = f"{dir_path}/"`，`draft_comment` 硬编码「运行时产物目录……预防性 ignore 后不再产生散件告警」 |
| 采纳路径存在（人工） | 同告警 `recommended_action`：「将 evidence 中 gitignore 草案行（含成因注释）追加至 .gitignore」——现无自动化执行，风险为人工误采纳路径 |
| 评审结果文件不构成散件 | `core/agent_runner/result_gate.py:1624`（spec-review → `.fenix/spec-review/<spec>/.fenix-run-result.json`）+ `.gitignore:26` `.fenix/*` |
| best-effort 单目录提交有先例 | `core/pm_engine/arbiter.py` `_materialize_proposal` 收尾（`git add spec/changes/<name>` + `git commit`，失败仅 WARNING 不阻断） |

原稿引用「3bf67a 实证」经 `git cat-file` 核验查无此提交，已弃用；上述证据均可独立复核。

## 2. 方向裁决：否决「落点迁移」，采纳「收尾提交」

proposal 原稿并列两方向。**迁移方向否决**，理由：

- SPEC 成文（proposal/design/tasks/specs）的生命周期消费方全部锚定 `spec/changes/<name>/`：STATE 状态机条目、晋升 lint、实现车道取证、归档动作（fenix-archive）、spec 列表 UI 枚举。迁入 `.fenix/spec-review/<name>/`（gitignored 运行时区）即脱离生命周期——晋升与实现都找不到文档。
- 评审结果文件**本来就已**落在 `.fenix/spec-review/<spec>/`（result_gate.py:1624）且被 `.gitignore:26` 覆盖，不存在散件问题，「迁移」对结果文件是无操作。

**采纳方向**：把滞留窗口用「收尾 best-effort 提交」兜住（对齐 `_materialize_proposal` 先例），同时掐断草案生成器对交付物目录的开药方能力。两层互为冗余：提交兜底缩短滞留窗口，草案豁免保证即便滞留（代差窗口、提交失败、外部写入）也不会产出有害草案。

## 3. 面 B：散件首现草案的 spec/ 豁免

改动点：`core/worktree_manager/stray_wip.py` `_write_first_sight_alert`。

- 判据：`dir_path == "spec" or dir_path.startswith("spec/")` → 交付物目录形态。
- 交付物形态：evidence **不携带** `gitignore草案:` 字段，改为 `交付物注记: spec/ 交付物目录不应 ignore，应提交入库`；`description`/`recommended_action` 同步条件化（交付物形态的建议从「追加草案行至 .gitignore」改为「核对归属后提交入库，或按产物真实落点迁出 spec/」）。
- 非 spec 形态：行为逐字不变（现网目录型运行时产物依赖此路径）。
- 不动归组判据（`_untracked_first_sight_groups`）：`spec/changes/<name>/` 全 untracked 时根目录判为 `spec/changes/<name>`，提示照发——保留「提醒提交」信号价值，只摘除有害草案。
- 不动 `.fenix/` negation 与豁免注记逻辑。

## 4. 面 A：spec-review 车道收尾提交钩子

改动点：`core/agent_runner/` spec-review 车道结果落盘收尾处（result_gate.py:1624 分派点附近）。

- 收尾时对 `.fenix/spec-review/<spec>/` 同名主树目录 `spec/changes/<spec>/` 检查 `git status --porcelain`：有变更/未跟踪条目才执行 `git add spec/changes/<spec>` + `git commit`（提交信息对齐 arbiter 先例形态，注明评审成文）。
- **幂等**：无变更不提交（porcelain 空即跳过），不产空提交。
- **best-effort**：任何 git 失败（锁冲突、identity 缺失）仅 WARNING 日志，绝不影响评审结果文件落盘与进程退出码——结果文件硬门优先级高于留痕整洁。
- **终态无关**：approved/repaired/rejected 三态都跑（rejected 时评审 agent 按写边界不改动文档，porcelain 通常为空 → 自然跳过；arbiter 已提交过的目录同样为空）。
- 并发防护：单目录 add+commit 粒度小，与 arbiter 物化提交同款竞态面（index.lock 由 git 自身拒绝、best-effort 吞掉），不引入新锁。

## 5. 边界与非目标

- 不改散件升级流（`maintree_untracked_stray_*` 阈值/升级时钟零触碰）——本 SPEC 只动首现草案生成面。
- 不自动执行 ignore 或 commit 之外的工作区动作（沿用「盘点零写副作用」原则；收尾提交是评审车道自身产物的落位，不属于盘点）。
- 不处理存量 `spec/changes/fix-arbiter-proposal-materialize-spec-dir/` 的补提交——运行时动作交由框架下次物化重放（`_materialize_proposal` 幂等跳过写、但提交分支可补）或人工，本 SPEC 只交付机制。
- 兼容性：无配置项新增；`.gitignore` 不动（spec/ 树保持零 ignore 规则）。

## 6. 测试策略

- 豁免面：构造 `spec/changes/<name>/` 与普通运行时产物目录两类 untracked 首现，断言前者 evidence 无草案行含交付物注记、后者逐字含现行草案（回归锚）。
- 收尾提交面：评审收尾钩子三态（有变更→提交且 untracked 消除；无变更→不产提交；git 失败→WARNING 且结果文件照常落盘）。
