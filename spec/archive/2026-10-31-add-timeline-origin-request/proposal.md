# Proposal: add-timeline-origin-request

## Why

用户经 /fenix-new 立项时提出的原始一句话需求目前没有任何持久化：STATE.md entry 只存 status/priority 等调度字段，proposal.md 是需求 Agent 加工后的文本，不是原话。时间过去了，在 Dashboard 上回看某个 SPEC 时无法知道「这个 SPEC 当初是用户随口一句什么话立项的」——尤其已经 done/pushed 的 SPEC，需求原文彻底不可追溯。

## What Changes

- 新增立项原话持久化：fenix-new 流程在创建 SPEC 脚手架时，把用户输入的原始一句话需求**原文照录**写入 `spec/changes/<name>/request.md`（随 SPEC 目录入库、归档时随目录迁移，零额外迁移逻辑）。
- 时间轴展示：SPEC 详情「运行时间轴」的**首个状态转移节点**（存在 drafted→reviewing 时恰为该转移；fast-track/直接晋升则为 drafted→ready 等）下方渲染原话引用块。
- 存量兼容：无 request.md 的存量/归档 SPEC 静默省略该展示（与时间轴 lane_summary 同模式），接口零报错，零数据迁移。
- 写侧契约进 skill 文档：`skills/fenix-new/SKILL.md` 增加写 request.md 的步骤与「原文照录、--modify 不更新」纪律。

## Capabilities

### New Capabilities
- `timeline-origin-request`: SPEC 立项原始一句话需求的持久化（request.md）与运行时间轴首个状态转移节点下的展示；含缺失文件的静默降级与归档路径解析。

### Modified Capabilities

（无——归档中既有的 timeline-admin-events / timeline-gate-failure-display / timeline-ocr-lane-visibility 均为其它节点/注记能力，与本能力无交集。）

## Impact

- `skills/fenix-new/SKILL.md`：新增「写 request.md」步骤（写侧唯一入口）。
- `spec/changes/<name>/request.md`：新文件形态，随既有 spec 目录提交流程入库，无新增提交逻辑。
- `core/dashboard/data/timeline.py`：`get_spec_timeline` 读取 request.md（经 resolve_spec_dir，活跃/归档通吃）并附到排序折叠后的首个 state 节点 `origin_request` 字段。
- `core/dashboard/static/src/pages/projects/components/SpecTimeline.tsx`：state 节点渲染分支增加 `origin_request` 引用块；字段缺失不渲染。
- 无数据库/配置迁移；STATE.md schema 零变更。
