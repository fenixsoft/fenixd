"""knowledge_routes.py — 项目知识真相源只读 API（add-knowledge-atlas）。

承载 2 个端点（均 GET、无副作用，project 从 query string 解析）：
- GET /api/knowledge/index?project=<name> → 总目录：index.md 文本 + 域清单
  + titles 标题映射（面包屑中文名数据源）；未初始化（无 index.md，首个蒸馏
  run 前）返回 ``initialized: False`` 占位结构。
- GET /api/knowledge/file?project=<name>&path=<rel> → 单文件内容。path 白名单
  前缀 ``domains/`` 与 ``adr/``；含 ``..`` / 绝对路径 / 反斜杠 / 越出真相源目录
  一律 400（路径穿越恒拒，先于存在性判断）；文件缺失 → 404。

蒸馏写侧在 core/knowledge.py（DistillManager），本路由层零写路径。
（GET /api/knowledge/graph 已随 graphify 关系图生成功能取消下线——2026-09-29，
生成车道与下发端点一并移除，前端探测代码同步删除。）
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger("fenixd.dashboard.routes.knowledge_routes")

# ADR 头部字段（模块级编译，_parse_adr_head / _adr_titles_from_index 用）
# [fenix-ignore:8d914361107d] 展示层有意宽松取原值下发：前端已无 adrs[].status
# 消费方（KnowledgeTab.tsx 全文无 .status 引用，ADR 清单视图已移除，仅保留
# adr/index.md 内容展示与 adrs[].title 面包屑），status 原值下发后无渲染影响；
# 按 core/knowledge.py 校验器（accepted|superseded）口径归一属行为变更，
# 留待 ADR 视图重构时一并处理。
_ADR_STATUS_RE = re.compile(r"^status:\s*(\S+)\s*$", re.M)
_ADR_SUPERSEDED_BY_RE = re.compile(r"^Superseded by:\s*(\S+)\s*$", re.M)
# ADR 首标题：'# ADR-NNN: <标题>' / '# ADR-NNN：<标题>'（distill.md 契约）
_ADR_TITLE_RE = re.compile(r"^#\s+ADR-\d{3}\s*[:：]\s*(.+?)\s*$", re.M)
# adr/index.md 表格行：'| ADR-NNN | 标题 | ...'（标题列兜底源）
_ADR_INDEX_ROW_RE = re.compile(r"^\|\s*(ADR-\d{3})\s*\|\s*([^|]+?)\s*\|", re.M)
# 首 H1 标题（titles 下发源）：'# <标题>'。能力页头部 marker 为 HTML 注释行、
# 二级标题缩进一格，均不匹配 ``^# ``，天然跳过；只取首处（首个 H1 即页题）。
_H1_TITLE_RE = re.compile(r"^#\s+(.+?)\s*$", re.M)

# 真相源目录相对路径（契约见 spec/knowledge/README.md）
KNOWLEDGE_DIR = "spec/knowledge"

# /api/knowledge/file 白名单前缀：能力页树 + ADR（index.md 走 /index 端点）
# 对端副本：前端 core/dashboard/static/src/pages/projects/components/
# KnowledgeTab.tsx 的 resolveKnowledgePath 亦持同一前缀白名单（仅站内导航
# 便利层）。新增/调整前缀时 MUST 两处同步，否则前端会把对应链接静默降级为
# SafeLink 外链导航而非站内拉取。
_ALLOWED_PREFIXES = ("domains/", "adr/")


def _parse_adr_head(text: str) -> tuple[str, str | None, str | None]:
    """解析 ADR 头部 ``(status, superseded_by, title)``；无 status 行回 'unknown'。

    契约见 core/knowledge_prompts/distill.md：status 行在 "## Context" 之前
    的头部；supersede 只标不改时头部追加 ``Superseded by: ADR-NNN(...)`` 行；
    首标题为 ``# ADR-NNN：<标题>``（半/全角冒号均收）。无标题行回 None
    （调用方以 adr/index.md 表格标题列兜底）。
    """
    head = text.split("## Context", 1)[0]
    m = _ADR_STATUS_RE.search(head)
    status = m.group(1) if m else "unknown"
    sm = _ADR_SUPERSEDED_BY_RE.search(head)
    tm = _ADR_TITLE_RE.search(head)
    return status, (sm.group(1) if sm else None), (tm.group(1) if tm else None)


def _adr_titles_from_index(text: str) -> dict[str, str]:
    """解析 adr/index.md 表格的 ``编号 → 标题`` 映射（标题列兜底源）。

    distill.md 契约列序为「编号、标题、状态、一句话摘要」；非表格形态
    （如列表）返回空映射，调用方回退 None。分隔行（``| --- |``）不匹配
    编号形态，天然跳过。
    """
    return dict(_ADR_INDEX_ROW_RE.findall(text))


def _read_h1_title(path: Path) -> str | None:
    """读文件提取首 H1 标题；读取失败/解码失败/无 H1 → None。

    titles 下发的单文件取题入口，调用方（域/能力页枚举）对 None 原样
    下发，前端按「无标题回退 slug」渲染，此处不抛错不告警（缺标题是
    蒸馏管线的合法中间态，非本端点异常）。
    """
    try:
        m = _H1_TITLE_RE.search(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return None
    return m.group(1) if m else None


def _safe_knowledge_file(proot: Path, rel: str) -> Path | None:
    """校验并解析用户提供的相对路径；不合法返回 None（调用方恒 400）。

    校验链（双保险）：非空、无反斜杠、非绝对路径、任意段非 ``..``、
    白名单前缀、resolve 后仍落在真相源目录内（防符号链接等绕过）。
    """
    if not rel or "\\" in rel or rel.startswith("/"):
        return None
    parts = Path(rel).parts
    if not parts or any(seg == ".." for seg in parts):
        return None
    posix_rel = Path(rel).as_posix()
    if not posix_rel.startswith(_ALLOWED_PREFIXES):
        return None
    kroot = (proot / KNOWLEDGE_DIR).resolve()
    try:
        # resolve 自身对含 NUL 字节的 rel 抛 ValueError，与越界共用同一拒绝分支（恒 400）
        resolved = (kroot / rel).resolve()
        resolved.relative_to(kroot)
    except ValueError:
        return None
    return resolved


class H14KnowledgeRoutesMixin:
    """H14 knowledge（对齐 H13 Architecture 汇聚方式；H13 已被占用）。"""

    def _api_knowledge_index(self, query):
        """GET /api/knowledge/index?project=<name>

        返回 ``{project, initialized, index_md, domains, adrs, titles}``；
        domains 为 ``[{name, pages, nav_exists}]``（pages 为域内能力页文件名清单，
        不含 _domain.md）；adrs 为 ``[{file, title, status, superseded_by}]``
        （按文件名排序，ADR 列表视图的编号/标题/状态标签数据源。title 取
        ADR 文件首标题 ``# ADR-NNN：<标题>``，缺失时以 adr/index.md 表格
        标题列兜底，仍缺为 null）。titles 为「页路径剥 .md → 首 H1 标题」
        映射（前端面包屑中文名数据源）：域键 ``domains/<域>`` 取 _domain.md
        首 H1，能力页键 ``domains/<域>/<页>`` 取页首 H1；无 H1/读取失败为
        null（前端回退 slug 展示）。ADR 标题不在 titles 重复下发，前端经
        adrs[].title 自行组装。``initialized`` 与 ``index_md`` 随
        index.md 存在性变化（缺失即 ``initialized: False`` / null）；
        ``domains``/``adrs``/``titles`` 始终按真相源目录实际内容填充——
        回填 bootstrap 先产域页、index.md 后置的中间态会出现
        ``initialized: False`` 且清单非空。项目不存在 → 404。
        """
        project = self._project_from_query(query)
        if project is None or not project.get("exists"):
            self._error(404, "project not found")
            return
        proot = Path(project["path"])
        kroot = proot / KNOWLEDGE_DIR
        index_md = kroot / "index.md"
        payload = {
            "project": project["name"],
            "initialized": index_md.is_file(),
            "index_md": None,
            "domains": [],
            "adrs": [],
            "titles": {},
        }
        if index_md.is_file():
            try:
                payload["index_md"] = index_md.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                logger.warning("knowledge index.md 读取失败（%s）: %s", project["name"], exc)
                self._error(500, "index.md 读取失败")
                return
        domains_dir = kroot / "domains"
        if domains_dir.is_dir():
            # 枚举本身失败（权限/IO）时按空清单降级，对齐 help_routes 双层容错口径
            try:
                domain_dirs = sorted(p for p in domains_dir.iterdir() if p.is_dir())
            except OSError as exc:
                logger.warning(
                    "knowledge domains 目录枚举失败（%s）: %s", project["name"], exc
                )
                domain_dirs = []
            for d in domain_dirs:
                # 枚举本身失败（权限/IO）时按空清单降级，对齐上下两处容错口径
                try:
                    pages = sorted(
                        p.name for p in d.glob("*.md") if p.name != "_domain.md"
                    )
                except OSError as exc:
                    logger.warning(
                        "knowledge domains/%s 能力页枚举失败（%s）: %s",
                        d.name,
                        project["name"],
                        exc,
                    )
                    pages = []
                payload["domains"].append(
                    {
                        "name": d.name,
                        "pages": pages,
                        "nav_exists": (d / "_domain.md").is_file(),
                    }
                )
                # titles：域键 + 能力页键（与前端面包屑/页路径同形，剥 .md）
                payload["titles"][f"domains/{d.name}"] = _read_h1_title(
                    d / "_domain.md"
                )
                for pg in pages:
                    payload["titles"][f"domains/{d.name}/{pg[:-3]}"] = (
                        _read_h1_title(d / pg)
                    )
        adr_dir = kroot / "adr"
        if adr_dir.is_dir():
            # adr/index.md 表格标题列（ADR 文件首标题缺失时的兜底源）
            index_titles: dict[str, str] = {}
            adr_index = adr_dir / "index.md"
            if adr_index.is_file():
                try:
                    index_titles = _adr_titles_from_index(
                        adr_index.read_text(encoding="utf-8")
                    )
                except (OSError, UnicodeDecodeError):
                    index_titles = {}
            try:
                adr_files = sorted(adr_dir.glob("ADR-*.md"))
            except OSError as exc:
                logger.warning(
                    "knowledge adr 目录枚举失败（%s）: %s", project["name"], exc
                )
                adr_files = []
            for adr in adr_files:
                try:
                    status, superseded_by, title = _parse_adr_head(
                        adr.read_text(encoding="utf-8")
                    )
                except (OSError, UnicodeDecodeError):
                    status, superseded_by, title = "unknown", None, None
                if title is None:
                    nm = re.match(r"^(ADR-\d{3})-", adr.name)
                    if nm:
                        title = index_titles.get(nm.group(1))
                payload["adrs"].append(
                    {
                        "file": adr.name,
                        "title": title,
                        "status": status,
                        "superseded_by": superseded_by,
                    }
                )
        self._json(payload)

    def _api_knowledge_file(self, query):
        """GET /api/knowledge/file?project=<name>&path=<rel>

        白名单（domains/、adr/ 前缀）内的单文件内容。违规路径（``..``、
        绝对路径、越界前缀、穿越）恒 400 且不泄露存在性；白名单内但文件
        缺失 → 404。
        """
        project = self._project_from_query(query)
        if project is None or not project.get("exists"):
            self._error(404, "project not found")
            return
        rel = query.get("path", [None])[0]
        proot = Path(project["path"])
        target = _safe_knowledge_file(proot, rel or "")
        if target is None:
            self._error(400, "非法路径（仅允许 domains/ 与 adr/ 前缀）")
            return
        if not target.is_file():
            self._error(404, "文件不存在")
            return
        try:
            content = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning("knowledge 文件读取失败（%s）: %s", rel, exc)
            self._error(500, "文件读取失败")
            return
        self._json(
            {
                "project": project["name"],
                "path": Path(rel).as_posix(),
                "content": content,
            }
        )
