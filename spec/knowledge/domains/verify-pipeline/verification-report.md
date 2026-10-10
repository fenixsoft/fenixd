# 验证报告落盘即入库
<!-- knowledge: capability=verification-report rev=5
     sources=spec/archive/2026-10-05-evo-add-verification-report-commit-on-write,spec/archive/2026-10-06-evo-add-push-closeout-verification-report-commit,spec/archive/2026-10-06-evo-verify-report-scenario-section-commit -->

验证报告 `spec/changes/<spec>/verification-report.md` 的版本化入库能力：报告写盘成功即同步提交进版本库，使「落盘」与「入库」合一，验证结论（含场景集演进小节）在归档前就有版本化留痕。

## 现行规则

- 报告本体入库时点：`ensure_verification_report`（`core/verify_report.py`）在报告文件写盘成功后，对该报告文件执行 pathspec 精确的 `git add` 与 `git commit`（两者同 pathspec），提交信息形态为 `[fenix] <spec>: verification-report 入库`。
- 两路生成均覆盖：验证 Agent 自写报告（闸门以 present 放行、框架未落盘但文件已在盘）与框架合成（`synthesize_verification_report` 落盘）两条路径都经 `ensure_verification_report` 单点汇聚；挂钩覆盖该函数全部成功出口，含 present 路径的提前返回出口——只挂合成写盘点会漏掉 Agent 自写主路径。
- 提交范围严格单文件：pathspec 仅含本 spec 的 `verification-report.md`，不扩大到其它任何文件；禁止 `git add -A -- spec` 整目录提交（会卷入其它 spec 的在途草案）。
- 场景段渲染合并进闸门 pre-commit 挂点：验证裁决采纳流程（verified / bug-found 采纳）中，「本轮场景集变更」小节不再尾段二次提交——报告闸门（`report_gate._ensure_verification_report`）以 `pre_commit` 回调（函数内延迟导入）注入渲染函数（`core/pm_engine/verification/scenario_gate.py`），在报告本体入库（`_commit_verification_report`）前渲染写回，闸门单次提交即同时含报告本体与场景段；采纳流程内报告相关提交至多一次。渲染函数自带的「写盘即入库」提交器在合并形态下因该 pathspec 与 HEAD 一致而幂等静默跳过（零额外提交、零 WARNING）。回调异常仅落 WARNING、不阻断闸门放行与后续提交（对齐「git 失败仅 WARNING」失败语义）；legacy 采纳车道共用同一闸门注入点，其报告首次获得场景段小节。
- 场景段每报告至多一段：报告已含「本轮场景集变更」标题即跳过渲染与提交——报告跨验证轮留存时不补写旧轮变更，Verifier 按报告闸门每轮重写报告后标题不复存在，新一轮变更小节照常补写。由此场景段带来的额外提交至多一次。
- 失败语义：git 不可用、index.lock 争用等提交失败只落 WARNING 日志（附 stderr 摘要），报告文件保留在磁盘，验证主流程与函数返回值均不受影响；不重试、不阻塞，报告写盘成功的事实不被提交失败覆盖。非 git 项目静默跳过、零日志。场景段入库在提交器内建降级之外再兜意外异常（仅 WARNING），入库动作绝不影响渲染写盘结论与裁决采纳主流程。
- 幂等：闸门在同一 spec 多轮验证、多次放行中反复进入；报告已入库且内容未再变化时静默跳过提交，不落 WARNING，不制造告警噪声。
- 内容认可红线：入库动作不把 `verification-report.md` 计入 spec 内容认可（`spec_has_content`）判定——该判定刻意排除报告文件，防止已合并成果因报告在盘而被盲目重实现；入库只做版本化，不触碰该判定。
- 入库挂点链：报告本体与场景段合并入库（闸门 pre-commit 挂点，采纳流程内报告相关提交至多一次）→ done→pushed 收口（`approve_push` 内、归档收口之前）对在盘未入库或有未提交修改的报告再做一次单文件入库，规则详见 [push 收口报告入库](push-closeout-report-commit.md)；pipeline 采纳尾段的场景段渲染点保留为兜底——闸门回调未生效的轮次（未来绕过 report_gate 的新采纳路径）仍由尾段渲染闭合滞留缝隙，闸门已合并时「标题已存在即跳过」幂等判定使其零成本跳过；merge-back 与归档整目录搬迁仍是兜底防线。历史滞留报告与未入库场景段不做主动回填，其入库由归档兜底在搬迁时完成。

## 溯源

- 2026-10-05 evo-add-verification-report-commit-on-write（spec/archive/2026-10-05-evo-add-verification-report-commit-on-write） — 新增验证报告落盘即入库全部规则（写盘成功即单文件提交、present 与合成两路覆盖、git 失败仅 WARNING 不阻塞、重复放行幂等静默、内容认可判定不受影响、归档兜底保留）
- 2026-10-06 evo-add-push-closeout-verification-report-commit（spec/archive/2026-10-06-evo-add-push-closeout-verification-report-commit） — 修改本页：入库挂点链规则补入 done→pushed 收口二次入库挂点（push 收口细则独立成页 [push-closeout-report-commit](push-closeout-report-commit.md)），兜底防线表述同步收敛
- 2026-10-06 evo-verify-report-scenario-section-commit（spec/archive/2026-10-06-evo-verify-report-scenario-section-commit） — 修改本页：入库挂点链补入场景段写盘即入库挂点（采纳流程渲染写回后立即单文件幂等提交、跨模块消费走公开别名、失败仅 WARNING 不扰主流程、非 git 静默跳过、每报告至多一段故额外提交至多一次、存量不回填）
- 2026-10-11 evo-verification-report-closeout-single-commit（spec/changes/evo-verification-report-closeout-single-commit） — 修改本页：「场景段写盘即入库」与「入库挂点链」改写为场景段渲染合并进闸门 pre-commit 挂点、采纳流程内报告相关提交至多一次（同秒双提交流水线去重）；push 收口与渲染函数直调路径不变，尾段渲染点降级为兜底防线
