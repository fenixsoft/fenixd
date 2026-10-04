# 提案：验证报告落盘即入库

## 背景与问题
verification-report.md 由验证链写盘（core/verify_report.py:757 ensure_verification_report），但收口链没有任何环节提交它：任务勾选回写只提交 tasks.md（core/pm_engine/engine.py:2121）、spec 定义提交发生在起草期、报告尚不存在（core/worktree_manager/lifecycle.py:407）、merge-back 只含实现分支内容（core/worktree_manager/mergeback.py:909）、push 零提交。spec/changes 下在途 41 例同名文件全是 WIP/docs/admin 等顺带提交（archive 侧另有 190 例由归档兜底入库），唯一确定性兜底是归档时整目录搬迁（core/dashboard/data/spec_archive.py:248 + core/archive_commit.py:63-76）。本窗口两个已收口 spec（add-codefix-affinity-batching、add-help-docs-mechanism-coverage）的报告因此滞留工作区：报告落盘晚于各自 merge（86789129、f5a959b7），此后到归档前验证结论无版本化留痕。

## 目标
ensure_verification_report 写盘成功后，对该报告文件做 pathspec 精确的 git add+commit，使「落盘」与「入库」同步，不再依赖归档兜底。该函数是验证 Agent 写与框架合成两路的单一汇聚点，单点改动即可全覆盖。

## 非目标
- 不改动 spec 内容认可判定——verification-report.md 保持不计入 spec_has_content（core/pm_engine/spec_integrity.py:55-84，防已合并成果被盲目重实现）；
- 不改动 merge-back 与归档兜底（保留为最后防线）；
- 不做历史回填（两个滞留 spec 已收口、验证闸门不再运行，本机制不主动追溯；其入库仍由归档兜底在搬迁时完成）。

## 代价与风险
- verify_report.py 是中性模块、无现成 git helper，需自带 subprocess git 调用（照 core/archive_commit.py:75-92 的 add/commit 同 pathspec 惯例）；
- 必须 pathspec 精确 add，禁用 git add -A -- spec 整目录（core/pm_engine/engine.py:2760 注释警示会卷入其它 spec 在途草案）；
- git 失败（锁冲突等）只落 WARNING，不得影响验证主流程与报告写盘结果。