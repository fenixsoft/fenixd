"""spec_naming.py — SPEC 名合法性契约单源（code-review item a26570d2bf14）。

kebab-case 权威正则的写入方 core/spec_gen.py（new_change._validate_name）与
消费方 core/signals.py（validate_scheduling_kick_spec / parse_verify_progress
的路径穿越防护）共享同一命名契约。历史上两侧各持同值副本，对齐纯靠注释里
的人工纪律维持：spec_gen 侧放宽/收紧命名规则后，new_change 能创建而
validate_scheduling_kick_spec 拒绝（write_scheduling_kick 功能性失效），或
parse_verify_progress 把合法 spec 判为不存在（路径穿越防护误伤）。收口到本
模块后命名规则演进改一处即全链生效。

两个消费方 MUST 直接从本模块导入使用，MUST NOT 另立同值副本。

本模块保持中立：不 import 仓库内任何其他模块（stdlib-only），
core.spec_gen 与 core.signals 均可无循环障碍地引用。
"""

import re

# SPEC 名 kebab-case 权威正则：^[a-z][a-z0-9]*(-[a-z0-9]+)*$
KEBAB_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")


def validate_spec_name(spec: str) -> str | None:
    """校验 SPEC 名是否为合法 kebab-case（命名契约单源的唯一校验入口）。

    判据即上方 KEBAB_RE 权威正则（^[a-z][a-z0-9]*(-[a-z0-9]+)*$）：SPEC 名已被
    fenix_spec.py new 约束为该形态，可安全作文件名/路径成分。黑名单式拒绝
    （仅查空串 / `/` / `\` / `..`）会放过 `.`、前导点、含 `:` 或非 ASCII 等
    「能当文件名但不合规」的输入——正则白名单与之等价且无遗漏。

    本函数语义中性、不绑定单一车道：write_scheduling_kick 信号文件名、
    parse_verify_progress 路径穿越防护、adjudication_narrative 产物路径拼接
    防护等场景同源引用。core.signals.validate_scheduling_kick_spec 为本函数
    的兼容别名薄委托（既有调用方沿用，新代码请直接用本名）。

    Returns:
        合法返回 None；不合法返回非空错误描述。
    """
    if not isinstance(spec, str):
        return f"spec 名必须为字符串（当前类型 {type(spec).__name__}）"
    if not spec:
        return "spec 名为空"
    if not KEBAB_RE.fullmatch(spec):
        return (
            f"spec 名不合法（须为 kebab-case，如 'fix-foo-bar'）：{spec!r}"
        )
    return None
