## Why

fenixd 框架与 dsh-plugins 目前只有「一次性安装」能力：Agent 按 `docs/install.md` 完成初装后，后续版本演进（框架已发布 v0.1.0→v0.1.7，插件 v0.1.0→v0.1.2）对已安装用户不可见、不可达——想获得新功能必须人工重走整本安装手册。需要一套不新增发布服务器、直接消费既有 GitHub Release/Tag 制品的自动更新机制，让已安装用户持续获得最新功能。

## What Changes

- **版本发现**：新增更新检查引擎——读本地版本单源（框架制品根 `VERSION` 文件），周期查询 GitHub `releases/latest` API（fenixd 公开仓库匿名直下；dsh-plugins 按现状兼容主源解析），语义化版本比较后判定可更新。
- **检查调度**：daemon 挂载低频周期检查（默认每日一次、失败退避静默重试），检查结果持久化为框架级更新状态，多项目 daemon 幂等共享，互斥防并发检查。
- **通知与一键更新**：dashboard 运维页新增更新状态卡（当前版本/最新版本/检查时间/形态标识）与「检查更新」「一键更新」动作；更新为半自动——检查自动、应用必须用户确认。
- **框架更新应用**：下载 Release 制品 + sha256 强校验 → staging 解压 + 完整性断言 → 双平台统一「停 daemon → 原地换装 → 起 daemon」三段式（在飞 run 预检保护）→ 用户级配置与项目骨架天然保留 → 失败回滚旧目录（保留一代）。
- **dsh-plugins 更新应用**：下载解压新版插件制品 → 对既有 profile 中 link: 指向旧插件目录的 fenix 插件重新注册（desktop profile 降级为文档指引，不自动改写）→ lib/ 完整性验证。
- **形态降级**：源码形态（git clone，无 `VERSION` 文件）不参与自动更新，UI 显式提示「git pull 更新」；dsh-plugins 私库鉴权按「匿名先行、失败回退凭证」双腿处理。
- **配置面**：用户级配置新增 `update:` 段（开关/间隔/镜像），跟随既有用户级配置体系。

## Capabilities

### New Capabilities

- `auto-update`: 框架与插件的版本发现、周期检查、更新通知、一键更新应用（框架三段式换装 + 插件重注册）、失败回滚、源码形态降级与配置面的端到端能力。

### Modified Capabilities

（无——既有能力域 knowledge index 22 域均不含版本更新语义，本变更为纯新增能力；daemon 排水/重启语义仅复用不修改。）

## Impact

- **新增**：`core/` 更新引擎模块（版本比较、GitHub API 客户端、下载校验、换装编排）；`bin/` 更新 CLI 入口；dashboard 更新状态 API 与运维页 UI。
- **修改**：daemon 周期调度挂载点（低频检查任务）；dashboard 运维页路由；`docs/install.md`（新增更新章节，改写「升级=重装手册」现状）；`docs/help/`；`~/.fenix/config.user.template.yaml`（`update:` 段注释文档）。
- **复用不修改**：`restart_request` 信号与 supervisor 排水重启、installer 幂等语义、`scripts/package.sh` 的 VERSION 写入与完整性断言清单、GitHub API `releases/latest` 查询先例（install.md §3A/§6b）。
- **跨仓库边界**：dsh-plugins 仓库发布流水线（版本文件进包）不属本仓库交付物；本能力以目录名解析为插件版本现状兼容主源，dsh-plugins 侧增强列为文档建议。
- **风险面**：daemon 自更新期间在飞 run 保护；Windows 目录占用（CWD/句柄）约束换装策略；GitHub API 匿名限流（60/h）下的检查退避；dsh 版本门（peerDependencies）更新后兼容放行路径。
