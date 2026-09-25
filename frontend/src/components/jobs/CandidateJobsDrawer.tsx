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
  Card,
  Checkbox,
  Drawer,
  Empty,
  Form,
  Image,
  Input,
  Modal,
  Space,
  Spin,
  Tag,
  Typography,
  Upload,
} from "antd";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  createCandidateJob,
  deleteCandidateJob,
  getCandidateJob,
  importCandidateJobs,
  listCandidateJobs,
  updateCandidateJob,
} from "../../api/candidateJob";
import { readAsDataUrl } from "../../utils/attachments";
import { formatDateTime } from "../../utils/format";
import FileDropZone from "../common/FileDropZone";
import { RowActions } from "../common/RowActions";
import CandidateJobDetailModal from "./CandidateJobDetailModal";
import type {
  CandidateJob,
  CandidateJobDetail,
  CandidateJobPayload,
  JobPayload,
} from "../../types";

const MAX_CANDIDATE_IMAGES = 4;
const MAX_IMAGE_BYTES = 2 * 1024 * 1024;

/**
 * 候选 → 正式岗位表单的预填值。
 *
 * **为什么需要它**：候选有两条来路，它们的字段分布正好相反——手工粘贴的只有 ``raw_text``
 * （采不到的结构化字段一个没有），而采集来的恰恰相反，内容全在 ``description`` /
 * ``requirements`` / ``location`` 这些列里，``raw_text`` 是空的。
 *
 * 之前「导入到岗位」只预填 ``raw_text``，于是**采集来的候选打开的是一个全空的表单**：
 * 用户看到的就是"导入进来什么都没有"，而数据其实一直都在候选里。
 *
 * 空值一律不带上（``JobFormModal`` 那边也是这么处理的）：把空串显式写进表单会让
 * "这个字段是空的"与"这个字段没被填过"分不开。
 */
export function candidateToJobPayload(candidate: CandidateJobDetail): Partial<JobPayload> {
  const payload: Partial<JobPayload> = {
    title: candidate.title,
    company: candidate.company,
    location: candidate.location,
    salary: candidate.salary,
    job_type: candidate.job_type,
    source_url: candidate.source_url,
    description: candidate.description,
    requirements: candidate.requirements,
    additional_info: candidate.additional_info,
    note: candidate.note,
  };
  return Object.fromEntries(
    Object.entries(payload).filter(([, value]) => value !== "" && value != null),
  ) as Partial<JobPayload>;
}

interface Props {
  open: boolean;
  onClose: () => void;
  /**
   * 交给父组件打开正式的岗位表单（预填这条候选的字段），保存后回报新岗位 id。
   *
   * **传的是取过详情的那一份**（``CandidateJobDetail``）：列表响应不带 JD，拿列表对象去预填
   * 会得到一个没有职位描述的表单——那正是"导入进来什么都没有"的来源。
   */
  onImport: (candidate: CandidateJobDetail) => void;
  /** 导入成功的标记：父组件拿到新岗位 id 后传进来，抽屉据此刷新并标记。 */
  importedCandidateId?: number | null;
  /** 从采集记录进入时，只显示选中的一条或多条官网采集批次。 */
  collectTaskIds?: number[];
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
  collectTaskIds = [],
}: Props) {
  const { message } = App.useApp();
  const [items, setItems] = useState<CandidateJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<CandidateJob | null>(null);
  const [formState, setFormState] = useState<FormState>(EMPTY_FORM);
  const [submitting, setSubmitting] = useState(false);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [detailCandidate, setDetailCandidate] = useState<CandidateJobDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [batchAction, setBatchAction] = useState<"import" | "delete" | null>(null);
  // 搜索词与"已提交的搜索词"分开：输入时不打接口，静置 300ms 才带上关键词重新拉取。
  // 备选岗位可能几百条，每敲一个字就请求一次既慢又没意义。
  const [keyword, setKeyword] = useState("");
  const [committedKeyword, setCommittedKeyword] = useState("");

  const taskFilterKey = collectTaskIds.join(",");
  const selectedPendingIds = useMemo(
    () =>
      items
        .filter((item) => selectedIds.includes(item.id) && item.status === "pending")
        .map((item) => item.id),
    [items, selectedIds],
  );

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setItems(
        await listCandidateJobs({
          ...(taskFilterKey
            ? { collectTaskIds: taskFilterKey.split(",").map((value) => Number(value)) }
            : {}),
          ...(committedKeyword ? { keyword: committedKeyword } : {}),
        }),
      );
    } catch (error) {
      message.error(error instanceof Error ? error.message : "加载备选岗位失败");
    } finally {
      setLoading(false);
    }
  }, [committedKeyword, message, taskFilterKey]);

  useEffect(() => {
    if (!open) return;
    const timer = window.setTimeout(() => setCommittedKeyword(keyword.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [keyword, open]);

  useEffect(() => {
    if (open) {
      setSelectedIds([]);
      // 每次打开都从"未筛选"开始：带着上次的关键词进来会让用户以为候选项丢了。
      setKeyword("");
      setCommittedKeyword("");
      void load();
    }
  }, [load, open, taskFilterKey]);

  // 搜索改变的是"看得见的那一批"，选中集必须跟着清空——否则批量导入/删除会作用到
  // 已经不在屏幕上的条目，用户看到的和实际发生的事对不上。
  useEffect(() => {
    setSelectedIds([]);
  }, [committedKeyword]);

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

  /**
   * 导入前先取这一条的**详情**：列表响应不带 JD（见 ``CandidateJobDetail`` 的说明），
   * 拿列表对象去预填表单会得到一个没有职位描述的空表单。
   *
   * 只在这一个动作上多一次请求：用户点一次「导入到岗位」换一次，而不是每次打开抽屉
   * 都把所有候选的正文一起拉下来。
   */
  const startImport = async (candidate: CandidateJob) => {
    try {
      const detail = await getCandidateJob(candidate.id);
      setDetailCandidate(null);
      onImport(detail);
    } catch (error) {
      message.error(error instanceof Error ? error.message : "读取这条备选岗位失败");
    }
  };

  const openDetails = async (candidate: CandidateJob) => {
    setDetailLoading(true);
    try {
      setDetailCandidate(await getCandidateJob(candidate.id));
    } catch (error) {
      message.error(error instanceof Error ? error.message : "读取这条备选岗位失败");
    } finally {
      setDetailLoading(false);
    }
  };

  const remove = async (candidate: CandidateJob) => {
    try {
      await deleteCandidateJob(candidate.id);
      setSelectedIds((current) => current.filter((id) => id !== candidate.id));
      message.success("已删除");
      await load();
    } catch (error) {
      message.error(error instanceof Error ? error.message : "删除失败");
    }
  };

  const toggleSelected = (candidateId: number, checked: boolean) => {
    setSelectedIds((current) =>
      checked
        ? [...new Set([...current, candidateId])]
        : current.filter((id) => id !== candidateId),
    );
  };

  const importSelected = async () => {
    if (selectedPendingIds.length === 0) {
      message.warning("请先选择待处理的备选岗位");
      return;
    }
    setBatchAction("import");
    try {
      const result = await importCandidateJobs(selectedPendingIds);
      setSelectedIds([]);
      await load();
      const details = [
        result.imported > 0 ? `新建 ${result.imported} 个` : "",
        result.duplicate > 0 ? `重复 ${result.duplicate} 个` : "",
        result.trashed > 0 ? `回收站已有 ${result.trashed} 个` : "",
        result.invalid > 0 ? `无效 ${result.invalid} 个` : "",
        result.missing > 0 ? `已不存在 ${result.missing} 个` : "",
      ].filter(Boolean);
      message.success(`批量导入完成：${details.join("，") || "没有可导入的岗位"}`);
    } catch (error) {
      message.error(error instanceof Error ? error.message : "批量导入失败");
    } finally {
      setBatchAction(null);
    }
  };

  const deleteSelected = async () => {
    if (selectedIds.length === 0) {
      message.warning("请先选择备选岗位");
      return;
    }
    setBatchAction("delete");
    try {
      const results = await Promise.allSettled(selectedIds.map((id) => deleteCandidateJob(id)));
      const deleted = results.filter((result) => result.status === "fulfilled").length;
      const failed = results.length - deleted;
      setSelectedIds([]);
      await load();
      if (failed > 0) {
        message.warning(`已删除 ${deleted} 个备选岗位，${failed} 个删除失败`);
      } else {
        message.success(`已删除 ${deleted} 个备选岗位`);
      }
    } catch (error) {
      message.error(error instanceof Error ? error.message : "批量删除失败");
    } finally {
      setBatchAction(null);
    }
  };

  const allSelected = items.length > 0 && selectedIds.length === items.length;

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
        {collectTaskIds.length > 0
          ? `这里只显示选中采集记录的岗位（${collectTaskIds.length} 条记录）。`
          : "这里放还没核对的招聘信息（粘贴的文本或截图）。"}
        点卡片查看详情；选中后可以批量导入或删除。
      </Typography.Paragraph>
      <Space wrap style={{ marginBottom: 12 }}>
        <Input.Search
          allowClear
          value={keyword}
          onChange={(event) => setKeyword(event.target.value)}
          placeholder="搜职位、公司、原文或备注"
          style={{ width: 260 }}
          aria-label="搜索备选岗位"
        />
        {committedKeyword ? (
          <Typography.Text type="secondary">
            「{committedKeyword}」匹配 {items.length} 条
          </Typography.Text>
        ) : null}
      </Space>
      {items.length > 0 && (
        <Space wrap style={{ marginBottom: 12 }}>
          <Checkbox
            checked={allSelected}
            indeterminate={selectedIds.length > 0 && !allSelected}
            disabled={batchAction !== null}
            onChange={(event) =>
              setSelectedIds(event.target.checked ? items.map((item) => item.id) : [])
            }
          >
            全选
          </Checkbox>
          <Typography.Text type="secondary">已选 {selectedIds.length} 条</Typography.Text>
          <Button
            size="small"
            disabled={selectedPendingIds.length === 0 || batchAction !== null}
            loading={batchAction === "import"}
            onClick={() => void importSelected()}
          >
            批量导入
          </Button>
          <Button
            size="small"
            danger
            disabled={selectedIds.length === 0 || batchAction !== null}
            loading={batchAction === "delete"}
            onClick={() => void deleteSelected()}
          >
            批量删除
          </Button>
          <Button
            size="small"
            disabled={selectedIds.length === 0 || batchAction !== null}
            onClick={() => setSelectedIds([])}
          >
            清空选择
          </Button>
        </Space>
      )}
      {loading ? (
        <Spin />
      ) : items.length === 0 ? (
        committedKeyword ? (
          <Empty
            description={`没有匹配「${committedKeyword}」的备选岗位`}
            image={Empty.PRESENTED_IMAGE_SIMPLE}
          >
            <Button size="small" onClick={() => setKeyword("")}>
              清空搜索
            </Button>
          </Empty>
        ) : (
          <Empty description="还没有备选岗位。看到感兴趣但来不及整理的招聘信息，先放到这里。" />
        )
      ) : (
        <div className="candidate-job-card-grid">
          {items.map((candidate) => {
            const selected = selectedIds.includes(candidate.id);
            return (
              <Card
                key={candidate.id}
                hoverable
                className={`candidate-job-card${selected ? " is-selected" : ""}`}
                onClick={(event) => {
                  const target = event.target as HTMLElement;
                  if (target.closest("button, a, input, .ant-dropdown, .row-actions")) return;
                  void openDetails(candidate);
                }}
                title={
                  <Space>
                    <Checkbox
                      checked={selected}
                      disabled={batchAction !== null}
                      onClick={(event) => event.stopPropagation()}
                      onChange={(event) => toggleSelected(candidate.id, event.target.checked)}
                    />
                    <Typography.Text strong>
                      {candidate.title || "（未识别岗位名）"}
                    </Typography.Text>
                  </Space>
                }
                extra={
                  <Tag color={candidate.status === "imported" ? "green" : "orange"}>
                    {candidate.status === "imported" ? "已导入" : "待处理"}
                  </Tag>
                }
              >
                <Space direction="vertical" size={6} style={{ width: "100%" }}>
                  <Typography.Text type="secondary">
                    {[candidate.company || "未识别公司", candidate.location, candidate.salary]
                      .filter(Boolean)
                      .join(" · ")}
                  </Typography.Text>
                  <Space wrap>
                    <Tag>{candidate.source || "未知来源"}</Tag>
                    {candidate.images.length > 0 && (
                      <Tag color="blue">截图 {candidate.images.length} 张</Tag>
                    )}
                    {candidate.raw_text && <Tag>原文 {candidate.raw_text.length} 字</Tag>}
                  </Space>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    更新于 {formatDateTime(candidate.updated_at)}
                  </Typography.Text>
                  <RowActions
                    primary={
                      candidate.status === "pending"
                        ? [
                            {
                              key: "import",
                              label: "导入到岗位",
                              onClick: () => void startImport(candidate),
                            },
                          ]
                        : []
                    }
                    more={[
                      {
                        key: "detail",
                        label: "查看详情",
                        onClick: () => void openDetails(candidate),
                      },
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
                </Space>
              </Card>
            );
          })}
        </div>
      )}

      <CandidateJobDetailModal
        candidate={detailCandidate}
        loading={detailLoading}
        onClose={() => setDetailCandidate(null)}
        onImport={(candidate) => void startImport(candidate)}
        onEdit={(candidate) => {
          setDetailCandidate(null);
          openEdit(candidate);
        }}
      />

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
              placeholder="如：市场营销专员"
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
