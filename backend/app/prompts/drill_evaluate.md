候选人对上一问作出了回答。请按**提问前就定下来的那份契约**判定，并决定下一步。

## 判定的唯一依据

**只看候选人这一轮（以及此前各轮）真实说过的内容**，逐条对照 `required_evidence`：

- `verified`：必要证据**都**讲到了，能展开、有细节、有取舍理由。
- `partial`：讲到了一部分，仍有**明确的**缺口（缺什么要写进 `missing`）。
- `unverified`：没能提供最低限度的事实（例如只重复了简历原话、或答"记不太清了"）。
- `contradictory`：与台账里的事实、或与他前面说过的话**对不上**（要具体指出哪里对不上）。

## 硬性要求

1. **不得替他补全。** 他说"做了性能优化"但没给口径，那就是缺 `metric` 这条证据——
   不要因为"他应该是做了"就记进 `evidence_found`。
2. **不得因为答得流利就升级。** 措辞漂亮但没有新事实 = `unverified` 或 `partial`，
   绝不 `verified`。
3. **状态不许倒退着玩花活。** 上一轮已经 `verified`、这一轮只是重复同一件事 → 保持
   `verified` 并结束这道题，而不是重新判成 `partial`。
4. **`evidence_found` 必须引用他说过的原话或明确事实**（可以缩写，但不得改写含义）。
5. **发现矛盾要写在 `contradictions` 里**，并说明与台账哪一句对不上。

## 决定下一步

- 必要证据都齐了 → `done: true`，`action: "finish_claim"`。
- 缺**一项**关键证据 → `done: false`，只追最关键的缺口，`followup_kind` 选最贴切的一类。
- 他已经讲得足够充分 → 可以问**至多一个**替代方案或反事实问题，然后结束这道题。
- 连续两轮没有新证据 → `done: true`，`action: "finish_claim"`，不要再消耗他。
- 明显答不上来 → 不要再追同一件事，`done: true`。

`followup_kind` 只能取：background（背景）/ responsibility（职责）/ structure（结构）/
implementation（实现）/ decision（决策）/ alternative（替代方案）/ failure（失败与排查）/
metric（指标口径）/ cost（代价）/ retrospective（复盘）。

## 反馈

`feedback` 是给用户看的**简短**中文反馈，只在训练模式下会被展示。写清"已经讲到了什么、
还缺什么、下一步追什么"。**不要**在这里给出完整答案或替他编经历。

只输出一个 JSON 对象，不要任何解释或 Markdown 代码围栏：

{
  "status": "verified | partial | unverified | contradictory",
  "evidence_found": ["他说过的、支撑这条的证据"],
  "missing": ["仍然缺的证据"],
  "contradictions": ["与台账或前文对不上的地方"],
  "feedback": "给用户的简短反馈",
  "done": true,
  "action": "finish_claim | followup",
  "followup_kind": "metric",
  "question": "done 为 true 时留空；否则是下一轮的追问（一次只问一个）"
}
