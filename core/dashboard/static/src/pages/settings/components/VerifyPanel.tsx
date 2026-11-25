import { Alert, Button, Card, Form, Input, Radio, Space, Switch, Typography } from 'antd';
import { MinusCircleOutlined, PlusOutlined } from '@ant-design/icons';
import { getIntl, useIntl } from '@umijs/max';
import { useEffect } from 'react';
import type { ReactNode } from 'react';
import type { ConfigData } from '@/services/dashboard';
import SyncFromUserButton from './SyncFromUserButton';
import { SETTINGS_ACTIONS_ROW_STYLE } from '../styles';
import { usePanelDirty, VERIFY_SAVE_OWNER } from '../panelDirty';
import { useGatedFormPanel } from '../useGatedFormPanel';

const { Text } = Typography;

// 产物路径逐项前端校验（与后端 validate_build_artifact_paths 同口径，仅为即时报错；
// 写入权威仍在后端，非法项在 POST /api/config 被 400 拒绝）。
function artifactPathRule(_rule: unknown, value: unknown): Promise<void> {
  const intl = getIntl();
  const v = typeof value === 'string' ? value.trim() : '';
  if (!v) return Promise.reject(new Error(intl.formatMessage({ id: 'settings.verify.artifactPath.empty' })));
  if (v.startsWith('/')) return Promise.reject(new Error(intl.formatMessage({ id: 'settings.verify.artifactPath.absolute' })));
  // 与后端 normalize_artifact_patterns 同口径：`".." in item.split("/")`，按
  // 独立路径段判定（docstring「含 '..' 段的项丢弃」）——dist..old/ 这类含
  // '..' 子串的合法目录名放行，与后端一致。旧注释误称后端为 `".." in item`
  // 子串判定（code-review item c30b8b2c0662），曾使前端比后端更严。
  if (v.split('/').includes('..')) return Promise.reject(new Error(intl.formatMessage({ id: 'settings.verify.artifactPath.dotdotSegment' })));
  if (!v.includes('*') && !v.endsWith('/'))
    return Promise.reject(new Error(intl.formatMessage({ id: 'settings.verify.artifactPath.prefixFormat' })));
  return Promise.resolve();
}

/** 产物三态提示文案（code-review item ca92db5ea623：抽出嵌套三元为具名函数）。 */
function buildArtifactsHint(state: HasBuildArtifactsState | undefined): string {
  const intl = getIntl();
  if (state === 'unset' || state === undefined) {
    return intl.formatMessage({ id: 'settings.verify.artifactsHint.unset' });
  }
  if (state === 'true') {
    return intl.formatMessage({ id: 'settings.verify.artifactsHint.true' });
  }
  return intl.formatMessage({ id: 'settings.verify.artifactsHint.false' });
}

/** 用户级只读分支的三态渲染（code-review item e5a67a93590c：抽出嵌套三元为具名
    函数，比照 buildArtifactsHint 的收敛形态——JSX 内只留一次函数调用）。 */
function buildUserScopeArtifactsSection(
  paths: string[] | undefined,
  hasArtifacts: boolean | null | undefined,
): ReactNode {
  if (paths?.length) {
    return (
      <ul style={{ margin: '12px 0 0', paddingLeft: 20 }}>
        {paths.map((p, i) => {
          // code-review item c5b0bd57f3db：稳定 key——配置路径实际唯一，
          // 直接用路径本身；病态重复条目回退「路径-索引」防 React 撞
          // key。索引 key 会在重排/插入/删除时按位置复用错误 DOM 节点。
          // 可选链：map 回调内 TS 收窄失效，非空由上方守卫保证。
          const key = paths?.indexOf(p) === i ? p : `${p}-${i}`;
          return (
            <li key={key}>
              <code>{p}</code>
            </li>
          );
        })}
      </ul>
    );
  }
  if (hasArtifacts === true) {
    // true + 空路径 = 三态表的「标志与路径不一致」未决态
    //（is_artifact_config_unresolved：判定恒假、按无产物处理）。
    // 旧实现此组合静默渲染「有派生物」、无路径亦无说明（code-review
    // item def8b9836b7e，下方 !==true 守卫把未决提示一并抑制）——
    // 显式说明矛盾态与其保守侧生效语义。
    const intl = getIntl();
    return (
      <Text type="warning" style={{ display: 'block', marginTop: 12 }}>
        {intl.formatMessage({ id: 'settings.verify.userScope.declaredTrueEmpty' })}
      </Text>
    );
  }
  return (
    hasArtifacts !== false &&
    hasArtifacts !== true && (
      <Text type="secondary" style={{ display: 'block', marginTop: 12 }}>
        {getIntl().formatMessage({ id: 'settings.verify.userScope.unresolvedHint' })}
      </Text>
    )
  );
}

/** has_build_artifacts 三态表单值：'unset'（未裁决）/ 'true'（有产物）/ 'false'（无产物）。
    antd Switch 无 indeterminate 语义，故用 Radio.Group 三选一承载（spec 6.3 约定）。 */
export type HasBuildArtifactsState = 'unset' | 'true' | 'false';

function toFormState(v: boolean | null | undefined): HasBuildArtifactsState {
  // 参数类型放宽含 null（code-review item deed1f27d507）：后端未裁决发 null。
  if (v === true) return 'true';
  if (v === false) return 'false';
  return 'unset';
}

// 表单值映射单源（code-review item 90e26b043318，比照 TokenBudgetPanel
// cbec8303669f 的 buildAgentsFormValues 形态）：initialValues 与回填 effect
// 共用，缺省调整只改此处，避免两份映射漏改一处导致初值与回填值分叉。
function buildVerifyFormValues(config: ConfigData) {
  return {
    // 非法手写值不进 Radio.Group（比照 SystemPanel 的 harness 归一，code-review
    // item 2752a5701cce）：`||` 只兜空值，.fenix 配置词表外取值会原样回填成
    // 「无一选项选中」且 required 因值非空放行、保存原样回传——显式按本文件
    // Radio.Group 词表归一到合法缺省。
    static_scope: config.verify?.static_scope === 'worktree' ? 'worktree' : 'main',
    deps_mode: config.verify?.deps_mode === 'prefer-offline' ? 'prefer-offline' : 'hardlink',
    serving_reclaim_enabled: config.verify?.serving_reclaim?.enabled ?? true,
    build_artifact_paths: (config.worktree?.build_artifact_paths || []).map(
      (p) => ({ path: p }),
    ),
    has_build_artifacts: toFormState(config.worktree?.has_build_artifacts),
  };
}

interface VerifyPanelProps {
  config: ConfigData;
  // 契约即 index.handleSave 的 Promise<boolean>（false=保存失败，成功/失败
  // toast 均由父级兜底），与其他面板口径一致（code-review item 3dd377800692）
  onSave: (values: Partial<ConfigData>) => Promise<boolean>;
  /** 当前项目名；项目级作用域才显示「同步用户级设置」按钮，且产物路径可编辑 */
  project?: string;
  /** 同步成功后回填配置（父组件 setConfig 驱动表单刷新） */
  onConfigSynced?: (config: ConfigData) => void;
}

export default function VerifyPanel({ config, onSave, project, onConfigSynced }: VerifyPanelProps) {
  const intl = useIntl();
  const [form] = Form.useForm();
  // 用户编辑置脏：切页签/作用域前由 index 经 anyPanelDirty 弹丢弃确认
  // （code-review item 8a3eb01dc2b9）。owner 与 index 传给 handleSave 的
  // dirtyOwner 同值配对（code-review item 4a1439f602af）：本页签同时挂
  // BranchGcPanel、两保存入口各清各的脏标记，保存本面板不复位其快照前
  // 已置脏的未保存编辑
  const { setDirty } = usePanelDirty(undefined, VERIFY_SAVE_OWNER);
  // 产物路径为项目级键：用户级作用域下只读展示（无 project 即用户级）
  const artifactEditable = Boolean(project);
  // 三态联动：无产物（false）时路径列表隐藏并显示结案提示
  const hasBuildArtifacts = Form.useWatch('has_build_artifacts', form) as
    | HasBuildArtifactsState
    | undefined;
  // 表单脚手架统一走 useGatedFormPanel（code-review item 5407d2f4b09b）：
  // 原手写 savingRef 重入守卫（原 item 2a3a76864687 / e565d4593ac3）、
  // lastBackfillRef 序列化比较回填门控（原 item 90e26b043318）与「校验与
  // 持久化分离」的 handleSave（原 item 9423058588de）曾与六个已收敛面板
  // 双份维护，收敛进 hook；本面板保留字段映射（buildVerifyFormValues）与
  // 保存载荷组装（artifactEditable 条件键 + 三态映射，见 buildPayload）。
  const { saving, initialValues, handleSave } = useGatedFormPanel({
    form,
    buildValues: () => buildVerifyFormValues(config),
    backfillDeps: [config.verify, config.worktree],
    onSave,
    buildPayload: (values): Partial<ConfigData> => {
      const payload: Partial<ConfigData> = {
        verify: {
          static_scope: values.static_scope,
          deps_mode: values.deps_mode,
          serving_reclaim: { enabled: values.serving_reclaim_enabled },
        },
      };
      // 产物路径仅项目级可写（用户级作用域下该卡片只读，不提交该键）
      if (artifactEditable) {
        // 校验器已拒绝空路径（artifactPathRule 的「路径不能为空」），故此处
        // 无需 filter 剔除空行——旧 filter 恒不生效（code-review item
        // 721019da2aa9）。保留 trim 归一（前后空白不影响规则判定）。
        payload.worktree = {
          build_artifact_paths: (values.build_artifact_paths || []).map(
            (row: { path?: string }) => (row?.path || '').trim(),
          ),
        };
        // 三态 → 配置值（code-review item 22ec00069cd7）：'unset' 表示撤销裁决，
        // 若省略该键，后端 _merge_config 会保留旧布尔值，保存+刷新后单选框弹回
        // 有/无产物、用户无法真正回到未配置态。null = 显式清除该键后由后端按未
        // 裁决处理（未被配置时读取为 undefined）。
        if (values.has_build_artifacts === 'true') {
          payload.worktree.has_build_artifacts = true;
        } else if (values.has_build_artifacts === 'false') {
          payload.worktree.has_build_artifacts = false;
        } else {
          // unset：显式清除（null 语义由 write 路径处理为移除该键）。
          // ConfigData['worktree'].has_build_artifacts 已声明 boolean | null
          // （code-review item b7d40351517d）：直接赋 null，「有意写 null」
          // 由类型系统表达，不再用断言掩盖（断言会静默挫败未来收紧）。
          payload.worktree.has_build_artifacts = null;
        }
      }
      return payload;
    },
  });

  // 「无派生物」时清空路径 List 的 store 值（code-review item aceafc981274）：
  // 三态切到 false 时整个 Form.List（name='build_artifact_paths'）卸载，
  // rc-field-form 默认保留卸载项值且 validateFields 只校验在场字段——此前
  // 输入的任意行（含 artifactPathRule 校验失败行，如 dist 缺尾斜杠）残留在
  // form store 被 handleSave 原样提交。切到「无派生物」即显式清值，保证
  // 提交口径与所见一致；再切回「有派生物」时从空列表开始，不受残留行污染。
  useEffect(() => {
    if (hasBuildArtifacts === 'false') {
      form.setFieldValue('build_artifact_paths', []);
    }
  }, [hasBuildArtifacts, form]);

  const artifactsState = hasBuildArtifacts ?? toFormState(config.worktree?.has_build_artifacts);
  const declaredNoArtifacts = artifactsState === 'false';

  return (
    <div>
      <h3>{intl.formatMessage({ id: 'settings.verify.title' })}</h3>
      <Text type="secondary">
        {intl.formatMessage({ id: 'settings.verify.desc' })}
      </Text>
      {/* 单一 Form 承载两张卡片：产物路径卡片的 Form.List 必须处于 Form 上下文内，
          否则 add/remove 会落到 rc-field-form 的默认空上下文（warning 桩），
          点击「添加产物路径」静默无反应。 */}
      <Form form={form} initialValues={initialValues} layout="vertical" onValuesChange={() => setDirty(true)}>
        <Card style={{ marginTop: 12 }}>
          <Form.Item
            name="static_scope"
            label={
              <>
                {intl.formatMessage({ id: 'settings.verify.staticScope.label' })}<span className="label-note">（verify.static_scope）</span>
              </>
            }
            rules={[{ required: true, message: intl.formatMessage({ id: 'settings.verify.staticScope.required' }) }]}
          >
            <Radio.Group>
              <div style={{ display: 'block', marginBottom: 16 }}>
                <Radio value="main">
                  <strong>main</strong> {intl.formatMessage({ id: 'settings.verify.staticScope.main' })}
                  <div>
                    <Text type="secondary">
                      {intl.formatMessage({ id: 'settings.verify.staticScope.mainDesc' })}
                    </Text>
                  </div>
                </Radio>
              </div>
              <div style={{ display: 'block' }}>
                <Radio value="worktree">
                  <strong>worktree</strong> {intl.formatMessage({ id: 'settings.verify.staticScope.worktree' })}
                  <div>
                    <Text type="secondary">
                      {intl.formatMessage({ id: 'settings.verify.staticScope.worktreeDesc' })}
                    </Text>
                  </div>
                </Radio>
              </div>
            </Radio.Group>
          </Form.Item>
          <Form.Item
            name="deps_mode"
            label={
              <>
                {intl.formatMessage({ id: 'settings.verify.depsMode.label' })}<span className="label-note">（verify.deps_mode）</span>
              </>
            }
            rules={[{ required: true, message: intl.formatMessage({ id: 'settings.verify.depsMode.required' }) }]}
            extra={intl.formatMessage({ id: 'settings.verify.depsMode.extra' })}
          >
            <Radio.Group>
              <div style={{ display: 'block', marginBottom: 16 }}>
                <Radio value="prefer-offline">
                  <strong>prefer-offline</strong> {intl.formatMessage({ id: 'settings.verify.depsMode.preferOffline' })}
                  <div>
                    <Text type="secondary">
                      {intl.formatMessage({ id: 'settings.verify.depsMode.preferOfflineDesc' })}
                    </Text>
                  </div>
                </Radio>
              </div>
              <div style={{ display: 'block' }}>
                <Radio value="hardlink">
                  <strong>hardlink</strong> {intl.formatMessage({ id: 'settings.verify.depsMode.hardlink' })}
                  <div>
                    <Text type="secondary">
                      {intl.formatMessage({ id: 'settings.verify.depsMode.hardlinkDesc' })}
                    </Text>
                  </div>
                </Radio>
              </div>
            </Radio.Group>
          </Form.Item>
          {/* 开关行与其它设置页一致：开关在前、名称紧随同行（.switch-inline-row），
              开关控件不带「开/关」文字（与其余开关统一） */}
          <div className="switch-inline-row">
            <Form.Item name="serving_reclaim_enabled" valuePropName="checked" noStyle>
              <Switch data-testid="serving-reclaim-switch" />
            </Form.Item>
            <span className="switch-inline-label">
              {intl.formatMessage({ id: 'settings.verify.servingReclaim.label' })}
              <span className="label-note">（verify.serving_reclaim.enabled）</span>
            </span>
          </div>
          <Text type="secondary">
            {intl.formatMessage({ id: 'settings.verify.servingReclaim.desc' })}
          </Text>
          {/* 收尾代码质量审查已迁至独立「质量」页签（add-quality-tab）：
              键路径 verify.impl_code_review 不变，仅换呈现位置 */}
        </Card>

        {/* 构建产物路径：标题与说明置于卡片外，与上方「验证契约」节同构 */}
        <h3 style={{ marginTop: 32 }}>{intl.formatMessage({ id: 'settings.verify.artifactPaths.title' })}</h3>
        <Text type="secondary">
          {intl.formatMessage({ id: 'settings.verify.artifactPaths.desc' })}
        </Text>
        <Card style={{ marginTop: 12 }} data-testid="artifact-paths-card">
          {artifactEditable ? (
            <>
              <Form.Item
                name="has_build_artifacts"
                label={
                  <>
                    {intl.formatMessage({ id: 'settings.verify.hasArtifacts.label' })}
                    <span className="label-note">（worktree.has_build_artifacts）</span>
                  </>
                }
                extra={buildArtifactsHint(hasBuildArtifacts)}
                data-testid="has-build-artifacts-form-item"
              >
                <Radio.Group data-testid="has-build-artifacts-radio">
                  <Radio value="unset">{intl.formatMessage({ id: 'settings.verify.hasArtifacts.unset' })}</Radio>
                  <Radio value="true">{intl.formatMessage({ id: 'settings.verify.hasArtifacts.true' })}</Radio>
                  <Radio value="false">{intl.formatMessage({ id: 'settings.verify.hasArtifacts.false' })}</Radio>
                </Radio.Group>
              </Form.Item>
              {declaredNoArtifacts ? (
                <Alert
                  type="success"
                  showIcon
                  message={intl.formatMessage({ id: 'settings.verify.noArtifacts.title' })}
                  description={intl.formatMessage({ id: 'settings.verify.noArtifacts.desc' })}
                  data-testid="artifact-paths-no-artifacts-alert"
                />
              ) : (
                <Form.List name="build_artifact_paths">
                  {(fields, { add, remove }) => (
                    // 组容器保留共享 id 供批量查询；行内 Input 的 testid 带行
                    // 索引（code-review item 2c30d035c56b）——旧实现各行复用
                    // 同一 testid，测试只能 getAllByTestId+index 整体寻址，
                    // 无法可靠定位/重排特定行。
                    <div data-testid="artifact-path-inputs">
                      {fields.map((field) => (
                        <Space key={field.key} align="baseline" style={{ display: 'flex', marginBottom: 8 }}>
                          <Form.Item
                            name={[field.name, 'path']}
                            rules={[{ validator: artifactPathRule }]}
                            style={{ marginBottom: 0, minWidth: 280 }}
                          >
                            <Input
                              placeholder={intl.formatMessage({ id: 'settings.verify.artifactPath.placeholder' })}
                              data-testid={`artifact-path-input-${field.name}`}
                            />
                          </Form.Item>
                          <Button
                            type="text"
                            danger
                            icon={<MinusCircleOutlined />}
                            aria-label={intl.formatMessage({ id: 'settings.verify.artifactPath.removeRow' })}
                            onClick={() => remove(field.name)}
                          />
                        </Space>
                      ))}
                      <Button
                        type="dashed"
                        icon={<PlusOutlined />}
                        onClick={() => add({ path: '' })}
                        data-testid="artifact-path-add"
                      >
                        {intl.formatMessage({ id: 'settings.verify.artifactPath.add' })}
                      </Button>
                    </div>
                  )}
                </Form.List>
              )}
            </>
          ) : (
            <>
              <Alert
                type="info"
                showIcon
                message={intl.formatMessage({ id: 'settings.verify.artifactPaths.readonlyHint' })}
                data-testid="artifact-paths-scope-hint"
              />
              <div style={{ marginTop: 12 }}>
                <Text>
                  {intl.formatMessage({ id: 'settings.verify.hasArtifacts.userScopeLabel' })}{' '}
                  {/* 后端 worktree_config_view 恒发该键、未裁决时取 None → JSON
                      `null`（**不是 undefined**）。旧实现只比 `=== undefined`，在
                      user-scope 只读分支下三支全假，该行渲染成空标签
                      （code-review item deed1f27d507）。以 null 为未裁决判据。 */}
                  {(config.worktree?.has_build_artifacts === null ||
                    config.worktree?.has_build_artifacts === undefined) && (
                    <Text type="warning">{intl.formatMessage({ id: 'settings.verify.hasArtifacts.unsetValue' })}</Text>
                  )}
                  {config.worktree?.has_build_artifacts === true && <Text>{intl.formatMessage({ id: 'settings.verify.hasArtifacts.true' })}</Text>}
                  {config.worktree?.has_build_artifacts === false && (
                    <Text>{intl.formatMessage({ id: 'settings.verify.hasArtifacts.falseValue' })}</Text>
                  )}
                </Text>
              </div>
              {buildUserScopeArtifactsSection(
                config.worktree?.build_artifact_paths,
                config.worktree?.has_build_artifacts,
              )}
            </>
          )}
        </Card>
      </Form>
      <div style={project ? SETTINGS_ACTIONS_ROW_STYLE : { textAlign: 'right', marginTop: 24 }}>
        {project && onConfigSynced && (
          <SyncFromUserButton project={project} page="verify" onSynced={onConfigSynced} />
        )}
        <Button type="primary" onClick={handleSave} loading={saving} disabled={saving} data-testid="verify-save">
          {intl.formatMessage({ id: 'settings.verify.save' })}
        </Button>
      </div>
    </div>
  );
}
