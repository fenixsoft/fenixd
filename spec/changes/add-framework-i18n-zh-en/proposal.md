# 提案：框架国际化与中英文缺省支持

## Why

fenix 框架当前是纯中文产品：Dashboard 前端全站文案、后端流出到 Dashboard 的用户可见消息、CLI 人读输出全部只有中文，非中文使用者无法使用框架。本项目已有「英文 id + 中文标题」的双语数据基因（SPEC 命名体系），但界面层与消息层没有国际化机制。需要建立框架级 i18n 能力，并以中英双语为第一版缺省实现，让框架对英文用户开箱可用。

## What Changes

- **前端（Dashboard 全站）**：引入 Umi Max 内建 locale 机制（react-intl），全站文案（六常规页 + 全局组件 + 菜单/页题/浏览器标题）中英双语化；缺省跟随浏览器/系统 locale，配置页提供手动切换（zh-CN / en-US）并持久化到 localStorage；antd 组件族文案随语言联动；未翻译键回退中文。
- **后端（用户可见消息）**：新增消息目录单源（core 层 zh/en 双语字典），Dashboard API 返回的用户可见字符串（error 字段、状态/事件/处置链标签等展示型文本）经目录输出；locale 按请求解析（Accept-Language 头，前端请求层统一附带），无匹配回退中文；后端内部运行日志保持中文不属本期能力面。
- **CLI（人读输出）**：`bin/fenix_cli.py` 等命令行工具的人读提示（成功/失败/错误提示）经同一消息目录单源输出；locale 解析链 = `--lang` 参数 > `FENIX_LANG` 环境变量 > 用户级配置 `general.locale` > 缺省 zh。
- **非目标（本期不做）**：Agent 提示词（`agents/*.md`）与 skills 文档（`skills/*/SKILL.md`）不翻译——它们是 LLM 功能面，翻译可能改变 agent 行为，风险大于收益；`docs/help/*.md` 帮助文档正文保持中文（文档语料量大、随语言切换的收益低）；SPEC 生成产物（proposal/design/tasks 模板）保持中文。

## Capabilities

### New Capabilities

- `dashboard-i18n`: Dashboard 前端国际化——Umi locale 基建（zh-CN 缺省 + en-US 目录、baseNavigator 跟随系统、localStorage 持久化）、全站文案抽取与双语目录、菜单/页题/antd locale 联动、配置页「界面语言」切换子项、语言未覆盖键回退中文、守卫测试。
- `backend-message-i18n`: 后端用户可见消息国际化——core 层消息目录单源（zh/en）、Dashboard API 展示型字符串经目录输出、按请求 locale 解析（Accept-Language）与中文回退、内部日志不翻译边界。
- `cli-message-i18n`: CLI 人读输出国际化——与后端共用消息目录单源，locale 解析链（`--lang` > `FENIX_LANG` > `general.locale` > zh），bin 下 CLI 工具人读提示双语化。

### Modified Capabilities

（无——已检索 `spec/changes/*/specs/` 与 `spec/archive/*/specs/`，框架此前无 i18n 相关能力；设置页新增「界面语言」子项属 `dashboard-i18n` 新能力的增量面，不构成既有能力 Requirement 变更。）

## Impact

- **前端**：`core/dashboard/static/`——`config/config.ts`（locale 开启 + antd 联动）、`src/app.tsx`（菜单名/运行时配置 locale 化）、`config/routes.ts`（document.title 链路）、新增 `src/locales/`（zh-CN/en-US 目录单源）、六页 + 全局组件文案抽取、设置页新增语言子项面板；既有守卫测试（node --test tests/*.test.mjs）全量回归。
- **后端**：`core/` 新增消息目录模块；`core/dashboard/routes/`（展示型 error/label 字段经目录输出）；Dashboard 服务端零新端点。
- **CLI**：`bin/fenix_cli.py` 输出层接入消息目录；`core/config.py` 新增 `general.locale` 配置键（用户级/项目级作用域既有机制复用）。
- **依赖**：零新前端依赖（react-intl 由 `@umijs/max` 内建提供）；后端/CLI 零新依赖（纯 Python 字典目录）。
- **知识域**：落成后需回填 `spec/knowledge/domains/dashboard-frontend/`（语言偏好与切换机制，镜像 ui-theme 结构）与 CLI 消息目录纪律。
