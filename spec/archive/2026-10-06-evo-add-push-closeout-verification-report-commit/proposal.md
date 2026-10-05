# add-push-closeout-verification-report-commit

## Why

验证报告存在一个入库窗口敞口：报告落盘时刻晚于实现 merge、早于 pushed 落定时，现有机制全部失位。两起实案（add-help-docs-mechanism-coverage、add-codefix-affinity-batching）：报告分别先于 pushed 落定 16 秒与 16 分钟在盘，此后在收口链上再无任何挂点——commit-on-write 三出口在更早的验证裁决时刻已跑完；approve_push（core/pm_engine/engine.py:2600）只 push 分支加归档移动残留，不提交报告；merge-back 的 inflight 卫与 stash 守卫显式排除 spec/changes。两份报告因此以未跟踪状态滞留工作区 2-3 天（09-27 自省点名后仍未清），验证结论无版本化留痕，clone 与全新环境缺配置。唯一兜底是归档整目录搬迁（core/archive_commit.py），且终态未归档 spec 已达 auto_threshold=50，兜底随时会以归档提交形态被动卷入——但那是被迫的脏形态，不是干净收口。

## What Changes

1. done→pushed 收口点（approve_push，_push_lock 内、transition(pushed) 之前）追加对本 spec verification-report.md 的 pathspec 精确入库，复用既有 _commit_verification_report（core/verify_report.py:805，幂等、fail-open）。
2. 失败降级：报告缺失、非 git 项目、git 失败仅记 WARNING，不阻断 pushed 落定（对齐框架「报告可丢，主链不可断」既有取向）。
3. 不做 merge-back / 归档前阻断式校验：滞留文件跨约 20 次成功 merge 共存是常态，阻断瘫批链；归档阻断则自锁唯一兜底。
4. verify.yaml 类全局配置不入 per-spec 收口硬门（无自然挂点），留给每日自省读侧卫生清单（纯读提示）。

## Non-Goals

- 不回填已 pushed 存量的 11 份带未提交「本轮场景集变更」小节的已跟踪报告（归档兜底吸收，与 evo-add-verification-report-commit-on-write 非目标口径一致）。
- 不改 merge-back 与归档链路。
- 不改验证放行出口（pipeline.py:948/:1120、legacy.py:348/:491）行为。

## Impact

- Specs: specs/push-closeout-report-commit/spec.md（ADDED：push 收口报告入库、失败降级不阻断）
- Code: core/pm_engine/engine.py（approve_push 插入库调用，延迟导入）、core/verify_report.py（docstring 或薄包装声明第二消费方）
- Tests: tests/test_push_closeout_report_commit.py（新增，覆盖入库/幂等/缺失/非 git/失败五分支）
- 行为变化：pushed 落定后本 spec 报告保证已入库；git 失败时 WARNING 降级、主链不受影响。