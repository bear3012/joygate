# task

你是 JoyGate 项目的代码执行者。你必须先阅读并严格遵守以下本地文件（Local is Truth）：
- docs_control_center/DEV_RULES_AI_FIRST.md
- docs_control_center/FIELD_REGISTRY.md
- 当前任务对应 README（docs_control_center/README_HACKATHON_CHARGER.md 或 docs_control_center/README_ECOMMERCE_INVENTORY.md）
- docs_control_center/TASK_CARD.md
- docs_control_center/RUN_LOG.md

然后按“反黑箱流程”执行（不要跳步）：

A) 人话复述目标（不超过 5 行）
- 你理解我要实现什么？
- 用户会看到什么变化？

B) 本次小积木范围（必须小）
- 这次只做一件事（一个可验证的小功能）
- 列出最多 1–3 个你要改的文件名
- 如果缺少文件或上下文：先让我打开/提供文件，不要猜

C) 字段检查（防口径漂移）
- 先检查 FIELD_REGISTRY.md 是否已有需要的字段/事件名
- 如果你认为“必须新增字段”：先输出要追加到 FIELD_REGISTRY.md 的登记条目（field_name/type/scope/meaning/example/status）
- 没有登记前：禁止在代码里使用新字段

D) 进行代码修改（严格增量）
- 禁止改名（字段/路由/变量/枚举值）
- 不允许大重构
- 不确定写 TODO，禁止编造
- 只改你在 B) 里列出的文件

E) 验货输出（必须给我能照抄的命令）
1) 变更总结：你改了什么（人话）
2) 改动文件清单（列表）
3) 最短验证命令：
   - 启动命令（例如 uvicorn / node / docker，按项目实际情况）
   - 1–2 条 curl（正常路径 + 错误路径如 402/429）
4) 每条命令的“预期输出长什么样”（用人话描述）

This command will be available in chat with /task
