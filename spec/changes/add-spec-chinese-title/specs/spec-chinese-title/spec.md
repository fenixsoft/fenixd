# spec-chinese-title Spec

## ADDED Requirements

### Requirement: 立项中文标题生成与存储

SPEC 立项（change 脚手架创建）时 SHALL 同时产生一个 5-25 字的中文标题，写入 `spec/changes/<name>/.spec.yaml` 的 `title` 字段。英文名（kebab-case 目录名）与中文标题为 id 与 name 的关系：一切输入、寻址、排序、信号与状态机继续以英文名为唯一键，中文标题纯展示、不参与任何寻址或匹配逻辑（名称搜索命中除外，见列表能力）。中文标题长度 5-25 字为**生成纪律**（两条立项通道的起草提示词约束），读侧与 API 不做长度校验、容错透传。

`--modify` 更新既有 SPEC 时，标题随需求演变可同步更新；标题仍准确时保持不变，MUST NOT 强制改写。

#### Scenario: fenix-new 立项写入标题

- **WHEN** 用户经 /fenix-new 立项新 SPEC（`fenix_spec.py new <name>` 之后、注册之前）
- **THEN** `.spec.yaml` 含 `schema: spec-driven`、`created`、`mode`、`title` 四字段，title 为 5-25 字中文标题

#### Scenario: evo 通道立项写入标题

- **WHEN** 自进化车道起草的草稿经 `materialize_draft` 落盘（spec 契约含 `title_cn` 字段）
- **THEN** 落盘的 `.spec.yaml` 在 schema/created/mode 之后含 `title: <title_cn 值>` 行；spec 契约缺 `title_cn` 时落盘不含 title 行、草稿不作废（容错缺省）

#### Scenario: 标题不参与寻址

- **WHEN** 任何消费方以 SPEC 为键操作（目录寻址、信号文件、STATE 条目、CLI/API 写入、fix-* 树构造、列排序）
- **THEN** 一律使用英文名；中文标题不出现在任何寻址路径或匹配键中

### Requirement: 读侧归档回退与 API 透传

title 读取 SHALL 单点实现：活跃目录 `spec/changes/<spec>/.spec.yaml` 优先，缺失时归档回退（与 `resolve_spec_dir` 同语义：归档目录名 = 日期前缀 + spec 名 + 可选冲突后缀）；字段缺失 / 文件缺失 / 解析失败 / 非法 spec 名一律返回 None（读侧容错，不抛异常）。`/api/specs` 列表项与 `/api/specs/<spec>` 详情 SHALL 透传 `title` 字段（string 或 null）。归档侧读取 SHALL 由调用方每轮单次扫描 `spec/archive/` 建立名称→目录映射后下发，MUST NOT 对每个已归档 spec 独立 glob（/api/specs 性能治理纪律）。

#### Scenario: 活跃 SPEC 读取标题

- **WHEN** `/api/specs?project=<p>` 响应某活跃 SPEC 条目且其 `.spec.yaml` 含非空 `title`
- **THEN** 该条目 `title` 字段为该字符串

#### Scenario: 已归档 SPEC 读取标题

- **WHEN** 某 SPEC 已迁出至 `spec/archive/<date>-<name>/` 且归档目录 `.spec.yaml` 含非空 `title`
- **THEN** `/api/specs` 响应该（archived=true）条目的 `title` 为该字符串

#### Scenario: 缺失容错

- **WHEN** 某 SPEC 的 `.spec.yaml` 缺 `title` 字段 / 文件不存在 / YAML 解析失败 / spec 名非法
- **THEN** API 条目 `title` 为 null，列表前端不渲染副标题行，其余字段与行为不变

### Requirement: 存量回填

本 SPEC 交付时 SHALL 为存量全部 SPEC 回填中文标题：活跃 `spec/changes/` 与归档 `spec/archive/` 逐目录读取 proposal/design 起草 5-25 字标题；归档目录缺 `.spec.yaml` 的（38 个）按脚手架约定补写（`schema: spec-driven` + `created` 取自归档清单条目 + `title`）。回填 MUST 幂等：已有非空 `title` 的文件跳过不覆盖。实现期新出现的缺标题 SPEC（实现窗口内新建/新归档）由收尾增量回扫兜底纳入。

#### Scenario: 全量回填完成

- **WHEN** 回填收尾自检运行（遍历 `spec/changes/` 与 `spec/archive/` 全部 `.spec.yaml`）
- **THEN** 全部文件含非空 `title` 字段且长度在 5-25 字范围内；自检脚本对缺标题或越界条目报错退出

#### Scenario: 回填幂等

- **WHEN** 回填对已含非空 `title` 的 `.spec.yaml` 执行
- **THEN** 原 title 保持不变（不覆盖、不重复追加 title 行）
