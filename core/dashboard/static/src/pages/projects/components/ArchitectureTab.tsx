// ArchitectureTab.tsx — 项目页「架构蓝图」分面（add-project-architecture-tab 2.2）
//
// 承载 archify 按需生成的项目架构图视图：
// - active 门控：仅在选中本分面时拉取 GET /api/architecture/status，未选中零
//   请求（对齐 QualityTab/RegressionTab 按需加载语义）；系统不在任何时机自动
//   触发生成（spec「不自动生成」，纯手动按钮）。
// - 四态渲染（后端状态机 none/generating/ready/failed）：
//   1) none：空态文案 + 「刷新架构图」按钮（首次手动触发）；
//   2) generating：生成中提示 + 按钮置灰 + 3s 轮询状态；
//   3) ready：生成时间/组件数元信息 + <iframe sandbox="allow-scripts">（不带
//      allow-same-origin，产物脚本与主站 cookie/DOM 隔离，design D6）+
//      可再次点击的「刷新架构图」按钮。iframe URL 恒带 present=1（archify
//      原生参数，见 architectureDiagramUrl 注释），架构图默认以演示模式
//      充满视口展示；用户仍可在图内工具栏退出/再进演示模式；
//   4) failed：错误信息展示 + 按钮恢复可点（重试覆盖旧错误）。
// - 容器显式 flex 定高（design D6）：桌面/移动两档高度常数（对齐 SessionPanel
//   实测偏移 222/234），useIsMobile 切换，minHeight 兜底，避免移动端越界。
import { useCallback, useEffect, useRef, useState } from 'react';
import type { CSSProperties } from 'react';
import dayjs from 'dayjs';
import { Alert, App, Button, Card, Space, Spin, Typography } from 'antd';
import {
  ApiError,
  architectureDiagramUrl,
  getArchitectureStatus,
  refreshArchitecture,
} from '../../../services/dashboard';
import type { ArchitectureStatus } from '../../../services/dashboard';
import { useIsMobile } from '../../../hooks/useIsMobile';

interface ArchitectureTabProps {
  project: string;
  active: boolean;
}

// ── 模块级命名常量（对齐 RegressionTab 5130098995b7 范式）────────────
const POLL_INTERVAL_MS = 3000;
// 分面高度 = 视口 − 页面 chrome（SessionPanel 同款实测常数：桌面 222 =
// 布局顶栏 56 + 页头 72 + Tabs 导航 46 + Tabs 内容上边距 16 + 底部 32；
// 移动端 234 按 390×844 实测校准）。超短视口由 minHeight 保底。
const FRAME_OFFSET_DESKTOP = 222;
const FRAME_OFFSET_MOBILE = 234;
const FRAME_MIN_HEIGHT = 320;

function fmtTime(iso?: string | null) {
  if (!iso) return '—';
  const d = dayjs(iso);
  return d.isValid() ? d.format('YYYY-MM-DD HH:mm:ss') : iso;
}

export default function ArchitectureTab({ project, active }: ArchitectureTabProps) {
  const { message } = App.useApp();
  const isMobile = useIsMobile();
  const [status, setStatus] = useState<ArchitectureStatus | null>(null);
  const [triggering, setTriggering] = useState(false);
  // 最近一次状态读取失败的可见错误态（code-review item 55aea63bbe02）：轮询
  // 止损只停定时器的话，本地 status 停在最后一次成功快照，generating 态会
  // 一直渲染「生成中」且按钮置灰，toast 消失后无任何错误展示与恢复入口。
  // 这里把失败暴露为常驻错误条 + 重试读取按钮；仅记录「进度读取失败」，
  // 不改写 status，与后端 failed 态（生成失败）语义不混淆。下一次成功读取
  // 或切换项目即清除，不恢复自动重试。
  const [readError, setReadError] = useState<string | null>(null);
  const pollTimerRef = useRef<number | null>(null);
  // 请求序号守卫（对齐 QualityTab/RegressionTab）：轮询与手动刷新并发时
  // 较慢的早期响应不得覆盖较新数据。
  const seqRef = useRef(0);
  // active 快照（模式同 loadStatusRef）：await 返回后闭包里的 active 可能
  // 已过期（请求在途时切离分面），离面复核以 ref 中的最新值为准。
  const activeRef = useRef(active);
  useEffect(() => {
    activeRef.current = active;
  }, [active]);

  const loadStatus = useCallback(async () => {
    if (!active || !project) return;
    const seq = ++seqRef.current;
    try {
      const data = await getArchitectureStatus(project);
      // seq 之外再复核最新 active：请求在途时切离分面则直接放弃，否则
      // generating 态会在此处新起 3s 轮询定时器，且之后每次 tick 因闭包
      // active=false 入口 early-return，定时器离面后永久空转（违背
      // 「离开分面停止轮询」语义）。
      if (seq !== seqRef.current || !activeRef.current) return;
      setStatus(data);
      setReadError(null);
      // generating → 3s 轮询；其余态停轮询
      if (data.state === 'generating') {
        if (pollTimerRef.current === null) {
          pollTimerRef.current = window.setInterval(() => {
            void loadStatusRef.current();
          }, POLL_INTERVAL_MS);
        }
      } else if (pollTimerRef.current !== null) {
        window.clearInterval(pollTimerRef.current);
        pollTimerRef.current = null;
      }
    } catch (e) {
      // 失败分支与成功分支同口径复核最新 active：切离分面后无新请求自增
      // seq，仅靠 seq 复核拦不住在飞失败响应——离面后不再弹 toast/写
      // readError（用户已看不见本分面的错误条）。
      if (seq !== seqRef.current || !activeRef.current) return;
      // 轮询失败止损（对齐 RegressionTab e419d82ceb2b）：持久后端错误时
      // 不再每 3s 重复打请求并重复弹同一 toast
      if (pollTimerRef.current !== null) {
        window.clearInterval(pollTimerRef.current);
        pollTimerRef.current = null;
      }
      // 止损之外同步落地可见错误条（55aea63bbe02）：自动刷新已停，但生成
      // 不因此中断，需给用户持续的错误展示与手动重试读取入口
      const errMsg = e instanceof Error ? e.message : String(e);
      setReadError(errMsg);
      message.error(`加载失败: ${errMsg}`);
    }
  }, [active, project, message]);

  // 最新 loadStatus 经 ref 供长生命周期 interval 调用（RegressionTab
  // 828b713abd5b 同款）：轮询目标始终跟随当前 active/project，避免项目
  // 切换后旧 interval 继续轮询上个项目。
  const loadStatusRef = useRef(loadStatus);
  useEffect(() => {
    loadStatusRef.current = loadStatus;
  }, [loadStatus]);

  // 跨项目切换清态（code-review item b015dc9cde42，口径同 RegressionTab
  // 0efd50f9753f / CodeFixProgressCard 1d0b747da6b2）：本组件随 Tab 常驻挂载，
  // project 变化只重启 active 门控的加载 effect、不卸载组件，组件级 status 会
  // 保留上一项目最后一次快照——新项目首个响应返回前仍渲染旧项目的生成时间/
  // 组件数与 iframe 架构图，而此刻「刷新架构图」按钮实际作用于新项目，所见与
  // 所指不一致；新项目请求失败时旧状态会持续滞留。对 project 专门 effect 清空
  // status，回落 none 引导态直至新项目数据到达。声明序在加载 effect 之前：
  // project 变化时清空先于新请求响应执行，不会误清新项目刚取到的数据。
  useEffect(() => {
    setStatus(null);
    setReadError(null);
  }, [project]);

  // active 门控：进入分面加载，离开分面停止轮询（未选中零请求）
  useEffect(() => {
    if (!active || !project) return;
    void loadStatus();
  }, [active, project, loadStatus]);

  // 切离分面清理轮询
  useEffect(() => {
    if (!active && pollTimerRef.current !== null) {
      window.clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  }, [active]);

  // 卸载清理轮询
  useEffect(() => {
    return () => {
      if (pollTimerRef.current !== null) {
        window.clearInterval(pollTimerRef.current);
        pollTimerRef.current = null;
      }
    };
  }, []);

  // ── 手动触发（spec：仅手动按钮触发，不自动生成）────────────────
  const handleRefresh = async () => {
    if (triggering) return;
    setTriggering(true);
    try {
      await refreshArchitecture(project);
      message.success('已受理，架构图生成中');
      // 立即拉取 generating 态 → 3s 轮询接管
      void loadStatus();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        // 单飞拒绝（稳定 HTTP 语义，不做中文消息子串匹配）：提示并拉取
        // 最新状态，由 generating 态轮询接管进度
        message.warning('架构图生成正在进行中，请稍候');
        void loadStatus();
      } else {
        const errMsg = e instanceof Error ? e.message : String(e);
        message.error(`触发失败: ${errMsg}`);
      }
    } finally {
      setTriggering(false);
    }
  };

  if (!active) return null;

  const state = status?.state ?? 'none';
  const generating = state === 'generating';

  // 四态共用的刷新按钮：generating 置灰；none/ready/failed 可点
  const refreshButton = (
    <Button
      type="primary"
      loading={triggering}
      disabled={generating}
      onClick={() => void handleRefresh()}
    >
      刷新架构图
    </Button>
  );

  // ── 读取失败错误条（code-review item 55aea63bbe02）──────────────
  // 四态之上叠加展示：仅标注「进度读取失败」，不改写四态语义（尤其不复用
  // failed 态，避免与真实生成失败混淆）；「重试读取」只重新拉状态，不触
  // 发新的生成。
  const readErrorBanner = readError ? (
    <Alert
      type="error"
      showIcon
      message="进度读取失败，已停止自动刷新"
      description={`${readError}（可点击「重试读取」，或切出本分面再切回触发重新读取）`}
      action={
        <Button size="small" onClick={() => void loadStatus()}>
          重试读取
        </Button>
      }
    />
  ) : null;

  // ── 四态渲染 ────────────────────────────────────────────────────
  if (state === 'none') {
    return (
      <Card variant="borderless">
        <Space direction="vertical" style={{ width: '100%' }} size={16}>
          {readErrorBanner}
          <Typography.Text strong>尚未生成架构图</Typography.Text>
          <Typography.Text type="secondary">
            点击「刷新架构图」后，系统将启动一次 headless claude（挂 archify skill）
            阅读本项目代码，产出一张高层运行时架构图（8–16 个核心组件 / 单一主路径 /
            外部依赖与信任边界 / 辅助信息进说明卡片，中文标注）。生成不自动进行，
            可随时手动触发；生成需要几分钟到十几分钟。
          </Typography.Text>
          <div style={{ textAlign: 'right' }}>{refreshButton}</div>
        </Space>
      </Card>
    );
  }

  if (state === 'generating') {
    return (
      <Card variant="borderless">
        <Space direction="vertical" style={{ width: '100%' }} size={16}>
          {readErrorBanner}
          <Space>
            <Spin size="small" />
            <Typography.Text strong>架构图生成中…</Typography.Text>
          </Space>
          <Typography.Text type="secondary">
            正在阅读项目代码并绘制架构图，通常需要几分钟到十几分钟；可离开本页，
            稍后回来查看。
          </Typography.Text>
          <div style={{ textAlign: 'right' }}>{refreshButton}</div>
        </Space>
      </Card>
    );
  }

  if (state === 'failed') {
    return (
      <Card variant="borderless">
        <Space direction="vertical" style={{ width: '100%' }} size={16}>
          {readErrorBanner}
          <Typography.Text strong>架构图生成失败</Typography.Text>
          <Typography.Text type="secondary">
            {status?.error || '原因未知，可重试或查看服务端日志'}
          </Typography.Text>
          <div style={{ textAlign: 'right' }}>{refreshButton}</div>
        </Space>
      </Card>
    );
  }

  // ready：元信息 + iframe 沙箱渲染 + 可再刷新。
  // key 取 generated_at：再生成完成后新时间戳强制 iframe 重新加载新产物。
  const containerStyle: CSSProperties = {
    display: 'flex',
    flexDirection: 'column',
    height: isMobile
      ? `calc(100dvh - ${FRAME_OFFSET_MOBILE}px)`
      : `calc(100vh - ${FRAME_OFFSET_DESKTOP}px)`,
    minHeight: FRAME_MIN_HEIGHT,
  };
  return (
    <Card variant="borderless">
      <Space direction="vertical" style={{ width: '100%' }} size={12}>
        {readErrorBanner}
        <div
          style={{
            display: 'flex',
            flexWrap: 'wrap',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 8,
          }}
        >
          <Space size={16} wrap>
            <Typography.Text type="secondary">
              生成时间：{fmtTime(status?.generated_at)}
            </Typography.Text>
            {status?.component_count !== null &&
            status?.component_count !== undefined ? (
              <Typography.Text type="secondary">
                核心组件：{status.component_count} 个
              </Typography.Text>
            ) : null}
            {status?.duration_ms !== null && status?.duration_ms !== undefined ? (
              <Typography.Text type="secondary">
                耗时 {Math.round(status.duration_ms / 1000)}s
              </Typography.Text>
            ) : null}
          </Space>
          {refreshButton}
        </div>
        <div style={containerStyle}>
          <iframe
            key={status?.generated_at ?? 'ready'}
            src={architectureDiagramUrl(project)}
            sandbox="allow-scripts"
            title="项目架构图"
            style={{ width: '100%', height: '100%', border: 0, borderRadius: 8 }}
          />
        </div>
      </Space>
    </Card>
  );
}
