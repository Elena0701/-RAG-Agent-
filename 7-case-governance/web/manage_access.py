"""Local administrator CLI. Invitation codes are NOT model API credentials."""
import argparse
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from access_control import AccessControl

WEB = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description="管理实时审查邀请码；仅在主机终端运行")
    parser.add_argument("--data-dir", type=Path, default=WEB/"data")
    sub = parser.add_subparsers(dest="action", required=True)
    create = sub.add_parser("create", help="创建个人邀请码，仅此次显示明文")
    create.add_argument("--name", required=True)
    create.add_argument("--role", choices=("member", "admin"), default="member")
    create.add_argument("--days", type=int, default=7)
    create.add_argument("--daily-limit", type=int)
    create.add_argument("--max-clauses", type=int)
    sub.add_parser("list", help="列出邀请码编号及权限，不显示邀请码明文")
    revoke = sub.add_parser("revoke", help="撤销邀请码，立即使其所有登录会话失效")
    revoke.add_argument("--id", required=True)
    args = parser.parse_args()
    access = AccessControl(args.data_dir/"access")
    if args.action == "create":
        try:
            record = access.create_invite(args.name,args.role,args.days,args.max_clauses,args.daily_limit)
        except ValueError as exc:
            parser.error(str(exc))
        print(f"名称：{record['name']}\n编号：{record['id']}\n角色：{record['role']}")
        print(f"邀请码（仅此一次显示）：{record['code']}")
        print(f"有效期：{record['days']}天；每次最多{record['max_clauses']}类；每日{record['daily_limit']}次")
        print("请单独发给该使用者；邀请码不是API密钥，模型费用由主机后台账户承担。")
    elif args.action == "list":
        for row in access.list_invites():
            expiry=datetime.fromtimestamp(row['expires'],timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M')
            print(f"{row['id']}  {row['name']}  {row['role']}  每次{row['max_clauses']}类/每日{row['daily_limit']}次  到期{expiry}  {'已撤销' if row['revoked'] else '未撤销'}")
    else:
        print("已撤销，所有相关会话失效。" if access.revoke(args.id) else "未找到该编号。")


if __name__ == "__main__":
    if not sys.stdout.isatty():
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
