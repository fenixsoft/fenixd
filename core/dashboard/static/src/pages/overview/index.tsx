import { PageContainer } from '@ant-design/pro-components';
import { Alert, Button, Card, Space, Spin } from 'antd';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useModel } from '@umijs/max';
import { getOverview, STREAM_URL } from '@/services/dashboard';
import type { OverviewData } from '@/services/dashboard';
import AlertBanner from './components/AlertBanner';
import IntroduceRow from './components/IntroduceRow';
import ProjectCards from './components/ProjectCards';

// dashboard-sse-refresh 3.3：overview 轮询 2s → 30s 心跳校准 + visibilitychange 补刷
const HEARTBEAT_MS = 30000;
// SSE 告警事件合帧窗口：AdminMonitor/watcher 批量升级告警、巡检集中写入时会在
// 短时间连发多个 alerts/admin_activities 事件，逐事件 tick 会让 AlertBanner 逐
// 事件各发一次 GET /api/alerts 形成重拉风暴；窗口内合并为一次横幅刷新
const ALERTS_TICK_COALESCE_MS = 500;

export default function OverviewPage() {
  const [data, setData] = useState<OverviewData | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [alertsTick, setAlertsTick] = useState(0);
  // 侧边栏「项目」子菜单数据源自启动时 getInitialState（此后永不自更新），
  // overview 是项目全集的最新来源——用 setInitialState 保持菜单与列表一致
  const { setInitialState } = useModel('@@initialState');
  // 在飞删除的项目名（ref：load 回调闭包读取，不进依赖避免重建 load→重挂 effect）
  const deletingRef = useRef<Set<string>>(new Set());
  // item 332c514d9d76：SSE 告警事件合帧定时器句柄（ref 供 onmessage 与卸载清理共用，
  // 同 activities 页 refreshTimerRef 惯例）
  const alertsTickTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // item 370293e2857d: load 自增请求序号——30s 心跳、visibilitychange 补刷、
  // ProjectCards onChanged 多处触发的 load 可并发在飞，响应到达顺序不保证，较早
  // 发出的响应后到会把旧 projects/totals 与 setInitialState 菜单写回覆盖新数据。
  // 仿 AlertBanner（fix 9e69e892b7e5）/activities 页（fix 01635701025b）loadSeqRef：
  // 仅最新一次请求允许落状态，过期响应（含其失败与收尾置位）直接丢弃
  const loadSeqRef = useRef(0);

  const load = useCallback(async () => {
    const seq = ++loadSeqRef.current;
    try {
      const d = await getOverview();
      // 写回前复核序号：过期请求不改写任何状态（data 与菜单均不覆盖）
      if (seq !== loadSeqRef.current) return;
      // 删除在飞期间（后端 stop_daemon 轮询可达 30s）overview 仍返回该项目，
      // 心跳/visibilitychange 补刷会把它刷回列表——过滤在飞删除项，
      // 直到删除落定（settleProjectLocal）后才恢复采用服务端真值
      const projects = (d.projects || []).filter((p) => !deletingRef.current.has(p.name));
      // [fenix-ignore:1a02afbcf833] 在飞删除窗口内 totals/token_usage 仍含被删项目：无可靠 per-project 分解可扣减（spec_updated_today/week 只进 totals 不进摘要，降级项目不进 totals），近似扣减反会引入错数；轮询落定后自愈，属乐观 UI 已知瞬态折衷
      setData({ ...d, projects });
      // 菜单校准：自动发现/他端删除后，侧边栏子菜单跟随最新项目全集
      const names = projects.map((p) => p.name);
      // 项目全集与上次完全相同时返回 prev，避免 30s 心跳/visibilitychange 补刷
      // 以新对象触发 @@initialState 消费者（布局/菜单）周期性无效重渲染
      // 显式注解 prev：.umi 生成类型缺失时该回调参数无法获得上下文类型（避免新增 TS7006）
      setInitialState((prev: { projects?: string[] } | undefined) => {
        const prevProjects = prev?.projects;
        if (
          prevProjects &&
          prevProjects.length === names.length &&
          prevProjects.every((n, i) => n === names[i])
        ) {
          return prev;
        }
        return { ...(prev || { projects: [] }), projects: names };
      });
      setError('');
    } catch (e) {
      // 过期请求的失败同样不落状态，防旧错误提示覆盖新请求结果
      if (seq !== loadSeqRef.current) return;
      // fix-dashboard-fault-isolation 3.1：请求失败 MUST NOT 清空已成功加载的
      // data——错误提示叠加在既有数据之上，刷新失败不清空已展示的项目卡片与 totals
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      // 收尾置 false 同样纳入序号守卫（对齐 activities 页 fix 9fc948945fc7）：
      // 旧请求后完成时不抢在并发中的新请求之前撤掉加载指示
      if (seq === loadSeqRef.current) setLoading(false);
    }
  }, [setInitialState]);

  // 乐观摘除：删除确认后立即从列表与侧边栏菜单移除该项目，
  // 不等后端 stop_daemon 轮询收尾（失败由 load() 重拉回滚）
  const removeProjectLocal = useCallback(
    (name: string) => {
      deletingRef.current.add(name);
      setData((prev) => (prev ? { ...prev, projects: prev.projects.filter((p) => p.name !== name) } : prev));
      setInitialState((prev) => ({
        ...(prev || { projects: [] }),
        projects: (prev?.projects || []).filter((n) => n !== name),
      }));
    },
    [setInitialState],
  );

  // 删除落定（成功或失败）：解除在飞标记，随后的 load() 重新采用服务端真值
  const settleProjectLocal = useCallback((name: string) => {
    deletingRef.current.delete(name);
  }, []);

  useEffect(() => {
    void load();
    // 30s 心跳校准：overview 仍作为本地统计的校准源（SSE 断线时心跳兜底）。
    // SSE 增量事件（state/refresh/run_meta）不再逐事件重拉 overview（2s→30s）。
    // item 2056f1d0624f：心跳受可见性门控——页面隐藏时 clearInterval 暂停，
    // 恢复可见时重启定时器并立即补刷，避免长驻后台标签持续消耗 daemon
    let hb = setInterval(() => void load(), HEARTBEAT_MS);
    const onVisible = () => {
      if (document.visibilityState === 'visible') {
        clearInterval(hb);
        hb = setInterval(() => void load(), HEARTBEAT_MS);
        void load();
      } else {
        clearInterval(hb);
      }
    };
    document.addEventListener('visibilitychange', onVisible);
    const es = new EventSource(STREAM_URL);
    es.onmessage = (ev: MessageEvent) => {
      let msg: { type?: string } = {};
      try {
        msg = JSON.parse(ev.data);
      } catch {
        return;
      }
      // alerts/admin_activities 事件均驱动横幅刷新（跨项目告警聚合，与 30s 心跳解耦）：
      // AdminMonitor 新写入的升级告警走 admin_alerts.json 变更，watcher 只广播
      // type=admin_activities（无 alerts 事件），不同驱则停留页面期间新告警不上屏
      if (msg.type === 'alerts' || msg.type === 'admin_activities') {
        // item 332c514d9d76：时间窗合帧——首个事件排程 ALERTS_TICK_COALESCE_MS 后的
        // 一次 tick，窗口内后续事件并入不再排程，逐事件重拉风暴收敛为每窗至多一次
        // GET /api/alerts（横幅仍与 30s 心跳解耦，只是合帧降频）
        if (alertsTickTimerRef.current === null) {
          alertsTickTimerRef.current = setTimeout(() => {
            alertsTickTimerRef.current = null;
            setAlertsTick((t) => t + 1);
          }, ALERTS_TICK_COALESCE_MS);
        }
      }
      // state/refresh/run_meta 不触发 overview 重拉：由 30s 心跳统一校准
    };
    // 卸载必须关闭，防 EventSource 连接泄漏
    return () => {
      es.close();
      clearInterval(hb);
      document.removeEventListener('visibilitychange', onVisible);
      // 合帧定时器随卸载清理，防卸载后仍触发 tick（同 activities 页统一清理惯例）
      if (alertsTickTimerRef.current !== null) {
        clearTimeout(alertsTickTimerRef.current);
        alertsTickTimerRef.current = null;
      }
    };
  }, [load]);

  return (
    <PageContainer
      header={{
        title: '跨项目概览',
        subTitle: data ? `监控 ${data.projects.length} 个项目` : ' ',
      }}
    >
      <AlertBanner refreshTick={alertsTick} />
      {error ? (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 16 }}
          message="概览数据加载失败"
          description={error}
          action={
            <Button size="small" onClick={() => void load()}>
              重试
            </Button>
          }
        />
      ) : null}

      {loading && !data ? (
        <Card>
          <div style={{ textAlign: 'center', padding: 48 }}>
            <Spin size="large" />
          </div>
        </Card>
      ) : data ? (
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          <IntroduceRow totals={data.totals} tokenRecent={data.token_usage?.recent ?? []} />
          <ProjectCards
            projects={data.projects}
            onChanged={() => void load()}
            onProjectRemoved={removeProjectLocal}
            onProjectSettle={settleProjectLocal}
          />
        </Space>
      ) : null}
    </PageContainer>
  );
}
