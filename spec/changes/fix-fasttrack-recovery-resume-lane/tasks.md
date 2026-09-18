## Deliverables

```yaml
# ── 派发层：fast-track 分支镜像续做消费（D1/D2）─────────────────
- path: core/pm_engine/dispatch/queue.py
  kind: modify

# ── runner：run_fast_track 透传 pre_wt_path（D3）──────────────
- path: core/agent_runner/runner.py
  kind: modify

# ── prompt：fast-track 分支注入恢复续做注记 + 去重（D6）─────────
- path: core/agent_runner/prompt_builder.py
  kind: modify

# ── fast-track 出口矩阵：降级出口固化不清锚点（D4）─────────────
- path: core/pm_engine/dispatch/fast_track.py
  kind: modify

# ── 两处有意清锚点出口的书面区分（D5）─────────────────────────
- path: core/pm_engine/engine.py
  kind: modify
- path: core/pm_engine/dispatch/rollback.py
  kind: modify

# ── 文档 ──────────────────────────────────────────────────
- path: docs/help/03-lifecycle.md
  kind: modify

# ── 测试 ──────────────────────────────────────────────────
- path: tests/test_fasttrack_recovery_resume.py
  kind: new
- path: tests/test_fast_track_scale_precheck.py
  kind: modify
- path: tests/test_interrupt_recovery_preserve.py
  kind: modify
```

## 1. 派发层：fast-track 分支镜像续做消费（D1/D2）

- [ ] 1.1 在 `core/pm_engine/dispatch/queue.py` 的 `_run_agent_worker` fast-track 分支中，把「无条件清除旧锚点」（现状位于规模档位标记写入之后、`self._run_fast_track_worker(spec_name)` 之前）改造为**镜像 implementer 分支**的续做消费序列，判据与顺序 MUST 逐条对齐 `queue.py` implementer 分支既有实现：①`dispatch_entry = self._pm.state_machine.read_one(spec_name) or {}`；②`resume_branch = dispatch_entry.get("branch") if dispatch_entry.get("_recovery_resume") else None`；③`resume_branch` 非空时经 `wm.resolve_resume_site(spec_name, resume_branch)` 三态解析（**MUST 复用该方法，MUST NOT 自行拼装载体判定**），`site[0]` 非 None 记 `resume_wt`，为 None 时打 WARNING 含 spec 名与分支名；④`if dispatch_entry.get("_recovery_resume"): update_spec(spec_name, {"_recovery_resume": None})`（**无条件消费，一次性**）；⑤`resume_wt` 非空时 `wm.mark_reused(spec_name, resume_wt, resume_branch or "")`（try/except 包住、失败仅 WARNING 不阻塞）并打 INFO `Resume dispatch for '<spec>' on preserved branch '<branch>' (worktree <wt>)`。注意 `wm` 需在该分支内可达（`self._pm.agent_runner.worktree_manager`）。

- [ ] 1.2 在同一分支内，把清锚点动作改为**仅 `resume_wt is None` 时执行**：保留既有 `if (_ft_entry.get("branch") or _ft_entry.get("implementer_run") or _ft_entry.get("_repair_awaiting_remerge")):` 条件与 `{"branch": None, "implementer_run": None, "_repair_awaiting_remerge": False}` 写入内容不变，但 MUST 整体置于 1.1 的续做判定**之后**、以 `resume_wt is None` 为前置；清锚点时 MUST 打 INFO 日志含被清空的旧锚点值（对齐 implementer 分支的 `新轮次派发清除旧锚点 '<spec>': branch=…, implementer_run=…` 文案）。`_fast_track_scale_tier` 的写入/清除逻辑 MUST 保持原位不动（它不属「本轮锚点」）。

- [ ] 1.3 在同一分支的规模预检 `if tier == "full": self._downgrade_fast_track_scale(...); return` 早退路径上，MUST NOT 新增任何锚点写入或清除动作（该路径在续做判定之前 return，锚点与 `_recovery_resume` 标记 MUST 原样留给随后的 implementer 派发消费）；在该 `return` 前加一行注释固定此语义（引 D4）。

- [ ] 1.4 在 fast-track 分支的续做判定段加对照注释，明写「本段与同文件 implementer 分支的 `_recovery_resume` 消费序列同源（interrupt-recovery-preserve D4/D5 / fix-recovery-branch-anchor D1）；两处结构改动 MUST 同步」，并在 implementer 分支对应段加一行反向引用注释，便于后续 reviewer 逐行对照。

## 2. runner：`run_fast_track` 透传 `pre_wt_path`（D3）

- [ ] 2.1 在 `core/agent_runner/runner.py` 的 `run_fast_track` 增加形参 `pre_wt_path: Path | None = None`，并透传至 `_execute_agent(spec_name, "fast-track", run_id, pre_wt_path=pre_wt_path)`；更新 docstring 说明「pre_wt_path 非 None 时在既有 worktree 内续做（interrupt-recovery-preserve 恢复续做），不创建新 worktree；语义与 `run_implementer` 同」。

- [ ] 2.2 核对并确认承载路径已支持该形参（`_execute_agent` → `_execute_agent_inner` 的 `st = _AttemptState(wt_path=pre_wt_path, …)` 与「跨 attempt 复用/失效改新建」判定 `core/agent_runner/runner.py` 中 `agent_type in ("implementer", "fast-track", "repair")` 分支）：若既有判定已覆盖 fast-track（当前实现已含 `"fast-track"`），则本项仅需在测试中固化；若发现缺口，就地补齐并复用既有 `_worktree_path_valid` 校验，MUST NOT 新增第二份路径有效性判定。

- [ ] 2.3 在 `core/pm_engine/dispatch/queue.py` 的 fast-track 分支中，把 1.1 解析出的 `resume_wt` 作为实参传给 `run_fast_track`：即把 `self._run_fast_track_worker(spec_name)` 调用改为传递载体（见 3.1 对 `_run_fast_track_worker` 签名的扩展），使 `resume_wt` 一路贯通到 `agent_runner.run_fast_track(pre_wt_path=…)`。

- [ ] 2.4 在 `core/pm_engine/dispatch/fast_track.py` 的 `_run_fast_track_worker` 增加形参 `pre_wt_path: Path | None = None` 并透传至 `self._pm.agent_runner.run_fast_track(spec_name, pre_wt_path=pre_wt_path)`；更新 docstring（在既有「完整路径」描述中补 `pre_wt_path` 分支），并确认该方法的**唯一**调用点是 `queue.py` 的 fast-track 分支（`grep -rn "_run_fast_track_worker(" core/` 结果仅 `def` 与一处调用），无其它调用点需同步。

## 3. prompt：fast-track 分支注入恢复续做注记 + 去重（D6）

- [ ] 3.1 在 `core/agent_runner/prompt_builder.py` 的 fast-track 分支（`elif agent_type == "fast-track":`）中，把既有 `prompt += self._fast_track_reuse_note(spec_name)` 改为互斥注入：优先注入 `self._recovery_resume_note(spec_name)`，其返回空串时再退回 `self._fast_track_reuse_note(spec_name)`。MUST NOT 同时注入两条（语义重叠、稀释注意力）。实现口径：`note = self._recovery_resume_note(spec_name) or self._fast_track_reuse_note(spec_name)` 后单次 `prompt += note`。

- [ ] 3.2 确认 `_recovery_resume_note`（`prompt_builder.py` 既有实现）在 fast-track 语境下文案正确：其文案固定为「本 spec 的实现 run 曾因 daemon 重启/停机被中断，框架保留了你在分支上的已提交成果，本轮在原 worktree 内继续实现（当前分支：`<branch>`）…」。**MUST 复用同一函数（单实现）**，MUST NOT 复制第二份文案；若函数名或注释中限定了「implementer」，就地改为「实现车道（implementer / fast-track）」措辞并同步 docstring。

- [ ] 3.3 核对 `_recovery_resume_note` 与 `_fast_track_reuse_note` 的判定源一致（二者均经 `wm.get_reuse_record(spec_name)`），在 `_recovery_resume_note` 的 docstring 中补一句「与 `_fast_track_reuse_note` 共享同一 `_active_reuse` 判定源、天然互斥；fast-track 分支以本注记优先」，供后续维护者理解无需额外去重逻辑。

## 4. fast-track 出口矩阵（D4/D5）

- [ ] 4.1 普查并逐一核对 fast-track 的全部派发出口，在 `core/pm_engine/dispatch/fast_track.py` 的每个重派出口（结果文件缺失分支、完成度判据拦截分支、`parse_fast_track_verification` 返回 None 分支、`validate_fast_track_result` 不通过分支、零变更哨分支、merge-back 失败降级 `ready` 分支）加一行注释，明写该出口对 `branch`/`implementer_run`/`_recovery_resume` 的处置（当前实现均为「不触碰」），供矩阵审计对照 spec 的出口表。MUST NOT 在这些出口新增清锚点或消费标记的动作。

- [ ] 4.2 在 `core/pm_engine/dispatch/fast_track.py` 的 `_downgrade_fast_track_scale` docstring 中增加一条要求：「本路径 MUST NOT 清空 `branch`/`implementer_run`，MUST NOT 消费 `_recovery_resume`——降级后走 implementer 车道，由后者按其分支消费续做标记（design D4）」，并在函数体内加同义注释。

- [ ] 4.3 在 `core/pm_engine/engine.py` 的 auto-recovery（stuck implementing）清锚点语句（写入 `{"status": "ready", "implementer_run": None, "tester_run": None, "branch": None, …}` 处）旁加注释，明写：「本处清锚点属有意重置——判据已确认『滞留超阈值且无存活子进程』即 run 已死；MUST NOT 消费 `_recovery_resume`（它不由本路径产出，且此时不存在可续做的在飞 run）」。

- [ ] 4.4 在 `core/pm_engine/dispatch/rollback.py` 的派发异常回滚清锚点语句旁加注释，明写：「本处清锚点属有意回滚——run **从未启动**，`_recovery_resume` 尚未被消费、锚点亦非本轮产出；MUST NOT 消费该标记，使其在原样重派时仍可被消费」。

## 5. 文档

- [ ] 5.1 在 `docs/help/03-lifecycle.md` 的恢复/重启相关小节补一段「fast-track 车道的恢复续做」说明：fast-track spec 经 daemon 重启恢复时与 implementer 车道同源消费 `_recovery_resume`，在保留分支的 worktree 内续做（不新建分支、不重做既有成果），载体不可用时降级为全新派发并留 WARNING。MUST 与既有 implementer 续做说明并列成同一小节，MUST NOT 另起互斥章节。

## 6. 测试

- [ ] 6.1 新建 `tests/test_fasttrack_recovery_resume.py`，覆盖以下用例（**MUST 用 mock/stub 构造 dispatch 环境，MUST NOT 依赖真实 daemon**）：①**续做命中不抹锚点**——STATE 为 `{status: ready, branch: "fenix/<spec>-<ts>", _recovery_resume: True}` 且 `resolve_resume_site` 返回可用载体时，派发后 `update_spec` **未**写入 `{"branch": None, …}`，且 `branch` 仍为该保留分支；②**载体贯通**——`run_fast_track` 收到 `pre_wt_path=<载体>`（断言调用实参）；③**标记一次性消费**——派发后 `_recovery_resume` 被写为 None；④**降级留痕**——`resolve_resume_site` 返回 `(None, None)` 时日志含 WARNING 且含分支名，且此时**允许**清锚点；⑤**无标记行为不变**——`_recovery_resume` 缺失时旧锚点被清空（与 implementer 分支非续做路径一致）；⑥**规模预检降级不碰锚点**——`tier == "full"` 早退时 STATE 的 `branch`/`_recovery_resume` 均未被改动。

- [ ] 6.2 在 `tests/test_fast_track_scale_precheck.py` 新增用例：带 `_recovery_resume` 标记与 `branch` 的 fast-track spec 被规模预检判 `full` 档降级后，`_downgrade_fast_track_scale` MUST NOT 清空 `branch`/`implementer_run`、MUST NOT 消费标记，且随后 `_enqueue(spec_name, "implementer")` 被调用一次。

- [ ] 6.3 在 `tests/test_interrupt_recovery_preserve.py` 新增 fast-track 端到端续做用例：①构造「interrupted implementing + 分支 ahead of main」的 STATE → 走 recovery preserve → 断言 `_recovery_resume=True` 与 `branch` 保留；②模拟 fast-track 派发 → 断言**不出现** `worktree_manager.create` 调用（不新建 worktree），且 `run_fast_track` 收到载体；③断言构建的 prompt 含恢复续做注记文案（含「不要重做已完成的工作」与分支名），且**不含** `_fast_track_reuse_note` 的重复段落。

- [ ] 6.4 在 `tests/test_interrupt_recovery_preserve.py` 补一条回归用例：无恢复痕迹时构建的 fast-track prompt 与 `_recovery_resume_note` 引入前逐字节一致（断言注记为空串、prompt 不含「中断恢复续做」标题）。

- [ ] 6.5 运行 `python3 -m pytest tests/test_fasttrack_recovery_resume.py tests/test_fast_track_scale_precheck.py tests/test_interrupt_recovery_preserve.py tests/test_recovery_branch_anchor.py tests/test_repair_remerge_pending.py -q` 确认全绿（含既有恢复链用例不回归）。

## 7. 收口

- [ ] 7.1 运行有界全量回归 `python3 bin/run_full_suite.py --timeout 3600 --baseline HEAD`（fix-run-hang-amplification 3.3：MUST NOT 裸调 `pytest tests/ -q`），按输出归类存量/引入失败并记录结论。

- [ ] 7.2 在 `tasks.md` 勾选全部已完成任务，并写 `.fenix-run-result.json`（`status: success`，附改动摘要与回归结论）。
