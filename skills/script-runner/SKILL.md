---
name: script-runner
description: "执行 scripts/ 目录下的本地脚本（.sh / .py）"
tools:
  - run_script
commands:
  - "/run"
model:
  temperature: 0.3
---

## 使用场景

- 用户需要运行预定义的自动化脚本
- 查看可用脚本列表

## 注意事项

- 仅支持 .sh 和 .py 脚本
- 脚本必须位于 scripts/ 目录下
- 执行有超时限制（120秒）
