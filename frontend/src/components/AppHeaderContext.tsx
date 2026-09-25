/**
 * 页头右侧的「当前数据集 + 用户头像」。
 *
 * 两件事放在一起，因为它们回答的是同一个问题：**我现在是在什么上下文里操作**。
 * - 数据集：简历通支持多套互相独立的数据集（工作一份、私人一份），而界面其余部分长得
 *   一模一样，切错数据集会产生"我的简历怎么不见了"这类误会。
 * - 头像：用「我的资料」里**当前启用的那张照片**，一眼就能认出这是谁的那份数据。
 *
 * 两个刻意的做法：
 * 1. **只读展示，不在这里切换**。切数据集是个"改变全局上下文"的动作，放在设置页里、
 *    让用户看清影响之后再做；页头只负责如实显示当前是哪一个（点了会跳去设置页）。
 * 2. **头像不出本机**。照片存在本地数据库里，这里只是把它显示出来，不发给任何模型。
 */
import { DatabaseOutlined, UserOutlined } from "@ant-design/icons";
import { Avatar, Skeleton, Tooltip } from "antd";
import { useCallback, useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { getProfile } from "../api/profile";
import { listDatasets } from "../api/settings";
import type { Profile } from "../types";
import type { DatasetInfo } from "../types/settings";

export default function AppHeaderContext() {
  const navigate = useNavigate();
  const location = useLocation();
  const [dataset, setDataset] = useState<DatasetInfo | null>(null);
  const [datasetCount, setDatasetCount] = useState(0);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [ready, setReady] = useState(false);

  const load = useCallback(async () => {
    try {
      const [datasets, current] = await Promise.all([listDatasets(), getProfile()]);
      setDataset(datasets.find((item) => item.is_active) ?? datasets[0] ?? null);
      setDatasetCount(datasets.length);
      setProfile(current);
    } catch {
      // 页头是全局装饰：读不到就少显示一块，绝不因此让整个应用报错或白屏。
      setDataset(null);
      setProfile(null);
    } finally {
      setReady(true);
    }
  }, []);

  useEffect(() => {
    void load();
    // 换页面时重取一次：用户在设置页切了数据集、或在资料页换了照片，回来就该看到新的。
    // 两个接口都是本地读，开销可以忽略；不重取的话页头会长期显示过期信息——而它的全部
    // 价值恰恰在于"我现在在哪个数据集里"。
  }, [load, location.pathname]);

  const displayName = (profile?.name || "").trim();
  const photo = (profile?.photo || "").trim();
  const initial = displayName ? Array.from(displayName)[0] : "";

  return (
    <div className="app-header-context">
      {!ready ? (
        <Skeleton.Avatar active size={36} shape="circle" />
      ) : (
        <>
          {dataset ? (
            <Tooltip
              title={
                datasetCount > 1
                  ? `当前数据集：${dataset.name}（共 ${datasetCount} 套）。切换请到「设置 → 数据集」`
                  : "当前数据集。可以到「设置 → 数据集」新建或导入另一套"
              }
            >
              <button
                type="button"
                className="app-dataset-chip"
                onClick={() => navigate("/settings")}
                aria-label={`当前数据集：${dataset.name}`}
              >
                <DatabaseOutlined />
                <span className="app-dataset-name">{dataset.name}</span>
              </button>
            </Tooltip>
          ) : null}
          <Tooltip title={displayName ? `${displayName}（照片来自「我的资料」）` : "还没填姓名"}>
            <Avatar
              size={36}
              src={photo || undefined}
              // AntD 的 Avatar 在有 icon 时会**忽略** children，所以"姓名首字"和"兜底图标"
              // 只能二选一：有名字就用首字（更像头像），没名字才用图标。
              icon={!photo && !initial ? <UserOutlined /> : undefined}
              className="app-user-avatar"
              alt={displayName ? `${displayName}的头像` : "用户头像"}
            >
              {!photo && initial ? initial : undefined}
            </Avatar>
          </Tooltip>
        </>
      )}
    </div>
  );
}
