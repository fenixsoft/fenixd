# 设计

## 改动点
core/verify_report.py ensure_verification_report（:757）：在该函数的**全部三个 ok 出口**（:786 action=present、:802 action=resynthesized、:843 action=synthesized）对 spec/changes/<spec>/verification-report.md 执行 git add -- <path> + git commit -m <msg> -- <path>（subprocess，照 core/archive_commit.py:75-92 惯例：add 与 commit 同 pathspec）。提交信息采用「[fenix] <spec>: verification-report 入库」形态，对齐库内既有提交文案风格。

挂钩 MUST 覆盖 present 出口：验证 Agent 自写报告（prompt 步骤 6）是主路径，该路径闸门原样保留在盘文件后于 :786 提前返回，**不经过** :711-722 的写盘调用（该写盘位于 synthesize_verification_report 内、仅合成路可达）——只挂写盘点会漏掉主路径，违背「两路生成均被覆盖」。

## 关键约束
- pathspec 精确：只 add/commit 本报告文件；禁用 git add -A -- spec 整目录（core/pm_engine/engine.py:2760 注释明确警示会卷入其它 spec 在途草案）；
- 内容认可红线：core/pm_engine/spec_integrity.py:55-84 刻意不把 verification-report.md 计入 spec_has_content（防已合并成果被盲目重实现），本改动只做 git 入库、绝不触碰该判定；
- 失败语义：git 非零退出仅落 WARNING（附 stderr 摘要），函数返回值与验证主流程不变——报告写盘成功的事实不被提交失败覆盖；
- 幂等：闸门在同一 spec 多轮验证/多次放行中反复进入（pipeline.py:925/:1077、legacy.py:330/:462 四调用点），报告已入库且内容未再变化时静默跳过（先探测待提交变化，或将 nothing to commit 视为成功）——重复放行不得反复落 WARNING 制造告警噪声；
- 并发：提交可能与任务回写（core/pm_engine/engine.py:2121）、归档提交（core/archive_commit.py）等并发争用 index.lock，按失败语义落 WARNING 即可，不重试、不阻塞；
- 单点覆盖：验证 Agent 写与框架合成（synthesize_verification_report）两路都经 ensure_verification_report，无需在 pipeline.py:925/:1077、legacy.py:330/:462 各调用点分别处理。

## 备选与否决
- report_gate.py _ensure_verification_report（:68）放行分支经 pipeline 调 engine 现成 _git_commit（core/pm_engine/engine.py:2148）：需打通验证子管线到 engine 的调用路径，且覆盖点分散在多个调用方，改动面更大，不采用；
- engine.approve_push（:2536）推送前对 done spec 的报告残留做收口提交：时机偏晚（push 前仍在丢失窗口内），作为可选防线不计入本期；
- merge-back 侧改动：报告永远不在实现分支上（mergeback.py:909 只 merge 分支内容），无从带起，不改。

## 测试
新增 tests/test_verification_report_commit.py：单文件提交触发（含 present 路径——Agent 已写报告、框架未落盘、闸门放行即入库）、git 失败仅 WARNING、pathspec 不卷入其它文件、重复放行幂等（已入库无变化不落 WARNING）四类场景；回归既有报告合成用例。