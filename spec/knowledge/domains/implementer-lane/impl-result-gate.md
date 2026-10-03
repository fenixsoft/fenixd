# 实现结果产物硬门（run 末校验）
<!-- knowledge: capability=impl-result-gate rev=1
     sources=spec/archive/2026-10-04-evo-add-fasttrack-verification-write-gate -->

实现 run 收工时对 `.fenix-run-result.json` 的机械校验关卡：契约类缺陷在 run 末当场判失败并原地补写，而不是拖到派发交接点才拒收、整轮成果作废。

## 现行规则

- 校验归属与触发条件：run 末产物硬门 `_check_impl_result_artifact`（`core/agent_runner/result_gate.py`）对实现 run 交付的结果文件做机械校验——文件存在、可解析、status 在白名单、tasks.md 完成度达标；在此之上，对 **status 为 success 且 mode 为 fast-track** 的结果文件还执行 verification 段校验：调用 `parse_fast_track_verification`（`core/fast_track_result.py`）解析，返回 None 即硬门失败，错误信息为「verification 段缺失或结构不完整」，run 不得以 success 收尾。
- verification 段合法形态（fail-closed，任一不满足即判失败）：顶层 `verification` 为 dict；`scenarios` 为非空 list，每条为 dict 且含非空 `scenario_id`、非空 `description`、`status` ∈ {pass, fail, error, warning, exempt}；`verdict` ∈ {verified, bug-found}（bug-found 是合法判定，可携带非 pass 场景与 bugs 清单）；`bugs` 缺省按空 list 处理。
- 诚实退出与 full 车道豁免：partial/error 状态不触发 verification 段校验（诚实退出语义，本就不含该段）；mode 非 fast-track 的结果文件不触发，full 车道行为与该校验无关。
- 车道判据与已知缺口：run 末校验以结果文件自报的 `mode` 字段为车道判据（schema 由 agents/fast-track.md 契约约定）。结果文件同时缺 mode 与 verification 段的双重模板偏离时，run 末门不触发——此类漏网由 dispatch 交接点 `_hard_check_fast_track`（`core/pm_engine/dispatch/fast_track.py`，无 mode 前置条件）拦截，结局为整轮重派，与无 run 末门时持平。
- dispatch 交接点是第二道防线：`_hard_check_fast_track` 持续生效，拦截转录捞回等绕过 run 末硬门的路径；两处共用同一解析器（`parse_fast_track_verification`），单源不设第二套 schema。
- 失败处置零新机制：run 末硬门失败抛 `AgentArtifactGateError`，由既有产物门重试机制按结构类失败走原地退避重试——同 session/worktree resume，实现者下一轮收到错误当场补写合规 verification 段后放行，run 正常 success 收尾，dispatch 交接点不再因此拒收。
- 注入契约与硬门同频：fast-track 车道派发提示词的结果文件契约段含专属义务句——success 结果文件必须含合法 verification 段（scenarios 非空、每条含非空 scenario_id/description、status 枚举合法、verdict 属 verified/bug-found），与 run 末校验同一解析器口径。契约句仅在 agent_type 为 fast-track 时拼入共用块，implementer（full 车道）契约文本不注入该义务。

## 溯源

- 2026-10-04 evo-add-fasttrack-verification-write-gate（spec/archive/2026-10-04-evo-add-fasttrack-verification-write-gate） — 新增本页：fast-track success 结果文件 run 末 verification 段硬校验、诚实退出与 full 车道豁免边界、契约段与硬门同频
