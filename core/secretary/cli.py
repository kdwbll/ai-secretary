from __future__ import annotations

import argparse
from pathlib import Path

from .app import DB, MEMORY, SERVICE


def main() -> None:
    parser = argparse.ArgumentParser(prog="second-brain", description="第二大脑本地 AI 助理")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="初始化记忆目录")
    chat = sub.add_parser("chat", help="对话")
    chat.add_argument("message", nargs="*")
    sub.add_parser("interview", help="开始冷启动采访")
    search = sub.add_parser("search", help="搜索记忆")
    search.add_argument("query")
    forget = sub.add_parser("forget", help="全局忘记某项信息")
    forget.add_argument("phrase")
    undo = sub.add_parser("undo", help="撤销一次修改")
    undo.add_argument("id", type=int)
    args = parser.parse_args()

    SERVICE.initialize()
    if args.command == "init":
        print("记忆目录已初始化。")
    elif args.command == "chat":
        message = " ".join(args.message).strip() or input("你：")
        print("助理：" + SERVICE.chat(message)["answer"])
    elif args.command == "search":
        for hit in MEMORY.search(args.query):
            print(f"[{hit['score']}] {hit['path']}\n{hit['excerpt']}\n")
    elif args.command == "forget":
        print(f"已删除 {MEMORY.forget(args.phrase)} 条相关信息。")
    elif args.command == "undo":
        MEMORY.undo(args.id)
        print("已撤销。")
    elif args.command == "interview":
        for item in SERVICE.interview_questions():
            answer = input(f"\n[{item['domain']}] {item['question']}\n> ").strip()
            if answer:
                SERVICE.chat(answer)
        print("采访完成，请在 memory/ 中查看并确认初版记忆。")


if __name__ == "__main__":
    main()
