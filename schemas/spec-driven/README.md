# spec-driven schema（vendored）

本目录为 fenix 原生 SPEC 生成器（`core/spec_gen.py`）所需的 spec-driven schema 数据，
从 OpenSpec 包 vendored 而来，供 fenix 在**不安装 npm 依赖** 的情况下
生成 proposal / design / specs / tasks 四种 artifact。

## 来源与版本

- 来源包：`@fission-ai/openspec` v1.3.1（npm 全局包）
- 原始路径：`/usr/lib/node_modules/@fission-ai/openspec/schemas/spec-driven/`
- 许可证：MIT（Copyright (c) 2024 OpenSpec Contributors）
- vendored 日期：2026-08-26

## 内容

| 文件 | 用途 |
|------|------|
| `schema.yaml` | artifact 定义（id / generates / requires / instruction / description）与 `apply` 段 |
| `templates/proposal.md` | proposal 文档骨架（## Why / What Changes / Capabilities / Impact） |
| `templates/design.md` | design 文档骨架（## Context / Goals / Decisions / Risks） |
| `templates/spec.md` | spec 文档骨架（## ADDED Requirements + Scenario） |
| `templates/tasks.md` | tasks 清单骨架（## 分组 + `- [ ] x.y` 勾选） |

## 升级方式

升级 schema 时替换本目录内容为上游新版本即可：

```bash
# 示例（上游路径可能变化）：
# cp -r <上游包>/schemas/spec-driven/* schemas/spec-driven/
```

`core/spec_gen.py` 通过 `Path(__file__).resolve().parent.parent / "schemas" / "spec-driven"`
定位本目录，替换后重启 fenix 相关命令即生效。生成的 artifact 布局
（`spec/changes/<name>/proposal.md` 等）与 fenix 核心的硬依赖保持一致。
