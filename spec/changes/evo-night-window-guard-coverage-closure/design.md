# Design

## 缺省多窗化

core/code_fix.py:3346 常量改「03:00-03:15,04:15-04:45」；:3340-3345 常量注释与 :3381 解析器 docstring 同步（模板不强配策略保留：缺省即覆盖已观测散布形态，显式配置仍可覆盖）。解析器 _parse_night_quiet_windows（:3381）零改动，实测「03:00-03:15,04:15-04:45」解析两窗成立。缺省字面量另有三处同步消费面随本变更一并更新（tasks 1.3/1.4）：tests/test_code_fix_night_quiet_window.py:174 源码契约断言、fenixd.py:4525 手动触发回链文案（CODE_FIX_RESULT_MESSAGES["night_quiet_window"] 硬编码「默认 04:15-04:45」）、spec/knowledge/domains/code-fix-lane/codefix-night-quiet-window.md 知识页缺省值描述。运行时 .fenix/config.yaml 不入 git，作为部署侧覆盖手段存在但不入 SPEC 交付——todo 建议①的「零代码变更」以此等价替换为仓库内一行缺省变更，效果更强（fresh-boot 亦生效）。

## 自进化避让落点

写 fenixd.py:4843 _check_evolution_checkpoint（宿主守卫→保留清理→单飞→就绪扫描→派发；守卫落在保留清理之后、单飞判定与派发之前——prune 不因窗顺延而跳过），不写 core/agent_runner/maintenance_runs.py:1353 run_evolution——tests/test_code_fix_night_quiet_window.py:538-539 对 maintenance_runs.py/event_bus.py 有「night_quiet_window」子串缺席契约（assertNotIn；reason 值 night_quiet_window_deferred 含该子串，故守卫与 skip 日志都必须留在宿主层 fenixd.py，不得下沉）。时长估计样本策略对齐 core/admin_monitor.py:1992-2050（近几轮归档 run_metrics duration_s），窗解析复用 from .code_fix import _parse_night_quiet_windows（先例 core/admin_monitor.py:2086-2097）；配置读同键 admin.code_review_fix.night_quiet_window、缺省 NIGHT_QUIET_WINDOW_DEFAULT，不引入第二份窗配置/第二键，读取/解析/导入异常一律按无窗 fail-open（对齐 admin 唤起避让形态 admin_monitor.py:2093-2097）。跳过时不写就绪扫描副作用、不推进水位，下轮巡检自然重触。

## 预检单点

core/agent_runner/runner.py:5985 _run_agent（Popen :6138）为全部车道共用 Popen 单点——实测 dispute-judge（:1618）、spec-review（:1839）、impl 派发族（:3530）与 maintenance_runs 五处维护车道直调（:387/:854/:1462/:2083/:3248）全部汇入，一处改动全车道可达；但预检按 agent_type 白名单仅挂维护车道（evolution/code-review/code-fix/administrator/self-review）派发，dispatch 族（spec/impl/dispute-judge/spec-review）、regression（maintenance_runs.py:2848 run_regression）与交互式 run 不做探测顺延——与 proposal Out of Scope「不动 spec-review/regression 车道派发时点」一致，维护车道（含未来维护车道）受益。探测＝socket.getaddrinfo 解析 API base 域名（getaddrinfo 为阻塞调用、无原生超时参数：放独立线程 join(2-3s) 判超时，超时按失败顺延，悬挂线程随 daemon 生命周期滞留可接受）；失败→本轮派发顺延并写含 reason 的跳过日志，由各车道既有重触发节奏接续；探测自身抛错→记日志后照常派发（fail-open），绝不阻断主派发路径。与 provider_circuit 瞬断冻结正交（彼为事后熔断，此为派发前预检，provider_circuit.py:124-138 ENOTFOUND 分类保持现状）；仅挂派发前，在飞 run 不受影响。todo 建议③的「断连期顺延派发并记跳过日志」由此落地，消除 evo-1792177308 形态的秒死与告警噪音。

## 与归档非目标的关系

spec/archive/2026-10-13-evo-codefix-night-quiet-window 曾把「不引入对上游可用性的主动探测」列为非目标——彼时对象是 code-fix 短批、无实损证据；今散布多窗（内核日志 8 次）＋单夜 148.11 美元损失构成新证据，本 SPEC 显式推翻该决定，收窄为维护车道派发前、fail-open、秒级超时的轻量探测。

## 已知代价

缺省加入 03:00-03:15 后，01:00 出发的周期审查在保守估计下更易判跨窗顺延（与 review-night-window-resume-hardening 的 max 估计叠加，审查整体后移到窗后）——属预期行为：宁可窗后跑，不可窗内烧。