from __future__ import annotations

# 独立进程入口必须先把项目 .env 写入 os.environ，再导入运行时模块。
# ruff: noqa: E402

import argparse
import asyncio
from collections.abc import Sequence

from backend.env import load_env


load_env()

import uvicorn

from backend.core.settings import get_settings


def selector_event_loop() -> asyncio.AbstractEventLoop:
    """uvicorn loop factory：在所有平台统一创建 SelectorEventLoop。

    uvicorn 0.36+ 在 Windows 单进程模式显式创建 ProactorEventLoop，并忽略
    事件循环策略；而深度研搜的 psycopg 异步 checkpoint 连接依赖 selector 型
    socket 就绪接口。SelectorEventLoop 与 Linux 默认及 uvicorn 子进程模式
    一致，且后端不使用 asyncio 子进程，切换是安全的。
    """

    return asyncio.SelectorEventLoop()


LOOP_FACTORY = "backend.__main__:selector_event_loop"


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m backend",
        description="知渊 API 服务入口",
    )
    parser.add_argument("--host", help="覆盖 API 监听地址")
    parser.add_argument("--port", type=int, help="覆盖 API 监听端口")
    parser.add_argument(
        "--reload",
        action="store_true",
        help="启用代码变更自动重载（需要 watchfiles）",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = _argument_parser().parse_args(argv)
    settings = get_settings()
    host = args.host or settings.app.host
    port = args.port or settings.app.port
    if not 1 <= port <= 65535:
        raise SystemExit("--port 必须位于 1..65535")
    uvicorn.run(
        "backend.app:app",
        host=host,
        port=port,
        reload=args.reload,
        loop=LOOP_FACTORY,
    )


if __name__ == "__main__":
    main()
