---
name: shell
description: "执行本地 Shell 命令或调用 Claude Code CLI"
tools:
  - shell_cmd
commands:
  - "/cmd"
  - "/claude"
model:
  temperature: 0.3
---

## 使用场景

- 用户需要执行系统命令查看状态、文件操作等
- 用户需要通过 Claude Code 进行代码相关操作

## 注意事项

- 危险命令（rm -rf, sudo 等）会被自动拦截
- 命令执行有超时限制（120秒）
- 输出过长会被截断
