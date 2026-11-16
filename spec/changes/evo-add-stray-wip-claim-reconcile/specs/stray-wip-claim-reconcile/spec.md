# 散件指纹入库自动核销升级告警

## ADDED Requirements

### Requirement: 升级条目携带指纹清单

maintree_stray_wip_stale 升级条目生成时 SHALL 把指纹文件集（路径列表）写入条目结构化字段；探测侧 SHALL 只消费结构化字段或可回提取的 evidence 文本，MUST NOT 依赖自然语言全文理解。

#### Scenario: 升级条目附清单

- **WHEN** 周期盘点产生第 N 度升级条目（core/worktree_manager/stray_wip.py 告警落库记录构造处）
- **THEN** 条目结构化字段含指纹文件集路径列表，与 stray_wip 指纹归一结果同源

### Requirement: 指纹入库自动核销

周期盘点 SHALL 对每个未核销（handled=False）的 maintree_stray_wip_stale 升级条目探测其指纹文件集是否已全部被 main 基线后新提交覆盖且工作区 clean；命中时 SHALL 自动核销（handled=True、handled_by="auto-resolve-claim"）并在 resolve_note 回填认领 commit 引用；任一文件未入库或工作区仍脏 SHALL 逐位保留原状。

#### Scenario: 人工以提交认领后自动核销

- **WHEN** 某悬置升级条目挂指纹 N 文件，main 基线后存在覆盖全部指纹文件的提交（单波或多波均可）、工作区该集合 clean
- **THEN** 条目核销 handled=True，resolve_note 含认领 commit SHA 与「人工已以提交认领主树直改形态，请确认是否仍需建立 worktree 车道」

#### Scenario: 未入库或仍脏不核销

- **WHEN** 指纹文件集中任一文件仍处于 tracked 未提交状态，或仅部分文件入库
- **THEN** 条目逐位保留（handled=False 不变），升级节奏与人工队列可见性不变

### Requirement: 存量条目回提取参与

无结构化指纹字段的存量悬置条目 SHALL 按 evidence 文本回提取文件集参与同一探测；回提取失败 SHALL 保守跳过（保持原状），MUST NOT 误核销。

#### Scenario: 旧形态条目回提取核销

- **WHEN** 存量悬置条目 evidence 含 5 个文件路径且该集合已全部入库 clean
- **THEN** 按同一条件核销并回填 commit；回提取不出完整文件集的另一条目保持原状