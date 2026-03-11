"""stock_quote tool: A股实时行情查询 (tushare realtime_quote)."""
from __future__ import annotations

import asyncio
import json
import logging
import os

from app.tools.registry import register_tool

logger = logging.getLogger(__name__)

_DEFINITION = {
    "type": "function",
    "function": {
        "name": "stock_quote",
        "description": "查询A股实时行情。输入股票代码（如 600000.SH），返回名称、现价、涨跌幅、成交量等实时数据。支持同时查询多只股票（逗号分隔）。",
        "parameters": {
            "type": "object",
            "properties": {
                "ts_code": {
                    "type": "string",
                    "description": "Tushare 股票代码，如 600000.SH 或 000001.SZ，多只用逗号分隔",
                }
            },
            "required": ["ts_code"],
        },
    },
}


def _init_tushare():
    """Lazy-init tushare with token from env."""
    import tushare as ts

    token = os.getenv("TUSHARE_TOKEN", "")
    if not token:
        raise RuntimeError("TUSHARE_TOKEN 未配置")
    ts.set_token(token)
    return ts


def _fetch_quote(ts_code: str) -> str:
    """Synchronous fetch — called via asyncio.to_thread."""
    ts = _init_tushare()
    df = ts.realtime_quote(ts_code=ts_code)

    if df is None or df.empty:
        return f"未找到 {ts_code} 的行情数据，请检查代码是否正确。"

    blocks: list[str] = []
    for _, row in df.iterrows():
        name = row.get("NAME", row.get("TS_CODE", ""))
        code = row.get("TS_CODE", "")
        price = float(row.get("PRICE", 0))
        pre_close = float(row.get("PRE_CLOSE", 0))
        open_ = row.get("OPEN", "")
        high = row.get("HIGH", "")
        low = row.get("LOW", "")
        volume = int(row.get("VOLUME", 0))
        amount = float(row.get("AMOUNT", 0))
        bid = row.get("BID", "")
        ask = row.get("ASK", "")
        dt = row.get("DATE", "")
        tm = row.get("TIME", "")

        change = price - pre_close if pre_close else 0
        pct = change / pre_close * 100 if pre_close else 0
        sign = "+" if change >= 0 else ""
        vol_str = f"{volume / 10000:.0f}万" if volume >= 10000 else str(volume)
        amt_str = f"{amount / 1e8:.2f}亿" if amount >= 1e8 else f"{amount / 1e4:.0f}万"

        block = (
            f"📈 {name} ({code})\n"
            f"现价: {price}  涨跌: {sign}{change:.2f} ({sign}{pct:.2f}%)\n"
            f"开: {open_}  高: {high}  低: {low}  昨收: {pre_close}\n"
            f"成交量: {vol_str}  成交额: {amt_str}\n"
            f"买一: {bid}  卖一: {ask}\n"
            f"时间: {dt} {tm}"
        )
        blocks.append(block)

    return "\n\n".join(blocks)


@register_tool("stock_quote", definition=_DEFINITION)
async def execute_stock_quote(arguments: str) -> str:
    try:
        args = json.loads(arguments)
        ts_code = args.get("ts_code", "")
    except (json.JSONDecodeError, AttributeError):
        ts_code = arguments

    ts_code = ts_code.strip()
    if not ts_code:
        return "Error: 缺少股票代码参数"

    logger.info("Tool call: stock_quote(%r)", ts_code)
    try:
        return await asyncio.to_thread(_fetch_quote, ts_code)
    except Exception as e:
        logger.exception("stock_quote failed")
        return f"行情查询失败: {e}"


if __name__ == "__main__":
    import sys

    from dotenv import load_dotenv

    load_dotenv()
    code = sys.argv[1] if len(sys.argv) > 1 else ""
    if not code:
        print("用法: python -m app.tools.stock_quote <ts_code>")
        print("示例: python -m app.tools.stock_quote 600000.SH")
        sys.exit(1)
    print(_fetch_quote(code))
