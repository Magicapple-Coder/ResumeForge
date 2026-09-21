/**
 * 站点侧筛选项：把招聘网站**自己的筛选栏**搬进采集条件里。
 *
 * 为什么值得单独一块：站点在接口侧就把不符合的岗位筛掉了，所以它比"采回来再本地筛"
 * **更准也更省**——本地筛要先翻页、抓详情，再把结果丢掉。
 *
 * 两条不能让步的性质：
 *
 * 1. **选项清单来自站点，不是这里写死的。** 写死的一份在站点改编码之后会静默筛错
 *    （用户以为按「本科」筛了，实际发出去的是另一个编码）。清单由后端读来，前端只渲染。
 * 2. **来源要标明。** 浏览器在跑时读到的是"你这个账号可见"的完整清单；没跑时用的是全网
 *    通用清单。两者可能不一样（实测：「求职类型」里「实习」这一档就因人而异），所以
 *    必须让用户知道自己拿到的是哪一份。
 */
import { InfoCircleOutlined, ReloadOutlined } from "@ant-design/icons";
import type { SelectProps } from "antd";
import { Alert, Button, Form, Select, Space, Tag, Tooltip, Typography } from "antd";
import { useCallback, useEffect, useMemo, useState } from "react";
import { getCollectFilterOptions } from "../../api/apply";
import type { CollectFilterGroup, CollectFilterOptions, CollectFilterSource } from "../../types";

/** 来源标签：颜色 + 文案。文案要说清"这份清单的可信度"，不能只说一个英文枚举值。 */
const SOURCE_TAG: Record<CollectFilterSource, { color: string; text: string; hint: string }> = {
  session: {
    color: "green",
    text: "读取自你的登录会话",
    hint: "这是你这个账号在招聘网站上真实能看到的选项，最准。",
  },
  public: {
    color: "blue",
    text: "全网通用清单",
    hint: "浏览器没启动，用的是不需要登录就能拿到的通用清单。个别选项（例如部分账号才有的「实习」）可能不在里面；启动浏览器后会被换成你自己账号可见的完整清单。",
  },
  snapshot: {
    color: "orange",
    text: "内置快照（离线）",
    hint: "联网读取失败，用的是内置的一份快照。编码可能已经过期，采集前建议连上网重读一次。",
  },
  unavailable: {
    color: "default",
    text: "本次读不到",
    hint: "这一项这次没能从站点读到，暂时不能按它筛。",
  },
};

interface Props {
  /** 是否禁用（有批次在跑时不允许改条件）。 */
  disabled: boolean;
}

/** antd Select 认得的下拉项形状（含"分组"那一层），用它标注免得 TS 推出一个联合类型。 */
type SelectOptionList = NonNullable<SelectProps["options"]>;

/** 把一组选项折成 antd Select 的 options；行业有 15 个一级分组，要分层展示。 */
function buildOptions(group: CollectFilterGroup): SelectOptionList {
  if (!group.options.some((item) => item.group)) {
    return group.options.map((item) => ({ value: item.code, label: item.label }));
  }
  const grouped = new Map<string, { value: string; label: string }[]>();
  for (const item of group.options) {
    const key = item.group || group.label;
    if (!grouped.has(key)) grouped.set(key, []);
    grouped.get(key)?.push({ value: item.code, label: item.label });
  }
  return [...grouped].map(([label, options]) => ({ label, options }));
}

export default function CollectSiteFilters({ disabled }: Props) {
  const [data, setData] = useState<CollectFilterOptions | null>(null);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await getCollectFilterOptions());
      setFailed(false);
    } catch {
      // 读不到就当"这个站点没有站点侧筛选"：它是可选能力，不该挡住整个采集表单。
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const groups = useMemo(
    () => (data?.groups ?? []).filter((group) => group.options.length > 0),
    [data],
  );
  // 来源**按值去重**：七个分组通常来自同一处，逐个渲染就会并排出现七个一模一样的标签，
  // 那不是在说明来源，只是在制造噪声。混了来源时才逐条列出。
  const sources = useMemo(() => [...new Set(groups.map((group) => group.source))], [groups]);

  if (failed && !data) {
    return (
      <Alert
        type="warning"
        showIcon
        message="没能读到招聘网站的筛选条件"
        description="不影响采集：关键词与城市照常生效。点下面的「重新读取」可以再试一次。"
        action={
          <Button size="small" icon={<ReloadOutlined />} onClick={() => void load()}>
            重新读取
          </Button>
        }
        style={{ marginBottom: 12 }}
      />
    );
  }
  if (groups.length === 0) return null;

  const sessionRead = data?.session_read ?? false;

  return (
    <div className="apply-collect-site-filters">
      <Space size={8} wrap style={{ marginBottom: 4 }}>
        <Typography.Text strong>按招聘网站的条件筛</Typography.Text>
        {sources.map((source) => {
          const meta = SOURCE_TAG[source] ?? SOURCE_TAG.unavailable;
          return (
            <Tooltip key={`tag-${source}`} title={meta.hint}>
              <Tag color={meta.color} style={{ marginInlineEnd: 0 }}>
                {meta.text}
              </Tag>
            </Tooltip>
          );
        })}
        <Button
          size="small"
          type="link"
          icon={<ReloadOutlined />}
          loading={loading}
          onClick={() => void load()}
        >
          重新读取
        </Button>
      </Space>

      <Typography.Text type="secondary" style={{ display: "block", marginBottom: 12 }}>
        <InfoCircleOutlined /> 这些是招聘网站筛选栏里的条件，网站在搜索时就替你筛掉了，
        比采回来再筛更准、也少翻很多页。选项清单读自站点本身，站点改版时会自动跟着变。
      </Typography.Text>

      {!sessionRead && (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 12 }}
          message="想拿到你这个账号可见的完整选项，请先启动投递专用浏览器"
          description="个别选项因人而异（例如学生账号在「求职类型」里能看到「实习」），只有在你已登录的浏览器里才读得到。当前用的是全网通用清单，够用但不一定全。"
        />
      )}

      <Space size={16} wrap>
        {groups.map((group) => (
          <Form.Item
            key={group.key}
            name={["filters", group.key]}
            label={group.label}
            extra={
              group.key === "jobType"
                ? "与下面的「岗位类型」分工：这里按网站自己的分类筛，下面的含「校招」（网站没有校招这一档）"
                : undefined
            }
          >
            <Select
              allowClear
              showSearch
              disabled={disabled}
              placeholder="不限"
              style={{ width: group.key === "industry" ? 240 : 170 }}
              optionFilterProp="label"
              // 选项多（行业 145 条）时要能搜；分组用 antd 的嵌套 options。
              options={buildOptions(group)}
              aria-label={`站点筛选-${group.label}`}
            />
          </Form.Item>
        ))}
      </Space>
    </div>
  );
}
