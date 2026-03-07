#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DevPilot 网页搜索模块
基于 DevPilot REST API 实现
"""

import asyncio
import json
import os
import logging
from typing import List, Optional
from dataclasses import dataclass, asdict
from pathlib import Path

import requests

# 设置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 常量配置
SEARCH_URL = "https://devpilot.zhongan.com/v1/search"
DEFAULT_TIMEOUT = 180  # 3 分钟
DEFAULT_MODEL = "sougou-search"
DEFAULT_SITES = []  # 空列表表示不限制域名，全网搜索
API_KEY_ENV_VAR = "DEVPILOT_API_KEY"


def _load_api_key_from_env_file(config_file: str = ".env") -> Optional[str]:
    """
    从 .env 文件加载 DEVPILOT_API_KEY

    Args:
        config_file: 配置文件路径

    Returns:
        API Key 或 None
    """
    config_path = Path(config_file)

    if not config_path.exists():
        return None

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    if key.strip() == API_KEY_ENV_VAR:
                        return value.strip()
    except Exception as e:
        logger.warning(f"读取配置文件失败: {e}")

    return None


@dataclass
class SearchResult:
    """单条搜索结果"""
    name: str
    url: str
    snippet: str
    site_name: Optional[str] = None
    date: Optional[str] = None


@dataclass
class SearchResponse:
    """搜索响应数据类"""
    results: List[SearchResult]
    success: bool
    error: Optional[str]
    query: str


def _get_api_key(api_key: Optional[str] = None) -> Optional[str]:
    """
    获取 API Key: 参数 > 环境变量 > .env 文件

    Args:
        api_key: 传入的 API Key（可选）

    Returns:
        API Key 或 None
    """
    if api_key:
        return api_key

    env_key = os.environ.get(API_KEY_ENV_VAR)
    if env_key:
        return env_key

    return _load_api_key_from_env_file()


def _parse_search_results(data: dict) -> List[SearchResult]:
    """
    解析搜索结果 JSON

    Args:
        data: API 响应数据

    Returns:
        SearchResult 列表
    """
    results = []

    # 尝试从不同的可能字段中获取结果
    items = data.get("results", data.get("data", []))

    if not isinstance(items, list):
        return results

    for item in items:
        if not isinstance(item, dict):
            continue

        result = SearchResult(
            name=item.get("name", item.get("title", "")),
            url=item.get("url", item.get("link", "")),
            snippet=item.get("snippet", item.get("description", "")),
            site_name=item.get("site_name", item.get("source", None)),
            date=item.get("date", item.get("published_date", None))
        )
        results.append(result)

    return results


def search(
    query: str,
    sites: Optional[List[str]] = None,
    api_key: Optional[str] = None,
    timeout: Optional[int] = None,
    model: Optional[str] = None
) -> SearchResponse:
    """
    同步搜索函数

    Args:
        query: 搜索查询字符串
        sites: 限制搜索的域名列表（可选）
        api_key: DevPilot API Key（可选，默认从环境变量读取）
        timeout: 请求超时时间（秒），默认 180 秒
        model: 搜索模型（可选，默认 sougou-search）

    Returns:
        SearchResponse: 搜索结果
    """
    # 获取 API Key
    resolved_api_key = _get_api_key(api_key)

    if not resolved_api_key:
        return SearchResponse(
            results=[],
            success=False,
            error=f"Missing API key. Set {API_KEY_ENV_VAR} in .env file, environment variable, or pass api_key parameter.",
            query=query
        )

    # 设置默认值
    if sites is None:
        sites = DEFAULT_SITES
    if timeout is None:
        timeout = DEFAULT_TIMEOUT
    if model is None:
        model = DEFAULT_MODEL

    # 构建请求
    headers = {
        "Accept": "*/*",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {resolved_api_key}",
        "User-Agent": "PostmanRuntime-ApipostRuntime/1.1.0"
    }

    payload = {
        "model": model,
        "query": query,
        "sites": sites
    }

    try:
        response = requests.post(
            SEARCH_URL,
            headers=headers,
            json=payload,
            timeout=timeout
        )

        response.raise_for_status()

        data = response.json()
        results = _parse_search_results(data)

        return SearchResponse(
            results=results,
            success=True,
            error=None,
            query=query
        )

    except requests.exceptions.Timeout:
        logger.error(f"搜索请求超时: {query}")
        return SearchResponse(
            results=[],
            success=False,
            error=f"Request timeout after {timeout} seconds",
            query=query
        )
    except requests.exceptions.HTTPError as e:
        logger.error(f"HTTP 错误: {e}")
        return SearchResponse(
            results=[],
            success=False,
            error=f"HTTP error: {e}",
            query=query
        )
    except requests.exceptions.RequestException as e:
        logger.error(f"网络请求错误: {e}")
        return SearchResponse(
            results=[],
            success=False,
            error=f"Request error: {e}",
            query=query
        )
    except json.JSONDecodeError as e:
        logger.error(f"JSON 解析错误: {e}")
        return SearchResponse(
            results=[],
            success=False,
            error=f"JSON decode error: {e}",
            query=query
        )
    except Exception as e:
        logger.error(f"搜索调用错误: {e}")
        return SearchResponse(
            results=[],
            success=False,
            error=f"Search error: {e}",
            query=query
        )


async def search_async(
    query: str,
    sites: Optional[List[str]] = None,
    api_key: Optional[str] = None,
    timeout: Optional[int] = None,
    model: Optional[str] = None
) -> SearchResponse:
    """
    异步搜索函数

    Args:
        query: 搜索查询字符串
        sites: 限制搜索的域名列表（可选）
        api_key: DevPilot API Key（可选，默认从环境变量读取）
        timeout: 请求超时时间（秒），默认 180 秒
        model: 搜索模型（可选，默认 sougou-search）

    Returns:
        SearchResponse: 搜索结果
    """
    try:
        import aiohttp
    except ImportError:
        # 如果 aiohttp 不可用，回退到同步实现
        logger.warning("aiohttp not available, falling back to sync implementation")
        return search(query, sites, api_key, timeout, model)

    # 获取 API Key
    resolved_api_key = _get_api_key(api_key)

    if not resolved_api_key:
        return SearchResponse(
            results=[],
            success=False,
            error=f"Missing API key. Set {API_KEY_ENV_VAR} in .env file, environment variable, or pass api_key parameter.",
            query=query
        )

    # 设置默认值
    if sites is None:
        sites = DEFAULT_SITES
    if timeout is None:
        timeout = DEFAULT_TIMEOUT
    if model is None:
        model = DEFAULT_MODEL

    # 构建请求
    headers = {
        "Accept": "*/*",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {resolved_api_key}",
        "User-Agent": "PostmanRuntime-ApipostRuntime/1.1.0"
    }

    payload = {
        "model": model,
        "query": query,
        "sites": sites
    }

    try:
        client_timeout = aiohttp.ClientTimeout(total=timeout)
        async with aiohttp.ClientSession(timeout=client_timeout) as session:
            async with session.post(SEARCH_URL, headers=headers, json=payload) as response:
                response.raise_for_status()
                data = await response.json()
                results = _parse_search_results(data)

                return SearchResponse(
                    results=results,
                    success=True,
                    error=None,
                    query=query
                )

    except asyncio.TimeoutError:
        logger.error(f"搜索请求超时: {query}")
        return SearchResponse(
            results=[],
            success=False,
            error=f"Request timeout after {timeout} seconds",
            query=query
        )
    except aiohttp.ClientResponseError as e:
        logger.error(f"HTTP 错误: {e}")
        return SearchResponse(
            results=[],
            success=False,
            error=f"HTTP error: {e.status} {e.message}",
            query=query
        )
    except aiohttp.ClientError as e:
        logger.error(f"网络请求错误: {e}")
        return SearchResponse(
            results=[],
            success=False,
            error=f"Request error: {e}",
            query=query
        )
    except json.JSONDecodeError as e:
        logger.error(f"JSON 解析错误: {e}")
        return SearchResponse(
            results=[],
            success=False,
            error=f"JSON decode error: {e}",
            query=query
        )
    except Exception as e:
        logger.error(f"搜索调用错误: {e}")
        return SearchResponse(
            results=[],
            success=False,
            error=f"Search error: {e}",
            query=query
        )


def format_search_results(response: SearchResponse) -> str:
    """
    格式化搜索结果为人类可读的字符串

    Args:
        response: 搜索响应

    Returns:
        格式化的字符串
    """
    if not response.success:
        return f"搜索失败: {response.error}"

    if not response.results:
        return f"未找到关于 '{response.query}' 的搜索结果"

    lines = [f"搜索结果 - '{response.query}':", ""]

    for i, result in enumerate(response.results, 1):
        lines.append(f"{i}. {result.name}")
        lines.append(f"   链接: {result.url}")
        if result.snippet:
            lines.append(f"   摘要: {result.snippet}")
        if result.site_name:
            lines.append(f"   来源: {result.site_name}")
        if result.date:
            lines.append(f"   日期: {result.date}")
        lines.append("")

    return "\n".join(lines)


def get_tool_definition() -> str:
    """
    获取 LLM 函数调用的工具定义

    Returns:
        JSON 格式的工具定义字符串
    """
    tool_def = {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "搜索互联网获取实时信息。当用户的问题涉及近期事件、实时数据、你不确定或知识截止日期之后的内容时，使用此工具进行网络搜索。返回相关网页的摘要信息。不要对你已经确信的常识性问题使用搜索",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索查询词，应简洁明确，使用与问题最相关的语言"
                    }
                },
                "required": ["query"]
            }
        }
    }
    return json.dumps(tool_def, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    import sys

    query = sys.argv[1] if len(sys.argv) > 1 else "Python 教程"

    print(f"搜索: {query}")
    print("-" * 50)

    result = search(query)

    if result.success:
        print(format_search_results(result))
    else:
        print(f"搜索失败: {result.error}")

    print("-" * 50)
    print("工具定义:")
    print(get_tool_definition())
