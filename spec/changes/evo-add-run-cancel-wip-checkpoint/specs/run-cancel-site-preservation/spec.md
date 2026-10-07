# run-cancel-site-preservation

## ADDED Requirements

### Requirement: run 取消路径现场保全

run 取消终止时必须尝试保全未提交现场：在取消旗标被确认命中且 worktree 在手时，先执行 WIP checkpoint（锚点 cancel），checkpoint 失败只降级不阻断取消收口；无现场可保全（attempt 间隙）时直接按既有取消收口。

#### Scenario: 用户取消在飞 run 时未提交工作先入 checkpoint

- **When** 取消旗标在 run 轮询环内被确认命中、当前 attempt 的 worktree 路径在作用域内
- **Then** 先调用既有 _wip_checkpoint_commit_safe 保全现场（checkpoint 消息含锚点 cancel 与 spec 名，便于审计区分「用户取消但现场已保全」），随后按既有取消路径收口
- **And** checkpoint 失败仅记录 WARNING，不阻断、不延迟取消收口

#### Scenario: attempt 间隙取消无现场可保全

- **When** 取消命中 attempt 间隙（not_running、无 worktree 可保全）
- **Then** 跳过 checkpoint，直接按既有取消收口，不报错

#### Scenario: 取消审计文案如实描述现场去向

- **When** 发出 run 取消审计告警
- **Then** recommended_action 如实描述：失败 implementer worktree 将登记为 legacy 保留（宽限期后回收），未提交改动不进入分支提交；不再使用「将随 cleanup(success=False) 丢弃」的失实表述

### Requirement: dashboard 取消入口二次确认

用户经 dashboard 发起 run 取消必须经过确认，且确认控件须带危险标识。

#### Scenario: QualityTab 取消按钮先确认后取消

- **When** 用户点击 QualityTab 的「取消」按钮
- **Then** 先弹出确认框（danger 标识），确认后才调用取消 API；取消请求路径与既有 ApiError.code 稳定错误码分支兼容