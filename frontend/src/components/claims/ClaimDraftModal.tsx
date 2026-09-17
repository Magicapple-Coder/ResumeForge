/**
 * 从一段资料草拟台账条目：粘贴 → 生成草稿 → 逐条核对 → 保存。
 *
 * 草稿一律带「待确认」状态入库，所以这里的核对环节不是走过场：用户至少要看一眼
 * 原始事实有没有被曲解。候选表述允许就地改，因为那是最常需要调整的一栏。
 */
import { App, Button, Checkbox, Empty, Input, Modal, Select, Space, Typography } from "antd";
import { useState } from "react";
import { createClaim, draftClaims } from "../../api/claims";
import type { Claim, ClaimDraftPayload, ClaimPayload } from "../../types";
import { CLAIM_CATEGORIES } from "../../types";

/**
 * 一行草稿。可提交的内容单独放在 `payload` 里，而不是把 UI 状态（勾选、行号）混进
 * payload 再"提交时抠掉"——那样早晚会漏抠一个字段。
 */
interface DraftRow {
  key: number;
  checked: boolean;
  payload: ClaimPayload;
}

interface Props {
  open: boolean;
  onClose: () => void;
  onSaved: (claims: Claim[]) => void;
}

export default function ClaimDraftModal({ open, onClose, onSaved }: Props) {
  const { message } = App.useApp();
  const [rawText, setRawText] = useState("");
  const [category, setCategory] = useState<ClaimDraftPayload["category"]>("项目经历");
  const [subject, setSubject] = useState("");
  const [rows, setRows] = useState<DraftRow[]>([]);
  const [notes, setNotes] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  const reset = () => {
    setRows([]);
    setNotes([]);
  };

  const generate = async () => {
    if (!rawText.trim()) {
      message.warning("请先粘贴要整理的资料");
      return;
    }
    setBusy(true);
    try {
      const result = await draftClaims({ category, subject, raw_text: rawText });
      setRows(result.drafts.map((payload, index) => ({ key: index, checked: true, payload })));
      setNotes(result.notes);
      if (result.drafts.length === 0) message.info("这段资料里没有提取出可核对的主张");
    } catch (error) {
      message.error(error instanceof Error ? error.message : "生成草稿失败");
    } finally {
      setBusy(false);
    }
  };

  /** 改可提交的内容。 */
  const update = (key: number, patch: Partial<ClaimPayload>) => {
    setRows((current) =>
      current.map((row) =>
        row.key === key ? { ...row, payload: { ...row.payload, ...patch } } : row,
      ),
    );
  };

  /** 改这一行的勾选状态（属于界面状态，不进 payload）。 */
  const toggle = (key: number, checked: boolean) => {
    setRows((current) => current.map((row) => (row.key === key ? { ...row, checked } : row)));
  };

  const save = async () => {
    const picked = rows.filter((row) => row.checked);
    if (picked.length === 0) {
      message.warning("请至少勾选一条");
      return;
    }
    setBusy(true);
    try {
      const saved: Claim[] = [];
      for (const row of picked) {
        saved.push(await createClaim(row.payload));
      }
      message.success(`已加入台账 ${saved.length} 条，状态都是「待确认」`);
      onSaved(saved);
      reset();
      onClose();
    } catch (error) {
      // 中途失败时已保存的条目仍然有效，如实说清数量，不要假装整批成功或整批失败。
      message.error(error instanceof Error ? error.message : "保存失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      title="从资料生成台账草稿"
      width={760}
      onCancel={() => {
        reset();
        onClose();
      }}
      footer={
        <Space>
          <Button
            onClick={() => {
              reset();
              onClose();
            }}
          >
            取消
          </Button>
          {rows.length > 0 && (
            <Button type="primary" loading={busy} onClick={() => void save()}>
              保存勾选的 {rows.filter((row) => row.checked).length} 条
            </Button>
          )}
        </Space>
      }
    >
      <Space direction="vertical" size={12} style={{ width: "100%" }}>
        <Typography.Text type="secondary">
          粘贴一段经历、项目说明或获奖情况。提取出来的条目一律是「待确认」，请逐条核对后再标为已确认。
        </Typography.Text>
        <Space size={12}>
          <Select
            value={category}
            onChange={setCategory}
            style={{ width: 160 }}
            options={CLAIM_CATEGORIES.map((value) => ({ value, label: value }))}
          />
          <Input
            value={subject}
            onChange={(event) => setSubject(event.target.value)}
            placeholder="主体（可留空，例如项目名）"
            style={{ width: 260 }}
          />
        </Space>
        <Input.TextArea
          rows={6}
          value={rawText}
          onChange={(event) => setRawText(event.target.value)}
          placeholder="把资料原文贴在这里，越具体越好；没写到的东西不会被补出来。"
        />
        <Button type="primary" loading={busy} onClick={() => void generate()}>
          生成草稿
        </Button>

        {notes.map((note) => (
          <Typography.Text key={note} type="secondary">
            · {note}
          </Typography.Text>
        ))}

        {rows.length === 0 ? (
          <Empty description="还没有草稿" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        ) : (
          <div className="claim-draft-list">
            {rows.map((row) => (
              <div key={row.key} className="claim-draft-row">
                <Checkbox
                  checked={row.checked}
                  onChange={(event) => toggle(row.key, event.target.checked)}
                />
                <div className="claim-draft-fields">
                  <Input
                    value={row.payload.title}
                    onChange={(event) => update(row.key, { title: event.target.value })}
                    placeholder="标题"
                    maxLength={200}
                  />
                  <Input.TextArea
                    rows={2}
                    value={row.payload.source_fact}
                    onChange={(event) => update(row.key, { source_fact: event.target.value })}
                    placeholder="原始事实"
                  />
                  <Input.TextArea
                    rows={2}
                    value={row.payload.candidate_wording}
                    onChange={(event) => update(row.key, { candidate_wording: event.target.value })}
                    placeholder="简历表述（未核实的内容请保留【待补】标记）"
                  />
                </div>
              </div>
            ))}
          </div>
        )}
      </Space>
    </Modal>
  );
}
