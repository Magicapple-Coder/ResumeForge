import { SearchOutlined } from "@ant-design/icons";
import { Alert, App, Button, Card, Input, List, Modal, Space, Table, Tag, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import { useCallback, useEffect, useState } from "react";
import {
  createOfficialSite,
  discoverOfficialCompanies,
  listOfficialDiscoveryHistory,
} from "../../api/official";
import type {
  OfficialCandidate,
  OfficialDiscovery,
  OfficialDiscoveryHistory,
  OfficialSitePayload,
} from "../../types";
import { formatDateTime } from "../../utils/format";

interface Props {
  open: boolean;
  onCancel: () => void;
  onAdded: () => Promise<void>;
}

type AddingState = { done: number; total: number } | null;

function historyToDiscovery(item: OfficialDiscoveryHistory): OfficialDiscovery {
  return {
    history_id: item.id,
    candidates: item.candidates,
    queries: item.queries,
    detail: item.detail,
  };
}

/** 按岗位搜公司、回看搜索快照、勾选后逐个添加的完整交互。 */
export default function OfficialDiscoveryModal({ open, onCancel, onAdded }: Props) {
  const { message, modal } = App.useApp();
  const [keywords, setKeywords] = useState("");
  const [city, setCity] = useState("");
  const [discovering, setDiscovering] = useState(false);
  const [discovery, setDiscovery] = useState<OfficialDiscovery | null>(null);
  const [leads, setLeads] = useState<OfficialCandidate[]>([]);
  const [chosen, setChosen] = useState<string[]>([]);
  const [adding, setAdding] = useState<AddingState>(null);
  const [history, setHistory] = useState<OfficialDiscoveryHistory[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true);
    try {
      setHistory(await listOfficialDiscoveryHistory());
    } catch (error) {
      message.error(error instanceof Error ? error.message : "加载搜索记录失败");
    } finally {
      setHistoryLoading(false);
    }
  }, [message]);

  useEffect(() => {
    if (!open) return;
    // 每次打开都清掉上次的结果，避免用户把旧结果误认为是新关键词的结果；历史记录仍保留。
    setDiscovery(null);
    setLeads([]);
    setChosen([]);
    void loadHistory();
  }, [loadHistory, open]);

  const handleDiscover = async () => {
    setDiscovering(true);
    try {
      const result = await discoverOfficialCompanies({ keywords, city });
      setDiscovery(result);
      setLeads(result.candidates);
      setChosen(result.candidates.map((item) => item.url));
      await loadHistory();
    } catch (error) {
      setDiscovery(null);
      setLeads([]);
      setChosen([]);
      message.error(error instanceof Error ? error.message : "搜索失败");
    } finally {
      setDiscovering(false);
    }
  };

  const handleHistory = (item: OfficialDiscoveryHistory) => {
    setKeywords(item.keywords);
    setCity(item.city);
    const result = historyToDiscovery(item);
    setDiscovery(result);
    setLeads(result.candidates);
    setChosen(result.candidates.map((candidate) => candidate.url));
  };

  const handleAddChosen = async () => {
    const picked = leads.filter((item) => chosen.includes(item.url));
    if (picked.length === 0) return;
    setAdding({ done: 0, total: picked.length });
    const failedUrls: string[] = [];
    const failureNotes: string[] = [];
    for (const [index, candidate] of picked.entries()) {
      setAdding({ done: index, total: picked.length });
      const name = candidate.company || candidate.host;
      const payload: OfficialSitePayload =
        candidate.target_field === "homepage_url"
          ? { company: name, homepage_url: candidate.url }
          : { company: name, careers_url: candidate.url };
      try {
        await createOfficialSite(payload);
      } catch (error) {
        failedUrls.push(candidate.url);
        failureNotes.push(`${name}：${error instanceof Error ? error.message : "添加失败"}`);
      }
    }
    setAdding(null);
    await onAdded();
    if (failedUrls.length === 0) {
      onCancel();
      message.success(`已添加 ${picked.length} 家，识别结果见列表`);
      return;
    }
    setChosen(failedUrls);
    setLeads(picked);
    modal.warning({
      title: `已添加 ${picked.length - failedUrls.length} 家，${failedUrls.length} 家没成功`,
      content: (
        <Space direction="vertical" size={2}>
          {failureNotes.map((text) => (
            <Typography.Text key={text} style={{ fontSize: 12 }}>
              {text}
            </Typography.Text>
          ))}
        </Space>
      ),
    });
  };

  const leadColumns: ColumnsType<OfficialCandidate> = [
    {
      title: "公司名称",
      dataIndex: "company",
      width: 200,
      render: (_value, lead, index) => (
        <Input
          size="small"
          value={lead.company}
          maxLength={128}
          aria-label="候选公司名称"
          onChange={(event) => {
            const next = [...leads];
            next[index] = { ...lead, company: event.target.value };
            setLeads(next);
          }}
        />
      ),
    },
    {
      title: "地址",
      dataIndex: "url",
      render: (_value, lead) => (
        <Space direction="vertical" size={0}>
          <Typography.Link
            href={lead.url}
            target="_blank"
            rel="noreferrer noopener"
            style={{ fontSize: 12, wordBreak: "break-all" }}
          >
            {lead.url}
          </Typography.Link>
          <Tag color={lead.is_careers_page ? "blue" : "default"}>
            {lead.is_careers_page ? "招聘页" : "公司站点"}
          </Tag>
        </Space>
      ),
    },
    {
      title: "线索来源",
      dataIndex: "evidence",
      width: 180,
      render: (_value, lead) =>
        lead.evidence ? (
          <Typography.Text
            type="secondary"
            style={{ fontSize: 12 }}
            ellipsis={{ tooltip: lead.evidence }}
          >
            {lead.evidence}
          </Typography.Text>
        ) : (
          <Typography.Text type="secondary">—</Typography.Text>
        ),
    },
  ];

  return (
    <Modal
      title="按岗位找公司"
      open={open}
      onCancel={onCancel}
      width={800}
      destroyOnClose
      footer={
        <Space>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {adding
              ? `正在识别 ${adding.done + 1}/${adding.total}……`
              : `已选 ${chosen.length} 家，添加时逐个识别`}
          </Typography.Text>
          <Button onClick={onCancel}>取消</Button>
          <Button
            type="primary"
            loading={adding !== null}
            disabled={chosen.length === 0}
            onClick={() => void handleAddChosen()}
          >
            添加所选
          </Button>
        </Space>
      }
    >
      <Space direction="vertical" size="middle" style={{ width: "100%" }}>
        <Card size="small" title="搜索记录" loading={historyLoading}>
          {history.length === 0 ? (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              还没有搜索记录。每次点击「找公司」都会自动保存。
            </Typography.Text>
          ) : (
            <List
              size="small"
              dataSource={history}
              style={{ maxHeight: 170, overflowY: "auto" }}
              renderItem={(item) => (
                <List.Item
                  actions={[
                    <Button key="open" type="link" size="small" onClick={() => handleHistory(item)}>
                      回看
                    </Button>,
                  ]}
                >
                  <Space direction="vertical" size={0}>
                    <Typography.Text>
                      {item.keywords || "未填写关键词"}
                      {item.city ? ` · ${item.city}` : ""}
                    </Typography.Text>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      {formatDateTime(item.created_at)} · {item.candidate_count} 条线索
                    </Typography.Text>
                  </Space>
                </List.Item>
              )}
            />
          )}
        </Card>

        <Space.Compact style={{ width: "100%" }}>
          <Input
            value={keywords}
            onChange={(event) => setKeywords(event.target.value)}
            onPressEnter={() => void handleDiscover()}
            placeholder="要找的岗位，例如：大模型应用开发"
            maxLength={200}
            allowClear
          />
          <Input
            value={city}
            onChange={(event) => setCity(event.target.value)}
            placeholder="城市（可不填）"
            maxLength={64}
            style={{ width: 160 }}
            allowClear
          />
          <Button
            type="primary"
            icon={<SearchOutlined />}
            loading={discovering}
            onClick={() => void handleDiscover()}
          >
            找公司
          </Button>
        </Space.Compact>

        {discovery && <Alert type="info" showIcon message={discovery.detail} />}
        {discovery && discovery.queries.length > 0 && (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            搜的是：{discovery.queries.join("；")}
          </Typography.Text>
        )}
        {leads.length > 0 && (
          <Table<OfficialCandidate>
            className="official-discovery-table"
            rowKey="url"
            size="small"
            dataSource={leads}
            pagination={false}
            scroll={{ y: 320 }}
            rowSelection={{
              selectedRowKeys: chosen,
              onChange: (keys) => setChosen(keys as string[]),
            }}
            columns={leadColumns}
          />
        )}
      </Space>
    </Modal>
  );
}
