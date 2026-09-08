// 验证探针 s4b：isRollback 徽标判定真值表（detail.tsx 判定表达式的字面执行）
const cases = [
  { tag: "bTrue", item: { backward: true, reason: "x" } },
  { tag: "bFalse", item: { backward: false, reason: "x" } },
  { tag: "legacy", item: { reason: "x" } },
  { tag: "bFalseNoReason", item: { backward: false, reason: "" } },
];
for (const { tag, item } of cases) {
  const isRollback =
    item.backward === true || (item.backward === undefined && !!item.reason);
  console.log(tag + "=" + isRollback);
}
