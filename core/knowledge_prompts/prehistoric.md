# 史前能力复原（prehistoric bootstrap）

你在 Fenix 项目主树根目录下工作。本次任务是「存量回填车道」史前复原段的一个 run：
归档目录全部始于 {{UNTIL_DATE}}，在此之前（仓库首提交 {{FIRST_REF}} 起至
{{UNTIL_DATE}} 前）的框架基础能力没有任何归档 delta 覆盖。你通过 git 考古 + 代码
骨架复原这批「史前能力」，产出清单与未覆盖能力的史前页，供回填车道求差与聚合。

## 输入

1. git 提交群（只读标题行，理解地基能力的演进脉络）：

   ```
   git log --reverse --format='%ad %s' --date=short --until={{UNTIL_DATE}} HEAD
   ```

2. `core/` 顶层模块骨架（模块名与模块 docstring 即能力边界）：验证引擎、状态机、
   派发、工作区管理、配置层等迁移期已存在的基础设施优先。

3. 归档链已覆盖能力全集（下方清单，求差基准）：清单内的能力**已被归档覆盖**。

## 产出（全部落盘后本 run 即结束，不要 git commit）

1. **史前能力清单** `{{PREHISTORIC_JSON_PATH}}`：JSON 数组，形如

   ```json
   [
     {"capability": "<kebab能力名>", "domain": "<kebab域目录名>",
      "baseline": "<一段话：该能力的史前基线规则（现行口径）>"}
   ]
   ```

   **宁缺勿滥**：只收「迁移期已存在、当前仍在生效、可从提交群与代码骨架确证」的
   基础能力；拿不准的不收（audit 车道后续可补）。清单须同时含已覆盖能力（其
   baseline 交给聚合批次作链头输入）与未覆盖能力两类，均需三字段齐备。

2. **史前能力页**：对清单中**未被归档覆盖**的能力（不在下方覆盖清单内），逐个写
   `spec/knowledge/domains/<域>/<能力>.md`：

   - marker 显式声明史前来源：

     `<!-- knowledge: capability=<能力名> rev=1 origin=prehistoric sources=git:{{FIRST_REF}}-..{{UNTIL_DATE}} -->`

   - 域优先复用既有 `spec/knowledge/domains/` 下已存在的域目录名；确无贴切域才新建
     （新建域须同步产出 `_domain.md` 并登记 `spec/knowledge/index.md`）；
   - 既有域的登记：把新页链接补进该域 `_domain.md` 的「能力页」表格（新行：
     能力页链接 + 一句话简介）与 `spec/knowledge/index.md` 的「能力域」表格
     （新域加一行：域名链接 + 一句话简介 + 能力数量纯数字）；
   - 单页（含 marker 与溯源段）不超过 150 行；
   - **禁历史叙述措辞**（「曾经/后来/当时/最初/迁移前」），只写现行规则；
   - 溯源段首行为史前复原行（**纯文本，不加链接**——无对应归档目录）：
     `- {{UNTIL_DATE}} 史前复原（git:{{FIRST_REF}}-..{{UNTIL_DATE}}） — 迁移期已存在的基础规则`。

3. 覆盖清单内的能力**不要**写页——其 baseline 已随清单交给聚合批次作链头输入。

## 归档链已覆盖能力全集（求差基准）

{{COVERED_CAPS}}

## 收尾自查（结束前逐项自查，任一不满足须修正后再结束）

- [ ] 清单 JSON 可解析、每项含 capability/domain/baseline 三字段；
- [ ] 每个未覆盖能力都有对应页面文件、marker 含 origin=prehistoric 且锚点形如
      `git:{{FIRST_REF}}-..{{UNTIL_DATE}}`；
- [ ] 单页不超 150 行、无历史措辞；
- [ ] 未修改 `spec/knowledge/` 与 `{{PREHISTORIC_JSON_PATH}}` 之外的文件。

{{VIOLATIONS_BLOCK}}
