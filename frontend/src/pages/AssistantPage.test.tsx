import { App as AntdApp } from "antd";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type {
  AssistantConversationBrief,
  AssistantConversationDetail,
  AssistantMessage,
  AssistantSkill,
  AssistantStreamEvent,
} from "../types";
import {
  MessageAttachments,
  MessageToolCalls,
} from "../features/assistant/components/AssistantMessageContent";
import AssistantPage, {
  AssistantMessageContent,
  MessageReasoning,
  MessageSources,
  StreamingStatus,
} from "./AssistantPage";

const apiMocks = vi.hoisted(() => ({
  createAssistantConversation: vi.fn(),
  deleteAssistantConversation: vi.fn(),
  deleteAssistantMessage: vi.fn(),
  deleteAssistantMessages: vi.fn(),
  getAssistantConversation: vi.fn(),
  listAssistantConversations: vi.fn(),
  renameAssistantConversation: vi.fn(),
  updateAssistantConversation: vi.fn(),
  sendAssistantMessage: vi.fn(),
  listJobs: vi.fn(),
  listResumes: vi.fn(),
}));
const skillApiMocks = vi.hoisted(() => ({ listSkills: vi.fn() }));
const scrollIntoViewMock = vi.fn();

// 先把真实导出铺开再覆盖要断言的那几个：只列名字的话，页面一旦导入新函数（比如批量删除），
// 这个替身里就没有它，调用处会抛 "is not a function"——而报错指向的是页面代码，很难看出
// 问题出在测试替身上。
vi.mock("../api/assistant", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/assistant")>()),
  createAssistantConversation: apiMocks.createAssistantConversation,
  deleteAssistantConversation: apiMocks.deleteAssistantConversation,
  deleteAssistantMessage: apiMocks.deleteAssistantMessage,
  deleteAssistantMessages: apiMocks.deleteAssistantMessages,
  getAssistantConversation: apiMocks.getAssistantConversation,
  listAssistantConversations: apiMocks.listAssistantConversations,
  renameAssistantConversation: apiMocks.renameAssistantConversation,
  updateAssistantConversation: apiMocks.updateAssistantConversation,
  sendAssistantMessage: apiMocks.sendAssistantMessage,
}));
vi.mock("../api/jobs", () => ({ listJobs: apiMocks.listJobs }));
vi.mock("../api/resumes", () => ({ listResumes: apiMocks.listResumes }));
// 页头会取一次技能列表；不拦掉的话 jsdom 里没有 fetch，会走到真实请求上。
vi.mock("../api/skill", () => ({ listSkills: skillApiMocks.listSkills }));

const CREATED_AT = "2026-08-20T10:00:00";
const CONVERSATIONS: AssistantConversationBrief[] = [
  {
    id: 1,
    title: "会话一",
    pinned: false,
    favorite: false,
    archived: false,
    group_name: "",
    message_count: 0,
    created_at: CREATED_AT,
    updated_at: CREATED_AT,
  },
  {
    id: 2,
    title: "会话二",
    pinned: false,
    favorite: false,
    archived: false,
    group_name: "",
    message_count: 0,
    created_at: CREATED_AT,
    updated_at: CREATED_AT,
  },
];

function conversationDetail(id: number): AssistantConversationDetail {
  const conversation = CONVERSATIONS.find((item) => item.id === id);
  if (!conversation) throw new Error(`未知测试会话：${id}`);
  return { ...conversation, messages: [] };
}

function makeSkill(id: number, name: string, enabled: boolean): AssistantSkill {
  return {
    id,
    name,
    description: "",
    enabled,
    source_name: `${name}.md`,
    prompt_chars: 120,
    files: [],
    updated_at: CREATED_AT,
  };
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

function renderPage(entry = "/assistant") {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <AntdApp>
        <AssistantPage />
      </AntdApp>
    </MemoryRouter>,
  );
}

/**
 * 记录空态元素的挂载与卸载。
 *
 * "闪一下"没法用某个时刻的断言捕捉——它在任何一次 findBy 之前就已经演出完了——所以只能在
 * 渲染前开始监听 DOM，事后数它被挂载了几次。
 */
function watchEmptyState() {
  const events: string[] = [];
  const classify = (nodes: NodeList, kind: string) => {
    for (const node of Array.from(nodes)) {
      if (node instanceof HTMLElement && node.classList.contains("assistant-empty-state")) {
        events.push(kind);
      }
    }
  };
  const observer = new MutationObserver((records) => {
    for (const record of records) {
      classify(record.addedNodes, "add");
      classify(record.removedNodes, "remove");
    }
  });
  observer.observe(document.body, { childList: true, subtree: true });
  return () => {
    observer.disconnect();
    return events;
  };
}

/** 带上路径探针，用来断言"点了之后去了哪"。 */
function renderPageWithLocationProbe() {
  function LocationProbe() {
    return <span data-testid="current-path">{useLocation().pathname}</span>;
  }
  return render(
    <MemoryRouter>
      <AntdApp>
        <AssistantPage />
        <LocationProbe />
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
  apiMocks.updateAssistantConversation.mockReset().mockImplementation(async (id, patch) => ({
    ...(CONVERSATIONS.find((item) => item.id === id) ?? CONVERSATIONS[0]),
    ...patch,
  }));
  apiMocks.deleteAssistantMessage.mockReset().mockResolvedValue(undefined);
  apiMocks.deleteAssistantMessages.mockReset().mockResolvedValue({ deleted: 0 });
  apiMocks.sendAssistantMessage.mockReset().mockResolvedValue(undefined);
  apiMocks.listJobs.mockReset().mockResolvedValue({ items: [], total: 0 });
  apiMocks.listResumes.mockReset().mockResolvedValue({ items: [], total: 0 });
  skillApiMocks.listSkills.mockReset().mockResolvedValue([]);
});

afterEach(() => {
  cleanup();
  document.body.innerHTML = "";
  // 「引导对话已经给过」是持久化标记，用例之间必须清掉，否则先跑的用例会把后跑的挡住。
  window.localStorage.clear();
});

describe("助手引导对话", () => {
  it("opens an onboarding conversation the first time there is nothing else", async () => {
    apiMocks.listAssistantConversations.mockResolvedValue([]);
    renderPage();

    await waitFor(() =>
      expect(apiMocks.createAssistantConversation).toHaveBeenCalledWith("", { welcome: true }),
    );
  });

  it("does not recreate it after the user has deleted every conversation", async () => {
    // 第一次进来时已经引导过（标记落了盘），之后用户把会话全删了。
    window.localStorage.setItem("resumeforge.assistant.welcome-shown", "1");
    apiMocks.listAssistantConversations.mockResolvedValue([]);

    renderPage();
    await waitFor(() => expect(apiMocks.listAssistantConversations).toHaveBeenCalled());

    // 删掉的东西不该自己长回来：重建等于把用户删过的数据又造一份。
    await waitFor(() => expect(apiMocks.createAssistantConversation).not.toHaveBeenCalled());
  });

  it("treats a failed conversation list as unknown, not as empty", async () => {
    apiMocks.listAssistantConversations.mockRejectedValue(new Error("网络不可用"));

    renderPage();
    await waitFor(() => expect(apiMocks.listAssistantConversations).toHaveBeenCalled());

    // 取不到列表时用户可能其实有一堆会话；按"空"处理会因为一次抖动就多建一条。
    await waitFor(() => expect(apiMocks.createAssistantConversation).not.toHaveBeenCalled());
  });
});

describe("助手深链", () => {
  it("opens the shared conversation", async () => {
    renderPage("/assistant?conversation=2");

    expect(await screen.findByRole("heading", { name: "会话二" })).toBeInTheDocument();
  });

  it("prefills the composer from the ask param without sending it", async () => {
    // 工作台的「找求职助手制作」会带着 ?ask= 跳过来；这里只预填、不自动发送。
    const ask = "帮我新建一个格式模板";
    renderPage(`/assistant?ask=${encodeURIComponent(ask)}`);

    const composer = await screen.findByPlaceholderText("输入求职、岗位、简历或项目经历相关问题");
    expect(composer).toHaveValue(ask);
    // 预填只是一份草稿：不能替用户自动发起一次模型调用。
    await waitFor(() => expect(apiMocks.sendAssistantMessage).not.toHaveBeenCalled());
  });

  it("does not drag the user back after they switch away", async () => {
    let listCalls = 0;
    apiMocks.listAssistantConversations.mockImplementation(() => {
      listCalls += 1;
      // 第二次返回"刷新过的"新数组：既还原真实后端每次返回新对象的做法，
      // 也给出一个可以等待的正信号——新列表真的渲染了。
      return Promise.resolve(
        listCalls === 1
          ? [...CONVERSATIONS]
          : CONVERSATIONS.map((item) => ({ ...item, title: `${item.title}·刷新` })),
      );
    });
    renderPage("/assistant?conversation=2");
    expect(await screen.findByRole("heading", { name: "会话二" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "会话一" }));
    expect(await screen.findByRole("heading", { name: "会话一" })).toBeInTheDocument();

    // 触发一次列表刷新（收藏会重新拉列表）。深链若只靠"依赖列表"来判断，
    // 这里就会把用户拽回会话二。
    fireEvent.click(screen.getAllByRole("button", { name: "更多对话操作" })[0]);
    const actionMenu = await waitFor(() => {
      const menu = document.querySelector(".assistant-conversation-actions-menu");
      if (!menu) throw new Error("conversation action menu has not opened");
      return menu;
    });
    fireEvent.click(within(actionMenu as HTMLElement).getByText("收藏对话"));

    // 先等新列表渲染出来（侧栏标题变了）……
    await waitFor(() => expect(screen.getAllByText("会话二·刷新")[0]).toBeInTheDocument());
    // ……再把后续的异步链（effect -> 选中 -> 取详情）跑干净再断言。
    // 只断言一次"标题还是会话一"是不够的：抢焦点发生在 effect 里，晚一拍才生效，
    // 早断言会绿得毫无意义。被抢走的话这里会多出一次会话二的详情请求。
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    expect(apiMocks.getAssistantConversation).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("heading", { name: "会话一" })).toBeInTheDocument();
  });
});

describe("助手新对话入口", () => {
  it("?new=1 时新建空对话，而不是恢复最近会话或引导对话", async () => {
    renderPage("/assistant?new=1");

    await waitFor(() => expect(apiMocks.createAssistantConversation).toHaveBeenCalled());
    // 新对话不带欢迎消息；也不能被「首次引导」逻辑抢走。
    expect(apiMocks.createAssistantConversation).not.toHaveBeenCalledWith("", { welcome: true });
  });
});

describe("AssistantPage", () => {
  it("offers pinned and favorite filters and conversation actions", async () => {
    renderPage();

    await screen.findByRole("button", { name: "会话一" });
    fireEvent.click(screen.getAllByRole("button", { name: "更多对话操作" })[0]);
    const actionMenu = await waitFor(() => {
      const menu = document.querySelector(".assistant-conversation-actions-menu");
      if (!menu) throw new Error("conversation action menu has not opened");
      return menu;
    });
    // 按文案点，不按位置：菜单顺序会变，位置断言会静默指到别的操作上。
    fireEvent.click(within(actionMenu as HTMLElement).getByText("置顶对话"));

    await waitFor(() =>
      expect(apiMocks.updateAssistantConversation).toHaveBeenCalledWith(1, { pinned: true }),
    );
    expect(screen.getByRole("radio", { name: "全部" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "收藏" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "已归档" })).toBeInTheDocument();
  });

  it("offers starter prompts for an empty conversation", async () => {
    renderPage();

    expect(await screen.findByText("可以这样问")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "查找招聘信息" }));

    expect(screen.getByPlaceholderText("输入求职、岗位、简历或项目经历相关问题")).toHaveValue(
      "请帮我查找与目标方向相关的招聘信息，并优先给出官网链接。",
    );
    expect(screen.getByRole("switch", { name: "联网搜索" })).toBeChecked();
  });

  it("does not flash the empty state while the conversation is still loading", async () => {
    const delayedList = deferred<AssistantConversationBrief[]>();
    apiMocks.listAssistantConversations.mockImplementation(() => delayedList.promise);

    const stopWatching = watchEmptyState();
    renderPage();
    delayedList.resolve(CONVERSATIONS);

    expect(await screen.findByText("可以这样问")).toBeInTheDocument();
    await waitFor(() => expect(apiMocks.getAssistantConversation).toHaveBeenCalledWith(1));

    // 只挂载一次：先画引导、再被骨架屏顶掉、随后又画回来，会在这里留下 remove + add。
    expect(stopWatching()).toEqual(["add"]);
  });

  it("shows how many skills are shaping the reply", async () => {
    skillApiMocks.listSkills.mockResolvedValue([
      makeSkill(1, "面试官追问", true),
      makeSkill(2, "简历诊断", true),
      makeSkill(3, "暂时不用", false),
    ]);

    renderPage();

    // 页头那枚常驻提示已经去掉了（截图反馈：右上角不需要技能模块），数量改由输入框
    // 旁的技能按钮承担——它同时也是一键开关的入口。
    const control = await screen.findByRole("button", { name: "技能" });
    expect(control).toHaveTextContent("技能（2）");
    // 没有启用的技能不参与作答，因此不计入数量。
    expect(control).not.toHaveTextContent("3");
  });

  it("takes the user to the workbench that manages skills", async () => {
    // 一个都没启用时，空态里有直达工作台的入口（本次不再走页头那枚提示）。
    renderPageWithLocationProbe();
    fireEvent.click(await screen.findByRole("button", { name: "到技能工作台添加技能" }));

    expect(screen.getByTestId("current-path")).toHaveTextContent("/skills");
  });

  it("tells a first-time user that skills exist", async () => {
    renderPage();

    expect(await screen.findByText("到技能工作台添加技能")).toBeInTheDocument();
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
          quoted_message_id: null,
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
          quoted_message_id: null,
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

  it("truncates a long attachment name but keeps the whole one on hover", async () => {
    const longName = "一份名字特别长的参考资料，长到足以把聊天气泡顶变形的那种.txt";
    render(<MessageAttachments attachments={[{ name: longName, kind: "text", data: "正文" }]} />);

    // 截断靠 CSS（标签本身不换行），所以全名必须另有一处能看到。
    const chip = screen.getByText(longName).closest(".assistant-attachment-tag");
    expect(chip).not.toBeNull();

    fireEvent.mouseEnter(chip as HTMLElement);

    expect(await screen.findByRole("tooltip")).toHaveTextContent(longName);
  });

  it("stamps the reply being sent, before the server has a timestamp for it", async () => {
    const stream = deferred<void>();
    apiMocks.sendAssistantMessage.mockImplementation(
      async (_id: number, _payload: unknown, onEvent: (event: AssistantStreamEvent) => void) => {
        onEvent({ type: "progress", message: "正在分析" });
        await stream.promise;
      },
    );

    renderPage();
    fireEvent.change(screen.getByPlaceholderText("输入求职、岗位、简历或项目经历相关问题"), {
      target: { value: "看看这个岗位" },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送消息" }));

    // 这条消息还没写进服务端，没有 created_at；但"什么时候发的"此时就该看得见。
    await screen.findByText("看看这个岗位");
    const stamp = await waitFor(() => {
      const node = document.querySelector(".assistant-message--user .assistant-message-time");
      if (!node) throw new Error("正在发送的气泡没有时间标记");
      return node;
    });
    expect(stamp.textContent).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/);

    stream.resolve();
  });

  it("shows an accessible generating status", () => {
    render(<StreamingStatus message="正在生成回答" />);

    expect(screen.getByRole("status")).toHaveTextContent("正在生成回答");
  });

  it("keeps the reasoning collapsed until the user expands it", () => {
    render(<MessageReasoning reasoning="先看看岗位，再对比简历。" />);

    // 默认折叠：不展开就看不到正文，只有「思考过程」这个标题。
    expect(screen.queryByText("先看看岗位，再对比简历。")).not.toBeInTheDocument();
    // 展开后才显示。用 aria-label 定位，避开 antd 对两字中文标签自动插空格的问题。
    const toggle = screen.getByLabelText("思考过程");
    expect(toggle).toBeInTheDocument();
    fireEvent.click(toggle);
    expect(screen.getByText("先看看岗位，再对比简历。")).toBeInTheDocument();
  });

  it("renders nothing when there is no reasoning", () => {
    // 不开思考、或更早存下的历史消息里没有 reasoning 字段时，界面必须和加这个功能之前
    // 完全一致——不能凭空多出一个空面板（安全降级）。
    const { container } = render(<MessageReasoning reasoning="" />);
    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByLabelText("思考过程")).not.toBeInTheDocument();
  });

  it("marks a truncated reasoning so it is not passed off as the whole thing", () => {
    render(<MessageReasoning reasoning="想了一部分…" truncated />);

    fireEvent.click(screen.getByLabelText("思考过程"));
    expect(screen.getByText(/只保留了前一部分/)).toBeInTheDocument();
  });

  it("keeps web sources collapsed until the user expands them", () => {
    render(
      <MessageSources
        sources={[{ title: "招聘官网", url: "https://example.com/job", snippet: "岗位信息" }]}
      />,
    );

    expect(screen.queryByRole("link", { name: "招聘官网" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /参考来源（1）/ }));
    const sourceLink = screen.getByRole("link", { name: "招聘官网" });
    expect(sourceLink).toHaveAttribute("rel", "noopener noreferrer");
    // 外链必须在新标签页打开，否则会把用户从助手页带走、丢掉当前对话上下文。
    expect(sourceLink).toHaveAttribute("target", "_blank");
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
  it("shows what the assistant did with tools while the reply is streaming", async () => {
    const stream = deferred<void>();
    apiMocks.sendAssistantMessage.mockImplementation(
      async (_id: number, _payload: unknown, onEvent: (event: AssistantStreamEvent) => void) => {
        onEvent({
          type: "start",
          user_message_id: 1,
          assistant_message_id: 2,
          conversation_title: "新对话",
        });
        onEvent({
          type: "tool",
          name: "create_job",
          arguments: { title: "字节跳动后端实习" },
          summary: "新增岗位「字节跳动后端实习」",
          link: "/jobs",
          ok: true,
          error: "",
          changed: true,
        });
        await stream.promise;
      },
    );

    renderPage();
    fireEvent.change(screen.getByPlaceholderText("输入求职、岗位、简历或项目经历相关问题"), {
      target: { value: "帮我把这个岗位存进去" },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送消息" }));

    // 助手改动了数据这件事必须一眼可见：现在记录默认折叠了，但改动项被提到折叠标题里，
    // 所以不展开也能看到"改动了 1 项"——原来的"必须一眼可见"由标题摘要保住，而不是丢掉。
    expect(await screen.findByText(/助手做了什么（1）/)).toBeInTheDocument();
    expect(screen.getByText(/改动了 1 项/)).toBeInTheDocument();
    // 逐条明细仍在折叠面板内，展开后可见，且「前往查看」跳转不变。
    expect(screen.queryByText("新增岗位")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /助手做了什么（1）/ }));
    expect(await screen.findByText("新增岗位")).toBeInTheDocument();
    expect(screen.getByText("新增岗位「字节跳动后端实习」")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "前往查看" })).toHaveAttribute("href", "/jobs");
  });

  it("flags a tool that failed", async () => {
    const stream = deferred<void>();
    apiMocks.sendAssistantMessage.mockImplementation(
      async (_id: number, _payload: unknown, onEvent: (event: AssistantStreamEvent) => void) => {
        onEvent({
          type: "tool",
          name: "get_job",
          arguments: { job_id: 999 },
          summary: "",
          link: "",
          ok: false,
          error: "岗位 999 不存在",
          changed: false,
        });
        await stream.promise;
      },
    );

    renderPage();
    fireEvent.change(screen.getByPlaceholderText("输入求职、岗位、简历或项目经历相关问题"), {
      target: { value: "看看 999 号岗位" },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送消息" }));

    // 失败不能被折叠藏起来：失败计数写在折叠标题里，不展开也能看到出了问题。
    expect(await screen.findByText(/1 项失败/)).toBeInTheDocument();
    // 展开后能看到具体是哪一条、为什么失败。
    fireEvent.click(screen.getByRole("button", { name: /助手做了什么（1）/ }));
    expect(await screen.findByText(/失败：岗位 999 不存在/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "前往查看" })).not.toBeInTheDocument();
  });

  it("never claims data changed when a historical tool call has no changed flag", () => {
    // changed 是随功能一起加的可选字段，更早存下的历史消息里没有。缺失必须按"没改动"处理，
    // 否则折叠标题会凭空报出「改动了 1 项」——那是在替后端编造它没说过的改动。
    render(
      <MessageToolCalls
        calls={[
          {
            name: "create_job",
            arguments: { title: "历史岗位" },
            summary: "新增岗位「历史岗位」",
            link: "/jobs",
            ok: true,
            error: "",
          },
        ]}
      />,
    );

    expect(screen.getByText(/助手做了什么（1）/)).toBeInTheDocument();
    expect(screen.queryByText(/改动了/)).not.toBeInTheDocument();
    expect(screen.queryByText(/项失败/)).not.toBeInTheDocument();
  });
});

describe("消息多选删除", () => {
  function message(id: number, role: "user" | "assistant"): AssistantMessage {
    return {
      id,
      conversation_id: 1,
      role,
      content: `${role} 消息 ${id}`,
      quoted_message_id: null,
      attachments: [],
      context: {},
      status: "complete",
      error: "",
      model: "test-model",
      created_at: CREATED_AT,
    };
  }

  function detailWithMessages() {
    return {
      ...conversationDetail(1),
      messages: [message(11, "user"), message(12, "assistant")],
    };
  }

  it("deletes the checked messages in one request", async () => {
    apiMocks.getAssistantConversation.mockResolvedValue(detailWithMessages());
    renderPage();
    await screen.findByText("user 消息 11");

    fireEvent.click(screen.getByRole("button", { name: /多选/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: "选择 你的这条消息" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "选择 助手的这条消息" }));
    expect(screen.getByText("已选 2 条")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /删除所选/ }));
    // 删除不可撤销，所以中间要过一次确认弹窗。按钮只在弹窗范围内找：页面上还有一个
    // 「删除所选」也含"删除"二字。antd 会在两个汉字的按钮里插一个空格（"删 除"），
    // 所以按正则匹配。
    const confirmDialog = await screen.findByRole("dialog");
    fireEvent.click(within(confirmDialog).getByRole("button", { name: /删\s*除/ }));

    // 一次请求删完，而不是循环调单条接口——后端在一个事务里删并校验会话归属。
    await waitFor(() => expect(apiMocks.deleteAssistantMessages).toHaveBeenCalledWith(1, [11, 12]));
  });

  it("cannot delete until something is checked", async () => {
    apiMocks.getAssistantConversation.mockResolvedValue(detailWithMessages());
    renderPage();
    await screen.findByText("user 消息 11");

    fireEvent.click(screen.getByRole("button", { name: /多选/ }));

    expect(screen.getByText("已选 0 条")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /删除所选/ })).toBeDisabled();
    expect(apiMocks.deleteAssistantMessages).not.toHaveBeenCalled();
  });

  it("offers no multi-select entry for an empty conversation", async () => {
    renderPage();
    await waitFor(() => expect(apiMocks.getAssistantConversation).toHaveBeenCalled());

    // 一条消息都没有时"多选"无从选起，按钮不该出现。
    expect(screen.queryByRole("button", { name: /多选/ })).not.toBeInTheDocument();
  });

  it("leaves multi-select when the user switches conversations", async () => {
    apiMocks.getAssistantConversation.mockResolvedValue(detailWithMessages());
    renderPage();
    await screen.findByText("user 消息 11");

    fireEvent.click(screen.getByRole("button", { name: /多选/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: "选择 你的这条消息" }));
    expect(screen.getByText("已选 1 条")).toBeInTheDocument();

    // 切到另一条会话：勾着的是上一条会话的消息 id，留着会让新会话里 id 相同的消息
    // 出现在"已选"里。
    fireEvent.click(screen.getByText("会话二"));

    await waitFor(() => expect(screen.queryByText("已选 1 条")).not.toBeInTheDocument());
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  });
});
