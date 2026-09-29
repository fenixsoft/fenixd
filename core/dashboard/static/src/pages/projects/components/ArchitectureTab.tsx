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
import { App, Button, Card, Space, Spin, Typography } from 'antd';
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
      if (seq !== seqRef.current) return;
      // 轮询失败止损（对齐 RegressionTab e419d82ceb2b）：持久后端错误时
      // 不再每 3s 重复打请求并重复弹同一 toast
      if (pollTimerRef.current !== null) {
        window.clearInterval(pollTimerRef.current);
        pollTimerRef.current = null;
      }
      message.error(`加载失败: ${e instanceof Error ? e.message : String(e)}`);
    }
  }, [active, project, message]);

  // 最新 loadStatus 经 ref 供长生命周期 interval 调用（RegressionTab
  // 828b713abd5b 同款）：轮询目标始终跟随当前 active/project，避免项目
  // 切换后旧 interval 继续轮询上个项目。
  const loadStatusRef = useRef(loadStatus);
  useEffect(() => {
    loadStatusRef.current = loadStatus;
  }, [loadStatus]);

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

  // ── 四态渲染 ────────────────────────────────────────────────────
  if (state === 'none') {
    return (
      <Card variant="borderless">
        <Space direction="vertical" style={{ width: '100%' }} size={16}>
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
