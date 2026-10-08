"""git 文本输出工具：quotePath C 风格引号路径反转义（全仓唯一实现）。

``git status --porcelain`` / ``git diff --name-only`` 等文本输出对含非 ASCII/
特殊字符的路径输出带引号 C 转义形（如 ``"docs/\\346\\226\\207.txt"``）。此前
``core.knowledge_backfill``（``_decode_git_quoted_path``）与
``core.worktree_manager.mergeback``（``_unquote_git_path``）各持一份独立实现且
细节已漂移（code-review 3e99a584fdf5），现收敛为本模块，两侧薄委托。

解码口径（以 mergeback 侧已修的 quote.c 字母转义表 + 更严格实现为合并基准）：
- 反斜杠 + **恰 3 位**八进制数字还原为一个字节（git quote.c 输出恒为 3 位，
  不足 3 位视为普通字符原样保留，不做贪心收集）；
- 反斜杠 + 引号/反斜杠与 a b f n r t v 七个控制字符按两字符转义还原单字节
  （quote.c sq_lookup 表，仅其余控制/高位字节才用八进制）；
- 未知转义序列：反斜杠原样保留，后随字符按普通字符处理，不臆造映射；
- 字节流按 UTF-8 解码，失败以 **surrogateescape** 兜底——与 Python 文件系统
  路径解码（``os.fsdecode``）同款，反转义结果可与盘上目录项名直接比较、参与
  文件系统操作；不用 latin-1（其映射出的 U+0080..U+00FF 与 fsdecode 结果
  永不相等，非 UTF-8 文件名场景下路径比对会静默失配）。
- 无引号行原样返回（对 ASCII 路径幂等零开销）。
"""

from __future__ import annotations

# git quotePath 的字母短转义表（quote.c sq_lookup）：引号/反斜杠按字面还原，
# a/b/f/n/r/t/v 七个控制字符输出两字符字母转义（如 \n、\t），值为其单字节
# 控制字符。
_LETTER_ESCAPES = {
    '"': 0x22,
    "\\": 0x5C,
    "a": 0x07,
    "b": 0x08,
    "f": 0x0C,
    "n": 0x0A,
    "r": 0x0D,
    "t": 0x09,
    "v": 0x0B,
}


def unquote_git_path(p: str) -> str:
    """反转义 git 文本输出中 core.quotePath 的 C 风格带引号路径（口径见模块 docstring）。"""
    if len(p) < 2 or not p.startswith('"') or not p.endswith('"'):
        return p
    body = p[1:-1]
    raw = bytearray()
    i = 0
    n = len(body)
    while i < n:
        c = body[i]
        if c == "\\" and i + 1 < n:
            letter = _LETTER_ESCAPES.get(body[i + 1])
            if letter is not None:
                raw.append(letter)
                i += 2
                continue
            octal = body[i + 1 : i + 4]
            if len(octal) == 3 and all(d in "01234567" for d in octal):
                raw.append(int(octal, 8))
                i += 4
                continue
        raw += c.encode("utf-8")
        i += 1
    return raw.decode("utf-8", "surrogateescape")
