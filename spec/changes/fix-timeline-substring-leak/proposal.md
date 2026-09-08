# fix-timeline-substring-leak

## Why

面板 SPEC 详情时间轴用子串匹配筛日志行：前缀名 spec（如 `add-verify-contract-autodraft`）会把姊妹 spec（`add-verify-contract-autodraft-ui`）的 `Updated SPEC` 状态更新整体吸收进自己的时间轴。2026-09-08 实证：`-ui` 的 12:16 收尾链（implemented→testing→verified→done→pushed）被错挂到基 spec 时间轴，打回重建的 from 推演指针被污染，基 spec 真实的「实现中→就绪」重启恢复被显示成「已推送→就绪」假回退；就近 error 覆写再把恢复文案贴满全部泄漏卡片。用户据时间轴做运维判断，假回退直接误导决策。

## What Changes

- `get_spec_timeline` 的 `Updated SPEC` 行判定由 `spec_name in msg` 子串匹配改为带引号全匹配 `f"'{spec_name}'" in msg`，杜绝姊妹 spec 状态泄漏（`Transition:` 正则已要求名字后紧跟空白，天然安全，不动）
- 打回重建分支：前向节点无同行 error 时 reason 置空（不再落 `_backtrack_reason` 的「状态回退」兜底文案），从结构上消除前向节点被就近 error 覆写传染的通道
- state 节点新增 `backward` 布尔字段（按 `_LIFECYCLE_ORDER` 判定方向），Transition 解析与打回重建两条路径统一输出
- 前端 `detail.tsx` 「↩ 状态回退」徽标判定由 `!!item.reason` 改为跟随 `backward` 字段（缺失时回退旧判定兼容存量），带 reason 的前向节点不再挂回退徽标
- 新增单测：名称隔离、from 推演保真、方向字段与徽标回归

## Capabilities

### New Capabilities

- `spec-timeline-accuracy`: SPEC 详情时间轴的名称精确隔离（子串泄漏免疫）、打回重建 from 推演保真、状态节点方向字段（backward）与前端回退徽标的方向化渲染

### Modified Capabilities

（无——时间轴此前无活跃 spec 级能力定义）

## Impact

- `core/dashboard/data.py`（get_spec_timeline 及打回重建/就近覆写邻域）
- `core/dashboard/static/src/pages/projects/detail.tsx`（时间轴卡片渲染）
- `tests/test_spec_timeline_name_isolation.py`（新增）
- 时间轴 API 响应新增 `backward` 字段（增量、向后兼容）；无配置/依赖变更；dist 不入库，merge 后框架自动重建
