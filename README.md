# GYL3-Claw

飞书个人智能助手 — 通过飞书 SDK 长连接接收消息，调用 AI 网关（OpenAI 兼容）进行智能问答。

## 核心特性

- **飞书 SDK 长连接** — 无需公网地址，WebSocket 直连飞书，开箱即用
- **结构化 Prompt 管理** — YAML 定义分层 prompt（角色/规则），watchdog 热加载，改完即生效
- **混合路由** — 命令前缀 → 场景锁定 → 关键词匹配 → AI 自动分类 → general 兜底
- **场景锁定** — `/switch` 锁定场景后无需每次带前缀
- **网络搜索** — `/web` 命令调用 DevPilot 搜索 API，实时获取网络信息
- **URL 解析** — `/url` 命令或直接发送链接，自动抓取网页内容并 AI 总结
- **脚本执行 + 定时任务** — subprocess 异步执行 + APScheduler 定时调度
- **Prompt 效果追踪** — `/eval` 打分，JSONL 持久化，持续迭代优化
- **对话记忆** — SQLite 异步存储会话历史，支持多轮上下文

## 架构

```
飞书用户
  ↓ (WebSocket 长连接)
lark.ws.Client 事件接收
  ↓
混合路由 (命令 → 插件注册表 → 锁定 → 关键词 → AI分类)
  ↓
执行器调度 (注册表查找 → AI对话兜底)
  ↓
飞书回复 (文本 / Markdown 卡片)
```

**插件化**：命令和执行器通过装饰器自注册，Tool 定义（OpenAI function calling schema）集中管理。新增命令/工具只需加一个文件，零核心文件改动。

## 快速开始

```bash
# 1. 安装
python -m venv .venv
source .venv/bin/activate
pip install -e .

# 2. 配置
cp .env.example .env
# 编辑 .env，填入飞书和 AI 网关凭证

# 3. 启动（后台常驻，被 kill 自动拉起）
claw start

# 或 webhook 模式（需公网地址）
claw start --webhook

# 前台运行（调试用）
claw start -f
```

## 配置

所有敏感配置统一在 `.env` 管理：

```bash
FEISHU_APP_ID=xxx          # 飞书应用 App ID
FEISHU_APP_SECRET=xxx      # 飞书应用 App Secret
AI_BASE_URL=https://xxx/v1 # AI 网关地址（OpenAI 兼容）
AI_API_KEY=xxx              # AI 网关密钥
AI_MODEL=claude-opus-4-6    # 默认模型（统一控制所有场景）
DEVPILOT_API_KEY=xxx        # DevPilot 搜索 API 密钥（/web 命令）
```

`config.yaml` 管理非敏感配置（token 数、温度、会话长度、端口等）。

Prompt YAML 中 `model.name` 留空则自动继承 `AI_MODEL`，也可单独指定覆盖。

## 飞书命令

| 命令 | 功能 |
|------|------|
| `/help` | 查看帮助 |
| `/list` | 列出所有可用场景 |
| `/switch <id>` | 锁定场景（后续消息自动使用） |
| `/current` | 查看当前场景和版本 |
| `/clear` | 清除上下文 + 解除锁定 |
| `/reload` | 手动热加载 Prompt |
| `/eval <1-5> [备注]` | 对上一轮回答打分 |
| `/prompt add <id> <名称> <描述> <角色说明>` | 创建新场景 |
| `/prompt del <id>` | 删除场景 |
| `/prompt show <id>` | 查看场景详情（含 System Prompt） |
| `/web <关键词>` | 搜索网络信息 |
| `/url <链接>` | 解析网页内容并 AI 总结 |
| `/schedule <自然语言描述>` | 用自然语言创建定时任务 |
| `/schedule list` | 查看定时任务 |
| `/schedule remove <名称>` | 删除定时任务 |
| `/cmd <命令>` | 执行本地 shell 命令（禁止高危命令） |
| `/claude <问题>` | 调用 Claude Code 回答问题 |
| `/run <script> [args]` | 执行本地脚本 |
| `/<场景id> <问题>` | 用指定场景处理本条消息 |

直接发送消息即可智能问答，系统自动匹配最合适的场景。直接发送 URL 链接会自动解析总结。

## CLI

```bash
# 服务管理
claw start [--port N] [--webhook]  # 启动后台服务（launchd 常驻，被 kill 自动拉起）
claw start -f [--port N]           # 前台启动（调试用）
claw stop                          # 停止服务
claw status                        # 查看服务状态
claw restart [--port N] [--webhook]  # 重启服务
claw logs [-f] [-n 50]             # 查看日志（-f 持续输出）
claw help                          # 查看帮助

# Prompt 管理
claw prompt list                   # 列出所有 Prompt 场景
claw prompt show <id>              # 查看 Prompt 详情
claw prompt edit <id>              # 编辑 Prompt（$EDITOR）
claw prompt add <id> <名称> <描述> <角色说明>  # 创建新场景
claw prompt del <id>               # 删除场景

# 其他
claw script list                   # 列出可用脚本
claw schedule list                 # 列出定时任务
claw schedule add <n> <cron> <type> <target>  # 添加定时任务
claw schedule remove <name>        # 删除定时任务
claw eval [domain]                 # 查看评测统计
```

## 目录结构

```
GYL3-Claw/
├── app/
│   ├── main.py              # 入口：长连接 + FastAPI
│   ├── config.py            # 配置加载（.env + config.yaml）
│   ├── cli.py               # CLI 管理工具
│   ├── daemon.py            # launchd 后台常驻管理
│   ├── feishu/              # 飞书 SDK 封装
│   ├── prompt/              # Prompt 管理器 + 热加载
│   ├── router/              # 混合路由（命令/关键词/AI分类）
│   ├── executor/            # 执行器（插件化自注册）
│   │   ├── registry.py      #   注册中心（COMMAND_HANDLERS + EXECUTORS）
│   │   ├── dispatcher.py    #   调度器（注册表查找 + chat 兜底）
│   │   ├── chat.py          #   AI 对话（tool calling 查注册表）
│   │   ├── shell.py         #   /cmd + /claude 命令插件
│   │   ├── script.py        #   /run 命令插件
│   │   ├── web_search_executor.py  # /web 命令插件
│   │   ├── url_executor.py  #   /url 命令插件
│   │   └── rag.py           #   RAG 执行器（开发中）
│   ├── tools/               # Tool 定义注册（OpenAI function calling）
│   │   ├── registry.py      #   注册中心（定义+执行合一）
│   │   └── web_search.py    #   web_search tool 插件
│   ├── memory/              # SQLite 数据库 + 对话记忆
│   ├── utils/               # 工具模块（网络搜索/URL解析等）
│   └── scheduler/           # APScheduler 定时任务
├── prompts/                 # Prompt YAML 配置（tools 字段支持引用名）
│   ├── _router.yaml         # 路由分类器
│   ├── general.yaml         # 通用助手（tools: [web_search]）
│   ├── code.yaml            # 代码助手
│   └── writing.yaml         # 写作助手
├── scripts/                 # 可执行脚本
├── logs/                    # 运行日志（按日期轮转）
├── config.yaml              # 非敏感配置
├── .env.example             # 环境变量模板
└── pyproject.toml           # 项目依赖
```

## 技术栈

- **Runtime**: Python 3.11+
- **飞书**: lark-oapi（官方 SDK，长连接模式）
- **AI**: openai SDK（自定义 baseURL）
- **Web**: FastAPI + uvicorn（后台健康检查 + 调试端点）
- **数据库**: SQLite（aiosqlite 异步 + WAL）
- **定时任务**: APScheduler
- **CLI**: click
- **热加载**: watchdog
