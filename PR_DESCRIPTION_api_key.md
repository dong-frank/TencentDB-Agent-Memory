## Title

feat(proxy): support per-user upstream LLM API key configuration

## Summary

Currently the proxy forwards each chat request to the upstream LLM using a single shared upstream
`apiKey` (global config or per-agent entry). This forces every user to share one key — a real problem
when different users are billed against their own accounts, or when an org wants each member to bring
their own provider key.

This PR lets each signed-in user bind **their own upstream LLM API key** from the panel, and makes the
proxy use **that user's key** (never the global/agent key) when forwarding to the upstream provider. The
key is stored in the core config params (scoped to `user`), read back dynamically at request time via a
new `getUserUpstreamApiKey` call, and injected into the upstream `authorization` header on both the primary
and retry paths.

Security-wise, the lookup is authenticated with the caller's own user key (`x-tdai-user-key`) and enforced
on the core side by `assertCallerIsOwner`, so a user can only ever read their own key — no cross-user access.

## Problem

`MemoryProxy/src/handler.ts` resolves the upstream key solely from `config.upstream.apiKey` / the agent
entry, so there is no notion of a per-user key. Consequences:

- Every user shares the same upstream key; there is no way for a user to supply their own provider key.
- Users who need their own key (billing isolation, personal providers, per-user rate limits) are stuck
  with the shared one, or must rely on the client passing its own key and hope the proxy doesn't override it.
- There is no UI to configure a per-user key.

## Fix

Three sides cooperate; the core config store is the single source of truth, the proxy reads it
dynamically at request time, and the panel exposes the configuration UI.

### 1. core — new `llm.api_key` config param (user-scoped)

`MemoryCore/src/metadata/config/metadata_config_params.json`: added an `llm` module with an `api_key`
param (default `""`, `allowed_scopes: ["global", "user"]`). User-scoped values are set via the existing
`config/user/set` route and automatically override the global value when read — no new storage logic.

### 2. proxy — resolve and inject the caller's own key

`MemoryProxy/src/handler.ts`:

```ts
let resolvedApiKey = effectiveApiKey;
if (userId && apiKey && tdaiClient) {
  try {
    resolvedApiKey = await tdaiClient.getUserUpstreamApiKey(apiKey, userId);
  } catch {
    resolvedApiKey = ""; // not configured — no fallback to global/agent key
  }
}
// buildUpstreamHeaders(..., resolvedApiKey) on primary and retry paths
```

- When `userId` is resolvable and the user has a configured key, that key is used.
- When unconfigured / lookup fails, `resolvedApiKey` stays `""` — the proxy does **not** fall back to the
  global/agent key, so the client's own key passes through and an upstream auth failure prompts the user
  to configure theirs.
- The global/agent key is only used as a fallback when `userId` cannot be resolved (e.g. auth disabled).

`MemoryProxy/src/tdai/client.ts`: added `getUserUpstreamApiKey(userKey, userId)` which POSTs
`/v3/meta/config/user/get` for `module:"llm", param_name:"api_key"`, authenticated with the caller's own
`x-tdai-user-key` so core's `assertCallerIsOwner` restricts reads to self. It is fail-open: on any
network/HTTP/envelope error it returns `""` (never throws, never blocks forwarding).

### 3. panel — "upstream LLM" configuration tab

`MemoryPanel/web/src/components/SettingsDialog.tsx`: added an **「上游 LLM / Upstream LLM」** tab that
reads the current logged-in user's `llm/api_key` (`config/user/get`) and lets them save (`config/user/set`)
or clear it, rendered as a `type="password"` field. I18n keys added in `en-US.ts` / `zh-CN.ts`.

## Test Plan

- Verified locally and on the cloud panel that the new "upstream LLM" tab shows the effective per-user key
  value, saves/clears it correctly, and persists to the core config store.
- Verified the proxy resolves a configured user key and injects it as `authorization: Bearer <user key>`
  into the upstream request on both the primary and retry paths.
- Verified the no-fallback semantics: with a user who has no configured key, the proxy leaves the header
  empty (client key passthrough) instead of substituting the global/agent key.
- `git diff` against the base `feat/server_team` confirms the PR touches only the 6 intended files
  (config param, panel tab, 2 i18n files, proxy handler, proxy tdai client) with no unrelated changes.

## Related Issues

None. No upstream issue exists for this capability; this is a direct contribution.

## Contributor

- dong-frank <1057762929@qq.com> (Signed-off-by / DCO)
