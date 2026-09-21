/** 内推管理面板：列表 + 转化率卡 + 删除（软删）+ 状态分色 + 图片备注上传。 */
import { App as AntApp } from "antd";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ReferralPanel from "./ReferralPanel";
import { REFERRAL_STATUS_COLORS } from "../types";

const apiMocks = vi.hoisted(() => ({
  listReferrals: vi.fn(),
  getReferralStats: vi.fn(),
  createReferral: vi.fn(),
  updateReferral: vi.fn(),
  deleteReferral: vi.fn(),
  uploadReferralImage: vi.fn(),
}));

vi.mock("../api/referrals", () => apiMocks);

const ITEMS = [
  {
    id: 1,
    job_id: null,
    job_title: "",
    company: "示例公司",
    referrer_name: "张三",
    referrer_contact: "微信 zs",
    relation: "前同事",
    position: "后端开发",
    channel: "牛客",
    status: "active",
    track_id: null,
    converted: true,
    submitted_at: "",
    note: "",
    created_at: "2026-09-19T08:00:00",
    updated_at: "2026-09-19T08:00:00",
  },
];

const STATS = { total: 4, converted: 2, rate: 0.5 };

function renderPanel() {
  return render(
    <AntApp>
      <ReferralPanel jobOptions={[]} trackOptions={[]} />
    </AntApp>,
  );
}

beforeEach(() => {
  apiMocks.listReferrals.mockReset().mockResolvedValue(ITEMS);
  apiMocks.getReferralStats.mockReset().mockResolvedValue(STATS);
  apiMocks.deleteReferral.mockReset().mockResolvedValue(undefined);
});

afterEach(() => {
  cleanup();
  document.body.innerHTML = "";
});

describe("ReferralPanel", () => {
  it("渲染内推列表与转化率小卡", async () => {
    renderPanel();

    expect(await screen.findByText(/张三 · 后端开发/)).toBeInTheDocument();
    expect(screen.getByText("示例公司 · 前同事 · 牛客")).toBeInTheDocument();
    // 「已转化」既出现在转化率卡标题、也出现在列表的 Tag 上，取任一即可。
    expect(screen.getAllByText("已转化").length).toBeGreaterThan(0);
    // 转化率卡：有效内推 / 已转化 / 转化率。
    expect(screen.getByText("有效内推")).toBeInTheDocument();
    expect(screen.getByText("转化率")).toBeInTheDocument();
    expect(apiMocks.getReferralStats).toHaveBeenCalled();
  });

  it("删除先确认，确认后走软删除并刷新统计", async () => {
    renderPanel();
    await screen.findByText(/张三 · 后端开发/);

    fireEvent.click(screen.getByRole("button", { name: "更多操作 张三" }));
    fireEvent.click(await screen.findByText("删除"));

    expect(apiMocks.deleteReferral).not.toHaveBeenCalled();
    fireEvent.click(await screen.findByRole("button", { name: "OK" }));

    await waitFor(() => expect(apiMocks.deleteReferral).toHaveBeenCalledWith(1));
  });

  it("状态分色映射与列表 Tag 颜色一致", async () => {
    expect(REFERRAL_STATUS_COLORS).toEqual({
      active: "blue",
      submitted: "green",
      closed: "default",
      invalid: "red",
    });

    renderPanel();
    await screen.findByText(/张三 · 后端开发/);

    // ITEMS 里是 active → 蓝色 Tag。
    expect(screen.getByText("已联系")).toHaveClass("ant-tag-blue");
  });

  it("新增表单含内推码与图片备注上传入口", async () => {
    renderPanel();
    await screen.findByText(/张三 · 后端开发/);

    fireEvent.click(screen.getByRole("button", { name: /新增内推/ }));

    expect(await screen.findByLabelText("内推码")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /上传备注图/ })).toBeInTheDocument();
  });

  it("上传备注图后出现缩略图，可移除", async () => {
    apiMocks.uploadReferralImage.mockResolvedValue({ path: "referral_images/ab12.png" });
    renderPanel();
    await screen.findByText(/张三 · 后端开发/);

    fireEvent.click(screen.getByRole("button", { name: /新增内推/ }));
    // Modal 渲染在 body 门户里，文件输入要查 document 而不是 render 容器。
    const input = document.querySelector<HTMLInputElement>('input[type="file"]');
    expect(input).not.toBeNull();
    const file = new File(["png-bytes"], "note.png", { type: "image/png" });
    fireEvent.change(input as HTMLInputElement, { target: { files: [file] } });

    await waitFor(() => expect(apiMocks.uploadReferralImage).toHaveBeenCalledOnce());
    expect(await screen.findByAltText("备注图 1")).toHaveAttribute(
      "src",
      "/api/referrals/images/ab12.png",
    );

    fireEvent.click(screen.getByRole("button", { name: "移除备注图 1" }));
    expect(screen.queryByAltText("备注图 1")).not.toBeInTheDocument();
  });

  it("点卡片打开详情，看得到联系方式与内推码", async () => {
    apiMocks.listReferrals.mockResolvedValue([
      { ...ITEMS[0], referral_code: "REF-888", note_images: [] },
    ]);
    renderPanel();
    await screen.findByText(/张三 · 后端开发/);

    fireEvent.click(screen.getByRole("button", { name: "详情" }));

    // 列表里只有内推人/公司/渠道，联系方式与内推码只在详情里出现。
    expect(await screen.findByText("联系方式")).toBeInTheDocument();
    expect(screen.getByText("微信 zs")).toBeInTheDocument();
    expect(screen.getByText("REF-888")).toBeInTheDocument();
  });
});
