from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from app.executor.dispatcher import RouteResult
from app.executor.script import list_scripts
from app.memory.conversation import clear_history, get_last_exchange
from app.prompt.manager import PromptManager
from app.router.classifier import classify_by_ai
from app.router.keyword import match_by_command, match_by_keyword
from app.scheduler.scheduler import add_scheduled_task, remove_scheduled_task, list_scheduled_tasks

logger = logging.getLogger(__name__)

EVAL_LOG_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "prompt_eval.jsonl"

_HELP_TEXT = """\
**Claw 飞书智能助手**

可用命令：
- `/help` — 查看此帮助
- `/list` — 列出所有可用场景
- `/switch <id>` — 锁定场景（后续消息自动使用）
- `/current` — 查看当前场景和版本
- `/clear` — 清除上下文 + 解除锁定
- `/reload` — 手动热加载 Prompt
- `/eval <1-5> [备注]` — 对上一轮回答打分
- `/prompt add/del/show` — 管理 Prompt 场景
- `/web <关键词>` — 搜索网络信息
- `/schedule <描述>` — 用自然语言创建定时任务
- `/schedule list` — 查看定时任务
- `/schedule remove <名称>` — 删除定时任务
- `/run <script> [args]` — 执行本地脚本
- `/<场景id> <问题>` — 用指定场景处理本条消息

直接发送消息即可智能问答，系统会自动匹配最合适的场景。"""


class Router:
    def __init__(self, prompt_manager: PromptManager):
        self.prompt_manager = prompt_manager
        self.session_domains: dict[str, str] = {}  # chat_id -> domain_id

    async def route(self, chat_id: str, user_id: str, message: str) -> RouteResult:
        text = message.strip()

        # System commands
        if text.startswith("/"):
            cmd_result = await self._handle_command(chat_id, user_id, text)
            if cmd_result is not None:
                return cmd_result

        # Locked session domain
        locked_domain = self.session_domains.get(chat_id)

        # Command prefix match (e.g., /code how to sort)
        prompts = self.prompt_manager.all_prompts
        cmd_match = match_by_command(text, prompts)
        if cmd_match:
            domain_id, remaining = cmd_match
            return RouteResult(type="chat", domain_id=domain_id, message=remaining or text)

        # If session is locked, use that domain
        if locked_domain:
            return RouteResult(type="chat", domain_id=locked_domain, message=text)

        # Keyword match
        kw_match = match_by_keyword(text, prompts)
        if kw_match:
            return RouteResult(type="chat", domain_id=kw_match, message=text)

        # AI classification fallback
        domain_id = await classify_by_ai(text, self.prompt_manager)
        return RouteResult(type="chat", domain_id=domain_id, message=text)

    async def _handle_command(
        self, chat_id: str, user_id: str, text: str
    ) -> RouteResult | None:
        parts = text.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        if cmd == "/help":
            return RouteResult(type="command", command_response=_HELP_TEXT)

        if cmd == "/list":
            domains = self.prompt_manager.list_domains()
            lines = ["**可用场景：**\n"]
            for d in domains:
                cmds = " ".join(d["commands"]) if d["commands"] else ""
                lines.append(f"- **{d['id']}** ({d['name']}): {d['description']}  {cmds}")
            return RouteResult(type="command", command_response="\n".join(lines))

        if cmd == "/switch":
            if not arg:
                return RouteResult(type="command", command_response="用法: /switch <场景id>\n使用 /list 查看可用场景")
            if not self.prompt_manager.get_prompt(arg):
                return RouteResult(type="command", command_response=f"场景 '{arg}' 不存在，使用 /list 查看可用场景")
            self.session_domains[chat_id] = arg
            cfg = self.prompt_manager.get_prompt(arg)
            return RouteResult(
                type="command",
                command_response=f"已切换到 **{cfg.name}** 场景（{arg}），后续消息将自动使用此场景。\n发送 /switch 其他场景 或 /clear 解除锁定。",
            )

        if cmd == "/current":
            locked = self.session_domains.get(chat_id)
            if locked:
                cfg = self.prompt_manager.get_prompt(locked)
                name = cfg.name if cfg else locked
                ver = cfg.version if cfg else "?"
                return RouteResult(type="command", command_response=f"当前场景: **{name}** ({locked}) v{ver}")
            return RouteResult(type="command", command_response="当前未锁定场景，系统将自动路由。")

        if cmd == "/clear":
            self.session_domains.pop(chat_id, None)
            count = await clear_history(chat_id)
            return RouteResult(type="command", command_response=f"已清除会话上下文（{count} 条记录），场景锁定已解除。")

        if cmd == "/reload":
            self.prompt_manager.reload()
            domains = self.prompt_manager.list_domains()
            names = [d["id"] for d in domains]
            return RouteResult(type="command", command_response=f"Prompt 已重新加载，当前场景: {', '.join(names)}")

        if cmd == "/eval":
            return await self._handle_eval(chat_id, user_id, arg)

        if cmd == "/run":
            return self._handle_run(arg)

        if cmd == "/web" or (cmd.startswith("/web") and len(cmd) > 4):
            # Support both "/web 关键词" and "/web关键词" (no space)
            web_query = arg
            if cmd != "/web":
                web_query = cmd[4:] + (" " + arg if arg else "")
            if not web_query:
                return RouteResult(type="command", command_response="用法: /web <搜索关键词>\n示例: /web Python 最新版本")
            return RouteResult(type="web_search", message=web_query)

        if cmd == "/schedule":
            return await self._handle_schedule(arg)

        if cmd == "/prompt":
            return self._handle_prompt(arg)

        # Check if it's a /<domain_id> <question> pattern
        potential_domain = cmd.lstrip("/")
        if self.prompt_manager.get_prompt(potential_domain) and arg:
            return RouteResult(type="chat", domain_id=potential_domain, message=arg)

        return None

    async def _handle_eval(self, chat_id: str, user_id: str, arg: str) -> RouteResult:
        if not arg:
            return RouteResult(type="command", command_response="用法: /eval <1-5> [备注]")
        parts = arg.split(maxsplit=1)
        try:
            score = int(parts[0])
            if not 1 <= score <= 5:
                raise ValueError
        except ValueError:
            return RouteResult(type="command", command_response="评分须为 1-5 的整数")

        note = parts[1] if len(parts) > 1 else ""
        exchange = await get_last_exchange(chat_id)
        if not exchange:
            return RouteResult(type="command", command_response="没有找到可评价的对话记录。")

        record = {
            "timestamp": datetime.now().isoformat(),
            "chat_id": chat_id,
            "user_id": user_id,
            "score": score,
            "note": note,
            "route_name": exchange["route_name"],
            "user_message": exchange["user_message"][:200],
            "assistant_message": exchange["assistant_message"][:200],
        }
        EVAL_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(EVAL_LOG_PATH, "a") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        return RouteResult(
            type="command",
            command_response=f"已记录评分 {'⭐' * score} ({score}/5){' — ' + note if note else ''}",
        )

    def _handle_prompt(self, arg: str) -> RouteResult:
        if not arg:
            return RouteResult(type="command", command_response=(
                "**Prompt 管理**\n\n"
                "创建: `/prompt add <id> <名称> <描述> <角色说明>`\n"
                "删除: `/prompt del <id>`\n"
                "查看: `/prompt show <id>`\n\n"
                "示例:\n"
                "`/prompt add finance 财务助手 财务分析和报表解读 你是一位资深财务分析师`"
            ))

        parts = arg.split(maxsplit=1)
        sub_cmd = parts[0].lower()
        sub_arg = parts[1].strip() if len(parts) > 1 else ""

        if sub_cmd == "add":
            fields = sub_arg.split(maxsplit=3)
            if len(fields) < 4:
                return RouteResult(type="command", command_response=(
                    "用法: `/prompt add <id> <名称> <描述> <角色说明>`\n"
                    "示例: `/prompt add finance 财务助手 财务分析和报表解读 你是一位资深财务分析师`"
                ))
            domain_id, name, description, role = fields
            err = self.prompt_manager.create_prompt(domain_id, name, description, role)
            if err:
                return RouteResult(type="command", command_response=err)
            return RouteResult(type="command", command_response=(
                f"场景 **{name}**（{domain_id}）创建成功\n"
                f"命令: `/{domain_id}`\n"
                f"角色: {role[:100]}"
            ))

        if sub_cmd == "del":
            if not sub_arg:
                return RouteResult(type="command", command_response="用法: `/prompt del <id>`")
            err = self.prompt_manager.delete_prompt(sub_arg)
            if err:
                return RouteResult(type="command", command_response=err)
            return RouteResult(type="command", command_response=f"场景 **{sub_arg}** 已删除")

        if sub_cmd == "show":
            if not sub_arg:
                return RouteResult(type="command", command_response="用法: `/prompt show <id>`")
            cfg = self.prompt_manager.get_prompt(sub_arg)
            if not cfg:
                return RouteResult(type="command", command_response=f"场景 '{sub_arg}' 不存在")
            system_msg = self.prompt_manager.build_system_message(sub_arg)
            cmds = " ".join(cfg.commands) if cfg.commands else "无"
            kws = ", ".join(cfg.keywords) if cfg.keywords else "无"
            return RouteResult(type="command", command_response=(
                f"**{cfg.name}** ({cfg.id}) v{cfg.version}\n"
                f"描述: {cfg.description}\n"
                f"命令: {cmds}\n"
                f"关键词: {kws}\n\n"
                f"System Prompt:\n```\n{system_msg}\n```"
            ))

        return RouteResult(type="command", command_response=(
            f"未知子命令: {sub_cmd}\n"
            "可用: `/prompt add` `/prompt del` `/prompt show`"
        ))

    def _handle_run(self, arg: str) -> RouteResult:
        if not arg:
            scripts = list_scripts()
            if not scripts:
                return RouteResult(type="command", command_response="没有可用的脚本。")
            return RouteResult(type="command", command_response=f"可用脚本: {', '.join(scripts)}\n用法: /run <script> [args]")
        parts = arg.split()
        script_name = parts[0]
        script_args = parts[1:] if len(parts) > 1 else None
        return RouteResult(type="script", script_name=script_name, script_args=script_args)

    async def _handle_schedule(self, arg: str) -> RouteResult:
        if not arg:
            return RouteResult(type="command", command_response=(
                "**定时任务管理**\n\n"
                "查看: `/schedule list`\n"
                "删除: `/schedule remove <名称>`\n"
                "添加: `/schedule <自然语言描述>`\n\n"
                "示例:\n"
                "`/schedule 每天早上9点执行daily_report脚本`\n"
                "`/schedule 工作日下午2点半发消息到oc_xxx`"
            ))

        parts = arg.split(maxsplit=1)
        sub_cmd = parts[0].lower()
        sub_arg = parts[1].strip() if len(parts) > 1 else ""

        if sub_cmd == "list":
            tasks = await list_scheduled_tasks()
            if not tasks:
                return RouteResult(type="command", command_response="暂无定时任务。\n用自然语言描述即可创建，如:\n`/schedule 每天早上9点执行daily_report脚本`")
            lines = ["**定时任务列表：**\n"]
            for t in tasks:
                status = "ON" if t["enabled"] else "OFF"
                lines.append(f"- [{status}] **{t['name']}** `{t['cron']}` {t['type']}:{t['target']}")
            return RouteResult(type="command", command_response="\n".join(lines))

        if sub_cmd == "remove":
            if not sub_arg:
                return RouteResult(type="command", command_response="用法: `/schedule remove <名称>`")
            ok = await remove_scheduled_task(sub_arg)
            if ok:
                return RouteResult(type="command", command_response=f"定时任务 **{sub_arg}** 已删除")
            return RouteResult(type="command", command_response=f"定时任务 '{sub_arg}' 不存在")

        # Natural language — let AI parse it
        scripts = list_scripts()
        return await self._parse_schedule_by_ai(arg, scripts)

    async def _parse_schedule_by_ai(self, description: str, scripts: list[str]) -> RouteResult:
        from app.executor.chat import _get_client
        from app.config import settings

        scripts_info = ", ".join(scripts) if scripts else "暂无脚本"
        prompt = f"""\
你是一个定时任务解析助手。根据用户的自然语言描述，提取定时任务参数。

可用脚本: {scripts_info}
任务类型: script（执行脚本）, message（发送消息到指定 chat_id）

请严格返回以下 JSON 格式（不要返回其他内容）:
{{
  "name": "任务名称（英文，简短）",
  "cron": "cron 表达式（5位: 分 时 日 月 周）",
  "type": "script 或 message",
  "target": "脚本名 或 chat_id",
  "summary": "一句话中文说明这个任务"
}}

如果描述不清楚无法解析，返回:
{{"error": "具体缺少什么信息"}}"""

        client = _get_client()
        try:
            resp = await client.chat.completions.create(
                model=settings.defaults.model,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": description},
                ],
                temperature=0,
                max_tokens=256,
            )
            text = resp.choices[0].message.content or ""
            # Extract JSON from response
            text = text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            result = json.loads(text)
        except (json.JSONDecodeError, Exception) as e:
            logger.exception("Failed to parse schedule description")
            return RouteResult(type="command", command_response=f"无法解析任务描述，请更具体地说明。\n\n示例:\n`/schedule 每天早上9点执行daily_report脚本`")

        if "error" in result:
            return RouteResult(type="command", command_response=f"信息不完整: {result['error']}\n\n请补充后重试。")

        name = result.get("name", "")
        cron = result.get("cron", "")
        task_type = result.get("type", "")
        target = result.get("target", "")
        summary = result.get("summary", "")

        if not all([name, cron, task_type, target]):
            return RouteResult(type="command", command_response="解析结果不完整，请更具体地描述任务。")

        if task_type not in ("script", "message"):
            return RouteResult(type="command", command_response=f"不支持的任务类型: {task_type}")

        await add_scheduled_task(name, cron, task_type, target)
        return RouteResult(type="command", command_response=(
            f"定时任务创建成功\n\n"
            f"**{name}**: {summary}\n"
            f"cron: `{cron}` | {task_type}:{target}"
        ))
