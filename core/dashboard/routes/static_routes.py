"""static_routes.py — H10 静态/截图（refactor-giant-classes D1/D3/D5）。

原为 DashboardHandler 的静态资源方法（`core/dashboard/server.py`），
原样搬移为 mixin（方法体零改动）。`_HASHED_STATIC_RE` 类属性随本
mixin 迁移；`_GZIP_EXT`/`_GZIP_MIN`/`_maybe_gzip` 在 H0 底座
（routes/base.py），经继承解析。

add-proto-dashboard-serving：fenix-prototype skill 的独立原型服务器
（serve_prototype.py）退役，原型静态伺服（`GET /proto/...`，本文件
`_serve_prototype`）与批注落盘（`POST /api/proto/<project>/<spec>/feedback`，
`_api_proto_feedback`）改由 dashboard 常驻进程承载；落盘 IO 单源在
`core/dashboard/prototype_io.py`。
"""

from __future__ import annotations

import gzip
import mimetypes
import os
import re
import urllib.parse
from pathlib import Path
from typing import Dict, Optional

from core.dashboard.prototype_io import (  # noqa: E402 — 落盘/校验/常量单源
    ALLOWED_IMAGE_EXT,
    FEEDBACK_FILE_NAME,
    FeedbackWriteRejected,
    PROTOTYPE_FILE_TYPES,
    append_feedback,
    spec_segment_safe,
)
from core.dashboard.uidebug_io import (  # noqa: E402 — session 文件单源
    delete_feedback,
    load_feedback,
    load_session,
    new_feedback_id,
    session_dir,
    session_segment_safe,
    update_feedback_text,
)


class H10StaticRoutesMixin:
    """H10 静态/截图（design D1 表 C H10）。"""

    _HASHED_STATIC_RE = re.compile(r"\.[0-9a-f]{8,}(?:\.async)?\.(?:js|css)$")

    # hashed 不可变 bundle 的 gzip 载荷缓存（code-review item 34967a77247a）：
    # ThreadingHTTPServer 的 worker 在 GIL 下串行执行，每请求对同一不可变
    # .js/.css 重压同一字节纯属浪费。仅缓存文件名带内容 hash 的文件
    # （_HASHED_STATIC_RE，index.html 除外）；key 含 (size, mtime_ns) 兜底
    # 同名重写，且键取自读 body 之前那次 stat——保证键与载荷出自同一文件
    # 版本（code-review item b0021abda19f）；单文件超上限不入缓（大小守卫），
    # 条目数超限整体清空（简单有界，防长生命周期下缓存无界增长）。
    _GZIP_PAYLOAD_CACHE_MAX_BYTES = 2 * 1024 * 1024
    _GZIP_PAYLOAD_CACHE_MAX_ENTRIES = 16
    # 并发（code-review item cfacda63459c）：类级共享、无锁，安全性依赖
    # CPython dict 单操作原子性（GIL）；value 为不可变 bytes、key 含文件
    # 版本，并发最坏只是回填互相覆盖或 clear 后重复压缩——接受该竞态，
    # 无结构性损坏。
    _gzip_payload_cache: Dict[tuple, bytes] = {}

    def _serve_static(self, filename: str):
        # NUL 字节混入 Path 拼接后 .resolve() 抛 ValueError（embedded null
        # byte，code-review item 747894f47c57），否则会穿透为不透明 500；
        # 按本方法对非法路径的既有语义答 404。
        if "\x00" in filename:
            self._error(404, "Not Found")
            return
        # 对外服务根收敛为 dist/（code-review item f3c00cefb7b8，security）：
        # static 目录是完整前端工程（src/ tests/ node_modules/
        # package-lock.json 等），整树作服务根会把源码与依赖树暴露给本机
        # 任意进程。全部已知运行时消费——根路径 index.html 特判（base.py
        # 传 "dist/index.html"，其 "dist/" 前缀在此剥离兼容）、index.html
        # 内 ./umi.* 根相对资源、public/ 的构建期拷贝——实际均落 dist/
        # （前端源码与 py 测试均无引用 static 根下非 dist 路径的 HTTP 请求）；
        # 收敛后原「根相对 → dist/」回退被主查找直接覆盖，一并移除。
        dist_root = (self.server.static_dir / "dist").resolve()
        target = (dist_root / re.sub(r"^dist/", "", filename)).resolve()
        # 防路径穿越：解析后必须仍在 dist 目录内（先 resolve 再包含检查，
        # 不 resolve 的词法前缀匹配不归一化「..」、不跟随 symlink，防线形同虚设）
        if not target.is_relative_to(dist_root):
            self._error(404, "Not Found")
            return
        if target.is_dir():
            # 目录分支拼接 index.html 后重做 resolve + 包含检查（code-review
            # item eb0ffce67033，security）：dist 内真实目录下的 index.html
            # 可以是指向 dist 外的 symlink，下方 is_file()/_send_file 会跟随
            # 读取，把外部文件内容经本通道外泄。与 _serve_prototype 对最终
            # target 的纵深口径对齐；越界按本方法既有越界语义答 404。
            target = (target / "index.html").resolve()
            if not target.is_relative_to(dist_root):
                self._error(404, "Not Found")
                return
        if not target.is_file():
            self._error(404, "Not Found")
            return
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        # 构建产物文件名带内容 hash，可安全长缓存；index.html 不缓存
        cache = "no-cache"
        if target.name != "index.html" and self._HASHED_STATIC_RE.search(target.name):
            cache = "max-age=31536000, immutable"
        self._send_file(target, ctype, cache=cache)

    def _serve_screenshot(self, path: str):
        # /screenshots/<project>/<spec>/<file>
        parts = path.split("/")
        # ['', 'screenshots', project, spec, file...]
        if len(parts) < 5:
            self._error(404, "Not Found")
            return
        project_name = urllib.parse.unquote(parts[2])
        spec = urllib.parse.unquote(parts[3])
        # spec 段防穿越（code-review item 5544a9f69b3b，critical）：spec 解码后
        # 可能还原出「..」组件——它会在 .resolve() 之前被嵌入基础目录，把
        # screenshots_dir 本身搬迁到约束目录之外（如
        # /screenshots/<project>/..%2F..%2Ftmp%2Fscreenshots），此时下方
        # target.is_relative_to(screenshots_dir) 对搬迁后目录内任意文件平凡
        # 通过。先校验 spec 不含「..」路径组件再拼接；file_part 的「..」仍由
        # 既有 resolve + is_relative_to 兜底（基础目录此后不可被搬迁）。
        #
        # 绝对路径形态（code-review item 4d4c8e4f2f4b，critical）：path 取自
        # urlparse 不解码 %2F，split 后上方 unquote 可还原出绝对段（如
        # /screenshots/<project>/%2Ftmp%2Ffoo/x.png → spec == '/tmp/foo'）；
        # pathlib 拼接遇绝对段会整体丢弃前缀，同样把 screenshots_dir 搬迁到
        # 约束目录之外，令包含检查平凡通过。与「..」搬迁同属攻击面，一并拒绝。
        # 校验单源复用 prototype_io.spec_segment_safe（拒绝空段/「.」「..」
        # 组件/绝对段/反斜杠折叠为「/」后判组件/NUL——NUL 即 %00 解码产物，
        # 会让下方 .resolve() 抛 ValueError（code-review item 747894f47c57）
        # 穿透为 500，一并拒绝），与 _serve_prototype/_api_proto_feedback
        # 同一实现，消除安全校验双实现的漂移风险（code-review item
        # 514e687d5772）。
        if not spec_segment_safe(spec):
            self._error(403, "Forbidden")
            return
        # 剩余部分一并 decode（code-review item 206cc192537f）：SPA 以
        # encodeURIComponent(file) 构建 URL，文件名含空格/#/%/非 ASCII 的截图
        # 在网络上恒为 percent-encoded，不解码则合法图片 404。解码后可能还原
        # 出「..」，由下方 resolve + is_relative_to 包含检查兜底。
        file_part = urllib.parse.unquote("/".join(parts[4:]))
        # 同上（code-review item 747894f47c57）：file_part 经 unquote 可能
        # 还原出 NUL 字节，混入下方 Path 拼接后 .resolve() 抛 ValueError
        # 穿透为不透明 500，按本文件对非法路径的既有语义答 403。
        if "\x00" in file_part:
            self._error(403, "Forbidden")
            return

        project = self.server.project_by_name(project_name)
        if project is None or not project.get("exists"):
            # 未知/非活跃项目答 404（code-review item bd493b870156）：与本包
            # 其余路由（spec_routes/run_routes/project_routes/code_review_routes
            # 均为 404 project not found）语义一致；403 会区分「项目存在性」
            # 并把鉴权失败与资源缺失混同。
            self._error(404, "project not found")
            return

        # 拼接刻意用原始 spec 而非 spec_segment_safe 内部判组件所用的反斜杠
        # 折叠形态（code-review item 4ff940f60087）：前提是仅 POSIX——反斜杠
        # 不作分隔符折叠，含「\」的 spec 在磁盘上是单个目录名，校验（折叠后）
        # 严格保守于拼接（对原始 spec），穿越防护不受影响；若移植到反斜杠作
        # 分隔符的平台（Windows），拼接处须同样先折叠。
        screenshots_dir = (
            Path(project["path"]) / ".fenix" / "verify-progress" / spec / "screenshots"
        ).resolve()
        target = (screenshots_dir / file_part).resolve()

        # 防路径穿越：解析后必须仍位于该项目 screenshots 目录内
        if not target.is_relative_to(screenshots_dir):
            self._error(403, "Forbidden")
            return
        if not target.is_file() or target.suffix.lower() not in ALLOWED_IMAGE_EXT:
            self._error(404, "Not Found")
            return
        ctype = mimetypes.guess_type(str(target))[0] or "image/png"
        self._send_file(target, ctype)

    def _serve_prototype(self, path: str):
        # /proto/<project>/<spec>/<file>（add-proto-dashboard-serving）
        # 静态伺服 .fenix/prototypes/<spec>/ 下的原型单文件 HTML 及其
        # 同目录资源（annotator.js、vendor、图片/字体），防护口径镜像
        # _serve_screenshot：段校验 → 项目须注册 → resolve + 包含检查 →
        # 后缀白名单（feedback.json 与手工放入的任意可执行/源码文件
        # 不经本通道外泄）。
        parts = path.split("/")
        # ['', 'proto', project, spec, file...]（file 允许为空：目录形态）
        if len(parts) < 4:
            self._error(404, "Not Found")
            return
        project_name = urllib.parse.unquote(parts[2])
        spec = urllib.parse.unquote(parts[3])
        # spec 段防穿越：与 _serve_screenshot 共用单源校验
        # prototype_io.spec_segment_safe（「..」组件搬迁攻击、绝对路径段
        # 丢弃前缀攻击、%00 NUL → resolve ValueError→500）。
        if not spec_segment_safe(spec):
            self._error(403, "Forbidden")
            return
        # file_part 一并 decode（同 _serve_screenshot：合法文件名含空格/#/%
        # 时网络上恒为 percent-encoded）；解码还原的「..」由下方 resolve +
        # is_relative_to 兜底，还原的 NUL 在此拒绝。
        file_part = urllib.parse.unquote("/".join(parts[4:]))
        if "\x00" in file_part:
            self._error(403, "Forbidden")
            return

        project = self.server.project_by_name(project_name)
        if project is None or not project.get("exists"):
            # 与 _serve_screenshot 同语义：未知/非活跃项目答 404（不区分
            # 项目存在性，避免把鉴权失败与资源缺失混同）
            self._error(404, "project not found")
            return

        proto_root = (
            Path(project["path"]) / ".fenix" / "prototypes"
        ).resolve()
        spec_dir = (proto_root / spec).resolve()
        # 纵深防御：spec 段已先拒「..」，此处 resolve + 包含检查兜住
        # symlink 等词法校验覆盖不到的搬迁形态
        if not spec_dir.is_relative_to(proto_root):
            self._error(403, "Forbidden")
            return
        if file_part:
            target = (spec_dir / file_part).resolve()
            if not target.is_relative_to(spec_dir):
                self._error(403, "Forbidden")
                return
        else:
            target = spec_dir
        if target.is_dir():
            if not path.endswith("/"):
                # 目录形态无尾斜杠 → 301 补斜杠（同 SimpleHTTPRequestHandler）：
                # 原型页的相对资源引用（src="annotator.js"）以文档 URL 为基
                # 解析，缺尾斜杠会落到上级目录。query 原样携带（proto_round
                # 迭代参数不得丢失）。301 会被中介缓存，但目录→目录/ 的映射
                # 恒定，缓存无害。
                raw, sep, query = self.path.partition("?")
                self._mark_response_started()
                self.send_response(301)
                self.send_header("Location", raw + "/" + (sep + query if sep else ""))
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            target = target / "index.html"
        # feedback.json 及其隔离 .bak / 伴生 .lock 不对外伺服：批注回流数据
        # 只经 agent 从磁盘读，静态通道只出原型渲染资源（与退役独立服务器
        # 同口径）
        if target.name == FEEDBACK_FILE_NAME or target.name.startswith(
                FEEDBACK_FILE_NAME + "."):
            self._error(403, "Forbidden")
            return
        if not target.is_file():
            self._error(404, "Not Found")
            return
        ctype = PROTOTYPE_FILE_TYPES.get(target.suffix.lower())
        if ctype is None:
            # 后缀白名单：原型目录不该出现可执行/源码/密钥类文件，即便被
            # 手工放进来也不经本通道外泄（与截图路由的 ALLOWED_IMAGE_EXT
            # 同思路；响应 404 与「文件不存在」不可区分）
            self._error(404, "Not Found")
            return
        # 原型处于高频修订循环：no-store 彻底禁存——no-cache 无 validator
        # 时浏览器行为未定义，曾致旧原型驻留磁盘缓存（frp 链路尤甚）
        self._send_file(target, ctype, cache="no-store, max-age=0")

    def _api_proto_feedback(self, project_name: str, spec: str,
                            query: dict) -> None:
        # POST /api/proto/<project>/<spec>/feedback（add-proto-dashboard-
        # serving）：fenix-prototype 批注回流端点，落盘语义单源在
        # prototype_io.append_feedback（锁内读改写、结构保留、损坏隔离）。
        if not spec_segment_safe(spec):
            self._error(403, "Forbidden")
            return
        project = self.server.project_by_name(project_name)
        if project is None or not project.get("exists"):
            self._error(404, "project not found")
            return
        proto_root = (
            Path(project["path"]) / ".fenix" / "prototypes"
        ).resolve()
        spec_dir = (proto_root / spec).resolve()
        if not spec_dir.is_relative_to(proto_root) or not spec_dir.is_dir():
            self._error(404, "prototype not found")
            return
        # _read_json_body 统一收口：Content-Length 合法性/256KB 上限/非法
        # JSON/非 dict 体各自结构化报错；anchor/text 字段校验与写入语义
        # 单源在 append_feedback（HTTP 层不重复）。
        annotation = self._read_json_body()
        if annotation is None:
            return
        try:
            target, note = append_feedback(spec_dir, annotation)
        except FeedbackWriteRejected as exc:
            self._error(exc.status, exc.message)
            return
        # stored 只透仓库内相对路径（code-review item 40e7ffda835d）：不把
        # 服务器绝对路径透给 HTTP 客户端（与 spec_routes._internal_error 的
        # 对外纪律一致）；dashboard 前端与 annotator 均不消费该字段，仅作
        # 人工排查提示。
        payload: dict = {
            "ok": True,
            "stored": str(target.relative_to(proto_root.parents[1])),
        }
        if note:
            payload["warning"] = note
        self._json(payload)

    # ── add-fenix-ui-debug：任意 URL 界面调试批注 ──────────────────────
    #
    # 路由族（GET 派发在 base._handle_inner 的 /proto/ 分支之后、SPA
    # fallback 之前）：
    #   GET  /uidebug-assets/annotator.js                     批注器资产
    #   GET  /uidebug/<project>/<session>/                    wrapper 页
    #   GET  /uidebug/<project>/<session>/~/<path>?<query>    反向代理
    #   POST /api/uidebug/<project>/<session>/feedback        批注落盘
    # session/target 单源 core/dashboard/uidebug_io.py，代理改写/取数单源
    # core/dashboard/uidebug_proxy.py；HTTP 层只做派发、守卫与响应组装。

    def _serve_uidebug(self, path: str) -> None:
        """/uidebug* 三形态派发（wrapper / 代理 / 资产）。"""
        if path == "/uidebug-assets/annotator.js":
            self._serve_uidebug_asset()
            return
        if path.startswith("/uidebug-assets/"):
            self._error(404, "Not Found")
            return
        if not path.startswith("/uidebug/"):
            self._error(404, "Not Found")
            return
        # ['', 'uidebug', project, session, ...tail]
        parts = path.split("/")
        if len(parts) < 4 or not parts[2] or not parts[3]:
            # /uidebug、/uidebug/<project> 缺 session → 404
            #（/uidebug/<project>/<session> 无尾段在本方法下方按 wrapper 处理）
            self._error(404, "Not Found")
            return
        project_name = urllib.parse.unquote(parts[2])
        session = urllib.parse.unquote(parts[3])
        tail = parts[4:]
        if not tail or tail[0] != "~":
            # wrapper（含 /uidebug/<p>/<s>/ 目录形态；无尾斜杠也直接回
            # wrapper 页——wrapper 是自足 HTML，文档相对引用不存在）
            self._serve_uidebug_wrapper(project_name, session)
            return
        # 代理子路径保留网络原始形态（percent-encoding 原样透传，不做
        # unquote/re-quote 往返——编码往返会破坏上游签名 URL 等场景）
        self._serve_uidebug_proxy(project_name, session, "/".join(tail[1:]))

    def _serve_uidebug_asset(self) -> None:
        # 批注器单源复用 fenix-prototype 资产（uidebug 模式开关内置）；
        # FRAMEWORK_ROOT 惰性导入单源 core.dashboard.server（勿重复定义）
        from core.dashboard import server as _server_mod

        asset = (_server_mod.FRAMEWORK_ROOT / "skills" / "fenix-prototype"
                 / "assets" / "annotator.js")
        if not asset.is_file():
            self._error(404, "annotator asset missing")
            return
        # no-store：annotator 随框架演进，陈旧缓存会造成端点/行为漂移
        self._send_file(asset, "application/javascript; charset=utf-8",
                        cache="no-store, max-age=0")

    def _uidebug_session_ctx(self, project_name: str, session: str):
        """共用守卫：session 段校验 → 项目须注册 → session 文件须在。

        返回 (project_path, session_cfg)；任一守卫不过时已写响应并返回 None
        （与 _serve_prototype 的早退风格一致）。
        """
        if not session_segment_safe(session):
            self._error(403, "Forbidden")
            return None
        project = self.server.project_by_name(project_name)
        if project is None or not project.get("exists"):
            self._error(404, "project not found")
            return None
        cfg = load_session(Path(project["path"]), session)
        if cfg is None:
            self._error(404, "session not found")
            return None
        return Path(project["path"]), cfg

    @staticmethod
    def _uidebug_round(query_raw: str):
        """从原始 query 提取 proto_round（严格 /^\d+$/，与 annotator 同口径）。"""
        m = re.search(r"(?:^|&)proto_round=(\d+)(?:&|$)", query_raw)
        return int(m.group(1)) if m else None

    def _serve_uidebug_wrapper(self, project_name: str, session: str) -> None:
        from core.dashboard import uidebug_proxy

        ctx = self._uidebug_session_ctx(project_name, session)
        if ctx is None:
            return
        project_path, cfg = ctx
        query_raw = urllib.parse.urlsplit(self.path).query
        round_no = self._uidebug_round(query_raw)
        html = uidebug_proxy.build_wrapper_html(
            project_name, session, cfg["target"], cfg.get("entry", ""), round_no,
            cfg.get("entry_query", ""))
        body = html.encode("utf-8")
        self._mark_response_started()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _serve_uidebug_proxy(self, project_name: str, session: str,
                             sub_path: str) -> None:
        from core.dashboard import uidebug_proxy

        ctx = self._uidebug_session_ctx(project_name, session)
        if ctx is None:
            return
        project_path, cfg = ctx
        target = cfg["target"]
        # proto_round 是 fenix 迭代参数，不属于目标应用——从上游 query 剥离，
        # 轮次经注入的全局量传给批注器（proxy.rebase_url_path 豁免前缀使
        # 其余 fenix 通道不受影响）
        query_raw = urllib.parse.urlsplit(self.path).query
        round_no = self._uidebug_round(query_raw)
        pairs = urllib.parse.parse_qsl(query_raw, keep_blank_values=True)
        upstream_query = urllib.parse.urlencode(
            [(k, v) for k, v in pairs if k != "proto_round"])
        upstream_url = uidebug_proxy.build_upstream_url(
            target, sub_path, upstream_query)
        # cookie 双向通道：请求方向——浏览器按会话 Path 作用域回流的 cookie
        # 原样转发上游（上游自身鉴权态，如 DSH 的 token 登录 cookie）；
        # 响应方向——上游 Set-Cookie 逐条改写为会话作用域后回给浏览器
        # （303 与正常分支同样处理，登录跳转常携带鉴权 Set-Cookie）
        browser_cookie = uidebug_proxy.cookie_header_from(self.headers)
        base = uidebug_proxy.session_base(project_name, session)
        try:
            status, headers, body = uidebug_proxy.fetch_upstream(
                upstream_url, cookie_header=browser_cookie)
        except uidebug_proxy.UpstreamUnreachable as exc:
            self._error(502, f"upstream unreachable: {exc}")
            return
        except uidebug_proxy.UpstreamBodyTooLarge as exc:
            self._error(502, str(exc))
            return
        set_cookies = uidebug_proxy.rewrite_set_cookies(headers, base)
        if 300 <= status < 400:
            # 重定向不在服务端跟随：Location 改写（同源落代理前缀内，
            # 跨源透传）后原状态码交浏览器自行跟随——301/307 语义保留
            location = uidebug_proxy.rebase_redirect(
                headers.get("Location") or "", upstream_url, target,
                uidebug_proxy.proxy_prefix(project_name, session))
            self._mark_response_started()
            self.send_response(status)
            self.send_header("Location", location)
            for sc in set_cookies:
                self.send_header("Set-Cookie", sc)
            self.send_header("Cache-Control", "no-store, max-age=0")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        content_type = headers.get("Content-Type") or "application/octet-stream"
        # SSE 流不进代理：fetch_upstream 已按 event-stream 空体短路（读正文
        # 会钉死工作线程），此处对空体 SSE 响应回 204 让前端连接快速失败
        # （批注环只需「看 + 批」，代理会话内实时推送不可用属预期降级）
        if content_type.strip().lower().startswith("text/event-stream"):
            self._mark_response_started()
            self.send_response(204)
            self.send_header("Cache-Control", "no-store, max-age=0")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        rewritten = uidebug_proxy.rewrite_response(
            content_type, body, headers,
            uidebug_proxy.proxy_prefix(project_name, session), round_no)
        if rewritten is not None:
            body, content_type = rewritten
            extra_ce = None           # 已解压/原文未压缩，不透 Content-Encoding
        else:
            ce = (headers.get("Content-Encoding") or "").strip()
            extra_ce = ce or None     # 未改写响应原样透传压缩形态
        self._mark_response_started()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store, max-age=0")
        for sc in set_cookies:
            self.send_header("Set-Cookie", sc)
        if extra_ce:
            self.send_header("Content-Encoding", extra_ce)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _uidebug_feedback_dir(self, project_name: str, session: str):
        """批注三通道（GET 列表 / POST 追加与更新 / DELETE 删除）共用守卫。

        _uidebug_session_ctx（session 段 → 项目注册 → session 文件在）之外
        再钉一次落盘目录必须留在项目根内（与 append 路径的纵深校验一致）。
        返回 (project_path, 会话目录 Path)；任一守卫不过时已写响应并返回
        None。
        """
        ctx = self._uidebug_session_ctx(project_name, session)
        if ctx is None:
            return None
        project_path, _cfg = ctx
        sdir = session_dir(project_path, session).resolve()
        if not sdir.is_relative_to(Path(project_path).resolve()):
            self._error(403, "Forbidden")
            return None
        return project_path, sdir

    def _api_uidebug_feedback_get(self, project_name: str, session: str) -> None:
        # GET /api/uidebug/<project>/<session>/feedback：批注列表（批注器
        # 面板的「已提交意见」与 agent 回收共用）。读侧惰性补发 id（历史
        # 无 id 条目迁移即落盘），删除/重编辑按 id 寻址。
        ctx = self._uidebug_feedback_dir(project_name, session)
        if ctx is None:
            return
        _project_path, sdir = ctx
        try:
            entries, note = load_feedback(sdir)
        except FeedbackWriteRejected as exc:
            self._error(exc.status, exc.message)
            return
        payload: dict = {"ok": True, "count": len(entries), "feedback": entries}
        if note:
            payload["warning"] = note
        self._json(payload)

    def _api_uidebug_feedback_delete(self, project_name: str, session: str,
                                     query: dict) -> None:
        # DELETE /api/uidebug/<project>/<session>/feedback?id=<id>：按 id
        # 删单条批注（面板「删除」按钮）。id 未命中/会话无批注 → 404。
        ctx = self._uidebug_feedback_dir(project_name, session)
        if ctx is None:
            return
        _project_path, sdir = ctx
        # parse_qs 值形态为 list（alert_routes 同口径）：取首值
        fb_id = (query.get("id") or [""])[0]
        fb_id = fb_id.strip()
        if not fb_id:
            self._error(400, "批注删除必须携带 id 查询参数")
            return
        try:
            deleted = delete_feedback(sdir, fb_id)
        except FeedbackWriteRejected as exc:
            self._error(exc.status, exc.message)
            return
        if not deleted:
            self._error(404, "feedback not found")
            return
        self._json({"ok": True, "deleted": fb_id})

    def _api_uidebug_feedback(self, project_name: str, session: str,
                              query: dict) -> None:
        # POST /api/uidebug/<project>/<session>/feedback 双语义（批注器
        # 面板同一提交入口）：
        #   body 无 id  → 追加新批注（落盘语义与 _api_proto_feedback 同源，
        #                 prototype_io.append_feedback），落点改
        #                 .fenix/ui-debug/<session>/（.fenix/* 已 gitignore）；
        #                 无 id 时补发稳定 id 供删除/重编辑寻址；
        #   body 带 id  → 重编辑：按 id 只重写 text（anchor/round 等既有
        #                 字段不动，补 edited 时间戳）。
        ctx = self._uidebug_feedback_dir(project_name, session)
        if ctx is None:
            return
        project_path, sdir = ctx
        annotation = self._read_json_body()
        if annotation is None:
            return
        fb_id = annotation.get("id")
        if fb_id is not None:
            # 更新分支：只需 id + text（编辑不改锚点，anchor 缺省合法）
            if not isinstance(fb_id, str) or not fb_id.strip():
                self._error(400, "批注 id 非法")
                return
            text = annotation.get("text")
            if not isinstance(text, str) or not text.strip():
                self._error(400, "批注必须包含非空 text 字段")
                return
            try:
                updated = update_feedback_text(sdir, fb_id.strip(), text.strip())
            except FeedbackWriteRejected as exc:
                self._error(exc.status, exc.message)
                return
            if updated is None:
                self._error(404, "feedback not found")
                return
            self._json({"ok": True, "updated": fb_id.strip()})
            return
        # 追加分支：id 由服务端单点补发（批注器不带；手工 curl 也不依赖）
        if not isinstance(annotation.get("id"), str) or not annotation["id"]:
            annotation["id"] = new_feedback_id()
        sdir.mkdir(parents=True, exist_ok=True)
        try:
            target, note = append_feedback(sdir, annotation)
        except FeedbackWriteRejected as exc:
            self._error(exc.status, exc.message)
            return
        payload: dict = {
            "ok": True,
            "stored": str(target.relative_to(Path(project_path).resolve())),
            "id": annotation["id"],
        }
        if note:
            payload["warning"] = note
        self._json(payload)


    def _hashed_gzip_payload(self, path: Path, body: bytes,
                             st: Optional[os.stat_result] = None) -> Optional[bytes]:
        """hashed 不可变 bundle 的 gzip 载荷（缓存命中/回填）；不压缩返回 None。

        调用方须自行保证客户端 Accept-Encoding 含 gzip（下方 _send_file 已
        守卫）。非 hashed 文件仍逐请求压缩（内容可变，不可缓存）。st 须为
        调用方读取 body 之前取得的 stat 结果（code-review item b0021abda19f），
        保证缓存键与 body 出自同一文件版本；未传入时兜底自取。
        """
        if path.suffix.lower() not in self._GZIP_EXT:
            return None
        immutable = (
            path.name != "index.html"
            and self._HASHED_STATIC_RE.search(path.name) is not None
        )
        if st is None:
            try:
                st = path.stat()
            except OSError:
                st = None
        key = None
        if immutable and st is not None:
            key = (str(path), st.st_size, st.st_mtime_ns)
        if key is not None:
            cached = self._gzip_payload_cache.get(key)
            if cached is not None:
                return cached
        if len(body) < self._GZIP_MIN:
            return None
        payload = gzip.compress(body, 5)
        # 条目数清空以「本次确要插入」为前提（code-review item 1dfa37965c96）：
        # 超过单文件上限不入缓时不得触碰既有缓存，否则持续访问超大 hashed
        # bundle 会反复清空其他条目，令小文件缓存形同虚设。
        if key is not None and len(body) <= self._GZIP_PAYLOAD_CACHE_MAX_BYTES:
            if len(self._gzip_payload_cache) >= self._GZIP_PAYLOAD_CACHE_MAX_ENTRIES:
                self._gzip_payload_cache.clear()
            self._gzip_payload_cache[key] = payload
        return payload

    def _send_file(self, path: Path, ctype: str, cache: str = "no-cache",
                   extra_headers: "list[tuple[str, str]] | None" = None):
        # 先 stat 后读（code-review item b0021abda19f）：gzip 缓存键的
        # (size, mtime_ns) 必须与 body 出自同一文件版本。若读后再 stat，
        # 两步之间文件被原地重写时键描述新版本、载荷却是旧内容的 gzip，
        # 此后同名请求恒命中陈旧 bundle；读前 stat 则键描述旧版本，重写
        # 后自然 miss 重压，不会以新键长期污染缓存。
        try:
            st = path.stat()
        except OSError:
            st = None
        try:
            body = path.read_bytes()
        except OSError:
            self._error(404, "Not Found")
            return
        self._mark_response_started()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", cache)
        for _name, _value in (extra_headers or ()):
            self.send_header(_name, _value)
        # Vary 无条件发送（与 base._maybe_gzip 口径对齐，同源结论
        # f812b5255a66 / 本条 858b231045be）：响应是否压缩随 Accept-Encoding
        # 变化，非压缩副本缺 Vary 时中介缓存可能把 identity 副本复用给支持
        # gzip 的下游客户端——Cache-Control immutable 的 hashed bundle 上
        # 即构成长期缓存正确性缺口。
        self.send_header("Vary", "Accept-Encoding")
        if path.suffix.lower() in self._GZIP_EXT and self._wants_gzip():
            payload = self._hashed_gzip_payload(path, body, st)
            if payload is not None:
                self.send_header("Content-Encoding", "gzip")
                body = payload
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)