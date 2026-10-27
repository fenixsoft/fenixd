import { Button, Card, Form, InputNumber, Switch, Typography } from 'antd';
import type { ConfigData } from '@/services/dashboard';
import { usePanelDirty } from '../panelDirty';
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
  const [form] = Form.useForm();
  // 用户编辑置脏：切页签/作用域前由 index 经 anyPanelDirty 弹丢弃确认
  const { setDirty } = usePanelDirty();
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
      <h3>分支回收（GC）</h3>
      <Text type="secondary">
        daemon 每轮启动清扫时，回收满足全部安全条件的已合并实现/验证分支：
        已完全并入基线分支（只允许 <code>git branch -d</code> 删除语义，未合并
        分支天然免疫）、tip 提交时间早于宽限期、未被任何 worktree 占用、所属
        SPEC 已归档或非活跃（实现/验证/评审中的 SPEC 分支一律豁免）。
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
              启用已合并分支回收
              <span className="label-note">（worktree.branch_gc.enabled）</span>
            </span>
          </div>
          <Text type="secondary">
            缺省开启。关闭后整个 GC 环节跳过——不扫描、不删除、无日志，行为与
            引入分支回收之前完全一致；分支数量将随每轮实现/验证重新累积。
          </Text>

          <Form.Item
            name="retention_days"
            label={
              <>
                宽限期天数
                <span className="label-note">
                  （worktree.branch_gc.retention_days）
                </span>
              </>
            }
            style={{ marginTop: 24 }}
            rules={[
              { required: true, message: '请输入宽限期天数' },
              // 正整数校验与 MiscSettingsPanel auto_threshold 同口径：不能用
              // InputNumber 的 min 代替——blur 时会把越界值静默钳回边界，
              // 用户永远看不到非法输入被拦截的表单错误提示
              {
                type: 'integer',
                min: 1,
                message: '须为不小于 1 的整数天',
              },
            ]}
            data-testid="branch-gc-field-retention_days"
          >
            <InputNumber precision={0} style={{ width: '100%' }} addonAfter="天" />
          </Form.Item>
          <Text type="secondary">
            缺省 {DEFAULT_RETENTION_DAYS} 天。分支合并后仍可能在宽限期内被读取
            （交付物读侧兜底 <code>git show &lt;branch&gt;:tasks.md</code>、验证
            diff 参照），宽限期过期后其内容已可从 main 等价读取，回收零内容风险。
            0/负数/非整数按非法值处理，回退缺省 7。保存后下次 daemon 启动清扫生效。
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
          保存
        </Button>
      </div>
    </div>
  );
}
