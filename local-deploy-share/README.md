# TDAI Memory — 部署配置模板 + 用户导入工具

对外分发的最小可用包，含两类文件：

```
local-deploy-share/
├── config/            # core + proxy 服务配置模板（占位符版本，需按你方基础设施填写）
│   ├── core.yaml
│   └── proxy.yaml
└── scripts/           # 用户导入 / 删除辅助脚本（直接读 config/core.yaml，无需再配库连接）
    ├── import-user.py       # 建用户 + 首次登录自动建 default-team/agent + 导入 3 个预置 Skill
    ├── delete-user.py       # 删用户 + 级联清 keys/members/acl
    ├── default_skills.py    # 预置 Skill 常量（被 import-user.py import，别单独跑）
    ├── users.example.json
    └── README.md
```

## 用途

- **`config/`** — memory-core（`:8420`）和 memory-proxy（`:8096`）两个服务的完整 YAML 模板，所有敏感字段全部替换成 `REPLACE_ME_*` 占位符，直接照着改就能拉起。
- **`scripts/`** — 帮你方把「用户已有 key」写进 memory 的 MongoDB 元数据库（即让用户的外部 API Key 直接充当 memory 的 `user_key`），不用走 core 官方 `/v3/meta/user/create` 接口重新生成 key。写库完成后再通过 core HTTP 接口自动给新用户创建默认 `default-team` + `default-agent-{username}` 并导入 3 个预置 Skill（`code-review` / `unit-test` / `api-docs`），让用户开箱即用。

## 快速开始

### 1. 填 config

按注释把两份 YAML 里的 `REPLACE_ME_*` 全部替换成你方实际值。**至少必填**：

**core.yaml**
- `llm.baseUrl` / `llm.apiKey` / `llm.model` — 任一 OpenAI 兼容 LLM 端点
- `redis.host` / `redis.port` / `redis.password`
- `shark.baseUrl` — 实例配置中心（下发 VDB/COS 凭证）；仅 memory recall 场景可以不用 skill/knowledge，此项可留占位不启用
- `metadata.store.mongoUri` — MongoDB 连接串；建议副本集以支持事务
- `metadata.systemUser.memory.userKey` — 高熵随机串，建议 `openssl rand -base64 32`

**proxy.yaml**
- `upstream.*` — 上游 LLM 三档（Anthropic / OpenAI 兼容 / Codex）按需填
- `redis.*` — 可跟 core 复用同一 Redis，用不同 `keyPrefix` 隔离
- `storage.cos.shark.baseUrl` — 建议跟 core.yaml 的 `shark.baseUrl` 一致
- `auth.url` / `tdai.endpoint` / `skill.endpoint` / `knowledge.endpoint` — 全部指向 core 的 base URL（如 `http://memory-core:8420`）
- `costGuard.analyzeUrl` / `analyzeApiKey` + `costGuard.agents.*.cheapUrl` / `cheapApiKey` — 便宜/分析模型端点

**观测/上报三件套**（`otel` / `clickhouse` / `kafka` / `langfuse` / `opik` / `creditReport`）默认全部 `enabled: false`，不需要就不用填。

### 2. 起服务

用你方自己的部署脚本 / K8s manifest 挂载这两份 YAML 即可。core 监听 `:8420`，proxy 监听 `:8096`。

### 3. 导入用户

服务起来后，把配好 `mongoUri` 的 `config/core.yaml` 放在 `scripts/../config/`（默认目录结构就是这样），然后：

```bash
cd scripts/
./import-user.py --username alice --apikey "ck_alice_own_key" \
    --core-endpoint "http://memory-core.internal:8420"
```

`--core-endpoint` 不传默认 `http://127.0.0.1:8420`（脚本跟 core 在同一台机器可省）。脚本会：
1. 直连 MongoDB 写 `meta_users` + `meta_user_keys`
2. 用新用户的 apikey 通过 core HTTP 建 `default-team` + `default-agent-{username}` + 3 个预置 Skill

详细用法（包括批量、追加 key、幂等语义、反悔）看 [`scripts/README.md`](./scripts/README.md)。

## 目录内没有的东西

对外分发只包这两个目录足以让 memory 起来 + 让用户用自己的 key 接入。以下运营方内部的东西**不在包内**，如需要请自行准备：

- **Shark**（实例配置中心）— 运营方内部服务，接口 contract 见 core 源码 `MemoryCore/src/shark/shark-client.ts`；也可自建等价服务或裁掉依赖它的 skill/knowledge 功能
- **前置 gateway**（nginx / API gateway）— 按 `codebuddy | claude-code | codex` 前缀分流到 proxy `:8096`
- **memory-hub**（前端 Panel + 知识服务）— 可选，用于给终端用户管理 team/agent/task
- **可观测组件**（Langfuse / ClickHouse / Opik / OTel / Kafka）— 按需自建

## 反馈

改动后有踩坑欢迎回抛给我们，一起补充占位符注释和缺省行为。
