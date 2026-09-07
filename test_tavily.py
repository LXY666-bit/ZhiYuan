import os

import pytest
from tavily import TavilyClient


def test_tavily_search():
    if os.getenv("TAVILY_LIVE_TEST") != "1":
        pytest.skip("set TAVILY_LIVE_TEST=1 to run the live Tavily smoke test")

    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        pytest.skip("TAVILY_API_KEY is required for the live Tavily smoke test")

    tavily = TavilyClient(api_key=api_key)

    # 执行搜索
    response = tavily.search(
        query="什么是 Tavily 搜索API？",
        search_depth="basic",
        max_results=3
    )

    # 打印结果
    print("=== 搜索结果 ===")
    for idx, item in enumerate(response["results"], 1):
        print(f"\n{idx}. 标题：{item['title']}")
        print(f"   链接：{item['url']}")
        print(f"   摘要：{item['content'][:120]}...")

    # 可选：加断言验证结果正常
    assert len(response["results"]) > 0, "未返回任何搜索结果"
