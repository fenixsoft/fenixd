# Proposal: wrapup-push-branch-guard

## Why

pm_engine 收尾推送判据与工作落地分支脱钩：core/pm_engine/engine.py:3446（归档收口 :3628 同款）硬编码 `_git_push_ref("main")`，而项目实际检出分支可为 master——推送校验的分支根本不承载工作。成功判据仅 returncode==0（:3333 起），Everything up-to-date 即成功、无 tip 前进断言；:3512 done→pushed 仅凭 main_ok。

后果已量化（cloud-phone，检出分支 master）：7 次「Main push succeeded」中 5 次为 up-to-date 空转（origin/main tracking ref 11-09 16:21 后零更新），另 4 次被远端 non-fast-forward 拒绝（04:33/05:03Z p2p、05:29/06:03Z m3）；STATE.md 8 个 spec 全标 pushed 与「origin/main 缺 95 提交」并存——pushed 状态不再证明交付可达远端，windows-desktop-client 全套交付一度仅存本地。讽刺的是 SHA 比对机器（ls-remote/rev-parse，engine.py:3290-3320）已存在，但只用于 fenix/* 分支 best-effort 去重。

缺陷在检出分支=main 的项目（fenixd 自身）不触发，纯属侥幸；任何检出分支≠main 的项目上收尾推送全部空转。

## What Changes

- **推送目标改实际基分支（core/pm_engine/engine.py）**：收尾与归档推送目标从硬编码 main 改为实际集成分支（复用 core/git_base_branch.py 基分支探测）。
- **tip 前进断言与空转告警（core/pm_engine/engine.py）**：推送成功判定从 returncode==0 升级为「远端 tip 前进」断言（复用既有 SHA 比对机器）；Everything up-to-date 空转不再计成功并发单条告警。
- **启动对账**：daemon 启动时对账本地相对远端的领先提交数并上报，兜住判据失明期的静默缺口。
- **单测**：覆盖基分支选择、tip 断言、空转告警、对账上报。

## Capabilities

### delivery-push-integrity

见 specs/delivery-push-integrity/spec.md。

## Impact

- core/pm_engine/engine.py 收尾推送路径（推送目标、成功判定、pushed 门数据源）。
- core/git_base_branch.py 仅被复用不修改（探测单源已有）。
- 不改变推送时机、退避与凭证处理（在途 fix-push-credential-env-and-retry-rearm 范围互斥、其 spec 明文不新增推送语义）。