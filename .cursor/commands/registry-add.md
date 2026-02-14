# registry-add

我要新增字段。请只生成 1 个字段（不要同时造多个），并按 docs_control_center/FIELD_REGISTRY.md 的格式输出：

- field_name（snake_case）
- type（string/int/bool）
- scope（出现在哪个接口/对象）
- meaning（一句人话解释）
- example（示例值）
- status（experimental 或 stable）

并同时给出应追加到 Change Log 表格的一行。
注意：没有登记前，禁止在代码里使用该字段。

This command will be available in chat with /registry-add
