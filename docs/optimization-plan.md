# GYL3-Claw 优化建议

> 2026-03-08 整理，基于当前代码全量分析 + Claude Code Skills 设计理念对比
> 2026-03-08 更新：已完成执行器插件化 + Tool 定义外置（建议 2/3/4）

---

## 一、架构层面：借鉴 Skills 的设计理念

### 1. Prompt YAML 增加 supporting files 支持

目前每个 prompt 就是一个 `.yaml` 文件，所有内容都塞在里面。当 system prompt 越写越长时会变得难维护。

**建议**：参考 Skills 的目录结构，改为每个场景一个目录：

```
prompts/
├── general/
│   ├── prompt.yaml          # 主配置（现有格式不变）
│   ├── reference.md         # 详细规则（按需加载）
│   └── examples.md          # 期望输出示例
├── url_reader/
│   ├── prompt.yaml
│   └── output_template.md   # 输出模板单独维护
├── code/
│   ├── prompt.yaml
│   └── conventions.md       # 编码规范
└── _router.yaml             # 路由器保持单文件
```

`build_system_message()` 时自动拼接目录下的 `.md` 文件，这样 prompt 迭代不用挤在一个 YAML 里。

### 2. 执行器插件化 ✅ 已完成

现在每加一个命令（`/web`、`/url`、`/cmd`、`/claude`），需要改 3 个文件：`router.py` + `dispatcher.py` + 新执行器。随着命令增多，router 的 `_handle_command` 会膨胀。

**已实现**：
- `app/executor/registry.py` — 注册中心（`COMMAND_HANDLERS` + `EXECUTORS`）
- 各执行器通过 `@register_command` / `@register_executor` 装饰器自注册
- `dispatcher.py` 改为 `EXECUTORS.get()` 查找，`router.py` 改为遍历 `COMMAND_HANDLERS`
- 新增命令只需加一个文件，无需修改 router/dispatcher

### 3. Tool 定义外置 ✅ 已完成

目前 `web_search` 的 tool 定义硬写在 `general.yaml` 里。如果要给多个场景都加 `web_search` 或新增 `url_fetch` tool，需要每个 YAML 都复制一份。

**已实现**：
- `app/tools/registry.py` — Tool 注册中心（定义 + 执行合一）
- `app/tools/web_search.py` — `@register_tool("web_search")` 自注册
- `prompts/general.yaml` 中 `tools: [web_search]`（字符串引用）
- `PromptManager.reload()` 调用 `resolve_tool_references()` 自动展开为完整 schema
- 支持混合模式：字符串查注册表，dict 原样透传（向后兼容）

---

## 二、实现层面：当前代码可优化的点

### 4. `chat.py` 中 `_execute_tool_call` 只支持 web_search ✅ 已完成

当 AI 的 tool calling 返回未知 tool 时只返回 `"Unknown tool: {name}"`。`url_fetch` 已作为 prompt 场景存在，但不能作为 tool call 被 AI 主动调用。

**已实现**：`_execute_tool_call()` 改为查 `app/tools/registry` 注册表，13 行 → 4 行。新增 tool 只需在 `app/tools/` 下加一个文件用 `@register_tool` 装饰器注册即可。

### 5. AI 分类开销

每条不匹配命令/关键词的消息都会调一次 AI 分类。一个活跃用户聊天时，大部分消息其实应该走 `general`。

**建议**：
- 短消息（<10 字）+ 无关键词 → 直接走 `general`，跳过分类
- 或加一个简单的 LRU 缓存，同一 chat_id 短时间内重复场景不再分类

### 6. URL fetcher 的 HTML 解析太粗糙

当前用正则去标签，对 JS 渲染的页面基本拿不到正文。

**建议**：
- 加一个 `readability` 或 `trafilatura` 库做正文提取（pip 一条依赖）
- fallback：正则方案作为后备

### 7. 对话历史无上限清理

`get_history` 取最近 20 条，但数据库里的消息只增不删。

**建议**：加一个定时任务，清理 7 天前的会话记录。或者在 `save_message` 时顺手删超出 `max_turns` 的旧消息。

### 8. 搜索/URL 结果没有进对话记忆

`/web` 和 `/url` 的结果直接返回，不走 `save_message`，所以 AI 后续聊天不记得之前搜过什么。

**建议**：在 dispatcher 中，`web_search` 和 `url_fetch` 执行完后也存入对话历史，让多轮对话能引用之前的搜索/解析结果。

---

## 优先级排序

| 优先级 | 建议 | 状态 |
|--------|------|------|
| 高 | 8. 搜索/URL 结果进记忆 | 待做 |
| 高 | 6. HTML 正文提取优化 | 待做 |
| ~~高~~ | ~~4. Tool 注册表化~~ | ✅ 已完成 |
| 中 | 5. AI 分类缓存 | 待做 |
| ~~中~~ | ~~3. Tool 定义外置~~ | ✅ 已完成 |
| 中 | 7. 对话历史清理 | 待做 |
| 低 | 1. Prompt 目录化 | 待做 |
| ~~低~~ | ~~2. 执行器插件化~~ | ✅ 已完成 |
