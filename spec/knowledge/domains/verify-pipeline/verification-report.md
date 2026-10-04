# 验证报告落盘即入库
<!-- knowledge: capability=verification-report rev=1 sources=spec/archive/2026-10-05-evo-add-verification-report-commit-on-write -->

验证报告 `spec/changes/<spec>/verification-report.md` 的版本化入库能力：报告写盘成功即同步提交进版本库，使「落盘」与「入库」合一，验证结论在归档前就有版本化留痕。

## 现行规则

- 入库时点：`ensure_verification_report`（`core/verify_report.py`）在报告文件写盘成功后，对该报告文件执行 pathspec 精确的 `git add` 与 `git commit`（两者同 pathspec），提交信息形态为 `[fenix] <spec>: verification-report 入库`。
- 两路生成均覆盖：验证 Agent 自写报告（闸门以 present 放行、框架未落盘但文件已在盘）与框架合成（`synthesize_verification_report` 落盘）两条路径都经 `ensure_verification_report` 单点汇聚；挂钩覆盖该函数全部成功出口，含 present 路径的提前返回出口——只挂合成写盘点会漏掉 Agent 自写主路径。
- 提交范围严格单文件：pathspec 仅含本 spec 的 `verification-report.md`，不扩大到其它任何文件；禁止 `git add -A -- spec` 整目录提交（会卷入其它 spec 的在途草案）。
- 失败语义：git 不可用、index.lock 争用等提交失败只落 WARNING 日志（附 stderr 摘要），报告文件保留在磁盘，验证主流程与函数返回值均不受影响；不重试、不阻塞。报告写盘成功的事实不被提交失败覆盖。
- 幂等：闸门在同一 spec 多轮验证、多次放行中反复进入；报告已入库且内容未再变化时静默跳过提交，不落 WARNING，不制造告警噪声。
- 内容认可红线：入库动作不把 `verification-report.md` 计入 spec 内容认可（`spec_has_content`）判定——该判定刻意排除报告文件，防止已合并成果因报告在盘而被盲目重实现；入库只做版本化，不触碰该判定。
- 兜底防线不变：merge-back 与归档整目录搬迁仍是报告入库的最后防线；机制生效前的历史滞留报告不做主动回填，其入库由归档兜底在搬迁时完成。

## 溯源

- 2026-10-05 2026-10-05-evo-add-verification-report-commit-on-write（spec/archive/2026-10-05-evo-add-verification-report-commit-on-write） — 新增验证报告落盘即入库全部规则（写盘成功即单文件提交、present 与合成两路覆盖、git 失败仅 WARNING 不阻塞、重复放行幂等静默、内容认可判定不受影响、归档兜底保留）
