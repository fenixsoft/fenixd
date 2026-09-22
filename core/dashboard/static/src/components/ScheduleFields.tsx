/**
 * ScheduleFields — 「执行时间」三档选择器（共享组件）
 *
 * 出处：evolve 设置页「自进化」页签的「同意立项」确认弹窗（SuggestedImprovementsPanel
 * 原 AcceptScheduleFields）。现同时服务两处立项入口：
 * - 设置页「自进化」→ 条目「同意」（acceptEvolutionItem）
 * - 项目页「代码审查」→ 「生成修复 SPEC」（generateFixSpec）
 *
 * 两处的时刻语义必须一致，故抽为单一实现点（MUST NOT 各写一套）：
 * - 立即执行 → null（清除 start_after，立即进调度）
 * - 指定时间 → UTC ISO8601（本地时刻选择，落盘前换算 UTC）
 * - 手工激活 → 哨兵字符串 "manual"（永不到期，须人工激活后方可被调度器拾取，
 *   见 add-spec-manual-activation D5/D11）
 */
import { DatePicker, Select } from 'antd';
import dayjs from 'dayjs';
import type { Dayjs } from 'dayjs';
import { useState } from 'react';

/** 三档执行时刻的可变载体（经 holder 向 Modal.confirm 的 onOk 回传）。 */
export interface AcceptSchedule {
  startAfter: string | null;
}

/** 哨兵值：手工激活（永不到期）。与后端 START_AFTER_MANUAL 字面量一致。 */
export const START_AFTER_MANUAL = 'manual';

// 与后端 ConfigLoader.is_valid_hhmm 同一锚定正则（^([01]\d|2[0-3]):[0-5]\d$）
// （code-review item 792cae005f21：旧 split(':').map(Number) 比后端校验宽松——
// '9:5'、'12:'（空分钟 → Number('') === 0）、'12:30:45'（秒被静默丢弃）都能
// 通过前端换算而后端拒绝，与 docstring「两侧共享同一转换规则」断言相悖）。
const HHMM_RE = /^([01]\d|2[0-3]):[0-5]\d$/;

/**
 * 把 "HH:mm" 换算成下一次到期的 UTC ISO；空/非法返回 null（= 立即执行）。
 *
 * 换算规则与后端 core/evolution.py: next_spec_run_at 同一句话：取当日该时刻，
 * 已过（或正好等于现在）则取次日。后端只在自动接受路径自算；人工同意走本函数
 * 算好的确切值提交，故两边不会对同一次立项各算一遍。合法性锚定检查与后端
 * is_valid_hhmm 同规则（见 HHMM_RE）。
 */
export function nextRunAtISO(runAt?: string | null): string | null {
  if (!runAt || !HHMM_RE.test(runAt)) return null;
  const [h, m] = runAt.split(':').map(Number);
  const now = dayjs();
  let target = now.hour(h).minute(m).second(0).millisecond(0);
  if (!target.isAfter(now)) target = target.add(1, 'day');
  return target.toISOString(); // dayjs 的 toISOString 输出 UTC（带 Z）
}

/** 校验 start_after 合法性：哨兵/空直通，ISO 必须晚于当前时刻。 */
export function isStartAfterValid(startAfter: string | null): boolean {
  if (!startAfter || startAfter === START_AFTER_MANUAL) return true;
  return dayjs(startAfter).isAfter(dayjs());
}

/** 把 start_after 渲染成提示文案后缀（成功 message 用）。 */
export function describeStartAfter(startAfter: string | null): string {
  if (startAfter === START_AFTER_MANUAL) return '，已设为待激活（手工激活后进入调度）';
  if (startAfter) return `，将于 ${dayjs(startAfter).format('YYYY-MM-DD HH:mm')} 执行`;
  return '';
}

// ── 过去时刻置灰（code-review item 5bc7a80927c6）────────────────────
// disabledDate 只禁更早的天——今天已过的钟点仍可选，过去时刻经 holder 写入
// 后只能靠调用方 onOk 的 isStartAfterValid 兜底报通用「执行时间必须晚于当前
// 时间」。过去时刻不应出现在 UI 中：disabledTime 按选中日精确置灰已流逝的
// 小时/分钟，对齐 projects/list.tsx disablePastTime 的同款约定（antd 6
// getDisabledHours/getDisabledMinutes）。本 picker 粒度为 HH:mm（秒面板未开、
// 提交时 second/millisecond 归零），且校验要求严格晚于现在——故当前分钟的
// :00 亦属过去，分钟置灰含当前分钟（与 list.tsx 的秒级粒度变体略宽一档）。
function rangeArray(start: number, endExclusive: number) {
  const out: number[] = [];
  for (let i = start; i < endExclusive; i += 1) out.push(i);
  return out;
}

function disablePastTimeSlot(picked: Dayjs | null) {
  const now = dayjs();
  if (!picked || !picked.isSame(now, 'day')) return {};
  return {
    disabledHours: () => rangeArray(0, now.hour()),
    disabledMinutes: (hour: number) =>
      hour === now.hour() ? rangeArray(0, now.minute() + 1) : [],
  };
}

/**
 * 「执行时间」三档选择（立即 / 指定时间 / 手工激活）。
 *
 * Modal.confirm 的内容渲染在独立 React root 里，父组件 state 变化不会重渲它，
 * 因此选择结果经 ``holder`` 可变对象回传——弹窗内每次改动即写入，onOk 读到的
 * 必然是最后一次选择（本组件自身用 useState 保证 UI 跟着变）。
 */
export default function ScheduleFields({
  holder,
  initial,
  hint,
}: {
  holder: AcceptSchedule;
  initial: string | null;
  /** 首行说明文案（缺省为「将为该条目创建 SPEC 并进入流水线。执行时间：」）。 */
  hint?: string;
}) {
  const [mode, setMode] = useState<'immediate' | 'scheduled' | 'manual'>(
    initial === START_AFTER_MANUAL ? 'manual' : initial ? 'scheduled' : 'immediate');
  // 配置为「立即」时改选「指定时间」的预填值：1 小时后（用户自己改）
  const [when, setWhen] = useState<Dayjs>(
    initial && initial !== START_AFTER_MANUAL
      ? dayjs(initial)
      : dayjs().add(1, 'hour').startOf('minute'));

  const commit = (nextMode: 'immediate' | 'scheduled' | 'manual', nextWhen: Dayjs) => {
    if (nextMode === 'manual') {
      // add-spec-manual-activation D11：手工激活档直接写哨兵字符串，无时区换算
      holder.startAfter = START_AFTER_MANUAL;
    } else {
      holder.startAfter = nextMode === 'scheduled'
        ? nextWhen.second(0).millisecond(0).toISOString()
        : null;
    }
  };

  return (
    <>
      <div style={{ marginBottom: 8 }}>
        {hint ?? '将为该条目创建 SPEC 并进入流水线。执行时间：'}
      </div>
      {/* 下拉与时间选择同行并排（弹窗已加宽），不换行 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'nowrap' }}>
        <Select
          value={mode}
          onChange={(next: 'immediate' | 'scheduled' | 'manual') => {
            setMode(next);
            commit(next, when);
          }}
          style={{ width: 200, flex: 'none' }}
          data-testid="accept-schedule-mode"
          options={[
            { value: 'immediate', label: '创建后立即执行' },
            { value: 'scheduled', label: '在指定时间执行' },
            { value: 'manual', label: '手工激活' },
          ]}
        />
        {mode === 'scheduled' && (
          <DatePicker
            showTime={{ format: 'HH:mm' }}
            format="YYYY-MM-DD HH:mm"
            value={when}
            disabledDate={(d) => d && d < dayjs().startOf('day')}
            disabledTime={disablePastTimeSlot}
            onChange={(v) => {
              if (!v) {
                // 清除（allowClear）回退「立即执行」档（code-review item
                // 0cec6ea1c2f8）：旧实现 v || when 恢复旧值后仍 commit
                // scheduled——清除变无操作且无反馈。回退后下拉档位随可见状态
                // 一同切换，即为本操作的可见反馈。
                setMode('immediate');
                commit('immediate', when);
                return;
              }
              setWhen(v);
              commit('scheduled', v);
            }}
            style={{ flex: 'none' }}
            data-testid="accept-schedule-at"
          />
        )}
      </div>
    </>
  );
}
