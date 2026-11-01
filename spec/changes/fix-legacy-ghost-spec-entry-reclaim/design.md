# Design: 存量幽灵条目结构性清退通道

## 背景

arbiter 早期版本 `_apply_proposals` 裸 add_spec 注册 STATE 条目、不创建
`spec/changes/<name>/` 目录，产出「幽灵条目」：评审链路对目录缺失条目必然
spec-review-incomplete 冻结（fix-planner 实证），spec 列表 UI 只枚举目录故
用户不可见。7f7ee45e2 已修增量（物化 proposal 先于注册，物化失败跳过立项
只记台账），但存量幽灵条目无终态通道——只能走「评审拒绝×2 → 冻结 → 人工
升级」，每条烧多个评审 run + 一次人工介入（本条目实证：单条成本 5 评审
run ≈ $3.3 + 1 人工升级，另有 1 run 被重启打断）。

## 目标

存量与漏网幽灵条目由 daemon 自动对账结构性清退，聚合留痕可审计，不再逐条
冻结/升级烧预算；正常条目零影响。

## 关键决策

### D1 不引入新状态机状态

原提案措辞「结构性落终态（revoked）」：代码库状态机无 `revoked` 枚举
（core/state_machine.py `VALID_TRANSITIONS`，终态仅 `pushed`），为从未立项
的条目扩状态机（枚举/序列化/UI/门禁全链路）代价与收益不成比例。幽灵条目
的定义就是「从未物化立项」——`remove_spec`（core/state_machine.py:2777，
`.STATE.md.lock` flock 内原子读取-剔除-写回）移除 + 台账 + 聚合告警留痕即
结构性终态语义。目录归档一致性由调用方负责的既有契约在此不适用：幽灵条目
本无目录，无可归档对象。

### D2 幽灵指纹：三条件 AND（零误杀取向）

对 STATE 中每个非终态条目（终态 `pushed` 豁免），以下三条件**同时**成立才判幽灵：

1. `spec_has_content(project_root, name)` 为 False（core/pm_engine/
   spec_integrity.py:71 既有纯函数：目录不存在/为空/无 proposal/design/
   tasks/specs/**/*.md）。物化过最小 proposal 的条目（7f7ee45e2 范式）恒为
   True，天然不命中——本条目自身即此形态。
2. git 全历史零提交：`git -C <project_root> log --all --
   spec/changes/<name>` 输出为空。已归档/曾提交后目录被误删的条目不会命中
   （历史仍在），只清退「从未立项过」的裸注册产物。
3. 新鲜度豁免：条目 created 距今 ≥ 30 分钟。物化与注册间理论上存在短暂竞
   态窗口，新条目不立即清退，留待下一轮对账。

任何一条不成立 → 不清退（维持既有链路）。三条件 AND 使误杀前提收敛为
「目录从未存在且从未提交且已注册超 30 分钟」——与幽灵定义重合。

### D3 清退动作与留痕

单轮对账先收集全部命中条目，再批量执行：

- 逐条 `remove_spec`（原子）；spec 名含非法路径成分（`_is_safe_spec_name`
  拒绝，对齐 spec_has_content 同谓词保守语义）的条目保守跳过不清退，只记
  告警待人工。
- 逐条台账留痕：kind=`ghost-entry-reclaimed`，含指纹三证据（created、目录
  探测结果、git log 空输出）。
- **单条聚合告警**：一轮至多一条告警，列出本轮全部清退条目与各自证据
  （替代逐条 freeze→escalate 的人工通道）；防重对齐
  `check_spec_content_missing` 的 full_scan 未处理告警先例
  （spec_integrity.py:253——同指纹未处理告警在场时不重复告警）。
- frozen 标记不豁免：冻结只是评审链路的烧钱等待态，指纹本身已证明「从未
  立项」（孪生条目 blocked+frozen 即此形态）。

### D4 挂点与配置

- 对账入口：daemon 启动回填期一次 + full_scan 周期复扫。组件方法形态
  （SpecIntegrityGate 同域新增），engine 挂点调用；幂等——非幽灵条目零副
  作用、零日志噪音。
- 配置开关 `gates.ghost_entry_reclaim`（默认 on）经 ConfigLoader 点号键读
  取；off 时对账入口直接返回。

### D5 边界

- worktree：git 判定统一 `git -C project_root`（daemon 主树视角）。
- 清退不触碰 spec/changes/ 目录（幽灵条目本无目录）；若目录被外部并发创
  建，指纹条件 1 在当轮已判 False，无竞争破坏面。
- 实现验证用 dry-run：实现 run 对主树 STATE 快照只读判定（命中恰为孪生条
  目），不做实盘 remove_spec——实盘清退由 daemon 合并后首轮对账自动完成。

## 回归防线

- 增量防复发：7f7ee45e2 物化先于注册；物化失败跳过立项只记台账，不再产
  裸注册条目。本对账是存量清道夫，不改变任何正常流转。
- 正常条目零影响：物化过 proposal → 条件 1 False；曾提交 → 条件 2 False；
  新条目 → 条件 3 False。评审中/实现中/冻结中且有目录的条目全部不命中。
- 测试：tests/test_spec_content_integrity.py 扩展——指纹三条件真值表、新
  鲜度豁免、非法名跳过、remove_spec/台账/聚合告警断言、幂等重放（第二轮
  零清退零重复告警）、off 开关跳过。
