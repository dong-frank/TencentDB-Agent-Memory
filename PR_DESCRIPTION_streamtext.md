## 标题

fix(core): MemoryCore 工具模式的 LLM 调用改用 `streamText`（流式），修复 `copilot.tencent.com/v2` 网关拒绝非流式请求导致 L2/L3 场景提取失败

## 摘要

MemoryCore 在工具模式（`tools=true`，用于 L2/L3 场景提取）下调用 LLM 时使用的是 **`generateText`（非流式）**，而被调用的 LLM 网关 `copilot.tencent.com/v2` **拒绝非流式** `chat/completions` 请求（返回 `code 11101` / `Bad Request`）。这导致每次场景提取在约 1 秒内抛错失败：

- L2/L3 场景提取 `tools=true` → `generateText` → 网关返回 400 → `SceneExtractor` 判定 `emptyExtraction=true` → L2 runner 返回 `{skipped:true}` → `scene_blocks/` 永远为空。
- 而 L1（`tools=false`）走 `streamText`（流式）正常，能成功产出记忆，进一步印证差异只在流式/非流式。

本 PR 将工具模式的 `generateText` 改为 **`streamText`（流式）**，使纯文本与工具任务都能正常完成，L2/L3 场景提取恢复可用。

## 问题

`MemoryCore/src/adapters/standalone/llm-runner.ts`：

- 纯文本路径（`tools=false`）走 `streamText`（第 327 行），正常。
- 工具模式路径（`tools=true`）走 `generateText`（第 381 行），非流式，被 `copilot.tencent.com/v2` 网关以 `code 11101` 拒绝（HTTP 400 Bad Request）。
- 由于 L2/L3 场景提取走工具模式，所有场景提取都失败，`scene_blocks/` 始终为空、`scenario/ls` 返回 `total:0`。

## 修复

把工具模式的 `generateText` 改为 `streamText`，并适配其 API 差异（AI SDK v6）：

```ts
import { streamText, tool, stepCountIs, jsonSchema } from "ai";
// generateText -> streamText（流式）

const result = streamText({ /* ...原有参数不变... */ });

// streamText 没有同步的 result.text / result.usage，需从 textStream 聚合，steps/usage 为异步
let accText = "";
for await (const chunk of result.textStream) {
  accText += chunk;
}
const text = accText.trim();
const steps = await result.steps;
const totalUsage = await result.totalUsage;

if (totalUsage) {
  this.lastUsage = {
    promptTokens: totalUsage.inputTokens ?? 0,          // 原 usage.promptTokens
    completionTokens: totalUsage.outputTokens ?? 0,     // 原 usage.completionTokens
    totalTokens: (totalUsage.inputTokens ?? 0) + (totalUsage.outputTokens ?? 0),
  };
}
```

要点：

- **流式调用**：`generateText` → `streamText`，适配网关仅支持流式的约束。
- **文本聚合**：`result.text` → 用 `for await (chunk of result.textStream)` 聚合出 `accText`。
- **steps**：`result.steps` → `await result.steps`。
- **usage**：`result.usage` → `await result.totalUsage`，且字段从 `promptTokens/completionTokens` 改为 `inputTokens/outputTokens`（streamText 的流式字段）。
- **多步工具循环不受影响**：AI SDK v6 移除了 `maxSteps`，但 `streamText` 的 `stopWhen`/`stepCountIs(maxIterations)` 仍可驱动多步工具循环，因此纯文本与工具任务均可正常执行。

## 测试

- 本地容器运行验证（容器以 tsx 跑源码）：L2 场景提取由 `Bad Request` 变为 `run() completed (stream): 32921ms, steps=2`，成功写入 3 个场景 `.md` 到 `scene_blocks/`。
- `memory-bridge/v3/scenario/ls` 返回 3 个条目（`team_id=team-iwqiplx8mt, agent_id=agt-i4xz40mhzd`），L2/L3 场景提取恢复。

## 关联

无。上游暂无此问题的 issue，为直接贡献。

## 贡献者

- dong-frank <1057762929@qq.com>（Signed-off-by / DCO）
