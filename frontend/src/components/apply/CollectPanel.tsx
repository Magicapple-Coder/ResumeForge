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
  Form,
  Input,
  InputNumber,
  Select,
  Skeleton,
  Space,
  Tag,
  Typography,
} from "antd";
import { useEffect, useState } from "react";
import { createCollectTask, getCollectConfig, updateCollectConfig } from "../../api/apply";
import { useApi } from "../../hooks/useApi";
import type { ApplyTask, ApplyTaskDetail, CollectConfig, CollectConfigOut } from "../../types";

interface Props {
  disabled: boolean;
  onStarted: (task: ApplyTask) => void;
  /** 最近一次采集批次：用来读取「未生效」条件。 */
  collectTask: ApplyTaskDetail | null;
}

function unmappedConditions(task: ApplyTaskDetail | null): string[] {
  const raw = task?.config?.unmapped_conditions;
  if (!Array.isArray(raw)) return [];
  return raw.filter((value): value is string => typeof value === "string" && value.length > 0);
}

export default function CollectPanel({ disabled, onStarted, collectTask }: Props) {
  const { message } = App.useApp();
  const [form] = Form.useForm<CollectConfig>();
  const { data, loading, error } = useApi<CollectConfigOut>(getCollectConfig, []);
  const [saving, setSaving] = useState(false);
  const [starting, setStarting] = useState(false);

  useEffect(() => {
    if (data) form.setFieldsValue(data);
  }, [data, form]);

  const save = async () => {
    const values = await form.validateFields();
    setSaving(true);
    try {
      await updateCollectConfig(values);
      message.success("采集条件已保存");
    } catch (err) {
      message.error(err instanceof Error ? err.message : "保存采集条件失败");
    } finally {
      setSaving(false);
    }
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
      const task = await createCollectTask();
      message.success("已开始采集，进度见下方");
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

  return (
    <div className="apply-collect-panel">
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
        </Space>

        <Space size={16} wrap>
          <Form.Item
            name="salary_min"
            label={
              <Space size={4}>
                最低薪资（K）
                <Tag color="orange">可能未生效</Tag>
              </Space>
            }
          >
            <InputNumber min={0} max={1000} style={{ width: 140 }} />
          </Form.Item>
          <Form.Item
            name="experience"
            label={
              <Space size={4}>
                经验要求
                <Tag color="orange">可能未生效</Tag>
              </Space>
            }
          >
            <Input placeholder="例如：3-5 年" style={{ width: 180 }} />
          </Form.Item>
          <Form.Item
            name="education"
            label={
              <Space size={4}>
                学历要求
                <Tag color="orange">可能未生效</Tag>
              </Space>
            }
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
    </div>
  );
}
