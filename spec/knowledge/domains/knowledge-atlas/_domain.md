# 知识真相源
> 最后更新：2026-10-05 03:23 UTC+8

知识真相源（`spec/knowledge/`）子系统：目录契约、归档蒸馏管线、ADR 决策索引、项目知识页签与配置开关等机制能力，加存量回填、周期体检、Graphify 关系图等维护车道。归档 SPEC 承担历史职责，真相源只装当前生效的业务规则，两者以溯源链接互指。本域能力页清单如下。

## 能力页

| 能力页 | 简介 | 更新时间 |
| --- | --- | --- |
| [knowledge-atlas-directory](knowledge-atlas-directory.md) | 真相源目录契约与能力页格式（marker 机器接口、溯源链接、150 行硬顶） | 2026-10-05 03:23 |
| [knowledge-distill-pipeline](knowledge-distill-pipeline.md) | 归档触发蒸馏管线（单点挂载、合并语义、收尾校验与自动提交） | 2026-10-05 03:23 |
| [knowledge-adr-index](knowledge-adr-index.md) | ADR 决策索引（抽取判据、三段式不可变、supersede 只标不改） | 2026-10-05 03:23 |
| [knowledge-dashboard-tab](knowledge-dashboard-tab.md) | 项目知识页签（按需加载、只读 API、index/ADR 视图） | 2026-10-05 03:23 |
| [knowledge-config](knowledge-config.md) | 知识真相源配置（knowledge.enabled 总开关与设置页登记） | 2026-10-05 03:23 |
| [knowledge-backfill](knowledge-backfill.md) | 存量归档批量回填（域骨架自举、台账断点续跑、批间校验提交） | 2026-10-05 03:02 |
| [knowledge-audit](knowledge-audit.md) | 周期 audit 体检（五类病灶、机械自修/语义转写分级处置、规模趋势） | 2026-10-05 03:02 |
| [knowledge-graph](knowledge-graph.md) | Graphify 关系图每日生成（fail-open、探测端点点亮、graph/ 三件套） | 2026-10-05 03:02 |
