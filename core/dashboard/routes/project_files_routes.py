"""project_files_routes.py — H15 项目文件浏览（add-project-home-tab）routes。

承载 4 个端点（query project + path，均 GET 无副作用）：
- GET /api/project-files/list    → 目录列表（git 属性 + README 判定 + non_git）
- GET /api/project-files/content → 文件内容（文本/二进制判定 + 256 KiB 截断）
- GET /api/project-files/download → 原始字节流（attachment，RFC 5987 文件名）
- GET /api/project-files/raw     → 图片内联字节流（白名单扩展名 + 精确
  Content-Type，供前端 <img> 直显；project-home-tab 增强 2026-11-10）

list/content 走 ``self._json``；download/raw 自写响应（流式 64 KiB 分块 +
Content-Length 实值，不走 ``_json``——原始字节流非 JSON）。四条路由以
3 元组注册（routes/base.py GET 表）：文件树含实时 git 属性，签名不廉价，
不参与 304 协商（无签名函数条目即不协商，宁缺 304 不假 304）。

项目解析口径对齐 ``project_routes._project_query_or_error``：缺 project
400、未知/目录缺失 404 "project not found"。路径错误响应体不含内部路径
细节（对齐 ``_api_project_describe`` 泛化文案纪律）：越界/``.git`` 一律
400 "Invalid path"，不区分具体越界形态。
"""

from __future__ import annotations

import logging
import urllib.parse
from pathlib import Path

from core.dashboard.data.project_files import (
    DOWNLOAD_CHUNK_BYTES,
    PathEscape,
    file_content,
    image_content_type,
    is_known_path,
    list_directory,
    resolve_relative,
    visible_files,
)

logger = logging.getLogger("fenixd.dashboard.routes.project_files_routes")


class H15ProjectFilesRoutesMixin:
    """H15 project-files（项目首页页签四通道）。"""

    def _project_files_target(self, query, what: str):
        """四端点共用解析：项目校验（对齐 _project_query_or_error）+ path
        containment。成功返回 (root, relpath, abs_path)；失败已发送错误
        响应并返回 None。path 缺省按根目录（空串）处理——list 通道根查询
        是主形态。"""
        project = self._project_query_or_error(query, what)
        if project is None:
            return None
        relpath = query.get("path", [""])[0] or ""
        root = Path(project["path"])
        try:
            abs_path = resolve_relative(root, relpath)
        except PathEscape:
            # 泛化文案：不回显 relpath/root 细节（越界探测面最小化）
            self._error(400, "Invalid path")
            return None
        return root, relpath, abs_path

    def _api_project_files_list(self, query):
        """GET /api/project-files/list?project=<name>&path=<relpath>

        目录列表：``{branch, latest, entries, readme, non_git}``（+
        可选 truncated_count）。磁盘不存在/实为文件的路径 → 404（path
        not found）：gitignored 目录（node_modules 等）2026-11-11 起随
        hidden 条目一并可列/可进（containment 后以磁盘 is_dir 为准）；
        磁盘不存在的集合外路径同样 404。
        """
        target = self._project_files_target(query, "项目文件列表")
        if target is None:
            return
        root, relpath, abs_path = target
        if relpath != "":
            # 集合校验（containment 双保险之外的第二道，design D3）：
            # 子目录查询做集合判定（根目录查询恒真，跳过）；非 git 项目
            # （集合为 None）交 list_directory 按 non_git 形态响应。
            # 2026-11-11 起：纯忽略目录不在集合内但磁盘存在 → 可进
            # （hidden 条目可导航）；磁盘不存在仍 404。
            files = visible_files(root)
            if files is not None and not (
                is_known_path(files, relpath) or abs_path.is_dir()
            ):
                self._error(404, "path not found")
                return
        if not abs_path.is_dir():
            # 文件路径不经列表通道（notes.txt 等）——集合内文件同样 404
            self._error(404, "path not found")
            return
        self._json(list_directory(root, relpath))

    def _api_project_files_content(self, query):
        """GET /api/project-files/content?project=<name>&path=<relpath>

        文件内容：``{content, lines, bytes, truncated, binary}``。目录 →
        400（目录不经内容通道）；不存在/非文件 → 404；gitignored 文件按
        磁盘实况 containment 后照常服务（与 GitHub「工作树实况」语义一致）。
        """
        target = self._project_files_target(query, "项目文件内容")
        if target is None:
            return
        _root, _relpath, abs_path = target
        try:
            if abs_path.is_dir():
                self._error(400, "path is a directory")
                return
            if not abs_path.is_file():
                self._error(404, "file not found")
                return
            self._json(file_content(abs_path))
        except OSError:
            # containment 通过后的读取竞态（并发删除等）：不外泄路径细节
            self._error(404, "file not found")
            return

    def _api_project_files_download(self, query):
        """GET /api/project-files/download?project=<name>&path=<relpath>

        原始字节流下发：Content-Length 取 stat 实值、64 KiB 分块流式发送；
        ``Content-Disposition: attachment; filename*=UTF-8''<basename>``
        （RFC 5987，quote 编码后 CR/LF 不可能出现在头值内，防注入）。
        目录 → 400；不存在 → 404。自写响应不走 ``_json``。
        """
        target = self._project_files_target(query, "项目文件下载")
        if target is None:
            return
        _root, _relpath, abs_path = target
        try:
            if abs_path.is_dir():
                self._error(400, "path is a directory")
                return
            size = abs_path.stat().st_size
        except OSError:
            self._error(404, "file not found")
            return
        filename = abs_path.name
        encoded = urllib.parse.quote(filename, safe="")
        self._mark_response_started()
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(size))
        self.send_header(
            "Content-Disposition",
            f"attachment; filename*=UTF-8''{encoded}",
        )
        # 二进制/octet-stream 强制不嗅探（含 HTML 形态文件的直开防线）
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command == "HEAD":
            return
        try:
            with abs_path.open("rb") as f:
                remaining = size
                while remaining > 0:
                    # 以已声明 size 为上界：并发追加时不超发字节，keep-alive
                    # 分帧不失步
                    chunk = f.read(min(DOWNLOAD_CHUNK_BYTES, remaining))
                    if not chunk:
                        # 并发截断致实际字节 < 声明长度：客户端会等不足字节
                        # 挂起，置 close_connection 让残留随连接关闭作废
                        self.close_connection = True
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except BrokenPipeError:
            # 客户端中断下载：交 _handle_inner 的 BrokenPipeError 分支静默收场
            raise
        except OSError:
            # 读中途失败（并发删除等）：响应已开始，不可再写第二响应；
            # 泛化留痕（不含路径细节），连接上的半截响应随异常终止
            logger.warning("文件下载读流失败（读取中断，响应已开始）")

    def _api_project_files_raw(self, query):
        """GET /api/project-files/raw?project=<name>&path=<relpath>

        图片内联通道（project-home-tab 增强）：仅服务图片扩展白名单
        （``IMAGE_INLINE_TYPES``），Content-Type 按扩展名精确下发，供前端
        ``<img>`` 直显。与 download 共用 containment/流式骨架，差异点：
        inline 语义（无 attachment 头）；非图片扩展 → 400（该通道专用于
        内联展示，保存文件走 download）；svg 追加 ``CSP: sandbox``（SVG
        可内嵌 ``<script>``，直开/内联场景一律禁脚本）。目录 → 400；
        不存在 → 404。自写响应不走 ``_json``。
        """
        target = self._project_files_target(query, "项目文件图片")
        if target is None:
            return
        _root, _relpath, abs_path = target
        # 目录/存在性先于扩展白名单（目录无后缀，先判扩展会把目录误报成
        # "not an inline image"，文案歧义；对齐 download 的错误形态次序）
        try:
            if abs_path.is_dir():
                self._error(400, "path is a directory")
                return
            size = abs_path.stat().st_size
        except OSError:
            self._error(404, "file not found")
            return
        ctype = image_content_type(abs_path)
        if ctype is None:
            self._error(400, "not an inline image")
            return
        self._mark_response_started()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(size))
        # 精确 Content-Type 之外仍不嗅探（双保险，对齐 download 防线）
        self.send_header("X-Content-Type-Options", "nosniff")
        if ctype == "image/svg+xml":
            self.send_header("Content-Security-Policy", "sandbox")
        self.end_headers()
        if self.command == "HEAD":
            return
        try:
            with abs_path.open("rb") as f:
                remaining = size
                while remaining > 0:
                    # 以已声明 size 为上界：并发追加时不超发字节，keep-alive
                    # 分帧不失步（与 download 通道同口径）
                    chunk = f.read(min(DOWNLOAD_CHUNK_BYTES, remaining))
                    if not chunk:
                        # 并发截断致实际字节 < 声明长度：置 close_connection
                        # 让残留随连接关闭作废，避免客户端等不足字节挂起
                        self.close_connection = True
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except BrokenPipeError:
            raise
        except OSError:
            logger.warning("文件图片读流失败（读取中断，响应已开始）")
