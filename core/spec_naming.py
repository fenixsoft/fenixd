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
