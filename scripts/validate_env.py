import os
import sys

REQUIRED_VARS = [
    "BOT_TOKEN",
    "DATABASE_URL",
    "REDIS_URL",
    "ALLOWED_CHAT_ID",
    "ALLOWED_CHATS",
    "MMR_CONCURRENCY_LIMIT",
    "OPENAI_API_KEY",
    "ADMIN_CHAT_ID",
]

OPTIONAL_VARS = [
    "WEBHOOK_URL",
    "BOT_NAME",
    "WEB_CONCURRENCY",
    "PORT",
]


def main() -> int:
    missing = [name for name in REQUIRED_VARS if not os.getenv(name)]
    if missing:
        print(f"ERROR: missing required env vars: {', '.join(missing)}")
        return 1

    for name in OPTIONAL_VARS:
        if name not in os.environ:
            print(f"WARN: optional env var {name} is not set")

    print("OK: required env vars are present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())