"""Agent — unified message handler with skill-based tool calling."""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from openai import AsyncOpenAI

from app.config import settings
from app.memory.conversation import clear_history, get_history, get_last_exchange, save_message
from app.agent.loader import SkillLoader
from app.agent.models import SkillFull
from app.tools.registry import get_tool_executor

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 5
EVAL_LOG_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "prompt_eval.jsonl"

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=settings.gateway.api_key,
            base_url=settings.gateway.base_url or None,
        )
    return _client


async def _execute_tool_call(name: str, arguments: str) -> str:
    executor = get_tool_executor(name)
    if executor:
        return await executor(arguments)
    return f"Unknown tool: {name}"


# ─── Help text ───

_HELP_TEXT = """\
**Claw 飞书智能助手**

可用命令：
- `/help` — 查看此帮助
- `/list` — 列出所有可用技能
- `/clear` — 清除上下文
- `/reload` — 重新加载技能配置
- `/eval <1-5> [备注]` — 对上一轮回答打分
- `/web <关键词>` — 搜索网络信息
- `/url <链接>` — 解析网页内容并总结
- `/cmd <命令>` — 执行本地 shell 命令
- `/claude <问题>` — 调用 Claude Code 回答问题
- `/schedule list` — 查看定时任务
- `/schedule remove <名称>` — 删除定时任务
- `/schedule <描述>` — 用自然语言创建定时任务
- `/stock <代码>` — 查询A股实时行情（如 600000.SH）

直接发送一个 URL 链接也会自动解析总结。

直接发送消息即可智能问答，Agent 会自动选择合适的工具。"""


class Agent:
    """Unified agent that understands intent, picks skills, and orchestrates tools."""

    def __init__(self, skill_loader: SkillLoader):
        self._skill_loader = skill_loader
        self.session_domains: dict[str, str] = {}  # preserved for /switch compat

    async def handle_message(self, chat_id: str, user_id: str, text: str) -> str:
        """Main entry point for all messages."""
        text = text.strip()

        # 1. System commands (deterministic, no LLM)
        if text.startswith("/"):
            cmd_result = await self._handle_system_command(chat_id, user_id, text)
            if cmd_result is not None:
                return cmd_result

        # 2. Skill slash commands (e.g., /web, /url, /cmd, /claude)
        if text.startswith("/"):
            parts = text.split(maxsplit=1)
            cmd = parts[0].lower()
            arg = parts[1].strip() if len(parts) > 1 else ""
            skill_result = await self._handle_skill_command(chat_id, user_id, cmd, arg, text)
            if skill_result is not None:
                return skill_result

        # 3. Pure URL detection → shortcut to url-reader skill
        from app.tools.url_fetcher import is_url
        detected_url = is_url(text)
        if detected_url:
            return await self._run_with_skill(
                chat_id, user_id, f"请分析总结这个网页: {detected_url}", "url-reader"
            )

        # 4. Default: Agent turn (LLM decides what to do)
        return await self._agent_turn(chat_id, user_id, text)

    # ─── System commands (no LLM) ───

    async def _handle_system_command(
        self, chat_id: str, user_id: str, text: str
    ) -> str | None:
        parts = text.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        if cmd == "/help":
            return _HELP_TEXT

        if cmd == "/list":
            metas = self._skill_loader.all_metas
            if not metas:
                return "暂无可用技能。"
            lines = ["**可用技能：**\n"]
            for name, m in sorted(metas.items()):
                cmds = " ".join(m.commands) if m.commands else ""
                line = f"- **{name}**: {m.description}"
                if cmds:
                    line += f"  ({cmds})"
                lines.append(line)
            return "\n".join(lines)

        if cmd == "/clear":
            self.session_domains.pop(chat_id, None)
            count = await clear_history(chat_id)
            return f"已清除会话上下文（{count} 条记录）。"

        if cmd == "/reload":
            self._skill_loader.reload()
            names = list(self._skill_loader.all_metas.keys())
            return f"技能已重新加载，当前: {', '.join(names)}"

        if cmd == "/eval":
            return await self._handle_eval(chat_id, user_id, arg)

        if cmd == "/schedule":
            return await self._handle_schedule(arg)

        return None  # not a system command

    # ─── Skill slash commands ───

    async def _handle_skill_command(
        self, chat_id: str, user_id: str, cmd: str, arg: str, full_text: str
    ) -> str | None:
        """Handle slash commands mapped to skills."""
        skill_name = self._skill_loader.resolve_command(cmd)
        if not skill_name:
            return None

        # Special handling for commands that need no-arg responses
        if skill_name == "shell" and cmd == "/cmd" and not arg:
            return "用法: /cmd <命令>\n示例: /cmd ls -la"
        if skill_name == "shell" and cmd == "/claude" and not arg:
            return "用法: /claude <问题>\n示例: /claude 用Python写一个快排"
        if skill_name == "web-search" and not arg:
            return "用法: /web <搜索关键词>\n示例: /web Python 最新版本"
        if skill_name == "url-reader" and not arg:
            return "用法: /url <网页链接>\n示例: /url https://example.com"
        if skill_name == "stock" and not arg:
            return "用法: /stock <股票代码>\n示例: /stock 600000.SH\n多只: /stock 600000.SH,000001.SZ"

        # Build appropriate user message for the skill
        if skill_name == "shell" and cmd == "/claude":
            import shlex
            user_msg = f"请执行以下 Claude Code 命令: claude -p {shlex.quote(arg)}"
        elif skill_name == "shell":
            user_msg = f"请执行以下命令: {arg}"
        elif skill_name == "url-reader":
            user_msg = f"请分析总结这个网页: {arg}"
        else:
            user_msg = arg

        return await self._run_with_skill(chat_id, user_id, user_msg, skill_name)

    # ─── Agent turn (default path) ───

    async def _agent_turn(self, chat_id: str, user_id: str, message: str) -> str:
        """Default agent turn: system prompt with all skills, all tools available."""
        # Build system prompt
        persona = self._skill_loader.get_agent_persona()
        skills_summary = self._skill_loader.get_skills_summary()
        system_parts = [p for p in [persona, skills_summary] if p]
        system_msg = "\n\n".join(system_parts)

        # Collect all tools
        tools = self._skill_loader.get_all_tools() or None

        # Conversation history
        history = await get_history(chat_id)
        await save_message(chat_id, user_id, "user", message, "agent")

        # LLM call with tool loop
        reply = await self._llm_tool_loop(
            system_msg=system_msg,
            user_msg=message,
            history=history,
            tools=tools,
        )

        await save_message(chat_id, user_id, "assistant", reply, "agent")
        return reply

    # ─── Run with specific skill ───

    async def _run_with_skill(
        self, chat_id: str, user_id: str, message: str, skill_name: str
    ) -> str:
        """Run a message with a specific skill's context and tools."""
        skill = self._skill_loader.load_full(skill_name)
        if not skill:
            return f"技能 '{skill_name}' 加载失败。"

        # Build system prompt: agent persona + skill instructions + references
        persona = self._skill_loader.get_agent_persona()
        parts = [persona] if persona else []
        if skill.instructions:
            parts.append(f"# 当前技能: {skill.meta.name}\n\n{skill.instructions}")
        if skill.references:
            parts.append(f"# 参考资料\n\n{skill.references}")
        system_msg = "\n\n".join(parts)

        tools = skill.tools or None

        # Model overrides from skill
        model_overrides = skill.meta.model_overrides

        # Conversation history
        history = await get_history(chat_id)
        await save_message(chat_id, user_id, "user", message, skill_name)

        reply = await self._llm_tool_loop(
            system_msg=system_msg,
            user_msg=message,
            history=history,
            tools=tools,
            model_overrides=model_overrides,
        )

        await save_message(chat_id, user_id, "assistant", reply, skill_name)
        return reply

    # ─── LLM tool loop ───

    async def _llm_tool_loop(
        self,
        system_msg: str,
        user_msg: str,
        history: list[dict],
        tools: list[dict] | None = None,
        model_overrides: dict | None = None,
    ) -> str:
        """Call LLM with tool loop, up to MAX_TOOL_ROUNDS iterations."""
        client = _get_client()
        overrides = model_overrides or {}

        model = overrides.get("name") or settings.defaults.model
        temperature = overrides.get("temperature", settings.defaults.temperature)
        max_tokens = overrides.get("max_tokens") or settings.defaults.max_tokens

        messages: list[dict] = []
        if system_msg:
            messages.append({"role": "system", "content": system_msg})
        messages.extend(history)
        messages.append({"role": "user", "content": user_msg})

        try:
            kwargs: dict = dict(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            if tools:
                kwargs["tools"] = tools

            for _ in range(MAX_TOOL_ROUNDS):
                resp = await client.chat.completions.create(**kwargs)
                msg = resp.choices[0].message

                if not msg.tool_calls:
                    return msg.content or ""

                # Append assistant message with tool_calls
                messages.append(msg.model_dump(exclude_none=True))

                # Execute each tool call
                for tool_call in msg.tool_calls:
                    logger.info(
                        "Agent tool call: %s(%s)",
                        tool_call.function.name,
                        tool_call.function.arguments[:200],
                    )
                    result = await _execute_tool_call(
                        tool_call.function.name,
                        tool_call.function.arguments,
                    )
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result,
                    })

            # Exhausted rounds — final call without tools
            kwargs.pop("tools", None)
            resp = await client.chat.completions.create(**kwargs)
            return resp.choices[0].message.content or ""

        except Exception:
            logger.exception("Agent LLM call failed")
            return "抱歉，AI 服务暂时不可用，请稍后重试。"

    # ─── Eval handler ───

    async def _handle_eval(self, chat_id: str, user_id: str, arg: str) -> str:
        if not arg:
            return "用法: /eval <1-5> [备注]"
        parts = arg.split(maxsplit=1)
        try:
            score = int(parts[0])
            if not 1 <= score <= 5:
                raise ValueError
        except ValueError:
            return "评分须为 1-5 的整数"

        note = parts[1] if len(parts) > 1 else ""
        exchange = await get_last_exchange(chat_id)
        if not exchange:
            return "没有找到可评价的对话记录。"

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

        return f"已记录评分 {'⭐' * score} ({score}/5){' — ' + note if note else ''}"

    # ─── Schedule handler ───

    async def _handle_schedule(self, arg: str) -> str:
        from app.scheduler.scheduler import add_scheduled_task, remove_scheduled_task, list_scheduled_tasks

        if not arg:
            return (
                "**定时任务管理**\n\n"
                "查看: `/schedule list`\n"
                "删除: `/schedule remove <名称>`\n"
                "添加: `/schedule <自然语言描述>`\n\n"
                "示例:\n"
                "`/schedule 每天早上9点执行daily_report脚本`\n"
                "`/schedule 工作日下午2点半发消息到oc_xxx`"
            )

        parts = arg.split(maxsplit=1)
        sub_cmd = parts[0].lower()
        sub_arg = parts[1].strip() if len(parts) > 1 else ""

        if sub_cmd == "list":
            tasks = await list_scheduled_tasks()
            if not tasks:
                return "暂无定时任务。\n用自然语言描述即可创建，如:\n`/schedule 每天早上9点执行daily_report脚本`"
            lines = ["**定时任务列表：**\n"]
            for t in tasks:
                status = "ON" if t["enabled"] else "OFF"
                lines.append(f"- [{status}] **{t['name']}** `{t['cron']}` {t['type']}:{t['target']}")
            return "\n".join(lines)

        if sub_cmd == "remove":
            if not sub_arg:
                return "用法: `/schedule remove <名称>`"
            ok = await remove_scheduled_task(sub_arg)
            if ok:
                return f"定时任务 **{sub_arg}** 已删除"
            return f"定时任务 '{sub_arg}' 不存在"

        # Natural language — AI parse
        return await self._parse_schedule_by_ai(arg)

    async def _parse_schedule_by_ai(self, description: str) -> str:
        from app.scheduler.scheduler import add_scheduled_task

        prompt = """\
你是一个定时任务解析助手。根据用户的自然语言描述，提取定时任务参数。

任务类型: command（执行 shell 命令）, message（发送消息到指定 chat_id）

请严格返回以下 JSON 格式（不要返回其他内容）:
{
  "name": "任务名称（英文，简短）",
  "cron": "cron 表达式（5位: 分 时 日 月 周）",
  "type": "command 或 message",
  "target": "shell 命令 或 chat_id",
  "summary": "一句话中文说明这个任务"
}

如果描述不清楚无法解析，返回:
{"error": "具体缺少什么信息"}"""

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
            text = text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            result = json.loads(text)
        except (json.JSONDecodeError, Exception):
            logger.exception("Failed to parse schedule description")
            return "无法解析任务描述，请更具体地说明。\n\n示例:\n`/schedule 每天早上9点执行daily_report脚本`"

        if "error" in result:
            return f"信息不完整: {result['error']}\n\n请补充后重试。"

        name = result.get("name", "")
        cron = result.get("cron", "")
        task_type = result.get("type", "")
        target = result.get("target", "")
        summary = result.get("summary", "")

        if not all([name, cron, task_type, target]):
            return "解析结果不完整，请更具体地描述任务。"

        if task_type not in ("command", "message"):
            return f"不支持的任务类型: {task_type}"

        await add_scheduled_task(name, cron, task_type, target)
        return (
            f"定时任务创建成功\n\n"
            f"**{name}**: {summary}\n"
            f"cron: `{cron}` | {task_type}:{target}"
        )
