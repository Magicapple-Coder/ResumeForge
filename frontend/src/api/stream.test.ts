import { describe, expect, it, vi } from "vitest";
import { consumeSSE, createSSEParserState, parseSSEChunk } from "./stream";

describe("parseSSEChunk", () => {
  it("parses CRLF, multiline data and an event left at EOF", () => {
    let parsed = parseSSEChunk(
      createSSEParserState(),
      'data: {"type":"delta",\r\ndata: "text":"first"}\r\n\r\ndata: tail',
    );

    expect(parsed.events).toEqual(['{"type":"delta",\n"text":"first"}']);

    parsed = parseSSEChunk(parsed.state, "", true);
    expect(parsed.events).toEqual(["tail"]);
    expect(parsed.state).toEqual(createSSEParserState());
  });

  it("keeps a CRLF delimiter intact when it is split between chunks", () => {
    const first = parseSSEChunk(createSSEParserState(), "data: one\r");
    const second = parseSSEChunk(first.state, "\n\r\n");

    expect(first.events).toEqual([]);
    expect(second.events).toEqual(["one"]);
  });
});

describe("consumeSSE", () => {
  it("decodes a UTF-8 character split across byte chunks", async () => {
    const bytes = new TextEncoder().encode('data: {"type":"delta","text":"你好"}\n\n');
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        for (const byte of bytes) controller.enqueue(Uint8Array.of(byte));
        controller.close();
      },
    });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(stream, { status: 200 })));
    const events: Array<{ type: string; text: string }> = [];

    await consumeSSE<{ type: string; text: string }>("/api/test", {}, (event) =>
      events.push(event),
    );

    expect(events).toEqual([{ type: "delta", text: "你好" }]);
  });
});
