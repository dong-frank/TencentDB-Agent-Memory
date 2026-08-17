# TDAI Memory — 司内部署指引（内部版本）

> 面向对象：想在司内环境把 TDAI Memory（core + proxy）跑起来、并让每个用户用自己那把「司内额度 Key」接入的同学。

## 0. 背景

司内部署版本和 GitHub 上的开源版本 **代码是一套**，大体安装步骤跟开源项目 `INSTALL.md` / `README.deployment.md` 完全一致——差异只在三处：

| 项 | 开源版 | 司内版 |
|---|---|---|
| 代码 | <https://github.com/TencentCloud/TencentDB-Agent-Memory>，默认分支 | 同一份代码，用 **`feat/server_team`** 分支（服务多实例 / team-proxy 增量） |
| 镜像 | Docker Hub 上的公开 tag | 司内私有 registry：<https://mirrors.tencent.com/#/private/docker?project_name=memory-team-control>（更新更勤，跟 `feat/server_team` 分支同步） |
| 用户 Key | Panel `/v3/meta/user/create` 一把梭生成 `sk-mem-...` | **不能** 用 Panel 生成，必须用「用户已有的司内额度 Key」直接落库 → 见本文 §3 |

其他 —— YAML 模板、启动命令、SDK 接入方式 —— 都跟开源仓一致，照抄即可。

---

## 1. 代码 & 镜像

### 代码
```bash
git clone https://github.com/TencentCloud/TencentDB-Agent-Memory
cd TencentDB-Agent-Memory
git checkout feat/server_team
```
四个子服务源码都在这里：`MemoryCore/` `MemoryProxy/` `MemoryPanel/` `MemoryKnowledge/`。

### 镜像（推荐直接用）
司内 registry：`mirrors.tencent.com/memory-team-control/*`

常用 tag 参考：
- `mirrors.tencent.com/memory-team-control/memory-core:<version>`
- `mirrors.tencent.com/memory-team-control/memory-proxy:<version>`
- `mirrors.tencent.com/memory-team-control/memory-hub:<version>`（Panel + Knowledge 合并镜像）

到 <https://mirrors.tencent.com/#/private/docker?project_name=memory-team-control> 页面看最新 tag。司内 registry 的镜像跟 `feat/server_team` 分支同步，会比开源 Docker Hub 上的 tag 更新一点，正式部署建议直接拉这里的镜像。

---

## 2. Proxy 上游配置的两种打法

`proxy.yaml` 里 `upstream:` 段决定「proxy 转发到哪个上游 LLM、用谁的 Key」，司内两种典型选择：

### 打法 A（默认推荐）— 透传客户端 Key，每人用自己的 CodeBuddy 额度

司内多数场景每个用户手里都有一把**自己申请的 CodeBuddy 额度 Key**，希望消耗的是自己那把 Key 的额度、账单也归自己。这种情况下 **proxy 侧不能写死任何 apiKey** —— 只配 `url`、把 Key 完全交给客户端透传上去。

```yaml
upstream:
  url: https://copilot.tencent.com/v2
  # Per-agent 覆盖: 只配 url, 不配 apiKey → 客户端 key 直接透传上游。
  # 注意: 一旦 agent 出现在下面这张表里, 外层 apiKey 的兜底就被切断,
  # 缺 apiKey 的 agent 会走"透传客户端 key"路径, 而非回落外层 —— 详见
  # tdai-memory-openclaw-plugin/MemoryProxy/config.example.yaml 里的三档语义表。
  agents:
    codebuddy:
      url: https://copilot.tencent.com/v2
    claude-code:
      # 上游 Anthropic 兼容层唯一入口 POST /v1/messages
      # (见 docs/tclaude-copilot-api.md §1)；proxy joinUrl 会拼 upstreamEndpoint
      # ("/messages")，所以 base 必须自带 /v1 尾巴，否则打到 /messages 会 404。
      url: https://copilot.tencent.com/v1
```

完整链路：
1. 每个用户拿自己那把 CodeBuddy Key 走 §3 的 `import-user.py` 脚本注册进 memory（把 Key 挂成 memory 的 `user_key`）
2. 用户在客户端（Claude Code / CodeBuddy CLI / …）里把这把 Key 配成 `Authorization: Bearer <key>`
3. proxy 收到请求 → 拿 Key 调 core `/v3/meta/auth/verify` 换 `user_id` 做鉴权 → 转发到上游时 **原样把客户端 Key 透传出去**，用的就是用户自己的 CodeBuddy 额度

⚠ 三档语义（源码位置：`MemoryProxy/config.example.yaml`）：
1. **外层 apiKey + agent 不在表里** → 用外层 Key
2. **agent 在表里 + `agents.<x>.apiKey` 有值** → 用 per-agent Key
3. **agent 在表里 + `agents.<x>.apiKey` 缺失** → 透传客户端 Key ← 打法 A 走这条

打法 A 落到 yaml 就是「外层不配 apiKey + agents 里也不配 apiKey」，两处都缺 → 走透传。

### 打法 B — 运营方统一模型服务，一把 Key 通吃

如果部署方 **不打算让每人用自己 CodeBuddy Key**、而是用运营方自己拉起来的统一模型服务（或者跟 LLM 供应商谈了统一账户），那 proxy 就在 upstream 直接配 url + apiKey，所有用户共用这把 Key：

```yaml
upstream:
  url: https://<运营方统一模型服务地址>/v1
  apiKey: <运营方申请的统一 Key>
  agents:
    codebuddy:
      url: https://<同上>/v2
    claude-code:
      url: https://<同上>/v1
```

这种打法下 §3 用户导入方案里的 `user_key` **也仍要唯一**（memory 鉴权按它做 user 隔离），只是它跟上游 LLM 的 Key 完全解耦 —— 用户 Key 只用来过 memory 鉴权、上游 Key 用运营方配的这把统一 Key。适合内部小规模自建、成本运营方兜底的场景。

### 其他配置
除了 `upstream:`，`proxy.yaml` / `core.yaml` 其他段落（Redis、Shark、CostGuard、Storage、观测三件套……）都按开源 `config.example.yaml` 的注释填就行。本仓 `config/core.yaml` 和 `config/proxy.yaml` 是**占位符版本**（所有敏感值替换成 `REPLACE_ME_*`），直接照着改，把 `REPLACE_ME_*` 填成实际值即可拉起。

---

## 3. 用户导入方案（司内独有）

### 3.1 问题

开源版走 Panel `/v3/meta/user/create` 建用户会生成 `sk-mem-...` 前缀的 `user_key`，这把 Key 是 **memory 服务自己产出**的、只能过 memory 鉴权、**不能**透传给上游 LLM。

司内场景下用户手里已经有一把 **CodeBuddy 申请的额度 Key**，我们希望：
- 用户直接拿这把 CodeBuddy Key 当 `Authorization: Bearer <key>` 调 proxy
- proxy 拿它去 core `POST /v3/meta/auth/verify` 换出 `user_id`
- proxy 转发到 `https://copilot.tencent.com/*` 时把这把 Key **原样透传**上去

于是需要把这把「用户已有的 Key」当作 memory 的 `user_key` 直接写进 core 的 MongoDB 元数据库 —— **绕开** Panel 的建用户接口。

### 3.2 工具

本目录 `scripts/` 下三个脚本就是干这件事的：

| 脚本 | 用途 |
|---|---|
| `import-user.py` | 直接写 MongoDB 建用户 + 挂上「用户自己的 Key」，并自动通过 core HTTP 建 `default-team` + `default-agent-{username}` + 3 个预置 Skill |
| `delete-user.py` | 直接写 MongoDB 删用户 + 级联清 `meta_user_keys` / `meta_team_members` / `meta_asset_acl` |
| `default_skills.py` | 3 个预置 Skill 常量（`code-review` / `unit-test` / `api-docs`），被 `import-user.py` import，不单独跑 |

关键设计点：
- **不强制 `sk-mem-` 前缀** —— core 的 `getUserByKey` 只按 `key_value` 精确匹配，`ck_...` / `sk-...` / 完全自定义前缀都过。所以 CodeBuddy Key 直接塞进去就能用。
- **写库逻辑与 core `MetadataService.createNormalUser → store.createUser` 完全对齐** —— 同一事务插 `meta_users` + `meta_user_keys`，字段 `auth_provider=local` / `user_type=normal` / `status=active` / key `is_default=true`。
- **建 team 走 MongoDB 直查+直插，不走 HTTP** —— 因为 core 的 `team/list` 按 user 隔离（新用户看不到别人的 team），`team-member/add` 又要 team admin 权限，走 HTTP 建/加入都会踩权限墙。

### 3.3 最短跑通路径

```bash
# 1. 填 config/core.yaml 的 metadata.store.mongoUri（脚本读它连库）
vim config/core.yaml

# 2. 装依赖
pip install pymongo pyyaml

# 3. 建单个用户
cd scripts/
./import-user.py \
  --username alice \
  --apikey "<alice 自己那把 CodeBuddy Key>" \
  --core-endpoint "http://memory-core.internal:8420"
```

stdout 出 `{"created": true, "user_id": "usr-xxx", ...}` 即成功，同时 alice 会自动获得 `default-team` 成员身份 + `default-agent-alice` + 3 个预置 Skill。

之后 alice 就可以拿 `<alice 自己那把 CodeBuddy Key>` 直接接入 proxy：
- **接入 proxy**：`Authorization: Bearer <apikey>`，base_url 走前置 gateway `/codebuddy/<instance_id>/...` 或 `/claude-code/<instance_id>/...`
- **直连 core**：header `x-tdai-user-key: <apikey>` + `x-tdai-service-id: <instance_id>`

### 3.4 批量导入

`scripts/users.example.json` 是模板：

```json
[
  {"username": "alice", "apikey": "ck_..."},
  {"username": "bob",   "apikey": "ck_...", "display_name": "Bob"},
  {"username": "alice", "apikey": "ck_extra_key...", "add_key": true}
]
```

跑：
```bash
./import-user.py --batch users.example.json --core-endpoint "http://memory-core.internal:8420"
```

### 3.5 给已有用户追加 Key

```bash
./import-user.py --username alice --apikey "ck_new_key" --add-key
```

追加的 Key `is_default=false`，跟原来那把并存，两把都能过鉴权。**不带 `--add-key` 时对已存在的 username 会拒绝执行**，防手滑打错 username 把 Key 塞到别人身上。

### 3.6 幂等语义速查

| 情况 | 默认 | 带 `--add-key` |
|---|---|---|
| user + key 都不存在 | 事务插两行 + 建 team/agent/skill → `created: true` | 同左 |
| key 已存在，同一 username | `created: false`（不改动） | 同左 |
| key 已存在，别的 username | ❌ 报错（防张冠李戴） | ❌ 报错 |
| username 已存在，key 是新的 | ❌ 报错拒绝 | ✅ 追加一把非 default key → `added_key: true` |

### 3.7 删除用户

```bash
# 默认 dry-run 只打印计划，绝不改库
./delete-user.py --username alice

# 真删
./delete-user.py --username alice --yes
```

级联清：`meta_users` + `meta_user_keys`（全部 key）+ `meta_team_members` + `meta_asset_acl`。
**不清**：`meta_agents` / `meta_tasks` / VDB L0-L3 记忆记录（跟 core 官方 `/v3/meta/user/delete` 行为一致，避免越权）。

想连 agent / skill 一起清，另走 core 的 `/v3/meta/agent/delete` 和 `/v3/skill/delete`。

### 3.8 更多细节

脚本完整参数、`--dry-run`、`--json`、事务依赖（需要 Mongo 副本集 + `metadata.store.mongoTransactions=true`）、system_admin 双保险 —— 全部在 [`scripts/README.md`](./scripts/README.md) 里，本文只覆盖最短路径。

---

## 4. 部署 checklist

1. **代码**：clone GitHub 仓，`checkout feat/server_team`
2. **镜像**：从司内 registry `mirrors.tencent.com/memory-team-control/*` 拉最新 tag
3. **配置**：本仓 `config/core.yaml` + `config/proxy.yaml` 里所有 `REPLACE_ME_*` 替换成实际值
   - 尤其注意 `proxy.yaml` 的 `upstream:` 段按 §2 打法 A（默认推荐，每人用自己 CodeBuddy Key）或 打法 B（运营方统一 Key）二选一
   - `core.yaml` 的 `metadata.store.mongoUri` 必填（脚本要连它）
4. **起服务**：用你方部署脚本 / K8s manifest 挂载这两份 YAML；core `:8420`，proxy `:8096`
5. **前置 gateway**：nginx / API gateway 按 `codebuddy | claude-code | codex` 前缀分流到 proxy `:8096`（可选，直连 proxy 也行）
6. **导入用户**：`./import-user.py --username <x> --apikey <x-的-CodeBuddy-Key>` 挨个建 or `--batch` 一次性建
7. **验证**：客户端拿 apikey 当 Bearer，走 gateway 或直连 proxy 发一个 `/v1/messages` 请求，看能不能过鉴权 + 落 memory

---

## 5. 参考

- 开源仓：<https://github.com/TencentCloud/TencentDB-Agent-Memory> 分支 `feat/server_team`
- 司内镜像：<https://mirrors.tencent.com/#/private/docker?project_name=memory-team-control>
- 完整脚本文档：[`scripts/README.md`](./scripts/README.md)
- 完整配置模板：[`config/core.yaml`](./config/core.yaml) / [`config/proxy.yaml`](./config/proxy.yaml)
- upstream 三档语义源码位置：`tdai-memory-openclaw-plugin/MemoryProxy/config.example.yaml`
