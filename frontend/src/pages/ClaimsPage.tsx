/**
 * 事实台账：把写进简历的每一句话沉淀成可核对、可复核的条目。
 *
 * 页面职责很窄——筛选、展示、把改动交给后端；判断规则（什么状态能进终稿、什么写法
 * 会被追问）全在后端算好随条目下发，前端不自己再判一次。顶部那行"事实基线"读数
 * 直接取 `/api/claims/baseline`，所以界面显示的就是生成简历时真正会用到的东西。
 */
import {
  FileAddOutlined,
  PlusOutlined,
  SafetyCertificateOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import { App, Button, Empty, Input, Select, Skeleton, Space, Statistic, Typography } from "antd";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { deleteClaim, getClaimBaseline, listClaims, updateClaim } from "../api/claims";
import ClaimCard from "../components/claims/ClaimCard";
import ClaimDraftModal from "../components/claims/ClaimDraftModal";
import ClaimFormModal from "../components/claims/ClaimFormModal";
import { useApi } from "../hooks/useApi";
import type { Claim } from "../types";
import { CLAIM_CATEGORIES, VERIFICATION_STATUSES, claimPayload } from "../types";

export default function ClaimsPage() {
  const { message } = App.useApp();
  const navigate = useNavigate();
  const [category, setCategory] = useState("");
  const [status, setStatus] = useState("");
  const [keyword, setKeyword] = useState("");
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Claim | null>(null);
  const [draftOpen, setDraftOpen] = useState(false);

  const { data, loading, error, reload } = useApi(
    () => listClaims({ category, status, keyword }),
    [category, status, keyword],
  );
  const baseline = useApi(() => getClaimBaseline(), []);

  const items = useMemo(() => data?.items ?? [], [data]);

  const remove = async (claim: Claim) => {
    try {
      await deleteClaim(claim.id);
      message.success("已移入回收站，可在「回收站」里恢复");
      await reload();
      await baseline.reload();
    } catch (err) {
      message.error(err instanceof Error ? err.message : "删除失败");
    }
  };

  const confirm = async (claim: Claim) => {
    try {
      // 后端会再校验一次占位符；前端只负责把当前值原样提交并换个状态。
      const saved = await updateClaim(
        claim.id,
        claimPayload(claim, { verification_status: "已确认" }),
      );
      // 后端可能因为"还留着【待补】"而拒绝，这里要如实说清是哪一条、为什么。
      if (saved.warnings.length > 0) {
        message.warning(`已标记为已确认，但还有待办：${saved.warnings[0]}`);
      } else {
        message.success("已标记为已确认");
      }
      await reload();
      await baseline.reload();
    } catch (err) {
      message.error(err instanceof Error ? err.message : "操作失败");
    }
  };

  const refreshAll = async () => {
    await reload();
    await baseline.reload();
  };

  return (
    <div className="claims-page">
      <div className="claims-page-head">
        <Space direction="vertical" size={0}>
          <Typography.Title level={4} style={{ margin: 0 }}>
            事实台账
          </Typography.Title>
          <Typography.Text type="secondary">
            每条对外说得出的话，都能回到一个出处。只有「已确认」的条目会作为事实进入简历生成；
            其余说法会被显式避开。
          </Typography.Text>
        </Space>
        <Space>
          {/* 深挖的输入就是台账条目，所以入口放在这里——从别处进它都要先绕一圈。 */}
          <Button icon={<ThunderboltOutlined />} onClick={() => navigate("/claims/drill")}>
            拿去深挖
          </Button>
          <Button icon={<FileAddOutlined />} onClick={() => setDraftOpen(true)}>
            从资料生成
          </Button>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => {
              setEditing(null);
              setFormOpen(true);
            }}
          >
            新建条目
          </Button>
        </Space>
      </div>

      <div className="claims-summary">
        <Statistic title="条目总数" value={data?.total ?? 0} />
        <Statistic
          title="已确认（可进正式简历）"
          value={data?.confirmed_count ?? 0}
          valueStyle={{ color: "#389e0d" }}
        />
        <Statistic
          title="待确认"
          value={data?.pending_count ?? 0}
          valueStyle={{ color: "#d48806" }}
        />
        <Statistic
          title="生成时可用的事实"
          value={baseline.data?.confirmed_count ?? 0}
          prefix={<SafetyCertificateOutlined />}
        />
        {(baseline.data?.blocked_wording.length ?? 0) > 0 && (
          <Statistic
            title="会被避开的未确认说法"
            value={baseline.data?.blocked_wording.length ?? 0}
            valueStyle={{ color: "#d4380d" }}
          />
        )}
      </div>

      <Space size={12} wrap className="claims-filters">
        <Select
          value={category}
          onChange={setCategory}
          style={{ width: 160 }}
          options={[
            { value: "", label: "全部分类" },
            ...CLAIM_CATEGORIES.map((value) => ({ value, label: value })),
          ]}
        />
        <Select
          value={status}
          onChange={setStatus}
          style={{ width: 160 }}
          options={[
            { value: "", label: "全部状态" },
            ...VERIFICATION_STATUSES.map((value) => ({ value, label: value })),
          ]}
        />
        <Input.Search
          allowClear
          placeholder="搜索标题、主体、事实或表述"
          style={{ width: 280 }}
          onSearch={setKeyword}
        />
      </Space>

      {loading && <Skeleton active paragraph={{ rows: 6 }} />}
      {error && <Typography.Text type="danger">{error}</Typography.Text>}
      {!loading && !error && items.length === 0 && (
        <Empty
          description={
            keyword || category || status
              ? "没有符合条件的条目"
              : "台账还是空的。可以先「从资料生成」一批草稿，或者手工新建一条。"
          }
        >
          <Button type="primary" onClick={() => setDraftOpen(true)}>
            从资料生成
          </Button>
        </Empty>
      )}

      <div className="claims-list">
        {items.map((claim) => (
          <ClaimCard
            key={claim.id}
            claim={claim}
            onEdit={() => {
              setEditing(claim);
              setFormOpen(true);
            }}
            onDelete={() => void remove(claim)}
            onConfirm={() => void confirm(claim)}
          />
        ))}
      </div>

      <ClaimFormModal
        open={formOpen}
        claim={editing}
        onClose={() => {
          setFormOpen(false);
          setEditing(null);
        }}
        onSaved={() => void refreshAll()}
      />
      <ClaimDraftModal
        open={draftOpen}
        onClose={() => setDraftOpen(false)}
        onSaved={() => void refreshAll()}
      />
    </div>
  );
}
