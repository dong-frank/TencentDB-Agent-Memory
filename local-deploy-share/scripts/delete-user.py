#!/usr/bin/env python3
"""直接从 MongoDB 删除用户（不走 core /v3/meta/user/delete 接口）。

对齐 core MetadataService.deleteUsers → store.deleteUsers：
  meta_users        删主档
  meta_user_keys    删 user_id 匹配的全部 key
  meta_team_members 删 user_id 匹配的全部成员关系
  meta_asset_acl    删 subject_type=user AND subject_id=... 的 ACL

**不清理**（跟 core 官方接口一致）：
  meta_agents.owner_user_id        → 会变孤儿，Panel 可能显示 unknown owner
  meta_tasks.creator_user_id       → 同上
  meta_participation_logs.user_id  → 同上
  VDB 里的 L0/L1/L2/L3 memory      → user_id filter tag 保留，需另清

保护：
  - 默认 dry-run，要真删必须 --yes
  - 拒绝删 system_admin，除非 --force-system-admin 且不是最后一个
  - 支持 --user-id 或 --username 定位（username 匹配 >1 会报错，需用 --user-id 精确指定）
  - 事务包 4 张表（config 里 mongoTransactions: true）
  - 会打印孤儿资源计数供 review

用法：
  预览：
    ./delete-user.py --user-id usr-mnoi0ee7oj
    ./delete-user.py --username alice

  执行：
    ./delete-user.py --user-id usr-mnoi0ee7oj --yes
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from pymongo import MongoClient

DEFAULT_DB_PREFIX = "tdai_metadata"


def sanitize_instance_id(iid: str) -> str:
    return re.sub(r'[/\\."$ \0]', "_", iid.strip())


def resolve_db_name(instance_id: str, prefix: str | None) -> str:
    p = (prefix or "").strip() or DEFAULT_DB_PREFIX
    s = sanitize_instance_id(instance_id)
    if not s:
        raise ValueError(f"instance_id invalid: {instance_id!r}")
    return f"{p}_{s[: 64 - len(p) - 1]}"


def mask_uri(uri: str) -> str:
    return re.sub(r"//([^:]+):[^@]+@", r"//\1:***@", uri)


def locate_user(users_col, args: argparse.Namespace) -> dict[str, Any]:
    """按 --user-id 或 --username 找出唯一目标用户。"""
    if args.user_id:
        u = users_col.find_one({"user_id": args.user_id})
        if not u:
            raise SystemExit(f"用户不存在: user_id={args.user_id}")
        return u
    if args.username:
        matches = list(users_col.find({"username": args.username}))
        if not matches:
            raise SystemExit(f"用户不存在: username={args.username}")
        if len(matches) > 1:
            ids = ", ".join(f"{m['user_id']}({m.get('auth_provider','?')})" for m in matches)
            raise SystemExit(
                f"username '{args.username}' 匹配到 {len(matches)} 个用户: {ids}。"
                f" 请用 --user-id 精确指定。"
            )
        return matches[0]
    raise SystemExit("必须指定 --user-id 或 --username")


def count_orphans(db, user_id: str) -> dict[str, int]:
    """预估删除后会变成孤儿的关联资源数（脚本不清理，仅报告）。"""
    return {
        "meta_agents.owner_user_id": db["meta_agents"].count_documents({"owner_user_id": user_id}),
        "meta_tasks.creator_user_id": db["meta_tasks"].count_documents({"creator_user_id": user_id}),
        "meta_participation_logs.user_id": db["meta_participation_logs"].count_documents({"user_id": user_id}),
    }


def count_cascade(db, user_id: str) -> dict[str, int]:
    """预估级联删除的行数（对齐 core 侧行为）。"""
    return {
        "meta_users": db["meta_users"].count_documents({"user_id": user_id}),
        "meta_user_keys": db["meta_user_keys"].count_documents({"user_id": user_id}),
        "meta_team_members": db["meta_team_members"].count_documents({"user_id": user_id}),
        "meta_asset_acl": db["meta_asset_acl"].count_documents(
            {"subject_type": "user", "subject_id": user_id}
        ),
    }


def do_delete(client: MongoClient, db, user_id: str) -> dict[str, int]:
    """事务包 4 张表的 deleteMany。"""
    deleted = {}
    with client.start_session() as s:
        with s.start_transaction():
            deleted["meta_user_keys"] = db["meta_user_keys"].delete_many(
                {"user_id": user_id}, session=s
            ).deleted_count
            deleted["meta_team_members"] = db["meta_team_members"].delete_many(
                {"user_id": user_id}, session=s
            ).deleted_count
            deleted["meta_asset_acl"] = db["meta_asset_acl"].delete_many(
                {"subject_type": "user", "subject_id": user_id}, session=s
            ).deleted_count
            deleted["meta_users"] = db["meta_users"].delete_one(
                {"user_id": user_id}, session=s
            ).deleted_count
    return deleted


def main() -> int:
    ap = argparse.ArgumentParser(description="从 MongoDB 删除 memory 用户 + 级联资源")
    ap.add_argument("--config", default=None, help="core.yaml 路径 (默认 ../config/core.yaml)")
    ap.add_argument("--instance-id", default="default", help="实例 ID (默认 default)")
    ap.add_argument("--user-id", help="精确定位用户 (优先级高于 --username)")
    ap.add_argument("--username", help="按 username 定位 (匹配 >1 会拒绝，需改用 --user-id)")
    ap.add_argument("--yes", action="store_true", help="真删。不加此 flag 默认只预览")
    ap.add_argument(
        "--force-system-admin",
        action="store_true",
        help="允许删除 system_admin 用户 (仍会拒绝删最后一个 system_admin)",
    )
    ap.add_argument("--json", action="store_true", help="屏蔽 stderr 日志，只 stdout 结果")
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

    def log(*m):
        if not args.json:
            print(*m, file=sys.stderr)

    log(f"[delete-user] config     = {cfg_path}")
    log(f"[delete-user] mongo      = {mask_uri(mongo_uri)}")
    log(f"[delete-user] instanceId = {args.instance_id}")
    log(f"[delete-user] dbName     = {db_name}")

    client = MongoClient(mongo_uri)
    try:
        db = client[db_name]
        user = locate_user(db["meta_users"], args)
        user_id = user["user_id"]
        username = user["username"]
        user_type = user.get("user_type", "normal")

        log("")
        log(f"[delete-user] 目标用户:")
        log(f"  user_id     = {user_id}")
        log(f"  username    = {username}")
        log(f"  auth_provider = {user.get('auth_provider')}")
        log(f"  user_type   = {user_type}")
        log(f"  status      = {user.get('status')}")
        log(f"  created_at  = {user.get('created_at')}")

        # 硬风险 1: system_admin
        if user_type == "system_admin":
            if not args.force_system_admin:
                raise SystemExit(
                    f"拒绝删除 system_admin 用户 (user_id={user_id})。"
                    f" 若确实需要请加 --force-system-admin（仍会拒删最后一个 system_admin）。"
                )
            # 对齐 core: 不允许删掉最后一个 system_admin
            total_admins = db["meta_users"].count_documents({"user_type": "system_admin"})
            if total_admins <= 1:
                raise SystemExit(
                    f"这是实例内最后一个 system_admin，拒绝删除（对齐 core last_system_admin 检查）"
                )

        cascade = count_cascade(db, user_id)
        orphans = count_orphans(db, user_id)

        log("")
        log("[delete-user] 级联删除计划:")
        for k, v in cascade.items():
            log(f"  {k:24s} → 删 {v} 行")
        log("")
        log("[delete-user] ⚠ 孤儿资源（脚本不清，跟 core 官方 delete 一致）:")
        for k, v in orphans.items():
            if v > 0:
                log(f"  {k:32s} = {v} 行 (owner 指向 {user_id} 会失效)")
            else:
                log(f"  {k:32s} = 0")
        log("")
        log("[delete-user] ⚠ VDB 中的 L0/L1/L2/L3 memory 记录不清（需另走 VDB 清理）")
        log("")

        if not args.yes:
            log("[delete-user] DRY-RUN。加 --yes 真删。")
            result = {
                "dry_run": True,
                "user_id": user_id,
                "username": username,
                "user_type": user_type,
                "cascade_plan": cascade,
                "orphans": orphans,
            }
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0

        deleted = do_delete(client, db, user_id)
        log(f"[delete-user] ✓ 删除完成: {deleted}")
        result = {
            "dry_run": False,
            "user_id": user_id,
            "username": username,
            "user_type": user_type,
            "deleted": deleted,
            "orphans_left": orphans,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:
        print(f"[delete-user] ERROR: {e}", file=sys.stderr)
        if os.environ.get("DEBUG"):
            import traceback
            traceback.print_exc()
        sys.exit(1)
