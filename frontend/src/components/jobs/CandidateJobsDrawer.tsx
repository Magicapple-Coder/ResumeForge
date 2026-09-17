/**
 * 备选岗位抽屉：先收下还没核对的招聘信息，确认后再导入正式岗位。
 *
 * 放在岗位广场页的抽屉里而不是独立页面：它是"导入前的中转站"，用的时候就该在
 * 岗位列表旁边。
 */
import { DeleteOutlined, EditOutlined, ImportOutlined, PlusOutlined } from "@ant-design/icons";
import {
  App,
  Button,
  Drawer,
  Empty,
  Form,
  Image,
  Input,
  Modal,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
  Upload,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { useCallback, useEffect, useState } from "react";
import {
  createCandidateJob,
  deleteCandidateJob,
  listCandidateJobs,
  updateCandidateJob,
} from "../../api/candidateJob";
import { readAsDataUrl } from "../../utils/attachments";
import { formatDateTime } from "../../utils/format";
import FileDropZone from "../common/FileDropZone";
import { RowActions } from "../common/RowActions";
import type { CandidateJob, CandidateJobPayload } from "../../types";

const MAX_CANDIDATE_IMAGES = 4;
const MAX_IMAGE_BYTES = 2 * 1024 * 1024;

interface Props {
  open: boolean;
  onClose: () => void;
  /** 交给父组件打开正式的岗位表单（预填这份招聘原文），保存后回报新岗位 id。 */
  onImport: (candidate: CandidateJob) => void;
  /** 导入成功的标记：父组件拿到新岗位 id 后传进来，抽屉据此刷新并标记。 */
  importedCandidateId?: number | null;
}

interface FormState {
  title: string;
  company: string;
  rawText: string;
  note: string;
  images: string[];
}

const EMPTY_FORM: FormState = { title: "", company: "", rawText: "", note: "", images: [] };

export default function CandidateJobsDrawer({
  open,
  onClose,
  onImport,
  importedCandidateId = null,
}: Props) {
  const { message } = App.useApp();
  const [items, setItems] = useState<CandidateJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<CandidateJob | null>(null);
  const [formState, setFormState] = useState<FormState>(EMPTY_FORM);
  const [submitting, setSubmitting] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setItems(await listCandidateJobs());
    } catch (error) {
      message.error(error instanceof Error ? error.message : "加载备选岗位失败");
    } finally {
      setLoading(false);
    }
  }, [message]);

  useEffect(() => {
    if (open) void load();
  }, [load, open]);

  // 父组件完成导入后（拿到正式岗位 id）刷新列表，状态标记随之更新。
  useEffect(() => {
    if (open && importedCandidateId !== null) void load();
  }, [importedCandidateId, load, open]);

  const openCreate = () => {
    setEditing(null);
    setFormState(EMPTY_FORM);
    setFormOpen(true);
  };

  const openEdit = (candidate: CandidateJob) => {
    setEditing(candidate);
    setFormState({
      title: candidate.title,
      company: candidate.company,
      rawText: candidate.raw_text,
      note: candidate.note,
      images: candidate.images ?? [],
    });
    setFormOpen(true);
  };

  const addImages = async (file: File) => {
    if (file.size > MAX_IMAGE_BYTES) {
      message.error("单张截图不能超过 2 MB");
      return;
    }
    if (formState.images.length >= MAX_CANDIDATE_IMAGES) {
      message.warning(`最多添加 ${MAX_CANDIDATE_IMAGES} 张截图`);
      return;
    }
    try {
      const dataUrl = await readAsDataUrl(file);
      setFormState((current) => ({ ...current, images: [...current.images, dataUrl] }));
    } catch {
      message.error("读取截图失败，请重试");
    }
  };

  const submit = async () => {
    if (submitting) return;
    const payload: CandidateJobPayload = {
      title: formState.title.trim(),
      company: formState.company.trim(),
      raw_text: formState.rawText,
      note: formState.note,
      images: formState.images,
      source: editing ? undefined : formState.images.length > 0 ? "招聘截图" : "粘贴文本",
    };
    if (!payload.title && !payload.raw_text?.trim() && formState.images.length === 0) {
      message.warning("请粘贴招聘信息、上传截图，或至少填写岗位名称");
      return;
    }
    setSubmitting(true);
    try {
      if (editing) {
        // 更新接口不接受 source：来源在创建时定下，编辑不改写它。
        await updateCandidateJob(editing.id, {
          title: payload.title,
          company: payload.company,
          raw_text: payload.raw_text,
          note: payload.note,
          images: payload.images,
        });
        message.success("备选岗位已更新");
      } else {
        await createCandidateJob(payload);
        message.success("已放进备选岗位");
      }
      setFormOpen(false);
      await load();
    } catch (error) {
      message.error(error instanceof Error ? error.message : "保存失败");
    } finally {
      setSubmitting(false);
    }
  };

  const remove = async (candidate: CandidateJob) => {
    try {
      await deleteCandidateJob(candidate.id);
      message.success("已删除");
      await load();
    } catch (error) {
      message.error(error instanceof Error ? error.message : "删除失败");
    }
  };

  const columns: ColumnsType<CandidateJob> = [
    {
      title: "岗位 / 公司",
      key: "title",
      render: (_, candidate) => (
        <Space direction="vertical" size={0}>
          <Typography.Text strong>{candidate.title || "（未识别岗位名）"}</Typography.Text>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {candidate.company || "未识别公司"}
            {candidate.raw_text ? ` · 原文 ${candidate.raw_text.length} 字` : ""}
          </Typography.Text>
        </Space>
      ),
    },
    {
      title: "来源",
      dataIndex: "source",
      width: 110,
      render: (value: string) => <Tag>{value}</Tag>,
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 110,
      render: (value: string, candidate) =>
        value === "imported" ? (
          <Tag color="green">已导入 #{candidate.imported_job_id ?? ""}</Tag>
        ) : (
          <Tag color="orange">待处理</Tag>
        ),
    },
    {
      title: "截图",
      dataIndex: "images",
      width: 80,
      render: (images: string[]) =>
        images.length > 0 ? <Tag color="blue">{images.length} 张</Tag> : "-",
    },
    {
      title: "更新时间",
      dataIndex: "updated_at",
      width: 170,
      render: (value: string) => formatDateTime(value),
    },
    {
      title: "操作",
      key: "actions",
      width: 190,
      render: (_, candidate) => (
        <RowActions
          primary={
            candidate.status === "pending"
              ? [{ key: "import", label: "导入到岗位", onClick: () => onImport(candidate) }]
              : []
          }
          more={[
            {
              key: "edit",
              label: "编辑",
              icon: <EditOutlined />,
              onClick: () => openEdit(candidate),
            },
            {
              key: "delete",
              label: "删除",
              danger: true,
              icon: <DeleteOutlined />,
              confirm: "删除这条备选岗位？",
              onClick: () => void remove(candidate),
            },
          ]}
        />
      ),
    },
  ];

  return (
    <Drawer
      title="备选岗位"
      width="min(880px, 100vw)"
      open={open}
      onClose={onClose}
      extra={
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
          添加备选
        </Button>
      }
    >
      <Typography.Paragraph type="secondary">
        这里放还没核对的招聘信息（粘贴的文本或截图）。点「导入到岗位」会打开正式岗位表单并预填原文，
        保存后这条备选就标记为已导入；也可以让求职助手代你导入。
      </Typography.Paragraph>
      {loading ? (
        <Spin />
      ) : items.length === 0 ? (
        <Empty description="还没有备选岗位。看到感兴趣但来不及整理的招聘信息，先放到这里。" />
      ) : (
        <Table
          rowKey="id"
          columns={columns}
          dataSource={items}
          pagination={false}
          size="small"
          scroll={{ x: 760 }}
        />
      )}

      <Modal
        title={editing ? "编辑备选岗位" : "添加备选岗位"}
        open={formOpen}
        width={720}
        confirmLoading={submitting}
        onCancel={() => {
          if (!submitting) setFormOpen(false);
        }}
        onOk={() => void submit()}
      >
        <Form layout="vertical">
          <Form.Item label="招聘信息来源">
            <Typography.Text type="secondary">
              由系统按你添加的内容自动标注（{formState.images.length > 0 ? "招聘截图" : "粘贴文本"}
              ）
            </Typography.Text>
          </Form.Item>
          <Form.Item label="岗位名称（可留空，导入时再补）">
            <Input
              value={formState.title}
              maxLength={128}
              placeholder="如：后端开发工程师"
              onChange={(event) => setFormState((c) => ({ ...c, title: event.target.value }))}
            />
          </Form.Item>
          <Form.Item label="公司名称">
            <Input
              value={formState.company}
              maxLength={128}
              placeholder="如：字节跳动"
              onChange={(event) => setFormState((c) => ({ ...c, company: event.target.value }))}
            />
          </Form.Item>
          <Form.Item label="招聘原文">
            <Input.TextArea
              value={formState.rawText}
              autoSize={{ minRows: 6, maxRows: 14 }}
              placeholder="把招聘信息原样粘贴进来，导入时会用它预填 JD"
              onChange={(event) => setFormState((c) => ({ ...c, rawText: event.target.value }))}
            />
          </Form.Item>
          <Form.Item label={`招聘截图（最多 ${MAX_CANDIDATE_IMAGES} 张，单张不超过 2 MB）`}>
            <Space direction="vertical" style={{ width: "100%" }}>
              <FileDropZone
                accept="image/jpeg,image/png,image/webp"
                disabled={formState.images.length >= MAX_CANDIDATE_IMAGES}
                hint="松开即可添加招聘截图"
                onFiles={(dropped) => dropped.forEach((file) => void addImages(file))}
                onRejected={() => message.error("招聘截图只支持 JPG、PNG 或 WebP")}
              >
                <Space wrap>
                  <Upload
                    accept="image/jpeg,image/png,image/webp"
                    showUploadList={false}
                    beforeUpload={(file) => {
                      void addImages(file as File);
                      return Upload.LIST_IGNORE;
                    }}
                  >
                    <Button icon={<PlusOutlined />}>添加截图</Button>
                  </Upload>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    也可以直接拖进来
                  </Typography.Text>
                </Space>
              </FileDropZone>
              {formState.images.length > 0 && (
                <Space wrap>
                  {formState.images.map((source, index) => (
                    <div key={`${index}-${source.slice(-16)}`} className="job-note-image-item">
                      <Image src={source} alt={`招聘截图 ${index + 1}`} width={96} />
                      <Button
                        type="text"
                        size="small"
                        danger
                        aria-label={`移除截图 ${index + 1}`}
                        icon={<DeleteOutlined />}
                        onClick={() =>
                          setFormState((c) => ({
                            ...c,
                            images: c.images.filter((_, i) => i !== index),
                          }))
                        }
                      />
                    </div>
                  ))}
                </Space>
              )}
            </Space>
          </Form.Item>
          <Form.Item label="备注" style={{ marginBottom: 0 }}>
            <Input.TextArea
              value={formState.note}
              autoSize={{ minRows: 2, maxRows: 4 }}
              placeholder="为什么先留着它、准备什么时候投（选填）"
              onChange={(event) => setFormState((c) => ({ ...c, note: event.target.value }))}
            />
          </Form.Item>
        </Form>
      </Modal>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        <ImportOutlined /> 已导入的备选会保留在列表里，方便回看它变成了哪个岗位。
      </Typography.Text>
    </Drawer>
  );
}
