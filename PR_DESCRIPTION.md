## Title

fix(panel): paginate `agent-fixed-asset` list to stop fixed assets being truncated in ChatMemory fixed-assets tab

## Summary

When a user has more than 20 fixed assets (skills, tools, chat memories, knowledge), the ChatMemory
"fixed-assets" tab silently omits assets from the list. The root cause is that the `agent-fixed-asset`
`list-with-detail` endpoint defaults to a page size of 20 (`DEFAULT_PAGINATION`) and sorts by
`priority DESC, created_at DESC`, while the ChatMemory fixed-assets handler only performed a **single**
list call and dropped the pagination params entirely — so chat_memory assets (which are auto-registered
with `priority:50`) were consistently pushed past the first page and never surfaced.

This PR fixes the handler to **aggregate all pages** by looping over `offset` until the `total` count is
reached (aligned with the existing `FA_PAGE_SIZE` pattern already used by `MetadataClient.getAgentFixedAssets`),
instead of relying on a single-page default or a hard-coded `limit`. This is the permanent fix — asset lists
of any size are now fully returned, not just capped at an arbitrary threshold.

## Problem

`MemoryPanel/src/panel/http/routes/chat-memory.ts`, `agent-fixed` handler:

- Made a single `list-with-detail` call with no pagination control, so it relied on the endpoint's
  default `limit: 20`.
- Assets with high `priority` (skills) always win; lower-priority `chat_memory` bindings get sorted
  past the first 20 and are silently dropped from the UI.
- The deeper issue: any fixed threshold (e.g. a naive `limit: 100`) is still a guess and would break
  once the asset count exceeds it.

## Fix

Replace the single call with a **pagination loop**:

```ts
const FA_PAGE_SIZE = 100;
const FA_PAGE_HARD_LIMIT = 500;
const fixedAssets: FixedAssetDetailRaw[] = [];
let offset = 0;
while (true) {
  const listEnv = await deps.metaKernel.invoke(
    'agent-fixed-asset/list-with-detail',
    { agent_id: agentId, apply_visibility_filter: false, touch_usage: false,
      limit: FA_PAGE_SIZE, offset }, ctx);
  if (listEnv.code !== 0) return respondEnvelope(c, listEnv);
  const data = listEnv.data as ListEnvelopeData<FixedAssetDetailRaw> | null;
  const page = Array.isArray(data?.items) ? data.items : [];
  fixedAssets.push(...page);
  const total = typeof data?.total === 'number' ? data.total : fixedAssets.length;
  offset += FA_PAGE_SIZE;
  if (fixedAssets.length >= total || page.length === 0 || offset >= FA_PAGE_HARD_LIMIT) break;
}
```

- Fetches pages of `FA_PAGE_SIZE` (100) until all `total` items are collected.
- Stops when the accumulated count reaches `total`, when a page comes back empty, or at a safety
  hard cap (500) to guard against pathological inputs.
- This mirrors the established `MetadataClient.getAgentFixedAssets` pagination pattern, so the
  handler now behaves consistently with the rest of the platform.
- The `filter(asset_type === 'chat_memory')` step that follows is unchanged.

## Test Plan

- Verified locally and on the cloud panel environment that the fixed-assets tab now returns **all**
  fixed assets (previously truncated at 20).
- Container rebuilt and health-checked (`tdai-memory-hub` healthy, panel `:8125` / knowledge `:8424`
  both `ok`).
- The compiled `chat-memory.js` in the deployed image contains the new pagination loop
  (`FA_PAGE_HARD_LIMIT`, `fixedAssets.length >= total`).

## Related Issues

None. No upstream issue exists for this bug; this is a direct contribution.

## Contributor

- dong-frank <1057762929@qq.com> (Signed-off-by / DCO)
