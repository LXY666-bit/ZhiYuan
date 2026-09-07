"""API 启动入口的 event loop 回归。

深度研搜的 psycopg 异步 checkpoint 连接要求 selector 型 event loop；
uvicorn 0.36+ 在 Windows 单进程模式会显式创建 ProactorEventLoop 并忽略
事件循环策略，因此入口必须通过自定义 loop factory 覆盖。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
import uvicorn

import backend.__main__ as entrypoint


def _fake_settings(host: str = "10.9.8.7", port: int = 9999) -> SimpleNamespace:
    return SimpleNamespace(app=SimpleNamespace(host=host, port=port))


def _install_fake_uvicorn_run(
    monkeypatch: pytest.MonkeyPatch, settings: SimpleNamespace | None = None
) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def fake_run(app: str, **kwargs: Any) -> None:
        captured.update(app=app, **kwargs)

    monkeypatch.setattr(uvicorn, "run", fake_run)
    monkeypatch.setattr(
        entrypoint, "get_settings", lambda: settings or _fake_settings()
    )
    return captured


def test_main_passes_selector_loop_factory_to_uvicorn(
    monkeypatch: pytest.MonkeyPatch,
):
    captured = _install_fake_uvicorn_run(monkeypatch)

    entrypoint.main([])

    assert captured["app"] == "backend.app:app"
    assert captured["loop"] == entrypoint.LOOP_FACTORY


def test_main_defaults_to_settings_host_and_port(monkeypatch: pytest.MonkeyPatch):
    captured = _install_fake_uvicorn_run(
        monkeypatch, _fake_settings(host="0.0.0.0", port=8000)
    )

    entrypoint.main([])

    assert captured["host"] == "0.0.0.0"
    assert captured["port"] == 8000
    assert captured["reload"] is False


def test_main_cli_arguments_override_settings(monkeypatch: pytest.MonkeyPatch):
    captured = _install_fake_uvicorn_run(monkeypatch)

    entrypoint.main(["--host", "127.0.0.1", "--port", "8123", "--reload"])

    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 8123
    assert captured["reload"] is True


def test_main_rejects_out_of_range_port(monkeypatch: pytest.MonkeyPatch):
    _install_fake_uvicorn_run(monkeypatch)

    with pytest.raises(SystemExit):
        entrypoint.main(["--port", "70000"])


def test_selector_event_loop_factory_returns_selector_loop():
    loop = entrypoint.selector_event_loop()
    try:
        assert isinstance(loop, asyncio.SelectorEventLoop)
    finally:
        loop.close()


def test_uvicorn_resolves_the_entrypoint_loop_factory():
    config = uvicorn.Config(
        "backend.app:app", loop=entrypoint.LOOP_FACTORY, lifespan="off"
    )

    assert config.get_loop_factory() is entrypoint.selector_event_loop
