# 设计

## 改动点
core/verify_report.py ensure_verification_report（:757，写盘调用 :711-722 成功返回前）：报告 ok 时对新落盘的 spec/changes/<spec>/verification-report.md 执行 git add -- <path> + git commit -m <msg> -- <path>（subprocess，照 core/archive_commit.py:75-92 惯例：add 与 commit 同 pathspec）。提交信息采用「[fenix] <spec>: verification-report 入库」形态，对齐库内既有提交文案风格。

## 关键约束
- pathspec 精确：只 add/commit 本报告文件；禁用 git add -A -- spec 整目录（core/pm_engine/engine.py:2760 注释明确警示会卷入其它 spec 在途草案）；
- 内容认可红线：core/pm_engine/spec_integrity.py:55-84 刻意不把 verification-report.md 计入 spec_has_content（防已合并成果被盲目重实现），本改动只做 git 入库、绝不触碰该判定；
- 失败语义：git 非零退出仅落 WARNING（附 stderr 摘要），函数返回值与验证主流程不变——报告写盘成功的事实不被提交失败覆盖；
- 单点覆盖：验证 Agent 写与框架合成（synthesize_verification_report）两路都经 ensure_verification_report，无需在 pipeline.py:925/:1077、legacy.py:330/:462 各调用点分别处理。

## 备选与否决
- report_gate.py _ensure_verification_report（:68）放行分支经 pipeline 调 engine 现成 _git_commit（core/pm_engine/engine.py:2148）：需打通验证子管线到 engine 的调用路径，且覆盖点分散在多个调用方，改动面更大，不采用；
- engine.approve_push（:2536）推送前对 done spec 的报告残留做收口提交：时机偏晚（push 前仍在丢失窗口内），作为可选防线不计入本期；
- merge-back 侧改动：报告永远不在实现分支上（mergeback.py:909 只 merge 分支内容），无从带起，不改。

## 测试
新增 tests/test_verification_report_commit.py：单文件提交触发、git 失败仅 WARNING、pathspec 不卷入其它文件三类场景；回归既有报告合成用例。