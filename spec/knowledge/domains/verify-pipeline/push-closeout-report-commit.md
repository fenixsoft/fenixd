# push 收口报告入库

<!-- knowledge: capability=push-closeout-report-commit rev=1
     sources=spec/archive/2026-10-06-evo-add-push-closeout-verification-report-commit -->

done→pushed 收口时对验证报告的兜底入库能力：闭合「报告落盘时刻晚于实现 merge、早于 pushed 落定」的入库窗口，使任何 spec 在终态落定前其验证报告必有版本化留痕。

## 规则

- 挂点：`approve_push` 在 `_push_lock` 持有段内、归档收口（`_archive_auto_commit`）与 `transition(pushed)` 之前，对本 spec 的 `spec/changes/<spec>/verification-report.md` 调用 `_commit_verification_report`（engine 侧函数内延迟导入）执行 pathspec 精确入库。验证裁决放行出口的 commit-on-write 发生在实现 merge 之前，push 收口是其之后唯一 per-spec 必经点，「报告落盘晚于实现 merge」的窗口在此闭合。
- 时序契约：报告入库先于归档收口执行——报告 commit 落本地 main 后即被归档收口尾部的 `_git_push_ref("main")` 顺带推上 origin，直达远端；不留滞本地 main 领先 origin 等下一次任意 push 的中间态。
- 触发判据与提交范围：报告未入库或已有未提交修改时提交，产生仅含该单文件的 commit；pathspec 严格限定本 spec 的报告文件，其他 spec 的在途草案与既有 staged 内容不受牵连。
- 幂等：报告已入库且工作区无该文件差异时静默跳过——零新提交、零 WARNING；push 幂等重入（重复 approve_push）不产生重复提交。
- 失败降级不阻断（「报告可丢，主链不可断」）：报告缺失或 git 操作失败仅记 WARNING，pushed 照常落定，push 主链对入库失败无感知。git add/commit 失败由 `_commit_verification_report` 内部捕获，WARNING 落 verify_report 通道（含 spec 名与 stderr 摘要），push 场景不另加前缀；engine 侧调用本身向外抛异常由外层兜底记 `push-closeout` 前缀 WARNING。
- 非 git 项目静默跳过：被管项目无 git 仓库时不落 WARNING，pushed 照常落定。
- 不做阻断式校验：merge-back 前与归档前均不设「工作区无未入库报告」阻断门——merge-back 阻断会瘫痪批修复链（滞留文件与成功 merge 长期共存是常态），归档阻断则锁死滞留报告唯一的自动入库兜底路径。verify.yaml 类全局配置无 per-spec 自然挂点，不入收口硬门，由每日自省读侧卫生清单纯读提示。
- 历史存量不回填：机制生效前已 pushed spec 的滞留报告不做主动回填，由归档兜底在搬迁时吸收。

## 关键行为

push 收口序列：main 推送（成功判据）→ 分支尽力推送 → 报告入库（本能力）→ 归档收口 → `transition(pushed)`。报告入库在任何分支上的失败都只降级为日志，不改变后续序列。

## 溯源

- 2026-10-06 evo-add-push-closeout-verification-report-commit（spec/archive/2026-10-06-evo-add-push-closeout-verification-report-commit） — 新建本页：done→pushed 收口对本 spec 验证报告的 pathspec 单文件入库（先于归档收口、随归档推送直达远端）、幂等静默、失败降级不阻断、非 git 静默跳过、不做 merge-back/归档阻断式校验、历史存量不回填
