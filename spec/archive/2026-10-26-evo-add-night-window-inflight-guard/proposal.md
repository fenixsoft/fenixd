## Why

本地每天 04:30 前后的断网窗已连日击杀在飞 run（本夜三车道三杀：code-fix 第 3 批、自进化重试、告警处置 admin 会话）。存量防线只覆盖「派发时刻落窗」（evo-codefix-night-quiet-window）与死后冷却/抢救，两处盲区：一是窗前派出、窗中在飞的 run 无任何保护；二是 admin 会话派发（core/admin_monitor.py）完全无瞬断冻结/断窗避让，往窗口里派即烧，死后还留下 fail-closed 升级滞留（告警 6cea21da2e0b）。

## What Changes

1. 预计跨窗顺延：code-fix 夜间批守卫从「派发时刻落窗」升级为「预计跨窗」——派出时刻加同链近批实测时长估计的预计结束时刻，与静默窗区间相交即顺延到窗末。
2. admin 派发避让：_invoke_administrator 唤起闸门新增两不派条件——provider 瞬断冻结态与夜间断窗期，命中即本轮跳过、留待下轮。

## Out of Scope

- 不改冷却（evo-add-codefix-conn-error-cooldown）与 salvage（evo-code-fix-api-timeout-salvage）语义。
- 不处理已升级滞留信号的收口（由主体终态收口 SPEC 另行覆盖）。
- 不动 pm_engine 全局派发队列的既有瞬断冻结闸。