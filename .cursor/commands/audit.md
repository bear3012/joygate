# audit

请按 docs_control_center/DEV_RULES_AI_FIRST.md 审计当前改动，逐条检查并输出结果：

1) 是否有改名（字段/路由/变量/枚举）？如果有，指出文件与位置，并给回滚建议。
2) 是否新增字段但未登记到 docs_control_center/FIELD_REGISTRY.md？如果有，输出应登记的条目格式。
3) 是否违反“只做一个小积木”（一次改太多文件/大重构）？如果有，建议拆分步骤。
4) 是否引入了新依赖/外部服务/隐藏配置？如果有，指出并给替代方案（优先不用新依赖）。
5) README 契约（字段/状态码）是否与代码一致？不一致就列差异与修复步骤。

输出格式：
- ✅ 通过项
- ❌ 不通过项（必须给修复步骤）

This command will be available in chat with /audit
