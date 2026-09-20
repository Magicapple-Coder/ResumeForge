/**
 * 求职进度页：漏斗计数、记录卡片、以及导入预览里最要紧的两件事。
 *
 * 导入这一步的风险是"用户以为没保存"和"用户以为保存了但没保存"，所以两条都测：
 * 关闭预览不能写任何数据，确认时只提交勾选的条目。
 */
import { App as AntdApp } from "antd";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Track, TrackList } from "../types";
import TrackerPage from "./TrackerPage";

const apiMocks = vi.hoisted(() => ({
  listTracks: vi.fn(),
  getTrack: vi.fn(),
  createTrack: vi.fn(),
  updateTrack: vi.fn(),
  deleteTrack: vi.fn(),
  parseTracks: vi.fn(),
  applyTracks: vi.fn(),
  exportTracks: vi.fn(),
}));

vi.mock("../api/tracker", () => apiMocks);
vi.mock("../utils/download", () => ({ downloadBlob: vi.fn(), printHtml: vi.fn() }));

function makeTrack(overrides: Partial<Track> = {}): Track {
  return {
    id: 1,
    company: "示例科技",
    title: "后端开发实习生",
    status: "applied",
    stage_note: "",
    applied_at: "2026-09-18",
    status_date: "",
    next_action: "",
    next_action_date: "",
    note: "",
    evidence: "",
    source: "apply",
    job_id: null,
    resume_id: null,
    created_at: "2026-09-18T00:00:00",
    updated_at: "2026-09-18T00:00:00",
    ...overrides,
  };
}

function makeList(items: Track[]): TrackList {
  const counts: Record<string, number> = {};
  for (const item of items) counts[item.status] = (counts[item.status] ?? 0) + 1;
  return {
    items,
    total: items.length,
    status_counts: counts,
    active_count: items.filter((item) => item.status !== "offer" && item.status !== "rejected")
      .length,
    offer_count: counts.offer ?? 0,
    rejected_count: counts.rejected ?? 0,
    month_count: items.filter((item) => item.applied_at.startsWith("2026-09")).length,
  };
}

function renderPage() {
  return render(
    <AntdApp>
      <TrackerPage />
    </AntdApp>,
  );
}

beforeEach(() => {
  for (const mock of Object.values(apiMocks)) mock.mockReset();
  apiMocks.listTracks.mockResolvedValue(makeList([]));
});

afterEach(cleanup);

describe("TrackerPage", () => {
  it("renders a record with its stage and source", async () => {
    apiMocks.listTracks.mockResolvedValue(
      makeList([makeTrack({ status: "interview", stage_note: "二面" })]),
    );
    renderPage();

    expect(await screen.findByText("示例科技")).toBeInTheDocument();
    expect(screen.getByText("后端开发实习生")).toBeInTheDocument();
    // 漏斗里也有「面试」两个字，所以这里用 getAllByText 而不是断言唯一。
    expect(screen.getAllByText("面试").length).toBeGreaterThan(0);
    expect(screen.getByText("二面")).toBeInTheDocument();
    expect(screen.getByText("投递台自动记录")).toBeInTheDocument();
  });

  it("marks a passed deadline as overdue", async () => {
    apiMocks.listTracks.mockResolvedValue(
      makeList([
        makeTrack({
          next_action: "确认面试时间",
          next_action_date: "2000-01-01",
        }),
      ]),
    );
    renderPage();

    expect(await screen.findByText(/确认面试时间/)).toBeInTheDocument();
    expect(screen.getByText(/已过期/)).toBeInTheDocument();
  });

  it("shows funnel counts drawn from the server summary", async () => {
    apiMocks.listTracks.mockResolvedValue(
      makeList([
        makeTrack({ id: 1, status: "applied" }),
        makeTrack({ id: 2, status: "interview", title: "算法实习生" }),
        makeTrack({ id: 3, status: "offer", title: "前端实习生" }),
      ]),
    );
    renderPage();

    await screen.findAllByText("示例科技");
    // 漏斗每一级都要在，哪怕是 0——少一级会让用户以为这个阶段不存在。
    for (const label of ["已投递", "筛选中", "测评/笔试", "面试", "Offer"]) {
      expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    }
  });

  it("filters by status when a funnel step is clicked", async () => {
    apiMocks.listTracks.mockResolvedValue(makeList([makeTrack({ status: "interview" })]));
    renderPage();
    await screen.findByText("示例科技");

    fireEvent.click(screen.getByRole("button", { name: /面试/ }));

    await waitFor(() => {
      expect(apiMocks.listTracks).toHaveBeenLastCalledWith({ status: "interview", keyword: "" });
    });
  });

  it("offers guidance when there is nothing yet", async () => {
    renderPage();
    expect(await screen.findByText(/还没有进度记录/)).toBeInTheDocument();
  });

  it("shows the error state rather than an empty list when loading fails", async () => {
    apiMocks.listTracks.mockRejectedValue(new Error("接口不可用"));
    renderPage();

    expect(await screen.findByText("接口不可用")).toBeInTheDocument();
    expect(screen.queryByText(/还没有进度记录/)).not.toBeInTheDocument();
  });

  it("deletes a record and reloads", async () => {
    apiMocks.listTracks.mockResolvedValue(makeList([makeTrack()]));
    apiMocks.deleteTrack.mockResolvedValue(undefined);
    renderPage();
    await screen.findByText("示例科技");

    fireEvent.click(screen.getByRole("button", { name: "更多操作 示例科技" }));
    fireEvent.click(await screen.findByText("删除"));
    // 二次确认走 modal.confirm（测试环境默认英文，确认按钮是「OK」）。
    fireEvent.click(await screen.findByRole("button", { name: "OK" }));

    await waitFor(() => expect(apiMocks.deleteTrack).toHaveBeenCalledWith(1));
  });
});

describe("TrackImportModal", () => {
  async function openImport() {
    renderPage();
    await screen.findByText(/还没有进度记录/);
    fireEvent.click(screen.getByRole("button", { name: /从通知导入/ }));
    fireEvent.change(screen.getByPlaceholderText(/按 Ctrl\+V 可以直接贴截图/), {
      target: { value: "【示例科技有限公司】您投递的「后端开发实习生」岗位已进入面试环节。" },
    });
    fireEvent.click(screen.getByRole("button", { name: /识别并预览/ }));
  }

  it("shows what will happen and why before writing anything", async () => {
    apiMocks.parseTracks.mockResolvedValue({
      items: [
        {
          record: {
            company: "示例科技",
            title: "后端开发实习生",
            status: "interview",
            stage_note: "",
            applied_at: "",
            status_date: "",
            next_action: "",
            next_action_date: "",
            note: "",
            evidence: "已进入面试环节",
          },
          action: "updated",
          reason: "「已投递」推进为「面试」",
          current_status: "applied",
        },
      ],
      parse_engine: "ai",
      notes: ["邮件里没有写投递日期"],
    });

    await openImport();

    expect(await screen.findByText("更新进度")).toBeInTheDocument();
    // 原因比结论重要：用户据此判断这条该不该勾。
    expect(screen.getByText("「已投递」推进为「面试」")).toBeInTheDocument();
    expect(screen.getByText("依据：已进入面试环节")).toBeInTheDocument();
    expect(screen.getByText(/邮件里没有写投递日期/)).toBeInTheDocument();
    // 预览阶段绝不能写数据。
    expect(apiMocks.applyTracks).not.toHaveBeenCalled();
  });

  it("submits only the checked records", async () => {
    const record = {
      company: "示例科技",
      title: "后端开发实习生",
      status: "interview" as const,
      stage_note: "",
      applied_at: "",
      status_date: "",
      next_action: "",
      next_action_date: "",
      note: "",
      evidence: "",
    };
    apiMocks.parseTracks.mockResolvedValue({
      items: [
        {
          record,
          action: "created",
          reason: "新增「示例科技 · 后端开发实习生」",
          current_status: "",
        },
        {
          record: { ...record, title: "算法实习生" },
          action: "unchanged",
          reason: "状态本来就是「面试」，没有新变化",
          current_status: "interview",
        },
      ],
      parse_engine: "local",
      notes: [],
    });
    apiMocks.applyTracks.mockResolvedValue({
      items: [],
      created: 1,
      updated: 0,
      unchanged: 0,
    });

    await openImport();
    await screen.findByText("新增记录");

    const checkboxes = screen.getAllByRole("checkbox");
    fireEvent.click(checkboxes[1]); // 取消第二条
    fireEvent.click(screen.getByRole("button", { name: /确认写入勾选的 1 条/ }));

    await waitFor(() => expect(apiMocks.applyTracks).toHaveBeenCalledTimes(1));
    const [submitted] = apiMocks.applyTracks.mock.calls[0];
    expect(submitted).toHaveLength(1);
    expect(submitted[0].title).toBe("后端开发实习生");
  });

  it("reports created and updated separately instead of a flat success", async () => {
    const record = {
      company: "示例科技",
      title: "后端开发实习生",
      status: "interview" as const,
      stage_note: "",
      applied_at: "",
      status_date: "",
      next_action: "",
      next_action_date: "",
      note: "",
      evidence: "",
    };
    apiMocks.parseTracks.mockResolvedValue({
      items: [{ record, action: "created", reason: "新增", current_status: "" }],
      parse_engine: "local",
      notes: [],
    });
    apiMocks.applyTracks.mockResolvedValue({ items: [], created: 1, updated: 2, unchanged: 0 });

    await openImport();
    await screen.findByText("新增记录");
    fireEvent.click(screen.getByRole("button", { name: /确认写入/ }));

    // 全都说成"已保存"会让用户以为每条进度都更新了。
    expect(await screen.findByText(/新增 1 条，更新 2 条/)).toBeInTheDocument();
  });
});
