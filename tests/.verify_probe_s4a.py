"""验证探针 s4a：detail.tsx isRollback 源码契约——跟随 backward 字段且保留存量回退分支。"""
import re
from pathlib import Path

src = (Path("core/dashboard/static/src/pages/projects/detail.tsx")
       .read_text(encoding="utf-8"))
m = re.search(r"const isRollback = ([^;]+);", src)
expr = m.group(1).strip() if m else "NOT_FOUND"
print("EXPR=" + expr)
print("HAS_BACKWARD_TRUE=" + str("backward === true" in expr))
print("HAS_LEGACY_FALLBACK=" + str("!!item.reason" in expr))
