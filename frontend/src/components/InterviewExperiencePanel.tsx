/** 面经知识库（R-15）：真实面经的增删改查，可绑定岗位、沉淀真实问题清单。 */
import { DeleteOutlined, EditOutlined, MoreOutlined, PlusOutlined } from "@ant-design/icons";
import {
  App,
  Button,
  Card,
  DatePicker,
  Dropdown,
  Empty,
  Form,
  Input,
  List,
  Modal,
  Select,
  Space,
  Spin,
  Tag,
  Typography,
} from "antd";
import dayjs from "dayjs";
import type { Dayjs } from "dayjs";
import { useCallback, useEffect, useState } from "react";
import {
  createInterviewExperience,
  deleteInterviewExperience,
  listInterviewExperiences,
  updateInterviewExperience,
} from "../api/interviewExperiences";
import { EXPERIENCE_ROUND_TYPES, EXPERIENCE_SOURCES, EXPERIENCE_SOURCE_LABELS } from "../types";
import type { ExperienceSource, InterviewExperience, InterviewExperiencePayload } from "../types";
import { useRowActionMenu } from "./common/rowActionMenu";

interface Props {
  jobOptions: { value: number; label: string }[];
}

export default function InterviewExperiencePanel({ jobOptions }: Props) {
  const { message } = App.useApp();
  const [items, setItems] = useState<InterviewExperience[]>([]);
  const [loading, setLoading] = useState(true);
  const [keyword, setKeyword] = useState("");
  const [source, setSource] = useState<string | undefined>();
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<InterviewExperience | null>(null);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm<InterviewExperiencePayload>();
  const buildMenu = useRowActionMenu();

  const loadList = useCallback(async () => {
    setLoading(true);
    try {
      setItems(
        await listInterviewExperiences({
          keyword: keyword.trim(),
          source: source || undefined,
        }),
      );
    } catch (error) {
      message.error(error instanceof Error ? error.message : "读取面经失败");
    } finally {
      setLoading(false);
    }
  }, [keyword, source, message]);

  useEffect(() => {
    void loadList();
  }, [loadList]);

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    setModalOpen(true);
  };

  const openEdit = (experience: InterviewExperience) => {
    setEditing(experience);
    form.setFieldsValue({
      title: experience.title,
      company: experience.company,
      position: experience.position,
      job_id: experience.job_id ?? undefined,
      content: experience.content,
      questions: experience.questions,
      tags: experience.tags,
      source: experience.source as ExperienceSource,
      difficulty: experience.difficulty,
      round_type: experience.round_type,
      interview_date: experience.interview_date,
    });
    setModalOpen(true);
  };

  const save = async () => {
    const values = await form.validateFields();
    setSaving(true);
    try {
      if (editing) {
        await updateInterviewExperience(editing.id, values);
      } else {
        await createInterviewExperience(values);
      }
      message.success(editing ? "已更新面经" : "已新增面经");
      setModalOpen(false);
      await loadList();
    } catch (error) {
      message.error(error instanceof Error ? error.message : "保存面经失败");
    } finally {
      setSaving(false);
    }
  };

  const doRemove = async (experience: InterviewExperience) => {
    try {
      await deleteInterviewExperience(experience.id);
      message.success("已删除");
      await loadList();
    } catch (error) {
      message.error(error instanceof Error ? error.message : "删除失败");
    }
  };

  return (
    <Space direction="vertical" style={{ width: "100%" }} size="middle">
      <Card size="small" title="面经知识库">
        <Space wrap>
          <Input.Search
            allowClear
            placeholder="搜索标题 / 岗位 / 正文"
            style={{ width: 240 }}
            onSearch={(value) => setKeyword(value)}
          />
          <Select
            allowClear
            placeholder="来源筛选"
            style={{ minWidth: 140 }}
            value={source}
            onChange={setSource}
            options={EXPERIENCE_SOURCES.map((value) => ({
              value,
              label: EXPERIENCE_SOURCE_LABELS[value],
            }))}
          />
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
            新增面经
          </Button>
        </Space>
      </Card>

      {loading ? (
        <Spin />
      ) : items.length === 0 ? (
        <Empty description="还没有面经，把面试里被问到的问题记下来吧" />
      ) : (
        <List
          dataSource={items}
          renderItem={(item) => (
            <List.Item
              actions={[
                <Dropdown
                  key="more"
                  trigger={["click"]}
                  menu={{
                    items: buildMenu([
                      {
                        key: "edit",
                        label: "编辑",
                        icon: <EditOutlined />,
                        onClick: () => openEdit(item),
                      },
                      {
                        key: "delete",
                        label: "删除",
                        danger: true,
                        icon: <DeleteOutlined />,
                        confirm: "删除这条面经？删除后可在回收站里找回。",
                        onClick: () => void doRemove(item),
                      },
                    ]),
                  }}
                >
                  <Button
                    type="text"
                    size="small"
                    icon={<MoreOutlined />}
                    aria-label={`更多操作 ${item.title || item.company}`}
                  />
                </Dropdown>,
              ]}
            >
              <List.Item.Meta
                title={
                  <Space size={6} wrap>
                    <span>{item.title || "未命名面经"}</span>
                    <Tag color="geekblue">
                      {EXPERIENCE_SOURCE_LABELS[item.source as ExperienceSource] ?? item.source}
                    </Tag>
                    {item.round_type && <Tag>{item.round_type}</Tag>}
                    {item.interview_date && <Tag>{item.interview_date}</Tag>}
                  </Space>
                }
                description={
                  <Space direction="vertical" size={2} style={{ width: "100%" }}>
                    <Typography.Text type="secondary">
                      {item.company}
                      {item.position ? ` · ${item.position}` : ""}
                      {item.difficulty ? ` · ${item.difficulty}` : ""}
                    </Typography.Text>
                    {item.questions.length > 0 && (
                      <Typography.Text type="secondary">
                        真实问题 {item.questions.length} 个：{item.questions.slice(0, 3).join("；")}
                      </Typography.Text>
                    )}
                    {item.tags.length > 0 && (
                      <Space size={4} wrap>
                        {item.tags.map((tag) => (
                          <Tag key={tag}>{tag}</Tag>
                        ))}
                      </Space>
                    )}
                  </Space>
                }
              />
            </List.Item>
          )}
        />
      )}

      <Modal
        title={editing ? "编辑面经" : "新增面经"}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={() => void save()}
        confirmLoading={saving}
        okText="保存"
        cancelText="取消"
      >
        <Form form={form} layout="vertical" initialValues={{ source: "self" }}>
          <Form.Item label="标题" name="title">
            <Input maxLength={200} placeholder="例如：某司后端一面" />
          </Form.Item>
          <Space style={{ display: "flex" }} align="start">
            <Form.Item label="公司" name="company" style={{ flex: 1 }}>
              <Input maxLength={128} placeholder="公司名" />
            </Form.Item>
            <Form.Item label="岗位" name="position" style={{ flex: 1 }}>
              <Input maxLength={128} placeholder="岗位名" />
            </Form.Item>
          </Space>
          <Form.Item label="关联岗位（选填，删除岗位不影响面经）" name="job_id">
            <Select
              allowClear
              showSearch
              optionFilterProp="label"
              placeholder="绑定后自动回填公司/岗位快照"
              options={jobOptions}
            />
          </Form.Item>
          <Form.Item label="正文（面试过程、怎么答的）" name="content">
            <Input.TextArea
              autoSize={{ minRows: 3, maxRows: 8 }}
              placeholder="记录面试流程与心得"
            />
          </Form.Item>
          <Form.Item label="被问到的真实问题" name="questions" extra="逐条回车添加，会沉淀进知识库">
            <Select mode="tags" placeholder="输入后回车" open={false} suffixIcon={null} />
          </Form.Item>
          <Form.Item label="标签" name="tags">
            <Select mode="tags" placeholder="例如：后端、算法题" open={false} suffixIcon={null} />
          </Form.Item>
          <Space style={{ display: "flex" }} align="start">
            <Form.Item label="来源" name="source" style={{ flex: 1 }}>
              <Select
                options={EXPERIENCE_SOURCES.map((value) => ({
                  value,
                  label: EXPERIENCE_SOURCE_LABELS[value],
                }))}
              />
            </Form.Item>
            <Form.Item label="难度" name="difficulty" style={{ flex: 1 }}>
              <Input maxLength={16} placeholder="例如：中等" />
            </Form.Item>
          </Space>
          <Space style={{ display: "flex" }} align="start">
            <Form.Item label="轮次" name="round_type" style={{ flex: 1 }}>
              <Select
                allowClear
                placeholder="选择常见轮次"
                options={EXPERIENCE_ROUND_TYPES.map((value) => ({ value, label: value }))}
              />
            </Form.Item>
            <Form.Item
              label="面试日期"
              name="interview_date"
              style={{ flex: 1 }}
              getValueProps={(value: string) => ({ value: value ? dayjs(value) : null })}
              normalize={(value: Dayjs | null) => (value ? value.format("YYYY-MM-DD") : "")}
            >
              <DatePicker style={{ width: "100%" }} />
            </Form.Item>
          </Space>
        </Form>
      </Modal>
    </Space>
  );
}
