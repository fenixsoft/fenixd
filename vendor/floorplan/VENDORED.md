# Vendored: floorplan

本目录是 [haydenschmitty/floorplan](https://github.com/haydenschmitty/floorplan) skill 包的
**vendored 快照**，作为本仓库的二进制依赖随库分发——运行时（项目架构图生成，
`core/dashboard/routes/architecture_routes.py`）直接读取本目录，**不执行任何联网安装**，
也不依赖用户环境安装的 skill。

## 溯源

| 项 | 值 |
|---|---|
| 上游仓库 | https://github.com/haydenschmitty/floorplan |
| 快照 commit | `94f81b463b7617e06d873ac71323ce71644c8399`（main 分支） |
| 上游版本 | 0.11.0（2026-11-16，见上游 CHANGELOG.md） |
| 许可 | MIT（见本目录 `LICENSE`，随包保留） |
| 落库日期 | 2026-11-25 |
| 运行时要求 | Node.js >= 18（零 npm 依赖，脚本为纯 ESM `.mjs`） |

## 与上游的差异

- **只保留 skill 本体**（`skills/floorplan/` 内容平铺到本目录：SKILL.md、workflow.json、
  `scripts/`、`references/`、`assets/`、`agents/`）。上游仓库顶层的插件打包与开发产物
  （`.claude-plugin/`、`.codex-plugin/`、`.agents/`、`docs/`、`tests/`、`tools/`、
  `package.json`、CHANGELOG.md、CHECKSUMS.txt 等）不入库——SKILL.md 运行期只引用
  本目录内的伴生文件，不读这些顶层产物。
- 新增本文件（溯源说明），上游无此文件。

## 升级方法

从上游对应 commit 复制 `skills/floorplan/` 目录整体替换本目录（剔除 skill 本体之外的
顶层产物，保留 `LICENSE` 与本文件），更新本文件的溯源表。禁止只替换 SKILL.md——指引
与伴生文件（scripts/assets 等）存在版本耦合。

## 运行形态（本项目用法）

- 生成走 headless claude 一次性 run（见 `architecture_routes.py` 的 prompt）：脚本均以
  `FLOORPLAN_UNATTENDED=1` 执行（unattended 模式：只写 map 目录、不写 CLAUDE.local.md、
  不动 `.git/info/exclude`、不起服务器不开浏览器），scan 用 `--out` 落到项目
  `.fenix/architecture/floorplan/.cache/`，build 用 `--out` 落到
  `.fenix/architecture/floorplan/`，最终经 map 目录内 `serve.mjs --export` 导出单文件
  `.fenix/architecture/diagram.html` 供 dashboard iframe 内嵌（export 版自含 hash CSP、
  无 Ask 条、无机器路径）。
- SKILL.md 中 `${CLAUDE_SKILL_DIR}` 占位符指本目录（SKILL.md 所在目录），生成 prompt
  已将其展开为绝对路径。
