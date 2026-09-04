# FAQ 与故障排查

按「现象 → 根因 → 处置」排查 Fenix 常见问题。每条都是真实运行中可能遇到的场景，交叉链接到各专题篇。

## 1. SPEC 卡在 ready 不派发

- **现象**：SPEC 状态长期为 ready，没有 implementer run 启动
- **根因**（按概率排序）：
  - 有更高优先级 SPEC 占用并发额度（`agents.max_concurrent`）
  - 达到每日运行上限 `agents.daily_run_limit`
  - 达到实现尝试预算（`_impl_run_budget_used >= impl_run_budget`）
  - SPEC 处于派发锁退避期（`pm.dispatch_backoff_schedule`，error 记录 backoff until）
  - daemon 未运行
- **处置**：
  - `/fenix-status` + Dashboard 概览页确认 daemon 健康
  - 查 `.fenix/logs/fenixd-<year>.log` 的 dispatch 相关记录
  - 查 STATE.md 该 spec 的 `error` 与 `_impl_run_budget_used` 字段
  - 若是预算耗尽：人工评估后调整 `agents.impl_run_budget`（约 30s 热更新）并 reset spec

相关：[调度与治理规则](06-governance.md#三类预算)、[SPEC 生命周期与状态机](03-lifecycle.md#blocked阻塞)

## 2. SPEC 反复打回（ready↔implementing 空转）

- **现象**：SPEC 在 ready 和 implementing 之间反复横跳，无明显进展
- **根因**：派发后 run 秒挂（启动即失败），进入冷却后又被立即重派
- **处置**：
  - 查看最新 impl run jsonl 首条事件（秒挂原因通常是环境/命令错误）
  - 看 Admin Monitor 是否报了 `flapping` 或 `repeated_failures` 信号
  - 修复根因（如损坏的 commands.test/build）后 reset spec

## 3. 烧钱快（token 消耗异常）

- **现象**：Dashboard token 面板数字涨得快，或收到 80%/100% 预算告警
- **根因**：
  - 验证场景反复失败导致修复循环多轮重验
  - 卡住的 run 在超时监督续期（extension）中空转
  - 多个同根 fix 并行派生
- **处置**：
  - 设为长超时续期上限 `agents.timeout_supervision.max_extensions` 调小或为 0
  - 检查是否陷入修复循环：看 `.fenix/verify-progress/<spec>/` 重验轮数与失败截图
  - 紧急止损：Dashboard 冻结该 SPEC
  - 预算告警本身不自动冻结，由人工决策（[配置参考](08-config.md#agents)）

## 4. merge 冲突反复失败

- **现象**：SPEC 在 merge-back 阶段反复失败，最终 blocked
- **根因**：与主分支/其它 worktree 产生 git 冲突，连续失败达 `merge_breaker_threshold`（默认 2）熔断
- **处置**：
  - 按提示清理 git 状态（stash / 分支冲突）
  - 手动解决冲突后 reset spec 重新 merge
  - 查 `merge_streak` 告警（critical 级）证据

相关：[调度与治理规则](06-governance.md#merge-修复通道与熔断)

## 5. 验证反复失败（fix 修不好）

- **现象**：验证报告持续 fail，fix 分支派生了多层（fix-fix-…）
- **根因**：根因未定位准（验证报告证据不足），或环境导致伪失败
- **处置**：
  - 先排除伪失败：构建失败/应用不可达不判 bug-found；确认不是环境问题
  - 看失败截图 `.fenix/verify-progress/<spec>/screenshots/` 与 report.json 的 assertion message
  - 修复循环有 3 轮流断；触发了 `family_explosion`（fix 族谱超限）则转人工
  - 人工审视 verify.yaml 契约（BASE_URL 铁律是否正常注入）

相关：[验证体系](05-verification.md)、[文件与数据地图](09-artifacts.md)

## 6. 告警横幅频响（升级告警反复弹）

- **现象**：Dashboard 顶部横幅同一 SPEC 反复出现告警
- **根因**：`admin.escalation_cooldown_minutes`（默认 15 分钟）冷却内会抑制；频响通常意味着困境真实存在且 auto-resolve 了又复发
- **处置**：
  - 查 admin_alerts.json 处置记录，看自动解决依据
  - 对照信号类型查治理篇对应规则

## 7. daemon 反复重启 / 断档

- **现象**：SPEC 进度倒退、中断状态被回退 ready
- **根因**：daemon 由 supervisor 托管（`fenixd_supervisor.py`），异常退出自动拉起；重启后 `implementing`/`testing` 回退 ready
- **处置**：
  - 查 daemon 日志 `.fenix/logs/fenixd-<year>.log` 尾部，确认崩溃原因
  - `/fenix-setup` 重建环境或 `/fenix-dashboard` 跨项目统一管理
  - 重启恢复是设计行为（[03 生命周期](03-lifecycle.md#daemon-重启中断恢复)），非数据丢失

## 8. 希望人工接管某个 SPEC

- **现象**：想暂停自动化，自己手工处理，或让 Administrator 介入
- **处置**：
  - **冻结**：Dashboard SPEC 行「冻结」或 `/fenix-freeze` → blocked + frozen 标记，自动链全部剥离
  - **解冻**：处理完用「解冻」恢复原状态
  - **呼叫 Admin**：Dashboard SPEC 行「呼叫 Admin」写 admin_invoke_request.json，daemon 下一轮拾取唤起

相关：[SPEC 生命周期与状态机](03-lifecycle.md#冻结与解冻)、[Dashboard 使用指南](07-dashboard.md)

## 9. 配置改了不生效

- **现象**：改了 `.fenix/config.yaml` 键，行为没变
- **根因**：
  - 改的是需重启生效的键（表见 [配置参考](08-config.md)）
  - `agents.timeout_supervision` 与顶层 `timeout_supervision` 同时配置，顶层是回退开关
  - 模板值与代码缺省不一致导致误读（[模板值与代码缺省不一致](08-config.md#模板值与代码缺省不一致)）
- **处置**：按键的生效方式决定重启与否；以项目 config.yaml 实际值为准

## 10. 找不到某个文件/目录

- **现象**：排查时需要某个产物（报告/日志/截图）找不到
- **处置**：对照 [文件与数据地图](09-artifacts.md#出问题去哪查对照表) 逐项核对；`.fenix/` 内文件可安全重新生成，缺失不一定是异常

## 相关文档

- [核心概念与架构](02-concepts.md)、[SPEC 生命周期与状态机](03-lifecycle.md)
- [验证体系](05-verification.md)、[调度与治理规则](06-governance.md)
- [配置参考](08-config.md)、[文件与数据地图](09-artifacts.md)