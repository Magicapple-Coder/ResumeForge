/** ATS 本地检测面板：格式风险 / 关键词覆盖 / 信息位置。
 *
 * 提供可选的 JD 文本输入，按 JD 抽出的关键词检查覆盖；不填 JD 时做通用关键词覆盖。
 * 结果带免责声明（本地规则估计，不代表真实 ATS 解析结果），必须展示给用户。
 */
import { ReloadOutlined } from "@ant-design/icons";
import { Alert, Button, Card, Empty, Input, Progress, Space, Spin, Tag, Typography } from "antd";
import { useMemo, useRef, useState } from "react";
import { runAtsCheck } from "../api/ats";
import { useApi } from "../hooks/useApi";
import type { AtsIssue, AtsIssueCategory, AtsSeverity } from "../types/ats";

const CATEGORY_ORDER: { key: AtsIssueCategory; label: string; color: string }[] = [
  { key: "format", label: "格式风险", color: "orange" },
  { key: "keyword", label: "关键词覆盖", color: "blue" },
  { key: "position", label: "信息位置", color: "purple" },
];

const SEVERITY: Record<AtsSeverity, { label: string; color: string }> = {
  high: { label: "高", color: "red" },
  medium: { label: "中", color: "orange" },
  low: { label: "低", color: "blue" },
};

interface Props {
  resumeId: number;
}

export default function AtsCheckPanel({ resumeId }: Props) {
  const [jdText, setJdText] = useState("");
  const jdTextRef = useRef("");
  const { data, loading, error, reload } = useApi(
    () => runAtsCheck(resumeId, jdTextRef.current),
    [resumeId],
  );

  const run = () => {
    jdTextRef.current = jdText;
    void reload();
  };

  const grouped = useMemo(() => {
    const map = new Map<AtsIssueCategory, AtsIssue[]>();
    for (const issue of data?.issues ?? []) {
      const list = map.get(issue.category) ?? [];
      list.push(issue);
      map.set(issue.category, list);
    }
    return CATEGORY_ORDER.map((item) => ({ ...item, issues: map.get(item.key) ?? [] }));
  }, [data]);

  return (
    <Space direction="vertical" style={{ width: "100%" }} size="middle">
      <Space.Compact style={{ width: "100%" }}>
        <Input.TextArea
          rows={2}
          value={jdText}
          placeholder="可选：粘贴岗位 JD 文本，按 JD 关键词检查覆盖（留空则做通用覆盖）"
          aria-label="JD 文本"
          onChange={(event) => setJdText(event.target.value)}
        />
        <Button type="primary" loading={loading} onClick={run}>
          开始检测
        </Button>
      </Space.Compact>

      {error && <Alert type="error" showIcon message={error} />}

      {data && !loading && (
        <>
          <Alert type="info" showIcon message={data.disclaimer} />
          <Space wrap align="center">
            <Typography.Text strong>ATS 参考分</Typography.Text>
            <Progress
              type="circle"
              size={64}
              percent={data.score}
              format={(value) => `${value ?? 0}`}
            />
            {CATEGORY_ORDER.map((item) => {
              const count = data.summary?.[item.key] ?? 0;
              if (!count) return null;
              return (
                <Tag key={item.key} color={item.color}>
                  {item.label} {count}
                </Tag>
              );
            })}
            <Button size="small" icon={<ReloadOutlined />} onClick={() => void reload()}>
              重新检测
            </Button>
          </Space>

          {data.matched_keywords.length > 0 && (
            <div>
              <Typography.Text type="secondary">已命中关键词：</Typography.Text>
              <Space wrap>
                {data.matched_keywords.map((word) => (
                  <Tag key={word} color="green">
                    {word}
                  </Tag>
                ))}
              </Space>
            </div>
          )}
          {data.missing_keywords.length > 0 && (
            <div>
              <Typography.Text type="secondary">未命中关键词：</Typography.Text>
              <Space wrap>
                {data.missing_keywords.map((word) => (
                  <Tag key={word}>{word}</Tag>
                ))}
              </Space>
            </div>
          )}

          {data.issues.length === 0 ? (
            <Empty description="未发现明显问题" />
          ) : (
            grouped.map((group) =>
              group.issues.length === 0 ? null : (
                <Card
                  key={group.key}
                  size="small"
                  title={
                    <Space>
                      <Typography.Text strong>{group.label}</Typography.Text>
                      <Tag color={group.color}>{group.issues.length}</Tag>
                    </Space>
                  }
                >
                  <Space direction="vertical" style={{ width: "100%" }} size="small">
                    {group.issues.map((issue, index) => (
                      <div
                        key={index}
                        style={{ borderTop: "1px solid #f0f0f0", paddingTop: 8 }}
                        data-ats-category={issue.category}
                      >
                        <Space size="small" wrap>
                          <Tag color={SEVERITY[issue.severity]?.color}>
                            {SEVERITY[issue.severity]?.label}
                          </Tag>
                          <Typography.Text strong>{issue.title}</Typography.Text>
                        </Space>
                        <Typography.Paragraph style={{ margin: "4px 0" }}>
                          {issue.detail}
                        </Typography.Paragraph>
                        {issue.evidence.length > 0 && (
                          <Space wrap>
                            {issue.evidence.map((item, evidenceIndex) => (
                              <Tag key={evidenceIndex} color="default">
                                {item}
                              </Tag>
                            ))}
                          </Space>
                        )}
                      </div>
                    ))}
                  </Space>
                </Card>
              ),
            )
          )}
        </>
      )}
      {loading && <Spin />}
    </Space>
  );
}
