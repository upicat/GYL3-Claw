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
