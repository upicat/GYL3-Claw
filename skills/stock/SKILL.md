---
name: stock
description: "查询A股实时行情，支持按股票代码查询现价、涨跌幅、成交量等数据。"
tools:
  - stock_quote
commands:
  - "/stock"
model:
  temperature: 0
---

## 使用场景

- 用户查询股票实时行情、价格
- 用户提到股票代码或股票名称想了解行情

## 使用方法

1. 从用户消息中提取股票代码（如 600000.SH）
2. 调用 stock_quote 工具查询实时行情
3. 将结果以清晰格式呈现给用户

## 注意事项

- 代码格式: 上海 .SH，深圳 .SZ（如 600000.SH、000001.SZ）
- 支持逗号分隔同时查多只股票
- 行情数据来自 tushare，仅供参考
