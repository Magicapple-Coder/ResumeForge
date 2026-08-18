/** 首页：数据概览、全局搜索、最近动态与快捷入口。 */
import { FileTextOutlined, RocketOutlined, SearchOutlined, StarOutlined } from "@ant-design/icons";
import { Alert, Card, Col, Empty, Input, List, Row, Space, Statistic, Tag, Typography } from "antd";
import { useEffect, useRef, useState } from "react";
import { createSearchParams, Link } from "react-router-dom";
import { getStats, searchAll } from "../api/search";
import { useApi } from "../hooks/useApi";
import type { SearchResult } from "../types";
import { formatDateTime } from "../utils/format";

export default function HomePage() {
  const { data: stats, loading, error: statsError } = useApi(getStats);
  const [searchText, setSearchText] = useState("");
  const [result, setResult] = useState<SearchResult | null>(null);
  const [resultKeyword, setResultKeyword] = useState("");
  const [searching, setSearching] = useState(false);
  const [searched, setSearched] = useState(false);
  const [searchError, setSearchError] = useState("");
  const searchVersion = useRef(0);

  useEffect(
    () => () => {
      searchVersion.current += 1;
    },
    [],
  );

  const onSearch = async (value: string) => {
    const keyword = value.trim();
    const currentSearch = ++searchVersion.current;
    if (!keyword) {
      setSearching(false);
      setSearched(false);
      setResult(null);
      setResultKeyword("");
      setSearchError("");
      return;
    }
    setSearching(true);
    setSearched(true);
    setResult(null);
    setSearchError("");
    try {
      const nextResult = await searchAll(keyword);
      if (currentSearch === searchVersion.current) {
        setResult(nextResult);
        setResultKeyword(keyword);
      }
    } catch (error) {
      if (currentSearch === searchVersion.current) {
        setResult(null);
        setSearchError(error instanceof Error ? error.message : "搜索失败，请重试");
      }
    } finally {
      if (currentSearch === searchVersion.current) setSearching(false);
    }
  };

  return (
    <div>
      {statsError && (
        <Alert type="error" showIcon message={statsError} style={{ marginBottom: 16 }} />
      )}
      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} xl={6}>
          <Card loading={loading}>
            <Statistic title="岗位总数" value={stats?.job_count ?? 0} prefix={<SearchOutlined />} />
          </Card>
        </Col>
        <Col xs={24} sm={12} xl={6}>
          <Card loading={loading}>
            <Statistic
              title="开放中岗位"
              value={stats?.open_job_count ?? 0}
              prefix={<RocketOutlined />}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} xl={6}>
          <Card loading={loading}>
            <Statistic
              title="已生成简历"
              value={stats?.resume_count ?? 0}
              prefix={<FileTextOutlined />}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} xl={6}>
          <Card loading={loading}>
            <Statistic
              title="近 7 天生成"
              value={stats?.week_resume_count ?? 0}
              prefix={<StarOutlined />}
            />
          </Card>
        </Col>
      </Row>

      <Card style={{ marginTop: 16 }}>
        <Typography.Title level={5}>全局搜索</Typography.Title>
        <Input.Search
          placeholder="搜索岗位（职位/公司/城市）或简历记录，如：后端开发 / 字节跳动"
          enterButton="搜索"
          size="large"
          loading={searching}
          value={searchText}
          onChange={(event) => setSearchText(event.target.value)}
          onSearch={(value) => void onSearch(value)}
        />
        {searchError && (
          <Alert type="error" showIcon message={searchError} style={{ marginTop: 16 }} />
        )}
        {searched && (
          <div style={{ marginTop: 16 }}>
            <Typography.Title level={5} type="secondary">
              匹配的岗位（{result?.jobs.length ?? 0}）
            </Typography.Title>
            <List
              size="small"
              dataSource={result?.jobs ?? []}
              locale={{ emptyText: <Empty description="没有匹配的岗位" /> }}
              renderItem={(job) => (
                <List.Item>
                  <Space>
                    <Link to={`/jobs?${createSearchParams({ keyword: resultKeyword })}`}>
                      {job.title}
                    </Link>
                    <Tag>{job.company}</Tag>
                    <Tag color="blue">{job.location}</Tag>
                    <Typography.Text type="secondary">{job.salary || "薪资面议"}</Typography.Text>
                  </Space>
                </List.Item>
              )}
            />
            <Typography.Title level={5} type="secondary" style={{ marginTop: 12 }}>
              匹配的简历记录（{result?.resumes.length ?? 0}）
            </Typography.Title>
            <List
              size="small"
              dataSource={result?.resumes ?? []}
              locale={{ emptyText: <Empty description="没有匹配的简历记录" /> }}
              renderItem={(resume) => (
                <List.Item>
                  <Space>
                    <Link to="/resumes">{resume.title}</Link>
                    <Tag>{resume.job_title}</Tag>
                    <Typography.Text type="secondary">
                      {formatDateTime(resume.created_at)}
                    </Typography.Text>
                  </Space>
                </List.Item>
              )}
            />
          </div>
        )}
      </Card>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} lg={12}>
          <Card title="最近岗位" extra={<Link to="/jobs">查看全部</Link>}>
            <List
              size="small"
              dataSource={stats?.latest_jobs ?? []}
              locale={{ emptyText: <Empty description="暂无岗位，去「岗位广场」手动添加" /> }}
              renderItem={(job) => (
                <List.Item>
                  <Space>
                    <Link to="/jobs">{job.title}</Link>
                    <Tag>{job.company}</Tag>
                    <Typography.Text type="secondary">
                      {formatDateTime(job.created_at)}
                    </Typography.Text>
                  </Space>
                </List.Item>
              )}
            />
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card title="最近生成的简历" extra={<Link to="/resumes">查看全部</Link>}>
            <List
              size="small"
              dataSource={stats?.latest_resumes ?? []}
              locale={{
                emptyText: <Empty description="暂无简历记录，去「岗位广场」选个岗位试试" />,
              }}
              renderItem={(resume) => (
                <List.Item>
                  <Space>
                    <Link to="/resumes">{resume.title}</Link>
                    <Typography.Text type="secondary">
                      {formatDateTime(resume.created_at)}
                    </Typography.Text>
                  </Space>
                </List.Item>
              )}
            />
          </Card>
        </Col>
      </Row>
    </div>
  );
}
