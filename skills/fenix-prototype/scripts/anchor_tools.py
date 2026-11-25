#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""锚保持比对工具（fenix-prototype · 任务 1.4）。

解析原型的 ``data-proto-id`` 稳定锚集合，对新旧两版原型输出保持/漂移比对报告，
供 SKILL.md 生成契约在重生成时引用（未波及区块 MUST 沿用原锚，批注不得错位）。

- ``extract``：单文件锚集合（锚 id、标签、元素文本快照、出现次数）。
- ``diff``：kept / dropped / added / 改名猜测对 + 保持率与结论。
- ``verify_unaffected``：给定受波及锚清单，机械断言「其余锚全部保持」；
  声明近乎覆盖全部旧锚时机械门退化为恒真，置 ``flagged`` 要求人工复核。

三个子命令顶层 ``ok`` 字段口径统一（成功 true；用法/文件错误与崩溃路径
向 stderr 输出 ``ok: false``）：

- ``extract``：``{ok, unclosed_count, discarded_count, anchors}``——两个
  计数分别统计 source="unclosed"（EOF 残帧回填）与 source="discarded"
  （标签错配/未闭合弹栈回填）两条恢复路径的锚数量，口径对齐。
- ``diff``：``{ok, old_total, new_total, kept, dropped, added, kept_ratio,
  verdict, rename_guesses, old_anchors, new_anchors}``（``ok`` 由 CLI 在
  比对完成时包装为 true）。
- ``diff --affected``（``verify_unaffected``）：``{ok, violations,
  invalid_affected, affected_declared, kept_ratio, rename_guesses, flagged,
  flag_reasons, affected_but_kept}``，``ok`` 即机械门结论（决定退出码
  0/1）；``flagged`` 为空洞化防御信号，不改写 ``ok``/退出码，是否放行由
  消费方（SKILL.md 契约）裁决人工复核。

元素文本快照用于人工核对锚对应关系（设计决策：批注含元素文本快照辅助核对；
改名猜测仅为线索，MUST 由 agent 人工确认，不自动改批注）。

纯 python 标准库、确定性解析（html.parser），MUST NOT 依赖现场 LLM 生成。

用法::

    python3 anchor_tools.py extract <原型.html>
    python3 anchor_tools.py diff <旧.html> <新.html> [--affected id1,id2]

退出码：0 = 完成；``diff --affected`` 时若未波及锚未全部保持以 1 退出（可作
生成管线的机械门）；2 = 用法/文件错误；3 = 工具自身未捕获异常（崩溃路径向
stderr 输出 ``ok: false`` JSON，不占用机械门违规的 1，退出码 1 保持单一语义）。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

# Windows 控制台编码兜底（proto_serve.py 同款）：锚快照文本取自原型 HTML
# 任意文案（含中文/emoji 等），SSH 会话/旧式控制台下 stdout 默认回落本地
# ANSI 代码页（cp1252/cp936），print 直接 UnicodeEncodeError 崩溃（__main__
# 兜底向 stderr 输出 ok:false JSON 也可能再度编码失败）。保编码不换，仅把
# 不可编码字符替换掉。
if sys.platform == "win32":
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass

ANCHOR_ATTR = "data-proto-id"
TEXT_SNAPSHOT_LIMIT = 80

_VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input",
              "link", "meta", "param", "source", "track", "wbr"}

#: 生成代码里的锚字面量（JS 对象键 / setAttribute），静态解析的补充来源
_JS_LITERAL_ANCHOR = re.compile(
    r"""['"]data-proto-id['"]\s*(?:\]\s*=\s*|:\s*)['"]([^'"]+)['"]"""
    r"""|setAttribute\(\s*['"]data-proto-id['"]\s*,\s*['"]([^'"]+)['"]""",
)


class _AnchorParser(HTMLParser):
    """收集 data-proto-id 锚与其元素文本快照（最近锚祖先原则）。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        # id -> {"id","tag","text","count"}（保持首现顺序）
        self.anchors: dict[str, dict] = {}
        self._stack: list[tuple[str, str | None, list[str]]] = []

    @staticmethod
    def _anchor_from_attrs(attrs) -> str | None:
        for name, value in attrs:
            if name == ANCHOR_ATTR:
                return (value or "").strip() or None
        return None

    def handle_starttag(self, tag, attrs):
        anchor_id = self._anchor_from_attrs(attrs)
        if tag in _VOID_TAGS:
            # void 元素没有闭合标签（不会弹栈）：带锚在开始标签处直接记录，
            # 无锚也不压栈，避免其锚帧滞留栈顶拦截后续文本归属
            if anchor_id:
                self._record(anchor_id, tag, "")
            return
        self._stack.append((tag, anchor_id, []))

    def handle_startendtag(self, tag, attrs):
        # 自闭合（xhtml 风格 / void 带斜杠，均走本回调而非 starttag）。
        # HTML5 语义下非 void 元素的自闭合斜杠被忽略、元素照常容纳子内容，
        # 故按 starttag 同款处理（压栈，子文本仍归属该锚，闭合时记录快照，
        # 与 annotator.js 运行时快照口径一致）；void 元素本无子内容，
        # starttag 分支即在开始标签处按空快照记录
        self.handle_starttag(tag, attrs)

    @staticmethod
    def _snapshot(texts: list[str]) -> str:
        # 与 annotator.js elementSnapshot 同口径：段间空格合并后压缩空白
        # （等价 replace(/\s+/g, " ").trim()），两工具产出可交叉比对
        return " ".join(" ".join(texts).split())

    def handle_endtag(self, tag):
        if tag in _VOID_TAGS:
            return
        # 弹栈到匹配标签（容错：标签未闭合/错配时不抛错）
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == tag:
                popped_tag, anchor_id, texts = self._stack[i]
                if anchor_id:
                    self._record(anchor_id, popped_tag, self._snapshot(texts))
                # 被跨越丢弃的带锚帧（未闭合/错配时）：其 texts 按最近锚祖先
                # 原则归属自身，回填记录避免快照静默丢失且无任何观测信号；
                # 附 source="discarded" 与正常闭合锚区分（快照可能不完整，
                # 供人工核对与 _guess_renames 匹配时识别恢复路径来源），口径
                # 与 close() 的 EOF 残帧（source="unclosed"）两条恢复路径对齐
                for lost_tag, lost_anchor, lost_texts in self._stack[i + 1:]:
                    if lost_anchor:
                        self._record(lost_anchor, lost_tag,
                                     self._snapshot(lost_texts),
                                     source="discarded")
                del self._stack[i:]
                return

    def handle_data(self, data):
        if not data.strip():
            return
        # 文本归给栈内所有锚帧（textContent 口径）：annotator.js
        # elementSnapshot 取 node.textContent（锚元素全部后代文本），嵌套锚
        # 时外层锚的快照须含内层锚所辖文本——只归最近锚帧会让外层快照缺失
        # 内层文本（如「前文 内文 后文」产出「前文 后文」），与运行时快照
        # 交叉比对漂移；逐段按文档序 append 到各帧，外层帧拼接顺序天然正确。
        # 无嵌套锚时栈内仅一帧带锚，与旧的「最近锚帧」口径等价
        text = data.strip()
        for _, anchor_id, texts in self._stack:
            if anchor_id is not None:
                texts.append(text)

    def _record(self, anchor_id: str, tag: str, text: str,
                source: str | None = None) -> None:
        entry = self.anchors.get(anchor_id)
        if entry is None:
            record = {
                "id": anchor_id,
                "tag": tag,
                "text": text[:TEXT_SNAPSHOT_LIMIT],
                "count": 1,
            }
            if source:
                record["source"] = source
            self.anchors[anchor_id] = record
        else:
            entry["count"] += 1

    def close(self) -> None:
        # 先冲刷解析缓冲，让尾部文本仍归属栈内锚帧，再收尾 EOF 残帧
        super().close()
        # 文档结束时仍滞留解析栈的带锚帧（未闭合元素）：其帧永不弹栈，
        # 按上方 lost-frame 同款口径回填记录，避免锚静默丢失被 diff 误判
        # dropped、verify_unaffected 机械门假阳性；附 source 标记便于人工核对
        for lost_tag, lost_anchor, lost_texts in self._stack:
            if lost_anchor:
                self._record(lost_anchor, lost_tag, self._snapshot(lost_texts),
                             source="unclosed")
        self._stack.clear()


def extract_anchors(html: str) -> dict[str, dict]:
    """解析 HTML，返回 {锚id: {id, tag, text, count}}（按首现顺序）。

    原型锚有两个来源：静态 HTML 属性（可直接解析出标签与文本快照）与
    生成代码字面量（React ``createElement({'data-proto-id': ...})`` /
    ``setAttribute('data-proto-id', ...)`——渲染前只存在于 ``<script>`` 文本里，
    渲染后由运行时注入 DOM）。后者用字面量扫描补充收录（无标签/文本快照，
    ``source: "js-literal"``），保证重生成锚保持比对对真实原型形态可用。
    """
    parser = _AnchorParser()
    parser.feed(html)
    parser.close()
    anchors = parser.anchors
    for match in _JS_LITERAL_ANCHOR.finditer(html):
        anchor_id = (match.group(1) or match.group(2) or "").strip()
        if not anchor_id:
            continue
        entry = anchors.get(anchor_id)
        if entry is not None:
            # 同一字面量多次出现（对应运行时注入的多个同锚元素）：与
            # _record 同款累加出现次数，两种来源的 count 语义一致
            entry["count"] += 1
            continue
        anchors[anchor_id] = {
            "id": anchor_id,
            "tag": "js-literal",
            "text": "",
            "count": 1,
            "source": "js-literal",
        }
    return anchors


def _guess_renames(old: dict[str, dict], new: dict[str, dict],
                   dropped: list[str], added: list[str]) -> list[dict]:
    """按元素文本快照猜测「改了名的同一区块」（仅线索，需人工确认）。"""
    guesses: list[dict] = []
    new_by_text: dict[str, str] = {}
    for anchor_id in added:
        text = new[anchor_id]["text"]
        if text:
            new_by_text.setdefault(text, anchor_id)
    for anchor_id in dropped:
        text = old[anchor_id]["text"]
        match = new_by_text.get(text)
        if match:
            guesses.append({"old": anchor_id, "new": match, "text": text})
    return guesses


def diff_anchors(old_html: str, new_html: str) -> dict:
    """新旧原型锚集合比对报告。"""
    old = extract_anchors(old_html)
    new = extract_anchors(new_html)
    kept = [anchor_id for anchor_id in old if anchor_id in new]
    dropped = [anchor_id for anchor_id in old if anchor_id not in new]
    added = [anchor_id for anchor_id in new if anchor_id not in old]
    kept_ratio = (len(kept) / len(old)) if old else 1.0
    report = {
        "old_total": len(old),
        "new_total": len(new),
        "kept": kept,
        "dropped": dropped,
        "added": added,
        "kept_ratio": round(kept_ratio, 4),
        "verdict": "all-kept" if not dropped else "anchors-changed",
        "rename_guesses": _guess_renames(old, new, dropped, added),
        "old_anchors": old,
        "new_anchors": new,
    }
    return report


#: 空洞化防御阈值：受波及声明覆盖旧锚占比达到该值即置 ``flagged``。声明
#: 覆盖全部旧锚时「其余锚全部保持」退化为恒真——与塞满无效锚 id 对称的
#: 架空路径（id 全部合法，violations/invalid_affected 均判不出），只能以
#: 防御信号暴露给人工复核。
HOLLOW_AFFECTED_COVERAGE = 0.8


def verify_unaffected(old_html: str, new_html: str, affected_ids: list[str]) -> dict:
    """机械断言：除声明的受波及锚外，旧原型其余锚 MUST 全部在新原型保持。

    未波及锚消失即违规（锚漂移 = 旧批注错位，本 SPEC 的反目标）。
    受波及清单中不存在于旧∪新锚集合的 id 属无效声明（笔误/编造），
    同样判违规（``invalid_affected`` 并入 ``ok`` 与退出码），防止机械门
    被塞满无效锚 id 静默架空。

    对称的架空路径——把全部真实旧锚 id 塞进声明——id 全部合法、违规判
    不出，改为防御信号：声明覆盖旧锚占比达到 ``HOLLOW_AFFECTED_COVERAGE``
    即置 ``flagged``（附 ``flag_reasons``）要求人工复核；``affected_but_kept``
    单列声明中实际保持的 id，让空洞化声明显式可见。``flagged`` 不改写
    ``ok`` 与退出码（向后兼容），是否放行由消费方（SKILL.md 契约）裁决。
    """
    report = diff_anchors(old_html, new_html)
    affected = set(affected_ids)
    old_ids = set(report["old_anchors"])
    violations = [anchor_id for anchor_id in report["dropped"] if anchor_id not in affected]
    invalid_affected = sorted(
        affected - old_ids - report["new_anchors"].keys())
    covered = affected & old_ids
    coverage = (len(covered) / len(old_ids)) if old_ids else 0.0
    flag_reasons: list[str] = []
    if old_ids and coverage >= HOLLOW_AFFECTED_COVERAGE:
        flag_reasons.append(
            f"受波及声明覆盖 {len(covered)}/{len(old_ids)} 个旧锚"
            f"（{coverage:.0%} ≥ {HOLLOW_AFFECTED_COVERAGE:.0%}），"
            "机械门「其余锚全部保持」接近恒真，须人工复核")
    return {
        "ok": not violations and not invalid_affected,
        "violations": violations,
        "invalid_affected": invalid_affected,
        "affected_declared": sorted(affected),
        "kept_ratio": report["kept_ratio"],
        "rename_guesses": report["rename_guesses"],
        "flagged": bool(flag_reasons),
        "flag_reasons": flag_reasons,
        "affected_but_kept": sorted(affected & set(report["kept"])),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _read_or_die(path: str) -> str:
    p = Path(path)
    if not p.is_file():
        print(json.dumps({"ok": False, "error": f"文件不存在：{path}"},
                         ensure_ascii=False), file=sys.stderr)
        sys.exit(2)
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        # 权限等文件级读取错误与「文件不存在」同归退出码 2（用法/文件错误），
        # 不落入 __main__ 崩溃兜底的退出码 3
        print(json.dumps({"ok": False, "error": f"文件不可读：{path}（{exc}）"},
                         ensure_ascii=False), file=sys.stderr)
        sys.exit(2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="fenix-prototype 锚保持比对")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_extract = sub.add_parser("extract", help="解析单文件锚集合")
    p_extract.add_argument("html")

    p_diff = sub.add_parser("diff", help="新旧原型锚保持比对")
    p_diff.add_argument("old_html")
    p_diff.add_argument("new_html")
    p_diff.add_argument("--affected", default="",
                        help="逗号分隔的受波及锚清单；提供时机械断言其余锚全部保持")

    args = parser.parse_args(argv)

    if args.cmd == "extract":
        anchors = extract_anchors(_read_or_die(args.html))
        values = list(anchors.values())
        print(json.dumps({"ok": True,
                          "unclosed_count": sum(1 for a in values
                                                if a.get("source") == "unclosed"),
                          # 与 unclosed_count 对齐的第二条恢复路径观测口径
                          # （source="discarded"，标签错配/未闭合弹栈回填）
                          "discarded_count": sum(1 for a in values
                                                 if a.get("source") == "discarded"),
                          "anchors": values},
                         ensure_ascii=False, indent=2))
        return 0

    old_html = _read_or_die(args.old_html)
    new_html = _read_or_die(args.new_html)
    if args.affected:
        affected = [a.strip() for a in args.affected.split(",") if a.strip()]
        result = verify_unaffected(old_html, new_html, affected)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 1
    # 顶层 ok: true 与 extract / verify_unaffected 成功口径及崩溃兜底的
    # ok:false 信封统一；机械门结论见 --affected 分支的 ok
    print(json.dumps({"ok": True, **diff_anchors(old_html, new_html)},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    # 崩溃兜底：退出码 1 专留 ``diff --affected`` 机械门违规，解析/读文件等
    # 未捕获异常以独立退出码 3 终止并向 stderr 输出 ok:false JSON（与
    # _read_or_die 口径一致），避免管线按退出码判定时把崩溃误读为锚漂移。
    # argparse 的用法错误走 SystemExit(2)，不落入本兜底。
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False,
                          "error": f"工具自身异常：{type(exc).__name__}: {exc}"},
                         ensure_ascii=False), file=sys.stderr)
        sys.exit(3)
