import { Button, Card, Form, InputNumber, Select, Tag, Typography } from 'antd';
import { useCallback, useEffect, useState } from 'react';
import type { ConfigData } from '@/services/dashboard';
import { getChainOverview } from '@/services/dashboard';
import type { ChainConfig, ChainOverviewData } from '@/services/dashboard';
import { usePanelDirty } from '../panelDirty';
import { useGatedFormPanel } from '../useGatedFormPanel';
import { SETTINGS_ACTIONS_ROW_STYLE } from '../styles';

const { Text } = Typography;

// add-escalation-chain-admin-arbiter 5.3：chain 配置节缺省与
// ConfigLoader.get_chain_config 缺省一致（admin_attempts=2 /
// arbiter_rulings=2 / reset_window_days=7 / blacklist=[]）。
const CHAIN_DEFAULTS: Required<ChainConfig> = {
  admin_attempts: 2,
  arbiter_rulings: 2,
  reset_window_days: 7,
  blacklist: [],
};

// 运行时水位轮询周期：与链头每次判定即时解析配置的热更新同拍——保存生效
// 后下一轮轮询即可观测新水位
const STATUS_REFRESH_MS = 30_000;

// blacklist 表单数组字段走 Form.List 的空态守卫值
const EMPTY_BLACKLIST: string[] = [];

// 四键表单映射单源（config 取值 ?? 缺省）：initialValues 与回填 effect 共用
// （ArbiterPanel 同款范式，避免两份映射漏改一处导致初值与回填值分叉）
function buildChainFormValues(cfg: ConfigData['chain'] | undefined) {
  return {
    admin_attempts: cfg?.admin_attempts ?? CHAIN_DEFAULTS.admin_attempts,
    arbiter_rulings: cfg?.arbiter_rulings ?? CHAIN_DEFAULTS.arbiter_rulings,
    reset_window_days: cfg?.reset_window_days ?? CHAIN_DEFAULTS.reset_window_days,
    blacklist: cfg?.blacklist ?? EMPTY_BLACKLIST,
  };
}

interface ChainPanelProps {
  config: ConfigData;
  /** 父级 index.handleSave（返回 Promise<boolean>），与 useGatedFormPanel
   *  onSave 契约同型（Promise<boolean | void>）。 */
  onSave: (values: Partial<ConfigData>) => Promise<boolean | void>;
  /** 项目名（项目级作用域下取运行时水位；用户级不传） */
  project?: string;
}

// 处置链设置面板（add-escalation-chain-admin-arbiter 5.3）：四键配置（配额
// 两轴 + 复位窗 + 信号黑名单）+ 运行时水位只读摘要（30s 轮询）。保存走既有
// 配置写回通道（index.handleSave → saveConfig → write_config 前置校验 +
// 白名单合并）；链头每次判定即时解析项目级配置，保存即热更新（无需重启）。
export default function ChainPanel({ config, onSave, project }: ChainPanelProps) {
  const [form] = Form.useForm();
  const { setDirty } = usePanelDirty();
  const { saving, initialValues, handleSave } = useGatedFormPanel({
    form,
    buildValues: () => buildChainFormValues(config.chain),
    backfillDeps: [config.chain],
    onSave,
    buildPayload: (values): Partial<ConfigData> => ({
      chain: {
        admin_attempts: values.admin_attempts,
        arbiter_rulings: values.arbiter_rulings,
        reset_window_days: values.reset_window_days,
        blacklist: values.blacklist ?? EMPTY_BLACKLIST,
      },
    }),
  });

  // 运行时水位只读摘要（恒 200 自含端点，失败静默为空态——非关键数据；
  // ArbiterPanel 的过期响应守卫同款：per-effect alive 判活，项目切换/卸载
  // 的迟到响应一律丢弃）
  const [status, setStatus] = useState<ChainOverviewData | null>(null);
  const loadStatus = useCallback(async (name?: string, isStale?: () => boolean) => {
    if (!name) return;
    try {
      const next = await getChainOverview(name);
      if (isStale?.()) return;
      setStatus(next);
    } catch {
      if (isStale?.()) return;
      setStatus(null);
    }
  }, []);
  useEffect(() => {
    if (!project) return;
    let alive = true;
    void loadStatus(project, () => !alive);
    // 30s 轮询：观测水位自然演进（在办件收口/配额累计），与处置链视图页同拍
    const timer = setInterval(() => void loadStatus(project, () => !alive), STATUS_REFRESH_MS);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [loadStatus, project]);

  const summary = status?.summary;

  return (
    <div data-testid="chain-panel">
      <h3>处置链（Admin → Arbiter → Human）</h3>
      <Text type="secondary">
        升级边信号默认进入自动处置链：Admin 拍板面自治处置（配额内），超出拍板面
        或配额耗尽自动转单 Arbiter 调查拍板，链终点失败才落人工告警（携全链痕）。
        同签名的配额按复位窗或 SPEC 状态翻转清零；黑名单信号（kill switch）绕过
        处置链直达人工——与引入链之前的告警路径逐字节一致。
      </Text>
      <Form
        form={form}
        initialValues={initialValues}
        layout="vertical"
        onValuesChange={() => setDirty(true)}
      >
        <Card style={{ marginTop: 12 }}>
          <Form.Item
            name="admin_attempts"
            label={
              <>
                Admin 尝试配额
                <span className="label-note">（chain.admin_attempts）</span>
              </>
            }
            rules={[
              { required: true, message: '请输入 Admin 尝试配额' },
              { type: 'integer', min: 1, message: '须为正整数次' },
            ]}
            data-testid="chain-field-admin_attempts"
          >
            <InputNumber precision={0} style={{ width: '100%' }} addonAfter="次/签名" />
          </Form.Item>
          <Text type="secondary">
            缺省 {CHAIN_DEFAULTS.admin_attempts} 次。同签名 Admin 拍板尝试达本次数后
            自动转单 Arbiter，不再重复同一拍板面。
          </Text>

          <Form.Item
            name="arbiter_rulings"
            label={
              <>
                Arbiter 拍板配额
                <span className="label-note">（chain.arbiter_rulings）</span>
              </>
            }
            style={{ marginTop: 24 }}
            rules={[
              { required: true, message: '请输入 Arbiter 拍板配额' },
              { type: 'integer', min: 1, message: '须为正整数次' },
            ]}
            data-testid="chain-field-arbiter_rulings"
          >
            <InputNumber precision={0} style={{ width: '100%' }} addonAfter="次/签名" />
          </Form.Item>
          <Text type="secondary">
            缺省 {CHAIN_DEFAULTS.arbiter_rulings} 次。同签名 Arbiter 复现信号达本次数后
            不再重派（死人开关单次豁免另计），强制升级人工。
          </Text>

          <Form.Item
            name="reset_window_days"
            label={
              <>
                配额复位窗
                <span className="label-note">（chain.reset_window_days）</span>
              </>
            }
            style={{ marginTop: 24 }}
            rules={[
              { required: true, message: '请输入复位窗天数' },
              { type: 'integer', min: 1, message: '须为正整数天' },
            ]}
            data-testid="chain-field-reset_window_days"
          >
            <InputNumber precision={0} style={{ width: '100%' }} addonAfter="天" />
          </Form.Item>
          <Text type="secondary">
            缺省 {CHAIN_DEFAULTS.reset_window_days} 天。签名静默满窗配额清零；
            SPEC 状态翻转即时清零，不待窗满。
          </Text>

          <Form.Item
            name="blacklist"
            label={
              <>
                信号黑名单（kill switch）
                <span className="label-note">（chain.blacklist）</span>
              </>
            }
            style={{ marginTop: 24 }}
            data-testid="chain-field-blacklist"
          >
            <Select
              mode="tags"
              open={false}
              tokenSeparators={[',', ' ']}
              placeholder="输入信号类型后回车（如 verify_env_blocked）"
              data-testid="chain-blacklist-input"
            />
          </Form.Item>
          <Text type="secondary">
            缺省空（全信号入链）。命中的信号绕过处置链直达人工，告警路径与合入前
            逐字节一致；每行一个信号类型，保存即热更新。
          </Text>
        </Card>
      </Form>

      {project && (
        <Card style={{ marginTop: 12 }} data-testid="chain-status-card">
          <h4 style={{ marginTop: 0 }}>
            运行时水位（只读，{STATUS_REFRESH_MS / 1000}s 刷新）
          </h4>
          {summary ? (
            <Text type="secondary">
              链在办 {summary.in_flight} 件；人工队列 {summary.queue} 件；签名水位{' '}
              {summary.signatures} 个
              {summary.quota_exhausted > 0 ? `（${summary.quota_exhausted} 个配额耗尽）` : ''}；
              链关联上升件 {summary.escalations} 条。
            </Text>
          ) : (
            <Text type="secondary">—（运行时水位不可得）</Text>
          )}
          <div style={{ marginTop: 8 }}>
            {(config.chain?.blacklist ?? []).map((sig) => (
              <Tag key={sig} color="red" data-testid="chain-blacklist-tag">
                {sig}
              </Tag>
            ))}
          </div>
        </Card>
      )}

      <div style={SETTINGS_ACTIONS_ROW_STYLE}>
        <Button
          type="primary"
          onClick={handleSave}
          loading={saving}
          disabled={saving}
          data-testid="chain-save"
        >
          保存
        </Button>
      </div>
    </div>
  );
}
