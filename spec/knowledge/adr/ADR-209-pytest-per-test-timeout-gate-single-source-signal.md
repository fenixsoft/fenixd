# ADR-209：pytest 单用例超时门仓级单源不可静默稀释，signal 中断保会话存续

date: 2026-10-03
status: accepted

## Context

慢用例长期没有机制性拦截：测试替身真自旋曾使单次全量回归从 ~250s 涨到 ~615s，约 41 次回归累计多烧 4.1 小时才被人工定位。给 pytest 加单用例超时存在三个方向的错误选型：把超时挂在逐入口命令上（回归命令追加 `--timeout` 只覆盖回归一个入口，spec 验证链/本地开发/worktree 全部漏掉，且配置多点多漂移）；把中断方法定为 thread（超时 dump 栈后 `os._exit` 整个 pytest 进程，一次慢用例即杀掉整场回归）；提供全局放宽阈值的配置项（规则被静默稀释，门名存实亡）。

## Decision

- 超时门是仓级机械规则，配置单源于仓根 `pytest.ini`（`timeout = 10` / `timeout_method = signal`）：凡以本仓为根执行 pytest 的入口（回归车道、spec 验证链、本地开发、worktree、嵌套 pytester 内层会话）一律自动生效，任何入口 MUST NOT 以命令行参数或独立配置文件重述/旁路该门；新增 pytest 入口零配置继承，不逐入口声明超时。
- 不提供全局放宽阈值的配置项；唯一放宽通道是显式豁免清单（`nodeid + timeout_seconds + reason` 三字段落盘、conftest 收集期按 nodeid 注入、schema 机械校验违规即测试失败）。后续需求要「某类用例更久」一律走清单登记，MUST NOT 新增全局旋钮。
- 中断方法固定 signal（SIGALRM 只中断主线程、超时判失败后同会话继续）：thread 方法的整进程代价不适合作为全局方法，MUST NOT 被引入为全局方法。SIGALRM 无法中断 C 扩展深处的阻塞，此类用例的处置是拆分/改造用例或登记更长时限豁免，不是切换全局方法。

## Consequences

- 门对全部入口一致生效、单点维护；代价是嵌套 pytest 会话（pytester 样例落在仓内 basetemp，rootdir 上溯命中仓根）会继承 10s 门——门行为的自验证样例必须显式 `-o` 压低阈值并以最小 `pytest.ini` 钉 rootdir，这成为测试工程域的固定样板。
- 静默放宽通道不存在；偶发 10s 误杀按回归失败走既有修复链，不为抖动放宽全局门。
- 超时失败在 junit XML 中是普通 failure（消息含 `Timeout (>Ns) from pytest-timeout` 机读标识），回归读侧零改动；与 ADR-119/ADR-164 的有界全量套件入口（套件级硬超时）分层互补，互不替代。
