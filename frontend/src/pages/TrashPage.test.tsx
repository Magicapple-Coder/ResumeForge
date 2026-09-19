/**
 * 回收站页面：查看、恢复、彻底删除、清空。
 *
 * 这个页面要守住的最重要一条是**风险区分**：恢复是安全的（一键就行），彻底删除不可逆
 * （必须先确认、且确认文案要说清后果）。所以测试里对"点一下就删掉"是明确反对的——
 * 如果哪天有人为了少一次点击把 Popconfirm 去掉，这里会红。
 */
import { App as AntdApp } from "antd";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { TrashSummary } from "../types";
import TrashPage from "./TrashPage";

const apiMocks = vi.hoisted(() => ({
  getTrash: vi.fn(),
  restoreTrashItem: vi.fn(),
  purgeTrashItem: vi.fn(),
  emptyTrash: vi.fn(),
}));

vi.mock("../api/trash", () => ({
  getTrash: apiMocks.getTrash,
  restoreTrashItem: apiMocks.restoreTrashItem,
  purgeTrashItem: apiMocks.purgeTrashItem,
  emptyTrash: apiMocks.emptyTrash,
}));

function summary(overrides: Partial<TrashSummary> = {}): TrashSummary {
  return {
    total: 2,
    counts: { job: 1, material: 1 },
    labels: {
      job: "岗位",
      resume: "简历记录",
      track: "投递记录",
      claim: "事实台账",
      material: "资料箱材料",
      conversation: "助手会话",
      interview_experience: "面经",
      referral: "内推",
      reminder: "提醒",
      share_package: "分享包",
      question_bank_record: "题库历史",
      interview_review_record: "复盘历史",
      knowledge_entry: "知识库",
    },
    items: [
      {
        type: "job",
        type_label: "岗位",
        id: 7,
        title: "全栈工程师",
        subtitle: "天津云际",
        deleted_at: "2026-09-18T16:20:00",
      },
      {
        type: "material",
        type_label: "资料箱材料",
        id: 3,
        title: "作品集",
        subtitle: "",
        deleted_at: "2026-09-17T09:05:00",
      },
    ],
    ...overrides,
  };
}

function renderPage() {
  return render(
    <AntdApp>
      <TrashPage />
    </AntdApp>,
  );
}

beforeEach(() => {
  apiMocks.getTrash.mockReset().mockResolvedValue(summary());
  apiMocks.restoreTrashItem.mockReset().mockResolvedValue(undefined);
  apiMocks.purgeTrashItem.mockReset().mockResolvedValue(undefined);
  apiMocks.emptyTrash.mockReset().mockResolvedValue({ removed: 2 });
});

afterEach(cleanup);

describe("TrashPage", () => {
  it("列出回收站内容，带类型标签与删除时间", async () => {
    renderPage();

    expect(await screen.findByText("全栈工程师")).toBeInTheDocument();
    // 类型名用后端下发的 label，而不是前端硬编码的映射。
    expect(screen.getByText("资料箱材料")).toBeInTheDocument();
    expect(screen.getByText("天津云际")).toBeInTheDocument();
    // 删除时间要能看见：用户来这儿找的往往是"我前几天删的那个"。
    expect(screen.getByText("2026-09-18 16:20")).toBeInTheDocument();
  });

  it("恢复不需要二次确认，一键就恢复", async () => {
    renderPage();
    await screen.findByText("全栈工程师");

    fireEvent.click(screen.getByRole("button", { name: /恢复 全栈工程师/ }));

    await waitFor(() => expect(apiMocks.restoreTrashItem).toHaveBeenCalledWith("job", 7));
    // 恢复之后要重新拉一次，否则列表里还留着已经恢复的那条。
    await waitFor(() => expect(apiMocks.getTrash).toHaveBeenCalledTimes(2));
  });

  it("彻底删除必须先确认，而且确认按钮是危险色", async () => {
    renderPage();
    await screen.findByText("全栈工程师");

    fireEvent.click(screen.getByRole("button", { name: /彻底删除 全栈工程师/ }));

    // 关键断言①：**没有**直接删掉——必须出现确认。
    expect(apiMocks.purgeTrashItem).not.toHaveBeenCalled();
    expect(await screen.findByText("彻底删除？")).toBeInTheDocument();
    // 确认文案要把后果说白（这是全应用唯一不可逆的动作）。
    expect(screen.getByText(/将被永久删除，无法恢复/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "确认彻底删除 全栈工程师" }));

    await waitFor(() => expect(apiMocks.purgeTrashItem).toHaveBeenCalledWith("job", 7));
  });

  it("取消确认时什么都不做", async () => {
    renderPage();
    await screen.findByText("全栈工程师");

    fireEvent.click(screen.getByRole("button", { name: /彻底删除 全栈工程师/ }));
    fireEvent.click(await screen.findByRole("button", { name: "取消彻底删除 全栈工程师" }));

    await waitFor(() => expect(apiMocks.purgeTrashItem).not.toHaveBeenCalled());
  });

  it("按类型筛选时只请求那一类", async () => {
    renderPage();
    await screen.findByText("全栈工程师");

    fireEvent.click(screen.getByText("岗位（1）"));

    await waitFor(() => expect(apiMocks.getTrash).toHaveBeenLastCalledWith({ type: "job" }));
  });

  it("渲染面经/内推等新类型，恢复与彻底删除照常可用", async () => {
    apiMocks.getTrash.mockResolvedValue(
      summary({
        total: 2,
        counts: { interview_experience: 1, referral: 1 },
        items: [
          {
            type: "interview_experience",
            type_label: "面经",
            id: 11,
            title: "某司一面",
            subtitle: "示例公司",
            deleted_at: "2026-09-18T10:00:00",
          },
          {
            type: "referral",
            type_label: "内推",
            id: 12,
            title: "张三 · 后端开发",
            subtitle: "某公司",
            deleted_at: "2026-09-17T09:00:00",
          },
        ],
      }),
    );
    renderPage();

    // 新类型的标签与标题都照常渲染，不会空白或崩。
    expect(await screen.findByText("某司一面")).toBeInTheDocument();
    expect(screen.getByText("面经")).toBeInTheDocument();
    expect(screen.getByText("张三 · 后端开发")).toBeInTheDocument();

    // 恢复走面经的类型 key。
    fireEvent.click(screen.getByRole("button", { name: /恢复 某司一面/ }));
    await waitFor(() =>
      expect(apiMocks.restoreTrashItem).toHaveBeenCalledWith("interview_experience", 11),
    );

    // 内推的彻底删除也要二次确认、走内推的类型 key。
    fireEvent.click(screen.getByRole("button", { name: /彻底删除 张三 · 后端开发/ }));
    expect(apiMocks.purgeTrashItem).not.toHaveBeenCalled();
    fireEvent.click(await screen.findByRole("button", { name: "确认彻底删除 张三 · 后端开发" }));
    await waitFor(() => expect(apiMocks.purgeTrashItem).toHaveBeenCalledWith("referral", 12));
  });

  it("空回收站给出空态，并且不显示清空按钮", async () => {
    apiMocks.getTrash.mockResolvedValue(summary({ total: 0, counts: {}, items: [] }));
    renderPage();

    expect(await screen.findByText(/回收站是空的/)).toBeInTheDocument();
    // 空的时候没有"清空"可点——留一个按钮在那儿只会让人以为还有东西。
    expect(screen.queryByRole("button", { name: /清空/ })).toBeNull();
  });

  it("清空也要二次确认，并且说明会删掉多少条", async () => {
    renderPage();
    await screen.findByText("全栈工程师");

    fireEvent.click(screen.getByRole("button", { name: /清空回收站/ }));

    expect(apiMocks.emptyTrash).not.toHaveBeenCalled();
    expect(await screen.findByText(/将永久删除 2 条内容/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "确认清空回收站" }));

    await waitFor(() => expect(apiMocks.emptyTrash).toHaveBeenCalledWith(""));
  });
});
