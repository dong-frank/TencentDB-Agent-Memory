# scripts — 用户导入 / 删除辅助脚本

| 脚本 | 干什么 |
|---|---|
| `import-user.py` | 直接写 MongoDB 建用户 + 自定义 apikey（绕过 core `/v3/meta/user/create`），并自动通过 core HTTP 接口给新用户创建默认 Team / Agent 并导入 3 个预置 Skill |
| `delete-user.py` | 直接写 MongoDB 删用户 + 级联清 keys/members/acl（对齐 core `/v3/meta/user/delete`） |
| `default_skills.py` | 预置 Skill 常量（code-review / unit-test / api-docs），被 `import-user.py` import，不单独运行 |

两个脚本都只依赖同级 `../config/core.yaml` 里的 `metadata.store.mongoUri` / `mongoDbPrefix` 读 Mongo；`import-user.py` 额外需要 core 的 HTTP 端点（`--core-endpoint`）。

---

## import-user.py

绕过 core `/v3/meta/user/create` 接口，直接往 MongoDB 元数据库塞用户 + 自定义 apikey。
**适用场景：用户已经在外部系统有一把自己的 key，想直接以这把 key 作为 memory 的 user_key。**

**用户创建成功后，自动通过 core HTTP 接口创建默认 Team、默认 Agent 并导入预置 Skill**（best-effort，失败仅 log 不影响用户创建结果）：

- `POST /v3/meta/team/create` → 创建 `default-team`（第一次；后续新用户走 MongoDB 直查已有 team_id 并直接 insert `meta_team_members` 加入）
- `POST /v3/meta/agent/create` → 创建 `default-agent-{username}`（每个用户一个独立 agent）
- `POST /v3/skill/create` ×3 → 导入 `code-review` / `unit-test` / `api-docs`

> 备注：`default-team` 复用走 MongoDB 而不是 HTTP 是因为 core 的 `team/list` 按 user 隔离（新用户看不到其他人的 team），且 `team-member/add` 需要 team admin 权限、新用户没这权限；直接查/写库能绕开这两处限制。core 的 `team/create` 也不做 name 唯一校验，所以复用检测必须先查库。

写库逻辑与 core `MetadataService.createNormalUser → store.createUser` 对齐：

- 集合：`meta_users` + `meta_user_keys`（同一事务）
- ID：`usr-{4位b36时间戳}{6位b36随机}` / `uky-...`
- 字段：`auth_provider=local` / `external_id=user_id` / `user_type=normal` / `status=active`
- key：`is_default=true` / `status=active` / `expires_at=null`
- **不强制** `sk-mem-` 前缀 — core 的 `getUserByKey` 只按 `key_value` 精确匹配，任意前缀（`ck_...` / `sk-...` / 自定义）都能过鉴权。

### 依赖

系统自带 Python 3 + 两个库：

```bash
python3 -c "import pymongo, yaml"  # 都在就直接跑；不在则：
pip install pymongo pyyaml
```

此外需要同目录下的 `default_skills.py`（预置 Skill 内容），随包一起分发。

### 单个用户

```bash
./import-user.py \
  --username alice \
  --apikey "ck_your_own_api_key_here" \
  --core-endpoint "http://memory-core.internal:8420"
```

`--core-endpoint` 不传则用默认 `http://127.0.0.1:8420`（脚本跟 core 在同一台机器时可省）。

进度打到 stderr，结果 JSON 打到 stdout：

```json
{
  "created": true,
  "user_id": "usr-3mfxa3b9c1",
  "username": "alice",
  "user_key": "ck_your_own_api_key_here"
}
```

stderr 会看到（示例）：

```
[import-user] ✓ 创建 alice → usr-3mfxa3b9c1
[import-user] ✔ 创建 default-team → tm-xxxxxxxxxx    ← 第一个用户建，后续用户是 "⊙ default-team 已存在" + "✔ 加入 default-team"
[import-user] ✔ 创建 default-agent-alice → ag-xxxxxxxxxx
[import-user] ✔ 导入 Skill "code-review"
[import-user] ✔ 导入 Skill "unit-test"
[import-user] ✔ 导入 Skill "api-docs"
```

想只拿 user_id：

```bash
./import-user.py --username alice --apikey "ck_..." --json | jq -r .user_id
```

### 给已有用户追加 key（`--add-key`）

已有用户想再挂一把 key 时用（比如用户已经有 default key，你想给他额外加把新 key）。默认不带此 flag 会拒绝执行，防止手滑打错 username 把 key 塞到别人身上。

```bash
./import-user.py \
  --username alice \
  --apikey "ck_another_key" \
  --add-key
```

输出：

```json
{
  "created": false,
  "added_key": true,
  "user_id": "usr-wotqp7ne19",
  "username": "alice",
  "user_key": "ck_another_key",
  "key_id": "uky-o66hcqvi9v",
  "note": "user 已存在，追加了一把新 key（is_default=False）"
}
```

追加的 key 是 **`is_default=false`**，不动用户原来的 default key；两把都能过 core 鉴权（core 的 `getUserByKey` 只按 `key_value` + `status=active` 匹配，跟 `is_default` 无关）。

> **注意**：`--add-key` 路径只加 key，**不**再触发 Team / Agent / Skill 的创建（这些资源在首次 `created=true` 那次已经建好）。

想撤旧的、把新 key 提升为 default 需要另做（暂未做成脚本）：

```javascript
// mongosh 里手改
db.meta_user_keys.updateMany({user_id: "usr-xxx", is_default: true}, {$set: {is_default: false}})
db.meta_user_keys.updateOne({key_id: "uky-yyy"}, {$set: {is_default: true}})
```

### 批量

```bash
./import-user.py --batch users.example.json
```

`users.example.json` 是 JSON 数组，每项至少 `username` + `apikey`，可选 `display_name`、`add_key`：

```json
[
  {"username": "alice", "apikey": "ck_..."},
  {"username": "bob",   "apikey": "ck_...", "display_name": "Bob"},
  {"username": "alice", "apikey": "ck_extra_key...", "add_key": true}
]
```

批量项里的 `"add_key": true` 会覆盖 CLI 的 `--add-key`（可以在同一次批量里，一部分是新建、另一部分是往已有用户追加 key）。

### 选项

| 选项 | 默认 | 说明 |
|---|---|---|
| `--config <path>` | `../config/core.yaml` | 读 `metadata.store.mongoUri` / `mongoDbPrefix` |
| `--instance-id <id>` | `default` | 库名 = `${mongoDbPrefix}_${sanitize(id)}`；同时作为 core HTTP 请求的 `x-tdai-service-id` |
| `--core-endpoint <url>` | `http://127.0.0.1:8420` | core 的 HTTP 地址，用于创建 Team / Agent / Skill |
| `--username` / `--apikey` | — | 单用户模式必填 |
| `--batch <file>` | — | 批量模式，与 `--username/--apikey` 二选一 |
| `--display-name <n>` | `null` | 可选，仅单个模式生效 |
| `--add-key` | 关 | 用户已存在时追加一把非 default key（不加此 flag 会报错拒绝，防误伤） |
| `--dry-run` | — | 不连库，只打印计划 |
| `--json` | — | 屏蔽 stderr 日志，只 stdout 结果 |

### 幂等语义

| 情况 | 默认行为 | 带 `--add-key` |
|---|---|---|
| user + key 都不存在 | 事务插两行 + 创建 team/agent/skill → `created: true` | 同左 |
| key 已存在，同一 username | `created: false`（不改动，也不再建 team/agent/skill） | 同左 |
| key 已存在，别的 username | ❌ 报错（防张冠李戴） | ❌ 报错（同左） |
| username 已存在，key 是新的 | ❌ 报错拒绝 | **追加一把非 default key** → `added_key: true`（不再建 team/agent/skill） |

批量模式下每项也能带 `"add_key": true` 覆盖 CLI 的 `--add-key`。

Team / Agent / Skill 的创建本身也是幂等的：

- `default-team` 全局唯一，第二个用户起自动复用已有 team_id + 加入成员
- `default-agent-{username}` 撞库时脚本会退回 `agent/list` 找到已有 agent_id 继续走后面的 skill 导入
- Skill 撞 `code=42201`（`SKILL_NAME_DUPLICATE`）视为已导入，跳过

### 拿到 user_id 之后

- **接入 proxy**：把 apikey 直接当 `Authorization: Bearer <apikey>`，base_url 走你们前置 gateway 的 `/codebuddy/<instance_id>/...` 或 `/claude-code/<instance_id>/...`
- **直连 core**：header `x-tdai-user-key: <apikey>` + `x-tdai-service-id: <instance_id>`

### 反悔

```bash
mongosh "<你的 mongoUri>" --eval '
  db = db.getSiblingDB("<mongoDbPrefix>_<instance_id>");
  db.meta_user_keys.deleteMany({key_value:"ck_..."});
  db.meta_users.deleteMany({username:"alice"});'
```

或走 core 官方 `POST /v3/meta/user/delete`（需 system_admin key），或用下面的 `delete-user.py`。

> 注意：`delete-user.py` 只删 user + keys + team_members + acl，**不删** agent / skill / team 本身。如果需要一起清 agent / skill，请另外走 core 的 `/v3/meta/agent/delete` 和 `/v3/skill/delete`。

---

## delete-user.py

绕过 core `/v3/meta/user/delete` 接口，直接从 MongoDB 删用户 + 级联清关联记录。
删除范围与 core `store.deleteUsers` 完全对齐。

### 级联删除范围（事务）

| 集合 | 条件 |
|---|---|
| `meta_users` | `user_id == <target>` |
| `meta_user_keys` | `user_id == <target>` (**含所有 key，不管 default 与否**) |
| `meta_team_members` | `user_id == <target>` |
| `meta_asset_acl` | `subject_type=user AND subject_id == <target>` |

### 不清理的孤儿（与 core 官方一致）

| 数据 | 影响 |
|---|---|
| `meta_agents.owner_user_id` | Panel 里显示 unknown owner，功能不受影响 |
| `meta_tasks.creator_user_id` | 同上 |
| `meta_participation_logs.user_id` | 同上 |
| VDB L0/L1/L2/L3 记忆记录 | filter tag 保留，需另走 VDB 清理才能真删 |

### 用法

```bash
# 预览（默认 dry-run，不改库）
./delete-user.py --user-id usr-xxx
./delete-user.py --username alice

# 真删（必须显式 --yes）
./delete-user.py --user-id usr-xxx --yes

# 删 system_admin 用户（额外要 --force-system-admin，仍会拒绝删最后一个 admin）
./delete-user.py --user-id usr-xxx --force-system-admin --yes
```

### 保护策略

- **默认 dry-run**：不加 `--yes` 只打印删除计划 + 孤儿计数，绝不改库
- **精确定位**：`--username` 匹配到 >1 用户时拒绝执行，需改用 `--user-id`
- **`system_admin` 双保险**：普通调用直接拒；加 `--force-system-admin` 后仍会检查是不是最后一个 admin
- **事务**：4 张表的 deleteMany 在同一事务里，中途失败自动回滚（需要 Mongo 副本集 + `metadata.store.mongoTransactions=true`）
- **VDB 不动**：脚本不连 VDB，避免越权，需要清 memory 请另走接口
