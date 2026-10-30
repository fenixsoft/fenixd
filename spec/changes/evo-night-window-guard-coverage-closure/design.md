# Design

## 缺省多窗化

core/code_fix.py:3249 常量改「03:00-03:15,04:15-04:45」；:3245-3247 与 :3280 附近注释同步（模板不强配策略保留：缺省即覆盖已观测散布形态，显式配置仍可覆盖）。解析器 _parse_night_quiet_windows（:3276）零改动，实测「03:00-03:15,04:15-04:45」解析两窗成立。运行时 .fenix/config.yaml 不入 git，作为部署侧覆盖手段存在但不入 SPEC 交付——todo 建议①的「零代码变更」以此等价替换为仓库内一行缺省变更，效果更强（fresh-boot 亦生效）。

## 自进化避让落点

写 fenixd.py:4504 _check_evolution_checkpoint（宿主守卫→保留清理→单飞→就绪扫描 守卫链的前置），不写 core/agent_runner/maintenance_runs.py:1209 run_evolution——tests/test_code_fix_night_quiet_window.py:512-513 对 maintenance_runs.py/event_bus.py 有 night_quiet 关键字缺席契约。时长估计样本策略对齐 core/admin_monitor.py:1865-1921（近几轮归档 run_metrics duration_s），窗解析复用 from .code_fix import _parse_night_quiet_windows（先例 core/admin_monitor.py:1945-1949）。跳过时不写就绪扫描副作用、不推进水位，下轮巡检自然重触。

## 预检单点

core/agent_runner/runner.py:5842 为维护车道共用 Popen 单点，一处改动全车道（含未来车道）受益。探测＝socket.getaddrinfo 解析 API base 域名、2-3 秒超时；失败→本轮派发顺延并写含 reason 的跳过日志，由各车道既有重触发节奏接续；探测自身抛错→记日志后照常派发（fail-open），绝不阻断主派发路径。与 provider_circuit 瞬断冻结正交（彼为事后熔断，此为派发前预检）；仅挂派发前，在飞 run 不受影响。todo 建议③的「断连期顺延派发并记跳过日志」由此落地，消除 evo-1792177308 形态的秒死与告警噪音。

## 与归档非目标的关系

spec/archive/2026-10-13-evo-codefix-night-quiet-window 曾把「不引入对上游可用性的主动探测」列为非目标——彼时对象是 code-fix 短批、无实损证据；今散布多窗（内核日志 8 次）＋单夜 148.11 美元损失构成新证据，本 SPEC 显式推翻该决定，收窄为维护车道派发前、fail-open、秒级超时的轻量探测。

## 已知代价

缺省加入 03:00-03:15 后，01:00 出发的周期审查在保守估计下更易判跨窗顺延（与 review-night-window-resume-hardening 的 max 估计叠加，审查整体后移到窗后）——属预期行为：宁可窗后跑，不可窗内烧。