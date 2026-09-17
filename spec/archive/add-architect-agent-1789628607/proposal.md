# Proposal: add-architect-agent

## Why

框架现有 9 类 agent 角色中，运维侧的「自省 Agent」（每日定时）数据源是**转录日志、告警、run 统计、git 提交**等运行期信号，产出「浪费/失误/可改进」条目；它**看不到代码本身的非功能属性（DFX）劣化**——可读性、健壮性、性能效率、可测试性、可观测性。这类劣化不会产生告警、不会失败、不会烧钱，但会持续抬高后续每次改动的成本，直到某天成为事故根因。当前缺少一个「以代码为主要数据源」的角色来持续看护 DFX 并向用户提出重构建议。

同时，本框架自身的巨型文件（`core/dashboard/data.py` 5334 行、`core/pm_engine/verification.py` 6304 行、`core/agent_runner/runner.py` 5076 行）正是这类无声劣化的典型，需要一个常设角色防止其复发。

## What Changes

- **新增一种 agent 角色「架构师（architect）」**：在每日自省时刻（与自省同周期、复用同一调度入口）执行，数据源为**自省增量窗口内变动过的代码文件清单**，方法为 DFX 五维评估（可读性/健壮性/性能效率/可测试性/可观测性），产出结构化重构建议条目。
- **审查范围受限**：MUST 只审查自省增量窗口 `[last_run_at, now]` 内（可配置上限截断）变更过的代码文件；MUST NOT 主动做全仓扫描。全仓级重构（如本次初始化重构）只由人工驱动立项。
- **产出汇入既有建议体系**：建议条目写入项目 `todo.md`（与自省条目同一文件与格式契约），供用户阅读与据此起草 SPEC；架构师 MUST NOT 自动创建 SPEC。
- **模型分配面板**：`agents.models` 新增 `architect` 槽位，Dashboard「模型分配」页新增对应卡片（前后端白名单同步）。
- **自进化页签设置**：在「自进化」页签新增架构师设置卡片（启用开关 / 审查窗口等），随既有配置热更新生效。

## Capabilities

### New Capabilities

- `architect-agent`: 架构师角色的触发时机、受限审查范围、DFX 评估方法、建议产出契约。

### Modified Capabilities

- `llm-model-assignment` / `agent-prompt-files`: 角色集新增 `architect`（模型分配白名单与 prompt 文件映射同步扩展）。
- `daily-self-review`: 自省调度入口追加一次架构师 run（共享调度入口与状态文件，但「已执行」判定使用独立状态键，避免两角色互相抑制）。

## Impact

- **代码**：`agents/architect.md`（新）、`core/config.py`（`KNOWN_AGENT_TYPES`）、`core/agent_runner/prompt_builder.py`（`AGENT_PROMPT_FILES` + `_build_architect_prompt`）、`core/agent_runner/runner.py`（`AGENT_TYPE_TO_ROLE` + `run_architect`）、`core/agent_runner/run_files.py`（`RUN_ID_AGENT_PREFIXES`）、`core/self_review.py`（调度接入 + 状态键分离 + 窗口内变更清单 + run 统计排除）、`core/dashboard/data.py`（受管键四处必改点）、前端 `AgentModelPanel.tsx` 与自进化页签卡片。
- **配置**：新增 `agents.models.architect`（角色模型分配）与项目级 `admin.architect.enabled` / `admin.architect.window_max_hours`（新增配置键须同步 Dashboard 界面与 `docs/help/09-config.md`）。
- **文档**：`docs/help/02-concepts.md`（Agent 类型表）、`docs/help/09-config.md`（`agents.models` 角色枚举）。
- **测试**：角色注册、prompt 加载、调度触发、状态键分离、窗口内变更清单、run 统计排除、建议产出、前后端白名单一致性、受管键读写往返。
- **注意（2026-09-15 评审更正）**：原稿称「本 spec 依赖可读性重构完成」——实测该依赖不可满足也无必要：`refactor-dashboard-data-module` 仅为 `spec/changes/` 下草稿未实现，`core/dashboard/data.py`（5334 行）与 `core/dashboard/data/` 包均按现状存在/不存在，故本 SPEC 直接登记 `core/dashboard/data.py` 为权威修改路径。唯一需避让的在飞改动是 `AgentModelPanel.tsx`（工作树已有并行 SPEC 的未提交修改），改动点限于 `AGENT_ROLES` 数组。
