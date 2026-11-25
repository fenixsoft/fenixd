import { Button, Card, Form, InputNumber, Switch, Typography } from 'antd';
import { useIntl } from '@umijs/max';
import type { ConfigData } from '@/services/dashboard';
import { usePanelDirty, BRANCH_GC_SAVE_OWNER } from '../panelDirty';
import { useGatedFormPanel } from '../useGatedFormPanel';
import { SETTINGS_ACTIONS_ROW_STYLE } from '../styles';

const { Text } = Typography;

// add-merged-branch-gc：分支 GC 配置节缺省与 ConfigLoader.get_branch_gc_config
// 缺省一致（enabled=true / retention_days=7）。宽限期保护合并后流程中的分支
// 读取窗口（deliverables D1 读侧兜底 git show <branch>:tasks.md、验证 diff
// 参照），窗口滑到 main 后读取结果等价。
const DEFAULT_RETENTION_DAYS = 7;

// 两字段表单映射单源（config 取值 ?? 缺省）：initialValues 与回填 effect 共用，
// 避免两份映射漏改一处导致初值与回填值分叉（MiscSettingsPanel 同款范式）
function buildBranchGcFormValues(bgc: ConfigData['worktree'] | undefined) {
  return {
    enabled: bgc?.branch_gc?.enabled ?? true,
    retention_days: bgc?.branch_gc?.retention_days ?? DEFAULT_RETENTION_DAYS,
  };
}

interface BranchGcPanelProps {
  config: ConfigData;
  /** 父级 index.handleSave（返回 Promise<boolean>），与 useGatedFormPanel
   *  onSave 契约同型（Promise<boolean | void>）——收窄为 Promise<void> 会在
   *  渲染处产生 TS2322（其余面板同款历史误差，本面板不新增）。 */
  onSave: (values: Partial<ConfigData>) => Promise<boolean | void>;
}

// 已合并分支 GC 设置面板（add-merged-branch-gc 3.3）：开关（worktree.
// branch_gc.enabled）+ 宽限期天数输入（retention_days，最小 1）。保存走既有
// 配置写回通道（index.handleSave → saveConfig → write_config 前置校验 + 白名单
// 合并），回显当前生效值（后端经 get_branch_gc_config 归一，非法值回显缺省）。
export default function BranchGcPanel({ config, onSave }: BranchGcPanelProps) {
  const intl = useIntl();
  const [form] = Form.useForm();
  // 用户编辑置脏：切页签/作用域前由 index 经 anyPanelDirty 弹丢弃确认。
  // owner 与 index 传给 handleSave 的 dirtyOwner 同值配对（code-review item
  // 4a1439f602af）：本页签同时挂 VerifyPanel、两保存入口各清各的脏标记，
  // 保存本面板不复位其快照前已置脏的未保存编辑
  const { setDirty } = usePanelDirty(undefined, BRANCH_GC_SAVE_OWNER);
  // 表单脚手架统一走 useGatedFormPanel（saving 重入守卫 / 序列化比较回填
  // 门控 / 校验与持久化分离，与 MiscSettingsPanel 同款）
  const { saving, initialValues, handleSave } = useGatedFormPanel({
    form,
    buildValues: () => buildBranchGcFormValues(config.worktree),
    backfillDeps: [config.worktree],
    onSave,
    buildPayload: (values): Partial<ConfigData> => ({
      worktree: {
        branch_gc: {
          enabled: values.enabled,
          retention_days: values.retention_days,
        },
      },
    }),
  });

  return (
    <div data-testid="branch-gc-panel">
      <h3>{intl.formatMessage({ id: 'settings.branchGc.title' })}</h3>
      <Text type="secondary">
        {intl.formatMessage({ id: 'settings.branchGc.desc1' })} <code>git branch -d</code>{' '}
        {intl.formatMessage({ id: 'settings.branchGc.desc2' })}
      </Text>
      <Form
        form={form}
        initialValues={initialValues}
        layout="vertical"
        onValuesChange={() => setDirty(true)}
      >
        <Card style={{ marginTop: 12 }}>
          <div className="switch-inline-row">
            <Form.Item name="enabled" valuePropName="checked" noStyle>
              <Switch data-testid="branch-gc-control-enabled" />
            </Form.Item>
            <span className="switch-inline-label">
              {intl.formatMessage({ id: 'settings.branchGc.enabledLabel' })}
              <span className="label-note">（worktree.branch_gc.enabled）</span>
            </span>
          </div>
          <Text type="secondary">
            {intl.formatMessage({ id: 'settings.branchGc.enabledDesc' })}
          </Text>

          <Form.Item
            name="retention_days"
            label={
              <>
                {intl.formatMessage({ id: 'settings.branchGc.retentionDays.label' })}
                <span className="label-note">
                  （worktree.branch_gc.retention_days）
                </span>
              </>
            }
            style={{ marginTop: 24 }}
            rules={[
              { required: true, message: intl.formatMessage({ id: 'settings.branchGc.retentionDays.required' }) },
              // 正整数校验与 MiscSettingsPanel auto_threshold 同口径：不能用
              // InputNumber 的 min 代替——blur 时会把越界值静默钳回边界，
              // 用户永远看不到非法输入被拦截的表单错误提示
              {
                type: 'integer',
                min: 1,
                message: intl.formatMessage({ id: 'settings.branchGc.retentionDays.integer' }),
              },
            ]}
            data-testid="branch-gc-field-retention_days"
          >
            <InputNumber precision={0} style={{ width: '100%' }} addonAfter={intl.formatMessage({ id: 'settings.branchGc.retentionDays.unit' })} />
          </Form.Item>
          <Text type="secondary">
            {intl.formatMessage({ id: 'settings.branchGc.retentionDays.desc1' }, { days: DEFAULT_RETENTION_DAYS })}{' '}
            <code>git show &lt;branch&gt;:tasks.md</code>
            {intl.formatMessage({ id: 'settings.branchGc.retentionDays.desc2' })}
          </Text>
        </Card>
      </Form>
      <div style={SETTINGS_ACTIONS_ROW_STYLE}>
        <Button
          type="primary"
          onClick={handleSave}
          loading={saving}
          disabled={saving}
          data-testid="branch-gc-save"
        >
          {intl.formatMessage({ id: 'settings.branchGc.save' })}
        </Button>
      </div>
    </div>
  );
}
