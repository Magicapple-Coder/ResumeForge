import { App as AntdApp } from "antd";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type {
  AssistantConversationBrief,
  AssistantConversationDetail,
  AssistantStreamEvent,
} from "../types";
import AssistantPage, {
  AssistantMessageContent,
  MessageSources,
  StreamingStatus,
} from "./AssistantPage";

const apiMocks = vi.hoisted(() => ({
  createAssistantConversation: vi.fn(),
  deleteAssistantConversation: vi.fn(),
  getAssistantConversation: vi.fn(),
  listAssistantConversations: vi.fn(),
  renameAssistantConversation: vi.fn(),
  sendAssistantMessage: vi.fn(),
  listJobs: vi.fn(),
  listResumes: vi.fn(),
}));
const scrollIntoViewMock = vi.fn();

vi.mock("../api/assistant", () => ({
  createAssistantConversation: apiMocks.createAssistantConversation,
  deleteAssistantConversation: apiMocks.deleteAssistantConversation,
  getAssistantConversation: apiMocks.getAssistantConversation,
  listAssistantConversations: apiMocks.listAssistantConversations,
  renameAssistantConversation: apiMocks.renameAssistantConversation,
  sendAssistantMessage: apiMocks.sendAssistantMessage,
}));
vi.mock("../api/jobs", () => ({ listJobs: apiMocks.listJobs }));
vi.mock("../api/resumes", () => ({ listResumes: apiMocks.listResumes }));

const CREATED_AT = "2026-08-20T10:00:00";
const CONVERSATIONS: AssistantConversationBrief[] = [
  { id: 1, title: "会话一", created_at: CREATED_AT, updated_at: CREATED_AT },
  { id: 2, title: "会话二", created_at: CREATED_AT, updated_at: CREATED_AT },
];

function conversationDetail(id: number): AssistantConversationDetail {
  const conversation = CONVERSATIONS.find((item) => item.id === id);
  if (!conversation) throw new Error(`未知测试会话：${id}`);
  return { ...conversation, messages: [] };
}

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function renderPage() {
  return render(
    <MemoryRouter>
      <AntdApp>
        <AssistantPage />
      </AntdApp>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
    configurable: true,
    value: scrollIntoViewMock,
  });
  scrollIntoViewMock.mockReset();
  apiMocks.listAssistantConversations.mockReset().mockResolvedValue(CONVERSATIONS);
  apiMocks.getAssistantConversation
    .mockReset()
    .mockImplementation((id: number) => Promise.resolve(conversationDetail(id)));
  apiMocks.createAssistantConversation.mockReset().mockResolvedValue(CONVERSATIONS[0]);
  apiMocks.deleteAssistantConversation.mockReset().mockResolvedValue(undefined);
  apiMocks.renameAssistantConversation.mockReset();
  apiMocks.sendAssistantMessage.mockReset().mockResolvedValue(undefined);
  apiMocks.listJobs.mockReset().mockResolvedValue({ items: [], total: 0 });
  apiMocks.listResumes.mockReset().mockResolvedValue({ items: [], total: 0 });
});

afterEach(() => {
  cleanup();
  document.body.innerHTML = "";
});

describe("AssistantPage", () => {
  it("offers starter prompts for an empty conversation", async () => {
    renderPage();

    expect(await screen.findByText("可以这样问")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "查找招聘信息" }));

    expect(screen.getByPlaceholderText("输入求职、岗位、简历或项目经历相关问题")).toHaveValue(
      "请帮我查找与目标方向相关的招聘信息，并优先给出官网链接。",
    );
    expect(screen.getByRole("switch", { name: "联网搜索" })).toBeChecked();
  });

  it("keeps loaded messages visible while refreshing the active conversation", async () => {
    const refreshedDetail = deferred<AssistantConversationDetail>();
    const loadedDetail: AssistantConversationDetail = {
      ...conversationDetail(1),
      messages: [
        {
          id: 1,
          conversation_id: 1,
          role: "assistant",
          content: "已加载的回复",
          attachments: [],
          context: {},
          status: "complete",
          error: "",
          model: "test-model",
          created_at: CREATED_AT,
        },
      ],
    };
    let detailRequests = 0;
    apiMocks.getAssistantConversation.mockImplementation(() => {
      detailRequests += 1;
      return detailRequests === 1 ? Promise.resolve(loadedDetail) : refreshedDetail.promise;
    });

    renderPage();
    expect(await screen.findByText("已加载的回复")).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText("输入求职、岗位、简历或项目经历相关问题"), {
      target: { value: "继续分析" },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送消息" }));

    await waitFor(() => expect(detailRequests).toBe(2));
    expect(screen.getByText("已加载的回复")).toBeInTheDocument();
    expect(document.querySelector(".assistant-messages .ant-skeleton")).not.toBeInTheDocument();

    refreshedDetail.resolve(loadedDetail);
  });

  it("positions a loaded conversation at the latest message without smooth scrolling", async () => {
    const delayedDetail = deferred<AssistantConversationDetail>();
    apiMocks.getAssistantConversation.mockImplementation(() => delayedDetail.promise);

    renderPage();
    await waitFor(() => expect(apiMocks.getAssistantConversation).toHaveBeenCalledWith(1));
    expect(scrollIntoViewMock).not.toHaveBeenCalled();

    delayedDetail.resolve({
      ...conversationDetail(1),
      messages: [
        {
          id: 1,
          conversation_id: 1,
          role: "assistant",
          content: "最新回复",
          attachments: [],
          context: {},
          status: "complete",
          error: "",
          model: "test-model",
          created_at: CREATED_AT,
        },
      ],
    });

    expect(await screen.findByText("最新回复")).toBeInTheDocument();
    await waitFor(() =>
      expect(scrollIntoViewMock).toHaveBeenCalledWith({ behavior: "auto", block: "end" }),
    );
    expect(scrollIntoViewMock).not.toHaveBeenCalledWith(
      expect.objectContaining({ behavior: "smooth" }),
    );
  });

  it("renders assistant Markdown as structured, safe content", () => {
    render(
      <AssistantMessageContent
        content={
          "## 投递建议\n\n**先确认招聘政策**\n- 保留投递记录\n1. 关注官网说明\n查看 [招聘官网](https://careers.example.com/faq)、https://jobs.example.com 与 `冷却期`。"
        }
      />,
    );

    expect(screen.getByRole("heading", { name: "投递建议" })).toBeInTheDocument();
    expect(screen.getByText("先确认招聘政策").tagName).toBe("STRONG");
    expect(screen.getByText("保留投递记录")).toBeInTheDocument();
    expect(screen.getByText("关注官网说明")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "招聘官网" })).toHaveAttribute(
      "rel",
      "noopener noreferrer",
    );
    expect(screen.getByRole("link", { name: "https://jobs.example.com" })).toHaveAttribute(
      "href",
      "https://jobs.example.com/",
    );
    expect(screen.getByText("冷却期").tagName).toBe("CODE");
  });

  it("renders standard Markdown tables with accessible headers and cells", () => {
    render(
      <AssistantMessageContent content={"| 阶段 | 建议 |\n| --- | --- |\n| 网申 | 关注官网 |"} />,
    );

    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "阶段" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "网申" })).toBeInTheDocument();
  });

  it("shows an accessible generating status", () => {
    render(<StreamingStatus message="正在生成回答" />);

    expect(screen.getByRole("status")).toHaveTextContent("正在生成回答");
  });

  it("keeps web sources collapsed until the user expands them", () => {
    render(
      <MessageSources
        sources={[{ title: "招聘官网", url: "https://example.com/job", snippet: "岗位信息" }]}
      />,
    );

    expect(screen.queryByRole("link", { name: "招聘官网" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /参考来源（1）/ }));
    expect(screen.getByRole("link", { name: "招聘官网" })).toHaveAttribute(
      "rel",
      "noopener noreferrer",
    );
  });

  it("shows conversation management only after opening the more-actions menu", async () => {
    renderPage();
    await screen.findByRole("button", { name: "会话一" });

    expect(screen.queryByRole("button", { name: /重命名/ })).not.toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "更多对话操作" })[0]);
    fireEvent.click(await screen.findByRole("button", { name: /重命名/ }));

    expect(await screen.findByDisplayValue("会话一")).toBeInTheDocument();
  }, 10_000);

  it("keeps the latest conversation when an older detail request finishes late", async () => {
    const firstRequest = deferred<AssistantConversationDetail>();
    apiMocks.getAssistantConversation.mockImplementation((id: number) =>
      id === 1 ? firstRequest.promise : Promise.resolve(conversationDetail(id)),
    );

    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "会话二" }));

    expect(await screen.findByRole("heading", { name: "会话二" })).toBeInTheDocument();
    firstRequest.resolve(conversationDetail(1));

    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "会话二" })).toBeInTheDocument(),
    );
    expect(screen.queryByRole("heading", { name: "会话一" })).not.toBeInTheDocument();
  });

  it("isolates a streaming reply from a conversation selected while it is running", async () => {
    const stream = deferred<void>();
    let emit: ((event: AssistantStreamEvent) => void) | undefined;
    apiMocks.sendAssistantMessage.mockImplementation(
      async (_id: number, _payload: unknown, onEvent: (event: AssistantStreamEvent) => void) => {
        emit = onEvent;
        onEvent({ type: "progress", message: "正在分析岗位" });
        onEvent({ type: "delta", text: "旧会话回复" });
        onEvent({
          type: "sources",
          sources: [{ title: "招聘官网", url: "https://example.com/job", snippet: "岗位信息" }],
          error: "",
        });
        await stream.promise;
      },
    );

    renderPage();
    expect(await screen.findByRole("heading", { name: "会话一" })).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText("输入求职、岗位、简历或项目经历相关问题"), {
      target: { value: "分析这份岗位" },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送消息" }));

    expect(await screen.findByText("旧会话回复")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "招聘官网" })).not.toBeInTheDocument();
    expect(screen.getByText("参考来源（1）")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "会话二" }));
    expect(await screen.findByRole("heading", { name: "会话二" })).toBeInTheDocument();
    expect(screen.queryByText("旧会话回复")).not.toBeInTheDocument();
    emit?.({ type: "delta", text: "仍属于旧会话" });
    expect(screen.queryByText("仍属于旧会话")).not.toBeInTheDocument();

    stream.resolve();
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "停止生成" })).not.toBeInTheDocument(),
    );
    expect(screen.getByPlaceholderText("输入求职、岗位、简历或项目经历相关问题")).toBeEnabled();
    expect(screen.getByRole("heading", { name: "会话二" })).toBeInTheDocument();
    expect(apiMocks.getAssistantConversation).toHaveBeenLastCalledWith(2);
  }, 10_000);

  it("prevents duplicate sends and aborts the active request", async () => {
    let signal: AbortSignal | undefined;
    apiMocks.sendAssistantMessage.mockImplementation(
      (
        _id: number,
        _payload: unknown,
        _onEvent: (event: AssistantStreamEvent) => void,
        nextSignal: AbortSignal,
      ) => {
        signal = nextSignal;
        return new Promise<void>((_resolve, reject) => {
          nextSignal.addEventListener("abort", () =>
            reject(new DOMException("aborted", "AbortError")),
          );
        });
      },
    );

    renderPage();
    await waitFor(() => expect(apiMocks.getAssistantConversation).toHaveBeenCalledWith(1));
    fireEvent.change(screen.getByPlaceholderText("输入求职、岗位、简历或项目经历相关问题"), {
      target: { value: "请给我建议" },
    });
    const sendButton = screen.getByRole("button", { name: "发送消息" });
    fireEvent.click(sendButton);
    fireEvent.click(sendButton);

    expect(apiMocks.sendAssistantMessage).toHaveBeenCalledOnce();
    fireEvent.click(await screen.findByRole("button", { name: "停止生成" }));
    expect(signal?.aborted).toBe(true);
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "停止生成" })).not.toBeInTheDocument(),
    );
    expect(screen.getByPlaceholderText("输入求职、岗位、简历或项目经历相关问题")).toBeEnabled();
  });

  it("aborts an active stream when the page unmounts", async () => {
    let signal: AbortSignal | undefined;
    apiMocks.sendAssistantMessage.mockImplementation(
      (
        _id: number,
        _payload: unknown,
        _onEvent: (event: AssistantStreamEvent) => void,
        nextSignal: AbortSignal,
      ) => {
        signal = nextSignal;
        return new Promise<void>((_resolve, reject) => {
          nextSignal.addEventListener("abort", () =>
            reject(new DOMException("aborted", "AbortError")),
          );
        });
      },
    );

    const view = renderPage();
    await waitFor(() => expect(apiMocks.getAssistantConversation).toHaveBeenCalledWith(1));
    fireEvent.change(screen.getByPlaceholderText("输入求职、岗位、简历或项目经历相关问题"), {
      target: { value: "保持连接" },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送消息" }));
    await waitFor(() => expect(apiMocks.sendAssistantMessage).toHaveBeenCalledOnce());

    view.unmount();

    expect(signal?.aborted).toBe(true);
  });

  it("reserves attachment slots while files are still being read", async () => {
    const reads = Array.from({ length: 5 }, () => deferred<string>());
    const textReaders = reads.map((read) => vi.fn(() => read.promise));
    const files = reads.map((_, index) => {
      const file = new File([`content-${index}`], `attachment-${index + 1}.txt`, {
        type: "text/plain",
      });
      Object.defineProperty(file, "text", {
        configurable: true,
        value: textReaders[index],
      });
      return file;
    });

    const view = renderPage();
    fireEvent.change(screen.getByPlaceholderText("输入求职、岗位、简历或项目经历相关问题"), {
      target: { value: "分析附件" },
    });
    expect(screen.getByRole("button", { name: "发送消息" })).toBeEnabled();
    fireEvent.change(view.container.querySelector('input[type="file"]') as HTMLInputElement, {
      target: { files },
    });

    await waitFor(() => expect(screen.getByRole("button", { name: "添加附件" })).toBeDisabled());
    expect(screen.getByRole("button", { name: "发送消息" })).toBeDisabled();
    reads.forEach((read) => read.resolve("附件内容"));

    expect(await screen.findByText("attachment-1.txt")).toBeInTheDocument();
    expect(screen.getByText("attachment-4.txt")).toBeInTheDocument();
    expect(screen.queryByText("attachment-5.txt")).not.toBeInTheDocument();
    expect(textReaders[4]).not.toHaveBeenCalled();
  });

  it("rejects a supported MIME type when its filename extension is unsafe", async () => {
    const view = renderPage();
    const disguisedFile = new File(["not executable"], "resume.exe", { type: "text/plain" });

    fireEvent.change(view.container.querySelector('input[type="file"]') as HTMLInputElement, {
      target: { files: [disguisedFile] },
    });

    expect(
      await screen.findByText("附件扩展名与文件类型不一致，或格式不受支持"),
    ).toBeInTheDocument();
    expect(screen.queryByText("resume.exe")).not.toBeInTheDocument();
    expect(apiMocks.sendAssistantMessage).not.toHaveBeenCalled();
  });
});
