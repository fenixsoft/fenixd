# design — add-push-closeout-verification-report-commit

## 窗口模型

敞口段 = 报告落盘时刻 ∈ (实现 merge, pushed)。验证裁决放行出口（core/pm_engine/verification/pipeline.py:948/:1120、legacy.py:348/:491 经 report_gate）发生在 merge 之前；push 收口是其之后唯一 per-spec 必经点。两起实案落此段：help-docs 报告落盘先于 pushed 16 秒、affinity-batching 先于 16 分钟。

## 挂点与实现

- 挂点：core/pm_engine/engine.py:2600 approve_push 内、_push_lock 持有段、_archive_auto_commit()（:2664）之前、transition(pushed)（:2673）之前。插在归档收口之前是刻意选择：报告 commit 落本地后即被 _archive_auto_commit 尾部的 _git_push_ref("main") 顺带推上 origin——报告不只本地入库而是直达远端；若插在归档收口之后，报告 commit 滞留本地 main 领先 origin，须等下一次任意 push 才上去。两者 pathspec 互不重叠（归档收口只取归档移动残留路径），无内容冲突。
- 实现：复用 core/verify_report.py:805 _commit_verification_report(project_root, spec_name, logger)——pathspec 单文件 add+commit、diff --cached 对 HEAD 的幂等探测、fail-open。engine.py 内以函数内延迟导入引用（同文件既有防装载环惯例）。
- 失败语义：调用外层 try/except 全兜底（仅兜函数本身向外抛的异常，记 push-closeout 前缀 WARNING），不阻断 pushed。注意 git add/commit 失败由 _commit_verification_report 函数内部捕获且不外抛，其 WARNING 落在既有 verify_report 通道（含 spec 名与 stderr 摘要）——push 场景不新增前缀，验收按 verify_report 通道 WARNING 断言；非 git 仓库该函数静默跳过（无 WARNING）。对齐 verify_report 内既有「报告可丢，主链不可断」取向与 _archive_auto_commit 同款容错。

## 为何不做阻断式校验（否决原建议）

- merge-back 前阻断「工作区无未入库报告」：滞留文件跨约 20 次成功 merge（09-27/09-28 实测），阻断会瘫痪整条批修复链；且 _detect_wip_overlap 与 ensure_clean_tree 对 spec/changes 的豁免是 fix-autostash-orphans 事故后的有意设计（core/worktree_manager/mergeback.py:123-152、core/worktree_manager/stash_guard.py:68）。
- 归档前阻断：归档整目录 add 是滞留报告唯一自动入库路径，阻断形成「没人提交→归档被拦→更没人提交」自锁。

## verify.yaml 的处理

非 per-spec 收口物、无自然挂点函数，硬门不合适；留给每日自省读侧卫生清单（git status --porcelain 过滤 spec/changes/*/verification-report.md 与 .fenix/verify.yaml，纯读不阻断）。已有覆盖：「分支自身改动 verify.yaml 且主树同文件脏」由 WIP overlap gate（escalate）拦截。

## Risks

- push 高频路径新增两三次 git 子进程（probe/add/diff/commit）：超时上限沿用 core/verify_report.py:53-54 惯例；持锁内 git 慢由 try/except 兜底，失败仅 WARNING。
- 与验证放行出口的重复提交：_commit_verification_report 幂等探测天然去重，重复触发零副作用。
- 未跟踪报告与其他 spec 在途草案混场：pathspec 精确提交保证隔离（tests/test_verification_report_commit.py 既有 TestPathspecPrecision 同款断言）。