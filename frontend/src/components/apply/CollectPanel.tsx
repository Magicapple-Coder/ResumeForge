/**
 * 自动采集：设置关键词/城市/筛选条件后显式开始，并把无法映射的条件如实标为「未生效」。
 *
 * 为什么要把「未生效」单独拎出来：关键词 + 城市 + 翻页是站点一定能接受的，而薪资/经验/学历
 * 能不能落到查询参数取决于站点——若不明确提示，用户会以为筛选生效了，实际却把不符合条件的
 * 岗位也采了进来。后端把这些条件写进 `task.config["unmapped_conditions"]`，界面据此显示。
 */
import { PlayCircleOutlined, SaveOutlined } from "@ant-design/icons";
import {
  Alert,
  App,
  Button,
  Checkbox,
  Form,
  Input,
  InputNumber,
  Popconfirm,
  Select,
  Skeleton,
  Space,
  Tag,
  Typography,
} from "antd";
import { useEffect, useState } from "react";
import { createCollectTask, getCollectConfig, updateCollectConfig } from "../../api/apply";
import { useApi } from "../../hooks/useApi";
import { formatDateTime } from "../../utils/format";
import type { ApplyTask, ApplyTaskDetail, CollectConfig, CollectConfigOut } from "../../types";
import CollectResultPanel from "./CollectResultPanel";

interface Props {
  disabled: boolean;
  onStarted: (task: ApplyTask) => void;
  /** 最近一次采集批次：用来读取「未生效」条件。 */
  collectTask: ApplyTaskDetail | null;
}

/** 采集结果的类型标注（C7）：仅入库标注，不参与站点筛选与去重。 */
const JOB_TYPE_OPTIONS = [
  { value: "校招", label: "校招" },
  { value: "实习", label: "实习" },
  { value: "社招", label: "社招" },
];

function unmappedConditions(task: ApplyTaskDetail | null): string[] {
  const raw = task?.config?.unmapped_conditions;
  if (!Array.isArray(raw)) return [];
  return raw.filter((value): value is string => typeof value === "string" && value.length > 0);
}

// ===== 历史条件（localStorage 快照）=====

const CONFIG_HISTORY_KEY = "rf.collect.configHistory";
const CONFIG_HISTORY_LIMIT = 20;

/** 一份采集条件的完整快照：保存时间与全部字段。 */
interface CollectConfigSnapshot {
  savedAt: string;
  config: CollectConfig;
}

/** 读取历史条件；缺省/损坏时回退空数组。 */
function readConfigHistory(): CollectConfigSnapshot[] {
  try {
    const raw = localStorage.getItem(CONFIG_HISTORY_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (entry): entry is CollectConfigSnapshot =>
        entry && typeof entry === "object" && "savedAt" in entry && "config" in entry,
    );
  } catch {
    return [];
  }
}

/** 把条件快照写成 localStorage（覆盖写）。 */
function writeConfigHistory(list: CollectConfigSnapshot[]): void {
  localStorage.setItem(CONFIG_HISTORY_KEY, JSON.stringify(list));
}

/** 历史下拉的展示文案：保存时间 + 关键词/城市/类型摘要。 */
function historySummaryLabel(snapshot: CollectConfigSnapshot): string {
  const { config, savedAt } = snapshot;
  const keywords = (config.keywords ?? []).slice(0, 3).join("、");
  const keywordText = keywords || "无关键词";
  const cityText = config.city?.trim() || "无城市";
  const typeText = config.job_type?.trim() || "不限";
  return `${formatDateTime(savedAt)} · ${keywordText} / ${cityText} / ${typeText}`;
}

function stringList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string" && item.length > 0)
    : [];
}

interface FilterSummary {
  /** 按条件明确筛掉的条数。 */
  filtered: number;
  /** 这次实际启用的本地筛选条件。 */
  applied: string[];
  /** 有岗位缺字段、没能判断的条件（那些岗位已保留）。 */
  undecided: string[];
  undecidedCount: number;
  /** 用户填了但没能识别的条件——**必须明说**，否则等于静默失效。 */
  unapplied: string[];
}

/** 从批次 config 里读出本地筛选的账目（后端写在 task.config，不新增数据库列）。 */
function filterSummary(task: ApplyTaskDetail | null): FilterSummary | null {
  const config = task?.config;
  if (!config) return null;
  const applied = stringList(config.filter_applied);
  if (applied.length === 0) return null;
  return {
    filtered: Number(config.filtered_out) || 0,
    applied,
    undecided: stringList(config.filter_undecided),
    undecidedCount: Number(config.filter_undecided_count) || 0,
    unapplied: stringList(config.filter_unapplied),
  };
}

export default function CollectPanel({ disabled, onStarted, collectTask }: Props) {
  const { message } = App.useApp();
  const [form] = Form.useForm<CollectConfig>();
  const { data, loading, error } = useApi<CollectConfigOut>(getCollectConfig, []);
  const [saving, setSaving] = useState(false);
  const [starting, setStarting] = useState(false);
  // 是否保存本次抓到的站点原文。默认不勾选——往磁盘写站点数据必须由用户显式开启。
  const [saveSamples, setSaveSamples] = useState(false);
  // 历史条件快照（localStorage 读取，最新在前）。
  const [history, setHistory] = useState<CollectConfigSnapshot[]>(() => readConfigHistory());
  const [historyValue, setHistoryValue] = useState<string | undefined>(undefined);

  useEffect(() => {
    if (data) form.setFieldsValue(data);
  }, [data, form]);

  /** 把当前表单整份快照存入历史（去重 + 上限 20）。 */
  const pushHistory = (config: CollectConfig) => {
    const savedAt = new Date().toISOString();
    setHistory((prev) => {
      const next = [
        { savedAt, config },
        ...prev.filter((entry) => JSON.stringify(entry.config) !== JSON.stringify(config)),
      ].slice(0, CONFIG_HISTORY_LIMIT);
      writeConfigHistory(next);
      return next;
    });
    setHistoryValue(savedAt);
  };

  const save = async () => {
    const values = await form.validateFields();
    setSaving(true);
    try {
      await updateCollectConfig(values);
      pushHistory(values as CollectConfig);
      message.success("采集条件已保存");
    } catch (err) {
      message.error(err instanceof Error ? err.message : "保存采集条件失败");
    } finally {
      setSaving(false);
    }
  };

  /** 选中某条历史 → 回填表单。 */
  const applyHistory = (savedAt: string) => {
    const snapshot = history.find((entry) => entry.savedAt === savedAt);
    if (snapshot) {
      form.setFieldsValue(snapshot.config);
      setHistoryValue(savedAt);
    }
  };

  const clearHistory = () => {
    setHistory([]);
    setHistoryValue(undefined);
    localStorage.removeItem(CONFIG_HISTORY_KEY);
  };

  const start = async () => {
    // 开始前先保存，避免"改了条件但用的是旧值"这种静默落差。
    const values = await form.validateFields();
    if (!values.keywords?.length && !values.city?.trim()) {
      message.warning("请至少填写一个关键词或城市");
      return;
    }
    setStarting(true);
    try {
      await updateCollectConfig(values);
      const task = await createCollectTask(saveSamples);
      message.success(
        saveSamples
          ? "已开始采集，进度见下方；本次会保存站点原文到 backend/data/captures/，完成时也会提示具体目录"
          : "已开始采集，进度见下方",
      );
      onStarted(task);
    } catch (err) {
      message.error(err instanceof Error ? err.message : "开始采集失败");
    } finally {
      setStarting(false);
    }
  };

  if (loading && !data) return <Skeleton active paragraph={{ rows: 6 }} />;
  if (error && !data) return <Alert type="error" showIcon message={error} />;

  const unmapped = unmappedConditions(collectTask);
  const filtered = filterSummary(collectTask);

  return (
    <div className="apply-collect-panel">
      {/* 用户反馈过"采完了只显示成功，不知道下一步做什么"。采集只是第一步、而且**不会**直接
          进岗位广场，所以这里把后面两步明确写出来，并指出每一步在哪个页签。 */}
      <Alert
        className="apply-collect-flow"
        type="info"
        showIcon
        message="采集之后还有两步才轮到投递"
        description={
          <ol style={{ margin: 0, paddingLeft: 18 }}>
            <li>
              采集把岗位放进下面的<span className="apply-collect-flow-em">「本次采集结果」</span>，
              <Typography.Text strong>不会</Typography.Text>直接进岗位广场——采到的噪声由你筛掉。
            </li>
            <li>在结果里勾选要留下的岗位，点「导入选中的岗位」。</li>
            <li>
              到<span className="apply-collect-flow-em">「投递队列」</span>
              把它们排进队列并显式开始投递， 结果在
              <span className="apply-collect-flow-em">「投递记录」</span>里看。
            </li>
          </ol>
        }
      />

      <Space size={8} wrap style={{ marginBottom: 12 }}>
        <Select
          aria-label="历史条件"
          placeholder="历史条件"
          allowClear
          style={{ minWidth: 320 }}
          value={historyValue}
          onChange={(value) => {
            if (value) applyHistory(value as string);
            else setHistoryValue(undefined);
          }}
          options={history.map((entry) => ({
            value: entry.savedAt,
            label: historySummaryLabel(entry),
          }))}
        />
        <Popconfirm
          title="清空历史条件"
          description="会删除全部已保存的采集条件快照，且不可恢复。"
          okText="清空"
          cancelText="取消"
          okButtonProps={{ danger: true }}
          onConfirm={clearHistory}
        >
          <Button size="small" type="link">
            清空历史
          </Button>
        </Popconfirm>
      </Space>

      <Form form={form} layout="vertical">
        <Form.Item name="keywords" label="关键词" extra="最多 10 个；与城市至少要填一个。">
          <Select mode="tags" placeholder="例如：后端开发、算法工程师" open={false} />
        </Form.Item>
        <Space size={16} wrap>
          <Form.Item name="city" label="城市">
            <Input placeholder="例如：北京" style={{ width: 180 }} />
          </Form.Item>
          <Form.Item name="per_task_limit" label="单批上限">
            <InputNumber min={1} max={200} style={{ width: 140 }} />
          </Form.Item>
          <Form.Item
            name="job_type"
            label={
              <Space size={4}>
                岗位类型
                <Tag color="blue">仅标注</Tag>
              </Space>
            }
            extra="只用于给采集结果标注类型，不参与站点筛选，也不影响去重"
          >
            <Select
              allowClear
              placeholder="不限"
              style={{ width: 160 }}
              options={JOB_TYPE_OPTIONS}
            />
          </Form.Item>
        </Space>

        <Space size={16} wrap>
          <Form.Item
            name="salary_min"
            label={
              <Space size={4}>
                最低薪资（K）
                <Tag color="blue">采集后筛选</Tag>
              </Space>
            }
            extra="按岗位薪资上限判断；岗位没给可判断的薪资时会保留，并标记为未能判断"
          >
            <InputNumber min={0} max={1000} style={{ width: 140 }} />
          </Form.Item>
          <Form.Item
            name="experience"
            label={
              <Space size={4}>
                经验要求
                <Tag color="blue">采集后筛选</Tag>
              </Space>
            }
            extra="填你自己的经验；与它没有重叠的岗位会被筛掉"
          >
            <Input placeholder="例如：3-5 年" style={{ width: 180 }} />
          </Form.Item>
          <Form.Item
            name="education"
            label={
              <Space size={4}>
                学历要求
                <Tag color="blue">采集后筛选</Tag>
              </Space>
            }
            extra="填你自己的学历；要求高于它的岗位会被筛掉"
          >
            <Input placeholder="例如：本科" style={{ width: 180 }} />
          </Form.Item>
        </Space>

        <Space size={16} wrap>
          <Form.Item name="interval_seconds" label="岗位间隔（秒）">
            <InputNumber min={1} max={600} style={{ width: 140 }} />
          </Form.Item>
          <Form.Item name="interval_jitter_seconds" label="随机抖动（秒）">
            <InputNumber min={0} max={300} style={{ width: 140 }} />
          </Form.Item>
        </Space>

        {/* 保存站点原文：这是排查解析问题 / 做真实样例回归的通道，属于支持路径而非日常流程，
            所以放在「开始采集」旁边、默认不勾，并把"存什么、存哪、会不会外传"一次说清——
            用户不知道它会往磁盘写东西就会用错。 */}
        <Form.Item style={{ marginBottom: 12 }}>
          <Checkbox
            checked={saveSamples}
            onChange={(event) => setSaveSamples(event.target.checked)}
            aria-label="保存本次抓到的站点原文（用于排查解析问题）"
          >
            保存本次抓到的站点原文（用于排查解析问题）
          </Checkbox>
          <Typography.Text type="secondary" style={{ display: "block", marginTop: 4 }}>
            会保存搜索与详情两个接口的响应原文；只存到本机
            backend/data/captures/，不进仓库、不进备份。
          </Typography.Text>
        </Form.Item>

        <Space>
          <Button icon={<SaveOutlined />} loading={saving} onClick={() => void save()}>
            保存条件
          </Button>
          <Button
            type="primary"
            icon={<PlayCircleOutlined />}
            loading={starting}
            disabled={disabled}
            onClick={() => void start()}
          >
            开始采集
          </Button>
        </Space>
      </Form>

      {unmapped.length > 0 && (
        <Alert
          className="apply-collect-unmapped"
          type="warning"
          showIcon
          message="以下条件未生效"
          description={
            <Typography.Paragraph style={{ marginBottom: 0 }}>
              这批采集里，{unmapped.join("、")} 无法映射到该站点的查询参数，因此
              <Typography.Text strong>没有</Typography.Text>
              按它们筛选；结果里可能包含不满足这些条件的岗位。关键词、城市与翻页正常生效。
            </Typography.Paragraph>
          }
        />
      )}

      {/* 本地筛选的账目：筛掉几条、有几条因为岗位没写字段而没能判断、以及自己的条件有没有
          被识别。三者都不说，用户就不知道"少了几个"是筛掉的还是没采到。 */}
      {filtered && (
        <Alert
          className="apply-collect-filtered"
          type="success"
          showIcon
          message={`已按${filtered.applied.join(" / ")}在采集后筛选`}
          description={
            <Space direction="vertical" size={2}>
              <Typography.Text>
                {filtered.filtered > 0
                  ? `本次筛掉 ${filtered.filtered} 个不符合条件的岗位。`
                  : "本次没有岗位被筛掉。"}
              </Typography.Text>
              {filtered.undecidedCount > 0 && (
                <Typography.Text type="secondary">
                  其中 {filtered.undecidedCount} 个岗位没有写
                  {filtered.undecided.join("、")}，无法判断，已保留在结果里（宁可多给你看，
                  也不误删）。
                </Typography.Text>
              )}
              {filtered.unapplied.length > 0 && (
                <Typography.Text type="danger">
                  注意：{filtered.unapplied.join("、")}
                  这条条件没能识别，本次没有生效——换个写法试试（例如「本科」「3-5 年」）。
                </Typography.Text>
              )}
            </Space>
          }
        />
      )}

      {/* 采集结果只陈列、不入库：勾选后才进岗位广场。 */}
      <CollectResultPanel
        taskId={collectTask?.id ?? null}
        disabled={disabled}
        refreshKey={`${collectTask?.status ?? ""}-${collectTask?.processed ?? 0}-${collectTask?.finished_at ?? ""}`}
      />
    </div>
  );
}
