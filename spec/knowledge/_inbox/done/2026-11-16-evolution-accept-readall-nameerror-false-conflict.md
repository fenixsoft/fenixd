# evolution accept read_all NameError('self') 假冲突全灭事件与进程内旧码固化机理（2026-11-16）

## 背景

18:44 用户在 dashboard 配置页自进化菜单点「批量同意」，20 个 analyzed 改进项全部报错「SPEC 名无法消解冲突」并从表格消失（状态置 draft_failed）。排查定案为 dashboard 进程持有坏代码中间稿的运行时事故，非数据/逻辑缺陷。投递供 distill 折叠。

## 结论（当前事实）

- **事故链**：14:16 fix-windows-service-userprofile 会话编辑 core/state_machine.py 的中间稿里，新增的 `StateParser._read_text_tear_guarded` 引用了未绑定的 `self`（该法是 @staticmethod）；fenix-dashboard.service 14:16:17 重启，在 14:16:19 定稿写入前 import 了这份坏稿并被 sys.modules 固化；此后每次 `resolve_spec_name`（core/evolution.py:1750）经 `_conflicted`（core/evolution.py:1764-1775）调 `state_machine.read_all()` 必抛 `name 'self' is not defined`，except 分支 fail-closed 判冲突 → 基名与 `-<item_id前6位>` 双候选全灭（.fenix/logs/fenixd.log 行 14253-14292 恰 40 条 WARNING，20 项 × 2 候选）→ 20 项全 draft_failed。两个已提交版本（b6bce5afc 与其父提交）AST 均干净——坏代码只存在于编辑在飞的中间稿。
- **进程内旧码固化机理**：evolution_routes.py:31-42 `_evolution_state_machine()` 惰性 import + 每请求新建实例，但 import 走 sys.modules 缓存——进程加载的模块版本固化为「首次 import 时刻」的磁盘内容，与后续磁盘修复无关。dashboard 启动树本身不 import state_machine（全链惰性），首次 evolution/状态页请求才触发。⇒ 「改完代码立刻重启服务」若与编辑窗口重叠，重启反而固化中间稿；「服务没重启」不等于「跑的是旧版」——也可能跑的是某次晚于你上次编辑的快照。
- **堆取证方法论**：/proc/PID/mem 找中文字符串常数常为假阴性——CPython 非纯 ASCII str 内部按 UCS2 存储，UTF-8 字节副本只在 str 被 encode 过（写日志/文件）后才存在。判「进程内代码版本指纹」必须用纯 ASCII 标记：本次用 qualname `StateParser._read_text_tear_guarded`（该方法只在 b6bce5afc 含中间稿才定义，父提交没有）实锤老进程持有未提交中间稿；中文 needle 命中=有 UTF-8 副本，未命中≠代码不存在。
- **git 日期考古陷阱**：rebase 会错位 author date，核对「哪个提交改过该文件」必须用 commit date（%cd）；`git log --follow -p` 输出被管道 head 截断会低估单提交差异。
- **恢复路径**：items.jsonl 中 draft_failed 且 reason==SPEC 名无法消解冲突、spec 字段完整、spec_name/decided_* 为 None 的条目，清 draft_failed_reason、status 置回 pending 即可重入（accept_item 幂等分支允许 pending/accept_failed）。本次 20 条已按此恢复（备份 .history/items.jsonl.bak-*），fenix-dashboard 已重启（新 PID 2895346）载入干净代码。

## 证据

- 日志：.fenix/logs/fenixd.log 行 14253-14292（2026-11-16T10:44:21~24Z，40 条 `evolution: 读取 STATE 判定重名失败，保守按冲突处理: name 'self' is not defined`）
- 版本链：core/state_machine.py 磁盘 == b6bce5afc（commit 14:18:21「fix(windows): v0.1.4 实测反馈 items 4-8——写侧三连修 + 裸 PATH 窗口消除」，唯一今日改动者）；父提交无 _read_text_tear_guarded；HEAD=faeb4eadd
- 进程：老 dashboard PID 2781822（14:16:17 启动，堆含 tear-guard qualname、无最终版中文 warning）已重启销毁；daemon worker 4 进程（14:20-14:33 启动）晚于定稿写入持干净代码

## 建议的系统性加固（distill 时转 SPEC 候选）

1. fail-closed 告警文案应携带异常类型与堆栈摘要（如 `SPEC 名无法消解冲突（read_all: NameError: name 'self' is not defined）`），而非笼统冲突话术——本次 20 项报错文案完全同质，掩盖了「是运行时异常不是真冲突」的信号。
2. read_all / _conflicted 的异常路径应可自愈：连续 N 次同一异常告警升级 + 提供「重置为 pending 重试」的运维动作（本次靠手工改台账）。
3. 服务重启/守护进程应避开「编辑在飞」窗口：fix 会话 commit 后再重启服务，或重启前校验待载入模块可编译（py_compile）+ 关键函数 smoke（read_all 空跑）。
4. 批量同意前端应把逐条失败原因聚合展示（现仅 toast 报错名，20 项同文案无差异线索）。

## 更新目标页（distill 时）

`spec/knowledge/domains/self-evolution/` 相关能力页（evolution accept/resolve_spec_name 冲突消解语义段补「read_all 异常 fail-closed 会成批误杀」子形态与恢复路径）；若 dashboard 进程模型有专页则补「sys.modules 固化首次 import 时刻代码版本」机理。
