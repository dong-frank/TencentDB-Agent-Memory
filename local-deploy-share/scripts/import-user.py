#!/usr/bin/env python3
"""直接写 MongoDB 导入用户（不走 core /v3/meta/user/create 接口）。

等价于 core MetadataService.createNormalUser → store.createUser：
  meta_users        插一行
  meta_user_keys    插一条 is_default=True 的 key

字段/ID 规则与 core 对齐（tdai-memory-openclaw-plugin/MemoryCore/src/metadata/*）：
  user_id  = "usr-" + 4位b36时间戳 + 6位b36随机
  key_id   = "uky-..." 同上
  auth_provider = "local", external_id = user_id
  user_type     = "normal", status = "active"
  key.status    = "active", is_default = True

库名（对齐 db-name.ts）:
  dbName = f"{mongoDbPrefix}_{sanitize(instanceId)}"  # 截断到 64 字符

用户创建成功后，自动通过 core HTTP 接口创建默认 Team / Agent 并导入预置 Skill：
  POST /v3/meta/team/create  → 创建 default-team
  POST /v3/meta/agent/create → 创建 default-agent-{username}
  POST /v3/skill/create ×3   → 导入 code-review / unit-test / api-docs

用法：
  单个：
    ./import-user.py --username alice \\
        --apikey "ck_your_own_api_key_here"

  指定 core 地址（默认 http://127.0.0.1:8420）：
    ./import-user.py --username alice --apikey "ck_xxx" \\
        --core-endpoint "http://memory-core.internal:8420"

  批量：
    ./import-user.py --batch users.example.json

  常用选项：
    --instance-id <id>     默认 default
    --config <path>        默认 ../config/core.yaml
    --core-endpoint <url>  默认 http://127.0.0.1:8420
    --display-name <n>     可选
    --dry-run              不写库，只打印计划
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import string
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError

from default_skills import PREBUILT_SKILLS

ID_PREFIX_USER = "usr"
ID_PREFIX_KEY = "uky"
B36 = string.digits + string.ascii_lowercase  # '0-9a-z'
TS_LEN = 4
RAND_LEN = 6
DEFAULT_DB_PREFIX = "tdai_metadata"
PK_RETRY = 3

# ── 默认 Team / Agent 常量 ──
DEFAULT_TEAM_NAME = "default-team"
DEFAULT_TEAM_DESC = "系统初始化时自动创建的默认团队，用于存放默认助手"
DEFAULT_AGENT_PREFIX = "default-agent-"
DEFAULT_AGENT_DESC = "默认助手，可处理通用开发任务与日常协作。"
DEFAULT_AGENT_ROLE_PROMPT = (
    "你是一个通用的开发助手，能够协助完成代码编写、问题排查、文档整理等日常开发任务。"
    "你会根据用户的需求灵活调整工作方式，提供准确、高效的帮助。"
)
DEFAULT_AGENT_RULES_PROMPT = (
    "- 优先理解用户的意图，必要时主动询问澄清\n"
    "- 给出的代码和建议应遵循最佳实践\n"
    "- 保持回复简洁、准确、可执行"
)
DEFAULT_AGENT_PROMPT = DEFAULT_AGENT_ROLE_PROMPT + "\n\n" + DEFAULT_AGENT_RULES_PROMPT
DEFAULT_AGENT_METADATA_JSON = json.dumps({
    "ui": {
        "role_prompt": DEFAULT_AGENT_ROLE_PROMPT,
        "rules_prompt": DEFAULT_AGENT_RULES_PROMPT,
    },
})


def _encode_b36(v: int, length: int) -> str:
    out = []
    for _ in range(length):
        out.append(B36[v % 36])
        v //= 36
    return "".join(reversed(out))


def _rand_b36(length: int) -> str:
    return "".join(B36[secrets.randbelow(36)] for _ in range(length))


def gen_id(prefix: str) -> str:
    ts = int(time.time()) % (36 ** TS_LEN)
    return f"{prefix}-{_encode_b36(ts, TS_LEN)}{_rand_b36(RAND_LEN)}"


def sanitize_instance_id(iid: str) -> str:
    return re.sub(r'[/\\."$ \0]', "_", iid.strip())


def resolve_db_name(instance_id: str, prefix: str | None) -> str:
    p = (prefix or "").strip() or DEFAULT_DB_PREFIX
    s = sanitize_instance_id(instance_id)
    if not s:
        raise ValueError(f"instance_id invalid: {instance_id!r}")
    return f"{p}_{s[: 64 - len(p) - 1]}"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def mask_uri(uri: str) -> str:
    return re.sub(r"//([^:]+):[^@]+@", r"//\1:***@", uri)


def load_users(args: argparse.Namespace) -> list[dict[str, Any]]:
    if args.batch:
        raw = json.loads(Path(args.batch).read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise ValueError(f"{args.batch} 必须是 JSON 数组")
        out: list[dict[str, Any]] = []
        for i, u in enumerate(raw):
            if not u.get("username") or not u.get("apikey"):
                raise ValueError(f"batch[{i}] 缺少 username 或 apikey")
            out.append({
                "username": str(u["username"]),
                "apikey": str(u["apikey"]),
                "display_name": u.get("display_name") or args.display_name,
                # batch 项自带 add_key=true 时覆盖全局 --add-key
                "add_key": bool(u.get("add_key", args.add_key)),
            })
        return out
    if args.username and args.apikey:
        return [{
            "username": args.username,
            "apikey": args.apikey,
            "display_name": args.display_name,
            "add_key": args.add_key,
        }]
    raise ValueError("必须指定 --username/--apikey 或 --batch <file>")


def add_user_key(keys_col, user_id: str, username: str, apikey: str) -> dict[str, Any]:
    """给已存在的用户追加一把非 default key。"""
    for _ in range(PK_RETRY):
        key_id = gen_id(ID_PREFIX_KEY)
        now = now_iso()
        key_doc = {
            "key_id": key_id,
            "user_id": user_id,
            "key_value": apikey,
            "name": None,
            "status": "active",
            "is_default": False,     # 不动原来的 default key
            "last_used_at": None,
            "expires_at": None,
            "created_at": now,
            "revoked_at": None,
            "metadata_json": "{}",
        }
        try:
            keys_col.insert_one(dict(key_doc))
            return {
                "created": False,
                "added_key": True,
                "user_id": user_id,
                "username": username,
                "user_key": apikey,
                "key_id": key_id,
                "note": "user 已存在，追加了一把新 key（is_default=False）",
            }
        except DuplicateKeyError as e:
            kp = getattr(e, "details", {}).get("keyPattern", {}) if hasattr(e, "details") else {}
            if any(k.endswith("_id") and k != "_id" for k in kp):
                continue  # key_id 撞库 → 重试
            raise
    raise RuntimeError("key_id 冲突超过重试上限")


def import_one(client: MongoClient, db, u: dict[str, Any]) -> dict[str, Any]:
    users_col = db["meta_users"]
    keys_col = db["meta_user_keys"]
    username = u["username"]
    apikey = u["apikey"]
    display_name = u.get("display_name")
    add_key = bool(u.get("add_key"))

    # 幂等预检 1: apikey 全局唯一（key_value 是 unique 索引）
    existing_key = keys_col.find_one({"key_value": apikey})
    if existing_key:
        eu = users_col.find_one({"user_id": existing_key["user_id"]})
        if not eu:
            raise RuntimeError(
                f"apikey 已存在但 user_id={existing_key['user_id']} 找不到用户记录（脏数据）"
            )
        if eu["username"] != username:
            raise RuntimeError(
                f"apikey 已被 {eu['username']} ({eu['user_id']}) 占用，与传入 {username} 不匹配"
            )
        return {
            "created": False,
            "user_id": eu["user_id"],
            "username": eu["username"],
            "user_key": apikey,
            "note": "user + apikey 均已存在，未做变更",
        }

    # 幂等预检 2: username 已存在 → 视 --add-key 决定「拒绝」还是「追加 key」
    eu = users_col.find_one({"auth_provider": "local", "username": username})
    if eu:
        if not add_key:
            raise RuntimeError(
                f"username '{username}' 已存在 (user_id={eu['user_id']}) 但传入的 apikey 不是它的任何一把 key。"
                f" 想给已有用户追加 key，请加 --add-key。"
            )
        # 追加一把 key（is_default=False，不动它原来的默认 key）
        return add_user_key(keys_col, eu["user_id"], eu["username"], apikey)

    # 双 insert，事务包起来（config 里 mongoTransactions: true，副本集支持）
    for attempt in range(PK_RETRY):
        user_id = gen_id(ID_PREFIX_USER)
        key_id = gen_id(ID_PREFIX_KEY)
        now = now_iso()
        user_doc = {
            "user_id": user_id,
            "password": None,
            "auth_provider": "local",
            "external_id": user_id,
            "username": username,
            "display_name": display_name,
            "raw_profile_json": "{}",
            "status": "active",
            "user_type": "normal",
            "created_at": now,
            "updated_at": now,
            "metadata_json": "{}",
        }
        key_doc = {
            "key_id": key_id,
            "user_id": user_id,
            "key_value": apikey,
            "name": None,
            "status": "active",
            "is_default": True,
            "last_used_at": None,
            "expires_at": None,
            "created_at": now,
            "revoked_at": None,
            "metadata_json": "{}",
        }
        try:
            with client.start_session() as s:
                with s.start_transaction():
                    users_col.insert_one(dict(user_doc), session=s)
                    keys_col.insert_one(dict(key_doc), session=s)
            return {"created": True, "user_id": user_id, "username": username, "user_key": apikey}
        except DuplicateKeyError as e:
            # user_id / key_id 撞库 → 重试；username / key_value 重复 → 抛
            kp = getattr(e, "details", {}).get("keyPattern", {}) if hasattr(e, "details") else {}
            if any(k.endswith("_id") and k != "_id" for k in kp):
                continue
            raise
    raise RuntimeError("PK 冲突超过重试上限")


# ══════════════════════════════════════════════════════════════════
# 通过 core HTTP 接口创建 Team / Agent / Skill
# ══════════════════════════════════════════════════════════════════
#
# 业务流程（用户已在 MongoDB 创建完成后串联执行）：
#
#   1. 查 default-team 是否已存在
#      → 方式：MongoDB meta_teams.find_one({name: "default-team"})
#      → 原因：HTTP team/list 按 user 隔离，新用户看不到其他用户建的 team，
#        因此不采用 HTTP 方式，改为直接查 MongoDB
#
#   2. 不存在 → HTTP team/create 创建
#      存在 → 先把用户加入该 team
#      → 方式：MongoDB meta_team_members.insert_one
#      → 原因：HTTP team-member/add 需要 team admin 权限，新用户无权限调用，
#        因此不采用 HTTP 方式，改为直接写 MongoDB
#
#   3. HTTP agent/create → 创建 default-agent-{username}
#
#   4. HTTP skill/create ×3 → 导入预置 Skill
#
# 注意：core 的 team/create 不做 name 唯一校验，因此步骤 1 必须用 MongoDB
# 查重，否则每次都会创建新的同名 default-team。

def core_post(endpoint: str, path: str, body: dict, service_id: str, user_key: str, timeout: int = 10) -> dict:
    """调 core HTTP 接口，返回解析后的 JSON envelope。"""
    url = f"{endpoint.rstrip('/')}{path}"
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {user_key}")
    req.add_header("x-tdai-service-id", service_id)
    req.add_header("x-tdai-user-key", user_key)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        return json.loads(raw) if raw.startswith("{") else {"code": e.code, "message": raw}
    except Exception as e:
        return {"code": -1, "message": str(e)}


def ensure_default_team_and_agent(
    endpoint: str,
    service_id: str,
    user_key: str,
    user_id: str,
    username: str,
    db,
    log_fn,
) -> tuple[str | None, str | None]:
    """创建 default-team + default-agent，返回 (team_id, agent_id)。失败返回 (None, None)。"""
    # 1. 查 MongoDB 判断 default-team 是否已存在（core 不做名字唯一校验，且
    #    team/list 按 user 隔离，新用户看不到其他用户建的 team）
    team_id: str | None = None
    existing_team = db["meta_teams"].find_one({"name": DEFAULT_TEAM_NAME, "status": "active"})
    if existing_team:
        team_id = existing_team["team_id"]
        log_fn(f"[import-user] ⊙ default-team 已存在 → {team_id}")

    if not team_id:
        resp = core_post(endpoint, "/v3/meta/team/create", {
            "name": DEFAULT_TEAM_NAME,
            "description": DEFAULT_TEAM_DESC,
            "owner_user_id": user_id,
        }, service_id, user_key)
        if resp.get("code") == 0:
            team_id = resp["data"]["team_id"]
            log_fn(f"[import-user] ✔ 创建 default-team → {team_id}")
            # team/create 自动将 owner 加为成员，无需额外 add
        else:
            log_fn(f"[import-user] ✘ 创建 default-team 失败: {resp.get('message', resp)}")
            return None, None
    else:
        # 复用已有 team：直接 MongoDB 写成员关系（新用户无 team-member/add 权限）
        try:
            db["meta_team_members"].insert_one({
                "team_id": team_id,
                "user_id": user_id,
                "role": "member",
                "status": "active",
                "joined_at": now_iso(),
            })
            log_fn(f"[import-user] ✔ 加入 default-team")
        except DuplicateKeyError:
            log_fn(f"[import-user] ⊙ 已是 default-team 成员")

    # 2. 创建 default-agent
    agent_name = f"{DEFAULT_AGENT_PREFIX}{username}"
    resp = core_post(endpoint, "/v3/meta/agent/create", {
        "team_id": team_id,
        "owner_user_id": user_id,
        "name": agent_name,
        "description": DEFAULT_AGENT_DESC,
        "prompt": DEFAULT_AGENT_PROMPT,
        "metadata_json": DEFAULT_AGENT_METADATA_JSON,
        "visibility": "team",
        "status": "active",
    }, service_id, user_key)
    if resp.get("code") == 0:
        agent_id = resp["data"]["agent_id"]
        log_fn(f"[import-user] ✔ 创建 {agent_name} → {agent_id}")
        return team_id, agent_id

    # 已存在：查询
    list_resp = core_post(endpoint, "/v3/meta/agent/list", {
        "team_id": team_id, "owner_user_id": user_id, "limit": 100,
    }, service_id, user_key)
    if list_resp.get("code") == 0:
        items = list_resp.get("data", {}).get("items", [])
        for a in items:
            if a.get("name") == agent_name:
                log_fn(f"[import-user] ⊙ {agent_name} 已存在 → {a['agent_id']}")
                return team_id, a["agent_id"]
    log_fn(f"[import-user] ✘ 创建 default-agent 失败: {resp.get('message', resp)}")
    return team_id, None


def import_prebuilt_skills(
    endpoint: str,
    service_id: str,
    user_key: str,
    user_id: str,
    team_id: str,
    agent_id: str,
    log_fn,
):
    """为 agent 导入预置 Skill。best-effort，失败仅 log。"""
    for sk in PREBUILT_SKILLS:
        try:
            resp = core_post(endpoint, "/v3/skill/create", {
                "user_id": user_id,
                "team_id": team_id,
                "agent_id": agent_id,
                "name": sk["name"],
                "content": sk["content"],
            }, service_id, user_key)
            code = resp.get("code")
            if code == 0:
                log_fn(f"[import-user] ✔ 导入 Skill \"{sk['name']}\"")
            elif code == 42201:  # SKILL_NAME_DUPLICATE — 幂等跳过
                log_fn(f"[import-user] ⊙ Skill \"{sk['name']}\" 已存在，跳过")
            else:
                log_fn(f"[import-user] ✘ Skill \"{sk['name']}\" 导入失败: code={code} {resp.get('message', '')}")
        except Exception as e:
            log_fn(f"[import-user] ✘ Skill \"{sk['name']}\" 异常: {e}")


def main() -> int:
    ap = argparse.ArgumentParser(description="直接写 MongoDB 导入 memory 用户 + 自定义 apikey")
    ap.add_argument("--config", default=None, help="core.yaml 路径 (默认 ../config/core.yaml)")
    ap.add_argument("--instance-id", default="default", help="实例 ID (默认 default)")
    ap.add_argument("--username")
    ap.add_argument("--apikey")
    ap.add_argument("--display-name", default=None)
    ap.add_argument("--batch", help="JSON 数组文件，每项 {username, apikey, display_name?, add_key?}")
    ap.add_argument(
        "--add-key",
        action="store_true",
        help="用户已存在时追加一把非 default key（不加此 flag 时会报错拒绝）",
    )
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true", help="仅打印结果 JSON，屏蔽进度日志")
    ap.add_argument("--core-endpoint", default="http://127.0.0.1:8420",
                    help="core 的 HTTP 地址（默认 http://127.0.0.1:8420）")
    args = ap.parse_args()

    script_dir = Path(__file__).resolve().parent
    cfg_path = Path(args.config).resolve() if args.config else (script_dir / ".." / "config" / "core.yaml").resolve()
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    store = ((cfg or {}).get("metadata") or {}).get("store") or {}
    mongo_uri = store.get("mongoUri")
    db_prefix = store.get("mongoDbPrefix")
    if not mongo_uri:
        raise SystemExit(f"metadata.store.mongoUri 缺失 ({cfg_path})")

    db_name = resolve_db_name(args.instance_id, db_prefix)
    users = load_users(args)

    def log(*m):
        if not args.json:
            print(*m, file=sys.stderr)

    log(f"[import-user] config     = {cfg_path}")
    log(f"[import-user] mongo      = {mask_uri(mongo_uri)}")
    log(f"[import-user] instanceId = {args.instance_id}")
    log(f"[import-user] dbName     = {db_name}")
    log(f"[import-user] users      = {len(users)}")

    if args.dry_run:
        log("[import-user] DRY-RUN，未连库")
        print(json.dumps(users, ensure_ascii=False, indent=2))
        return 0

    client = MongoClient(mongo_uri)
    results: list[dict[str, Any]] = []
    try:
        db = client[db_name]
        for u in users:
            r = import_one(client, db, u)
            results.append(r)
            if r["created"]:
                tag = "✓ 创建"
            elif r.get("added_key"):
                tag = "＋ 加 key"
            else:
                tag = "⚠ 已存在"
            log(f"[import-user] {tag} {r['username']} → {r['user_id']}")

            # ── 新增：创建 Team + Agent + Skill（仅新创建用户才走）──
            if r["created"]:
                try:
                    team_id, agent_id = ensure_default_team_and_agent(
                        args.core_endpoint, args.instance_id, u["apikey"],
                        r["user_id"], r["username"], db, log,
                    )
                    if team_id and agent_id:
                        import_prebuilt_skills(
                            args.core_endpoint, args.instance_id, u["apikey"],
                            r["user_id"], team_id, agent_id, log,
                        )
                except Exception as e:
                    log(f"[import-user] ✘ Team/Agent/Skill 创建异常，已跳过: {e}")
    finally:
        client.close()

    payload = results[0] if (len(users) == 1 and not args.batch) else results
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:
        print(f"[import-user] ERROR: {e}", file=sys.stderr)
        if os.environ.get("DEBUG"):
            import traceback
            traceback.print_exc()
        sys.exit(1)
