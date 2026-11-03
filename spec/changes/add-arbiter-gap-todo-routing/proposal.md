## Why

arbiter 立项通道产出的「提案最小成文」草案连续两例被 spec-review 两轮否决冻结
（2026-11-03 `fix-scenario-revision-choice-registration-surface` substantive 桶：
前提被现行代码证伪；`fix-escalation-freeze-vs-parallel-admin-race` format 桶：
方案主体缺失占位文本），根因是**车道职责越界**而非提案质量可调参：框架缺口
（裁决注册表、升级竞态等机制面）的修复需要设计与产品面裁量，arbiter 的调查
报告粒度天然不足以成文，其立项产出必然是占位草案闯评审硬门。用户定调车道
边界：**arbiter 只修 SPEC 问题，不修框架缺口**——框架缺口发现记自省 todo.md，
由框架自改进车道统一消费立项。拆掉立项通道后，提案质量治理的三层补丁
（晋升守卫/查重扩展/前提实测）全部不需要——出口关掉，问题连根消失。

## What Changes

- **立项通道退役**：arbiter 消费调查报告 `proposals` 数组的立项写点
  （三限节流+物化+add_spec）整体移除；`_materialize_proposal` 与常量
  `PROPOSAL_MAX_PER_RUN` / `PROPOSAL_WEEKLY_QUOTA` 删除
- **gap→todo 路由**：调查报告的提案数组改语义为 `gaps`（框架缺口发现），
  消费端逐条记 `.fenix/todo.md`（走既有 fs_utils todo 锁 + todo_format 结构
  契约，来源标记 arbiter + 触发签名 + run_id，条目按「可直接起草 SPEC」标准）；
  自进化车道既有 todo 消费机制不变，天然接手立项
- **台账 kind 演进**：`spec-proposed` / `proposal-dedup` 写点改为 `gap-noted`
  （append-only 台账既有条目原样保留）；消费端对旧 `proposals` 字段容错
  （切换窗内旧 run 产物记 WARNING 台账不落池，不静默丢失）
- **prompt 契约红线**：`agents/arbiter.md` 立项节流三限段与 proposals schema
  改写为禁立项红线 + gaps 上报纪律；「修复走裁决包建议人类或立项」的「或立项」
  半句改为「或记 todo 由自进化立项」
- **知识治理**：`arbiter-proposal-filing` 能力页退役注记与 `arbiter-lane` 页
  立项节流→禁立项改写，经知识 `_inbox` 投递由蒸馏折叠

## Capabilities

### New Capabilities

（无——路由能力挂既有 `arbiter-lane` 能力的新增需求）

### Modified Capabilities

（无 spec 级修改——`arbiter-lane` 既有需求（触发面/白名单/配额）不变，本次为
ADDED 新需求；`arbiter-proposal-filing` 能力在 spec 层无既有需求块（其归档
变更系清退载体无 specs/），契约改写走知识页治理不经 spec delta）

## Impact

- `core/pm_engine/arbiter.py`：立项写点/物化/节流常量移除，gaps→todo 路由，
  台账 kind 演进
- `agents/arbiter.md`：红线与报告 schema 改写（prompt 契约段，merge 纪律注意）
- `tests/test_arbiter_lane.py`：新增退役断言与 todo 路由断言（实测评审注：既有套件无立项路径测试，grep proposal/materialize/立项 均零命中立项主题，纯新增不改既有用例）
- `spec/knowledge/_inbox/`：两页知识改写素材投递（蒸馏折叠）
- daemon 行为变更，合并后需重启生效（restart_request 交付项）
- 不动：spec-review 晋升 lint 的缺 tasks.md 放行语义（fast-track 依赖）、
  `add_spec` 存在性查重（其他车道在用）、台账既有 spec-proposed 条目
