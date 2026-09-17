/**
 * 面试深挖页：进行中的问答、评分契约的可见性、复盘与复练。
 *
 * 三条是这个功能的信任基础，所以逐条测：
 * 1. **契约对用户可见**——藏起来才会让人怀疑"是不是看人下菜碟"；
 * 2. **真实模拟模式下不在每题后念判定**——念了会让人按判分标准答题，而不像真面试；
 * 3. **不出现任何分数**——这个功能的全部意义就是用证据状态代替伪精确的总分。
 */
import { App as AntdApp } from "antd";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DrillSession, DrillSessionBrief } from "../types";
import DrillPage from "./DrillPage";

const apiMocks = vi.hoisted(() => ({
  listDrillSessions: vi.fn(),
  createDrillSession: vi.fn(),
  getDrillSession: vi.fn(),
  answerDrill: vi.fn(),
  finishDrill: vi.fn(),
  deleteDrillSession: vi.fn(),
  listRehearsal: vi.fn(),
  rehearse: vi.fn(),
  listClaims: vi.fn(),
  listJobs: vi.fn(),
}));

vi.mock("../api/drill", () => apiMocks);
vi.mock("../api/claims", () => ({ listClaims: apiMocks.listClaims }));
vi.mock("../api/jobs", () => ({ listJobs: apiMocks.listJobs }));

const CONTRACT = {
  id: 1,
  claim_id: 5,
  claim_title: "检索接口",
  question: "为什么用混合召回？",
  intent: "验证个人边界与技术取舍",
  required_evidence: ["说清两条召回路径各自的分工", "说明本人负责的实现范围"],
  followup_triggers: ["只罗列名词，没有数据流"],
  stop_condition: "证据齐了就结束",
  status: "not_covered" as const,
  evidence_found: [],
  missing: [],
  contradictions: [],
  followup_depth: 0,
  next_followup_kind: "",
  created_at: "2026-09-18T00:00:00",
};

function makeSession(overrides: Partial<DrillSession> = {}): DrillSession {
  return {
    id: 1,
    title: "检索平台 · 主张深挖",
    job_id: null,
    job_title: "",
    company: "",
    status: "active",
    feedback_policy: "deferred",
    max_questions: 6,
    current_index: 1,
    created_at: "2026-09-18T00:00:00",
    contracts: [CONTRACT],
    turns: [],
    review: {},
    summary: {
      questions: 1,
      verified_count: 0,
      partial_count: 0,
      unverified_count: 0,
      contradictory_count: 0,
      status_counts: {},
    },
    pending: CONTRACT,
    ...overrides,
  };
}

const BRIEF: DrillSessionBrief = {
  id: 1,
  title: "检索平台 · 主张深挖",
  job_id: null,
  job_title: "",
  company: "",
  status: "active",
  feedback_policy: "deferred",
  max_questions: 6,
  current_index: 1,
  created_at: "2026-09-18T00:00:00",
};

function renderPage() {
  return render(
    <MemoryRouter>
      <AntdApp>
        <DrillPage />
      </AntdApp>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  for (const mock of Object.values(apiMocks)) mock.mockReset();
  apiMocks.listDrillSessions.mockResolvedValue([]);
  apiMocks.listRehearsal.mockResolvedValue([]);
  apiMocks.listClaims.mockResolvedValue({
    items: [],
    total: 0,
    confirmed_count: 0,
    pending_count: 0,
    category_counts: {},
  });
  apiMocks.listJobs.mockResolvedValue({ items: [], total: 0 });
});

afterEach(cleanup);

describe("DrillPage", () => {
  it("shows the question and keeps the scoring contract visible", async () => {
    apiMocks.getDrillSession.mockResolvedValue(makeSession());
    apiMocks.listDrillSessions.mockResolvedValue([BRIEF]);
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: /继续/ }));

    expect(await screen.findByText("为什么用混合召回？")).toBeInTheDocument();
    // 契约必须能看到：用户有权知道自己在被怎么衡量。
    expect(screen.getByText(/这道题的评分标准/)).toBeInTheDocument();
    expect(screen.getByText("说清两条召回路径各自的分工")).toBeInTheDocument();
    expect(screen.getByText("只罗列名词，没有数据流")).toBeInTheDocument();
  });

  it("does not print a score anywhere", async () => {
    apiMocks.getDrillSession.mockResolvedValue(makeSession());
    apiMocks.listDrillSessions.mockResolvedValue([BRIEF]);
    const { container } = renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /继续/ }));
    await screen.findByText("为什么用混合召回？");

    // 这个功能的全部意义就是用证据状态代替伪精确的总分。
    expect(container.textContent).not.toMatch(/\d+\s*分/);
  });

  it("submits an answer and shows the next question", async () => {
    apiMocks.getDrillSession.mockResolvedValue(makeSession());
    apiMocks.listDrillSessions.mockResolvedValue([BRIEF]);
    apiMocks.answerDrill.mockResolvedValue({
      status: "partial",
      evidence_found: ["说明了分工"],
      missing: ["没有说明本人负责的范围"],
      contradictions: [],
      feedback: "",
      finished: false,
      session: makeSession({
        current_index: 2,
        turns: [
          {
            id: 1,
            contract_id: 1,
            question: "为什么用混合召回？",
            answer: "因为关键词召回不够。",
            status: "partial",
            feedback: "还差个人边界",
            created_at: "2026-09-18T00:01:00",
          },
        ],
        pending: { ...CONTRACT, question: "这块具体是谁写的？", followup_depth: 1 },
      }),
    });

    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /继续/ }));
    await screen.findByText("为什么用混合召回？");

    fireEvent.change(screen.getByPlaceholderText(/照实说你做过什么/), {
      target: { value: "因为关键词召回不够。" },
    });
    fireEvent.click(screen.getByRole("button", { name: /提交回答/ }));

    expect(await screen.findByText("这块具体是谁写的？")).toBeInTheDocument();
    expect(apiMocks.answerDrill).toHaveBeenCalledWith(1, "因为关键词召回不够。");
    // 上一轮的记录要能回看。
    expect(screen.getByText(/逐轮记录/)).toBeInTheDocument();
  });

  it("keeps the verdict quiet in deferred mode", async () => {
    apiMocks.getDrillSession.mockResolvedValue(makeSession());
    apiMocks.listDrillSessions.mockResolvedValue([BRIEF]);
    apiMocks.answerDrill.mockResolvedValue({
      status: "partial",
      evidence_found: [],
      missing: ["没有说明本人负责的范围"],
      contradictions: [],
      feedback: "",
      finished: false,
      session: makeSession({
        pending: { ...CONTRACT, question: "再想想？", followup_depth: 1 },
      }),
    });

    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /继续/ }));
    await screen.findByText("为什么用混合召回？");
    fireEvent.change(screen.getByPlaceholderText(/照实说你做过什么/), {
      target: { value: "答了一版。" },
    });
    fireEvent.click(screen.getByRole("button", { name: /提交回答/ }));

    await screen.findByText("再想想？");
    // 判定本身如实显示（界面不撒谎），但**不念"还缺什么"**——那等于把判分标准念出来，
    // 会让人按标准答题而不像真面试。
    expect(screen.getByText(/上一轮判定：部分验证/)).toBeInTheDocument();
    expect(screen.getByText(/真实模拟模式：判定已记录/)).toBeInTheDocument();
    expect(screen.queryByText(/还缺：没有说明本人负责的范围/)).not.toBeInTheDocument();
  });

  it("shows the feedback in training mode", async () => {
    apiMocks.getDrillSession.mockResolvedValue(makeSession({ feedback_policy: "immediate" }));
    apiMocks.listDrillSessions.mockResolvedValue([BRIEF]);
    apiMocks.answerDrill.mockResolvedValue({
      status: "partial",
      evidence_found: [],
      missing: ["没有说明本人负责的范围"],
      contradictions: [],
      feedback: "还差个人边界",
      finished: false,
      session: makeSession({
        feedback_policy: "immediate",
        pending: { ...CONTRACT, question: "再想想？", followup_depth: 1 },
      }),
    });

    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /继续/ }));
    await screen.findByText("为什么用混合召回？");
    fireEvent.change(screen.getByPlaceholderText(/照实说你做过什么/), {
      target: { value: "答了一版。" },
    });
    fireEvent.click(screen.getByRole("button", { name: /提交回答/ }));

    expect(await screen.findByText("还差个人边界")).toBeInTheDocument();
    expect(screen.getByText(/还缺：没有说明本人负责的范围/)).toBeInTheDocument();
  });

  it("renders the review with actions and rehearsal when finished", async () => {
    apiMocks.getDrillSession.mockResolvedValue(
      makeSession({
        status: "finished",
        pending: null,
        review: {
          covered: "本轮覆盖了 1 条主张。",
          verified_summary: "讲得清的有：检索接口",
          gaps_summary: "还没站住的有：数据清洗",
          actions: [{ claim_title: "数据清洗", kind: "补事实", detail: "补上数据来源与规模" }],
          rehearsal: [{ claim_title: "数据清洗", kind: "evidence", why: "说不清口径" }],
        },
      }),
    );
    apiMocks.listDrillSessions.mockResolvedValue([{ ...BRIEF, status: "finished" }]);
    apiMocks.listRehearsal.mockResolvedValue([
      { claim_title: "数据清洗", kind: "evidence", why: "说不清口径", kind_label: "证据题" },
    ]);

    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /看复盘/ }));

    expect(await screen.findByText("本轮覆盖了 1 条主张。")).toBeInTheDocument();
    expect(screen.getByText("面试前的行动清单")).toBeInTheDocument();
    expect(screen.getByText("补上数据来源与规模")).toBeInTheDocument();
    // 行动项要写清"这一类该怎么做"，否则"补事实"三个字等于没说。
    expect(screen.getByText(/去把当时的决策、难点、口径补上/)).toBeInTheDocument();
    expect(await screen.findByText("证据题")).toBeInTheDocument();
  });

  it("generates a fresh rehearsal question without recording it", async () => {
    apiMocks.getDrillSession.mockResolvedValue(
      makeSession({ status: "finished", pending: null, review: { rehearsal: [] } }),
    );
    apiMocks.listDrillSessions.mockResolvedValue([{ ...BRIEF, status: "finished" }]);
    apiMocks.listRehearsal.mockResolvedValue([
      { claim_title: "数据清洗", kind: "variant", why: "缺口径", kind_label: "变体题" },
    ]);
    apiMocks.rehearse.mockResolvedValue({
      claim_title: "数据清洗",
      kind: "variant",
      question: "如果数据量翻一百倍，你的清洗流程还成立吗？",
      expect: "说明扩展限制",
    });

    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /看复盘/ }));
    fireEvent.click(await screen.findByRole("button", { name: /出一道/ }));

    expect(
      await screen.findByText("如果数据量翻一百倍，你的清洗流程还成立吗？"),
    ).toBeInTheDocument();
    // 出题不落库——文案要说清这一点。
    expect(screen.getByText(/不会计入这一场的记录/)).toBeInTheDocument();
  });

  it("offers guidance when there is no history", async () => {
    renderPage();
    expect(await screen.findByText(/还没有深挖记录/)).toBeInTheDocument();
  });

  it("opens the start dialog and explains that the standard is locked first", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /开始深挖/ }));

    expect(await screen.findByText(/先定标准，再提问/)).toBeInTheDocument();
    // 这句话是这个功能的信任基础：标准在看到回答之前就定下来。
    expect(screen.getByText(/在你看到问题\*\*之前\*\*定下来/)).toBeInTheDocument();
    // 页头也提到了"不评总分"，所以用 getAllByText。
    expect(screen.getAllByText(/不评总分/).length).toBeGreaterThan(0);
    expect(screen.getByText(/它回答的是「这条主张我讲不讲得清/)).toBeInTheDocument();
  });

  it("says how to get confirmed claims when the ledger has none", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /开始深挖/ }));

    expect(await screen.findByText(/还没有「已确认」的条目/)).toBeInTheDocument();
    // 不能只给个空下拉——要告诉用户去哪儿确认。
    expect(screen.getByText(/先去「事实台账」确认几条/)).toBeInTheDocument();
  });
});
