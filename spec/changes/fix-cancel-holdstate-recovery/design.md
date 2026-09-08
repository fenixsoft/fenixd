# fix-cancel-holdstate-recovery 设计

## Context

取消链路（add-run-cancel D4）：run 收尾分支发现 `cancelled=True` 时只 `update_spec(spec, {"error": "run 被人工取消：…"})`——status 不翻转（implementing/testing 停留）、run 字段保留、不入队。运行期防重派靠收尾分支早退；重启后防线消失：`recover_interrupted`（core/state_machine.py:751）只看 status∈INTERRUPTED_STATES，对 implementing 走复位 ready+恢复重派、对 testing 走重验计数+复位 implemented，取消保持被静默覆盖。

监测面同样会打破保持：`admin_monitor._detect_stuck` 覆盖 implementing/testing 超阈值且无 run 进度的 spec → 自动升级 Administrator，Administrator 可能自行复位——用户「我来决定何时重派」的意图被代理破坏。

## Goals

- 重启恢复不覆盖人工取消决策（不复位、不重派、不计数）
- 保持态可被显式复位解锁，解锁路径与现状一致（admin 处置 / 面板 / unfreeze）
- 监测链路不自动打破保持态

## Decisions

- **D1 标记载体**：spec entry 布尔字段 `_cancelled_hold`，随 STATE.md 持久化、重启天然存活，与 `_retry_count`/`_merge_fp` 等内部字段同层。不用独立标记文件——字段随 spec 生命周期，无孤儿清理问题，且 update_spec/transition 既有写路径零新增。
- **D2 写入点**：六处 hold-state 收尾分支各在既有 update_spec 调用中加 `"error"` 同层的 `"_cancelled_hold": True`（dispatch.py:977 implementer、dispatch.py:1732 邻域 fast-track、dispatch.py:2173 邻域 repair、verification.py:1005/1257/1788 邻域三处）。不收敛 helper——六处形态各异，逐点一行加键，改动面最小。
- **D3 恢复跳过**：`recover_interrupted` 循环体最前（status 分支判定之前）查 `entry.get("_cancelled_hold")` → 命中即 log info（「跳过重启恢复：人工取消保持 '<name>'」）并 continue。覆盖 implementing 与 testing 两分支；重启重验计数（bump_verify_redo_count）在 testing 分支内、跳过判定之后，天然不递增；冻结路径（重验超限）不受影响。
- **D4 解锁时机**：`update_spec` 内 updates 显式含 `status` 键时同步写 `"_cancelled_hold": False`。覆盖所有复位路径（admin 处置、面板重派、freeze/unfreeze、恢复逻辑自身）；hold spec 在恢复路径被提前 continue，不会自清。仅写 error 等隐式 updates 不清（取消收尾自身只写 error，自洽）。
- **D5 监测豁免**：`_detect_stuck` 循环内在 status 过滤后追加 `entry.get("_cancelled_hold")` 跳过；`_detect_blocked_stuck` / `_detect_repeated_failures` 实现时核对——hold spec status 停 implementing/testing，blocked_stuck 天然不命中（只看 blocked）；repeated_failures 若按 error/重试计数判定，hold spec 不新增失败计数，预期不命中，核对确认即可、命中才加豁免。
- **D6 存量兼容**：已取消但无标记的存量 spec 不迁移（重启仍按现状复位），与今天行为一致、零回填成本。

## Risks

- 取消保持 spec 长期滞留：有意的等待态，无自动链路再打扰（stuck 豁免后由人决定）；后续真正要继续时显式复位一步即可。
- `_cancelled_hold` 字段被时间轴/面板展示层误读：内部下划线字段族先例（`_retry_count` 等）不外泄，无新增展示。
- 六处写入点遗漏（未来新增 run 类型）：spec 场景钉六处行为，且实现任务要求 grep `hold-state` 全量核对写点清单。
