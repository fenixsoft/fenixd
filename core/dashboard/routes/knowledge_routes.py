"""knowledge_routes.py — 项目知识真相源只读 API（add-knowledge-atlas）。

承载 3 个端点（均 GET、无副作用，project 从 query string 解析）：
- GET /api/knowledge/index?project=<name> → 总目录：index.md 文本 + 域清单；
  未初始化（无 index.md，首个蒸馏 run 前）返回 ``initialized: False`` 占位结构。
- GET /api/knowledge/file?project=<name>&path=<rel> → 单文件内容。path 白名单
  前缀 ``domains/`` 与 ``adr/``；含 ``..`` / 绝对路径 / 反斜杠 / 越出真相源目录
  一律 400（路径穿越恒拒，先于存在性判断）；文件缺失 → 404。
- GET /api/knowledge/graph?project=<name> → graph/graph.html 存在性探测：
  存在下发文件（text/html + CSP ``sandbox allow-scripts``，对齐 architecture
  diagram 先例——生成物内联脚本以不透明源运行），缺失 404 结构化错误。

蒸馏写侧在 core/knowledge.py（DistillManager），本路由层零写路径。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger("fenixd.dashboard.routes.knowledge_routes")

# ADR 头部字段（模块级编译，_parse_adr_head 用）
_ADR_STATUS_RE = re.compile(r"^status:\s*(\S+)\s*$", re.M)
_ADR_SUPERSEDED_BY_RE = re.compile(r"^Superseded by:\s*(\S+)\s*$", re.M)

# 真相源目录与 graph 产物相对路径（契约见 spec/knowledge/README.md）
KNOWLEDGE_DIR = "spec/knowledge"
GRAPH_FILENAME = "graph.html"

# /api/knowledge/file 白名单前缀：能力页树 + ADR（index.md 走 /index 端点）
_ALLOWED_PREFIXES = ("domains/", "adr/")


def _parse_adr_head(text: str) -> tuple[str, str | None]:
    """解析 ADR 头部 ``(status, superseded_by)``；无 status 行回 'unknown'。

    契约见 core/knowledge_prompts/distill.md：status 行在 "## Context" 之前
    的头部；supersede 只标不改时头部追加 ``Superseded by: ADR-NNN(...)`` 行。
    """
    head = text.split("## Context", 1)[0]
    m = _ADR_STATUS_RE.search(head)
    status = m.group(1) if m else "unknown"
    sm = _ADR_SUPERSEDED_BY_RE.search(head)
    return status, (sm.group(1) if sm else None)


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
    resolved = (kroot / rel).resolve()
    try:
        resolved.relative_to(kroot)
    except ValueError:
        return None
    return resolved


class H14KnowledgeRoutesMixin:
    """H14 knowledge（对齐 H13 Architecture 汇聚方式；H13 已被占用）。"""

    def _api_knowledge_index(self, query):
        """GET /api/knowledge/index?project=<name>

        返回 ``{project, initialized, index_md, domains, adrs}``；domains 为
        ``[{name, pages, nav_exists}]``（pages 为域内能力页文件名清单，
        不含 _domain.md）；adrs 为 ``[{file, status, superseded_by}]``（按
        文件名排序，ADR 列表视图的状态标签数据源）。未初始化（真相源目录
        或 index.md 缺失）→ ``{initialized: False, index_md: null,
        domains: [], adrs: []}`` 占位。项目不存在 → 404。
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
        }
        if index_md.is_file():
            try:
                payload["index_md"] = index_md.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                logger.warning("knowledge index.md 读取失败（%s）: %s", project["name"], exc)
                self._json({"error": "index.md 读取失败"}, 500)
                return
        domains_dir = kroot / "domains"
        if domains_dir.is_dir():
            for d in sorted(p for p in domains_dir.iterdir() if p.is_dir()):
                pages = sorted(
                    p.name for p in d.glob("*.md") if p.name != "_domain.md"
                )
                payload["domains"].append(
                    {
                        "name": d.name,
                        "pages": pages,
                        "nav_exists": (d / "_domain.md").is_file(),
                    }
                )
        adr_dir = kroot / "adr"
        if adr_dir.is_dir():
            for adr in sorted(adr_dir.glob("ADR-*.md")):
                try:
                    status, superseded_by = _parse_adr_head(
                        adr.read_text(encoding="utf-8")
                    )
                except (OSError, UnicodeDecodeError):
                    status, superseded_by = "unknown", None
                payload["adrs"].append(
                    {
                        "file": adr.name,
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
            self._json({"error": "非法路径（仅允许 domains/ 与 adr/ 前缀）"}, 400)
            return
        if not target.is_file():
            self._json({"error": "文件不存在"}, 404)
            return
        try:
            content = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning("knowledge 文件读取失败（%s）: %s", rel, exc)
            self._json({"error": "文件读取失败"}, 500)
            return
        self._json(
            {
                "project": project["name"],
                "path": Path(rel).as_posix(),
                "content": content,
            }
        )

    def _api_knowledge_graph(self, query):
        """GET /api/knowledge/graph?project=<name>

        graph/graph.html 存在 → 下发（text/html + CSP sandbox，同
        architecture diagram 先例）；缺失 → 404 结构化错误（code
        ``knowledge_graph_not_generated``，前端按 code 渲染占位）。
        """
        project = self._project_from_query(query)
        if project is None or not project.get("exists"):
            self._error(404, "project not found")
            return
        proot = Path(project["path"])
        graph = proot / KNOWLEDGE_DIR / "graph" / GRAPH_FILENAME
        if not graph.is_file():
            self._json(
                {"error": "关系图尚未生成", "code": "knowledge_graph_not_generated"},
                404,
            )
            return
        self._send_file(
            graph,
            "text/html; charset=utf-8",
            extra_headers=[
                ("Content-Security-Policy", "sandbox allow-scripts"),
            ],
        )
