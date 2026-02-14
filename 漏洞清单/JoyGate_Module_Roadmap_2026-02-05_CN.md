# JoyGate｜模块路线图（Hackathon · Charger Track）
版本日期：2026-02-05（Asia/Singapore）

> 目标：把 README 的“评委叙事”拆成一个个可落地的小模块；每个模块都能 **实现 → 测试 → 把证据写进 RUN_LOG.md**。  
> 唯一词典真源：`docs_control_center/FIELD_REGISTRY.md`（先登记再写代码，禁止随意改名）。

---

## 0) 全局规则（所有模块都必须遵守）

### 0.1 硬约束（不讨论）
- **一个对话只做一个模块**；完成后必须测试并记录到 `RUN_LOG.md`（见 `docs_control_center/WORKFLOW.md`）。
- **同步路径只做最小原子决策**（不能被审计/持久化/外部网络拖慢）；异步任务失败不影响“机器人续跑”。
- **不碰实时控制**：JoyGate 是“任务级建议/调度”，心跳是**秒级**在线检测，不做毫秒级控制。
- **HARD_BLOCKED 永不自动解封**：系统可以复核/提醒/升级，但不能把 HARD 改回 OPEN；唯一权威是 **工单 DONE**。
- **Grid 语义**：`segment_id` = `cell_{x}_{y}`（字符串键，不做几何假设，避免“网格幻觉”）。
- **风控边界（本对话确定）**：不收保证金；风控必须是 JoyGate 权限内的限制（限流/资格门槛/预算熔断/提示园区执行），不越权裁决。

### 0.2 Cursor 每个模块必须自审的 3 件事
1) **对照 FIELD_REGISTRY 自审**：接口字段名、枚举值、错误码、返回结构，不能自造词。  
2) **并发/幂等自审**：同一请求重复来会不会“重复加分/重复建事件/重复触发审计”？  
3) **状态机边界自审**：`incident_status` ≠ `hazard_status`；“权重/限流/预算” ≠ “封控/裁决”。

### 0.3 本对话新增原则（给积分/信誉模块用）
- **只给“可验证事件”加分**（默认不做“充电闭环奖励”，防刷分农场）。
- **惩罚/风控输出必须带证据链**：对园区输出“哪个厂商/哪个机器人不守规矩”时，必须能引用 `evidence_refs / witness / oracle / vision`（不凭感觉）。
- **成本防御**：低分不应导致“更多视觉 → 成本失控”。正确方向是：低分 → **票权更低 / 推进门槛更高 / 预算熔断更早**。

---

## A) 已完成模块（对照 RUN_LOG 证据）
> 这些保持为“证据为准”。（如果你 RUN_LOG 里已有更多记录，可以继续追加到这里。）

### M0 环境与最小可跑通
- **人话目标**：服务能启动，`POST /v1/reserve` 能返回 200。
- **证据**：RUN_LOG 记录 2

### M1 配额与资源忙（基础防抢）
- **人话目标**：同 joykey 第二次 reserve → 429；同 charger 被占 → 409；`oracle/stop_charging` 后可再 reserve。
- **证据**：RUN_LOG 记录 3 / 4

### M2 状态仓库 + 可观测快照
- **人话目标**：`GET /v1/snapshot` 能看到 `chargers / holds`。
- **证据**：RUN_LOG 记录 4

### M3 压测与并发一致性
- **人话目标**：并发 reserve 不“超卖”，能自动 cleanup。
- **证据**：RUN_LOG 记录 5 / 6

### M4 snapshot schema 对齐词典
- **人话目标**：HoldSnapshot 新增字段默认值对齐 FIELD_REGISTRY。
- **证据**：RUN_LOG 记录 6

### M5 词典化落地（Temporal Consistency Verification）
- **人话目标**：新增字段/枚举必须先登记；README/代码/词典不漂移。
- **证据**：RUN_LOG 记录 7

### M6｜事件列表（Dashboard 的“剧情主线”）
- **人话目标**：能 `GET /v1/incidents` 看到事件列表（可空），字段口径与词典一致。
- **证据**：RUN_LOG（你已有 incidents 相关记录；若未单列，可在下一次补写一条“仅验证列表 200”的记录）

### M7｜阻塞上报（把“异常”变成“事件”）
- **人话目标**：`POST /v1/incidents/report_blocked` 创建事件；`GET /v1/incidents` 可见。
- **证据**：RUN_LOG（incident 相关记录）

### M8.1｜Witness（桩占用投票：语义完成 + 双层测试）
- **人话目标**：witness allowlist、charger_state 校验、幂等去重、evidence_refs 上限（<=5）、推进 `EVIDENCE_CONFIRMED`、`list_incidents` 不泄露内部字段。
- **证据**：
  - RUN_LOG 记录 32（store-level 单元测试）
  - RUN_LOG 记录 33（HTTP 集成测试：路由/headers/返回码/字段口径）

---

## B) 下一阶段模块（按“评委可见价值” + 依赖顺序）
> 你接下来只需要：从“最关键、最能加分的模块”开始，一个一个做（一个对话一个模块）。

---

## M8.2｜Witness 权重版（接入积分/信誉：票权、门槛、成本防御）
**人话目标**：投票不是“人人一票”。系统根据机器人信誉分给不同**票权**，并在冲突/高风险时触发更稳的“多源确认/视觉兜底”（但受预算熔断保护）。  

**依赖**
- 依赖积分/信誉模块（见下方 M16）提供：`vote_weight / tier / flags`。

**约束（本对话确定）**
- 低分机器人：**票权更低、推进门槛更高**；但**不应导致更多视觉频率**（避免成本被攻击拖爆）。
- 成本防御：必须有**预算/熔断/限流**（至少全局 budget + vendor budget）。
- 允许“狼来了”处理：被降权/暂停资格的主体仍可通过**带证据的路径**参与（例如提交 evidence_refs，但不计入票权/或记为 low-trust），避免真事故完全失声。

**接口口径**
- 对外接口不变：`POST /v1/witness/respond` → 204  
- 对内：witness 聚合改为按 `vote_weight` 累加（而不是 +1）。

**最小测试（证据写 RUN_LOG）**
1) 同一 incident：w1/w2（不同 tier）投票后，tally 权重符合预期  
2) “低分/被标记低可信”投票不应导致额外视觉被自动触发（若你实现了视觉触发门槛，必须证明预算熔断有效）

**Cursor 自审重点**
- 幂等：`points_event_id` 去重仍成立；重复投票不会重复加分/重复写 insight。
- 并发：权重 tally 原子更新不丢票。

---

## M9｜Witness（路段投票）+ hazards 影子层（先展示，再制度化）
**人话目标**：机器人对某个网格 `cell_x_y` 投票 `PASSABLE / BLOCKED / UNKNOWN`；系统把它显示在 `snapshot.hazards`（先当“影子提示层”）。  

**约束**
- **hazards 是实验性“提示层”**：不等于 HARD 封控；更不能被 `segment_passed` 直接“解封”。
- `incident_status` 与 `hazard_status` 必须分清。

**接口口径**
- `POST /v1/witness/segment_respond` → 204  
  输入字段按词典：`incident_id, segment_id, segment_state, evidence_refs?, points_event_id?`
- `GET /v1/snapshot` → （实验性）`hazards`

**最小测试（证据写 RUN_LOG）**
1) 发送 `segment_respond` → 204
2) `GET /v1/snapshot`：hazards 出现该 segment

**Cursor 自审重点**
- segment_id 只当字符串键；服务端不要做几何计算（避免“网格幻觉”）。
- 幂等：重复投票不应重复创建 hazard 条目。

---

## M10｜走通过新鲜度（segment_passed：省摄像头成本）
**人话目标**：机器人刚走通过的路段，在未来一小段时间里默认更可信，从而减少复核/视觉成本。  

**约束**
- `segment_passed` **不直接改变 hazard_status**，只是“规划权重/成本控制”信号。  
- **底线**：绝不允许它解封 `HARD_BLOCKED`。

**接口口径**
- `POST /v1/telemetry/segment_passed` → 204  
  输入字段按词典：`joykey?, fleet_id?, segment_ids, event_occurred_at, truth_input_source`

**最小测试（证据写 RUN_LOG）**
- 上报 `segment_passed` → 204；再用 snapshot/ledger 看到“收到了这个信号”的痕迹（最简可写入审计 summary）

**Cursor 自审重点**
- 时间处理：`event_occurred_at` vs server now（拒绝明显未来/负值）。
- 并发同段更新 last_passed_at 时序一致性。

---

## M11｜审计账本（让评委相信“你没黑箱乱控”）+ Sidecar 安全回退
**人话目标**：系统做过哪些关键决定（建议/安全回退/封控/升级）都能查到；证明 JoyGate 不对抗 OEM 安全回路。  

**约束**
- 账本写入失败不能阻塞同步路径（允许异步补写）。
- Planner Cooldown 是**内部策略**：不新增字段，不改 hazard_status，只影响“建议排序/渐进恢复”。

**接口口径**
- `GET /v1/audit/ledger` → `audit_status` + 决策哈希链 + `sidecar_safety_events`

**最小测试（证据写 RUN_LOG）**
1) 造一条 `sidecar_safety_event`（模拟 ACCEPTED/REJECTED/SAFETY_FALLBACK 等）  
2) `curl /v1/audit/ledger`：能看到该条记录

**Cursor 自审重点**
- 并发写入 ledger：不丢、不乱序（最简：加锁 append）。
- 不要在 UI 或 API 里“写死 audit_status”。

---

## M12｜视觉审计（vision_audit：事件驱动兜底，stub 也可以）
**人话目标**：当 witness 冲突/稀疏超时/高风险时，触发一次视觉审计任务；UI 能看到任务状态。  

**约束**
- 必须是 **event-driven**（按需触发），不做持续监控。
- 返回 202 表示“已入队”，不要在同步路径里等结果。
- **成本防御（与积分/风控一致）**：必须受 budget/熔断控制。

**接口口径**
- `POST /v1/ai/vision_audit` → 202（`ai_job_id`, `ai_job_status=ACCEPTED`）
- 任务状态/结果可先通过 `incidents.ai_insights` 或 ledger summary 表达（以词典为准）

**最小测试（证据写 RUN_LOG）**
- `curl -X POST /v1/ai/vision_audit ...` → 202  
- `GET /v1/incidents` 或 `/v1/audit/ledger`：能看到 job 痕迹（job_id + 状态）

**Cursor 自审重点**
- 重复提交同一 incident 的审计：要幂等（至少不要无限新建 job）。
- 异步状态机不会卡死（ACCEPTED → IN_PROGRESS → COMPLETED/FAILED）。

---

## M12A｜Gemini API 适配器（LLM Client / Provider Adapter）
**人话目标**：把 “/v1/ai/*” 背后的大模型调用封装成可替换模块：今天用 Gemini，明天换别家不改对外 API。  

**约束**
- **对外接口不变**：`/v1/ai/vision_audit`、`/v1/ai/dispatch_explain`、`/v1/ai/policy_suggest` 字段/返回严格按 FIELD_REGISTRY。
- **异步优先**：同步路径只负责“入队/记录”；调用 Gemini 走后台 worker/线程；失败不能拖慢主服务。
- **默认不存原始媒体**：只存 `evidence_refs`（引用）+ `ai_insights.summary`（摘要）+ `confidence`；不把图片/视频落盘。
- **幂等与限流**：同一 `incident_id + ai_report_type` 重复触发，必须可复用同一报告（或至少不无限创建）；要有 provider 侧 QPS/退避。

**最小测试（证据写 RUN_LOG）**
1) `POST /v1/ai/vision_audit` → 202（拿到 id）  
2) mock 模式把 job 标成 COMPLETED  
3) `GET /v1/incidents`/`ledger` 看到摘要

---

## M13｜解释层（给评委/运营看的“为什么这样建议”）
**人话目标**：评委问“你为什么让机器人绕开这格/换到这个桩”，系统能给出可读解释（异步）。  

**约束**
- 解释层不改变任何权威状态，只输出解释文本/摘要。
- 解释必须引用“证据来源”（witness / telemetry / oracle / vision），而不是编造。

**接口口径**
- `POST /v1/ai/dispatch_explain` → 202（stub 也行）
- （可选）`POST /v1/ai/policy_suggest`、`POST /v1/admin/apply_policy_suggestion`（先做 stub）

---

## M14｜Hazard 制度化（SOFT_BLOCKED：自动复核 → 必要时升级 HARD）
**人话目标**：从“影子 hazards”升级到制度：SOFT 会自动复核，持续不通再升级 HARD。  

**约束**
- SOFT 的复核是“复核/升级”，不是“自动解封 HARD”。
- 复核频率与次数按词典 policy config（默认值可在代码里作为默认）。

---

## M15｜工单闭环（HARD_BLOCKED 唯一解封入口）
**人话目标**：HARD_BLOCKED 永不自动解封；只有专职人员工单 DONE 才能解封。并且系统支持“主动复核”提醒/升级，但仍不解封。  

**硬规则**
- **任何定时器、witness、telemetry、vision 都不能把 HARD 改回 OPEN**。
- Active Re-certification（复核 A/B）只产生“提醒/升级/审计”，不产生解封。

---

## M16｜积分与信誉（Robot Score + Vendor Score，治理优先）
> 定位：JoyGate 不做“警察式裁决”，但需要提供园区治理与激励信号。  
> 该模块独立于 M8（witness/evidence），其它模块只通过接口接入积分，不与内部实现耦合。

**人话目标**
- 让园区管理者看到：哪些厂商/机器人更守规矩、更可靠（**治理**）。
- 让厂商看到：自己的算法在“真实园区协作”里表现如何（**可选价值**）。
- 高分有好处（优先体验/更少摩擦）；低分有约束（更严格门槛/提示园区执行），但 **不越权裁决**。

**核心口径（本对话已定）**
- `robot_score` 初始 **60**。
- `vendor_score_total` = 50%（机器人映射） + 50%（运营治理分，绑定总分，治理优先）。
- Tier：A/B/C/D（阈值你后续可调；模块先支持 tier 映射）。
- 投票权重：采用你定的“**两头高、中间低**”形状（最活跃与最不活跃权重更高，中间更低）——用于治理与抗刷分的实验策略（先做成可配置）。
- **只给可验证事件加分**（默认不做充电闭环奖励，防刷分农场）。
- 对园区输出“低分/风险”必须附带证据链（witness/vision/oracle/evidence_refs）。

**需要用到积分的地方（接入点清单）**
- Witness：`vote_weight`、推进门槛、资格/限流 flags
- 视觉审计：预算/熔断（global + vendor）
- Dashboard：vendor 排名、风险清单（带 evidence_refs 证据链）
- （可选）资源体验：人工复核队列优先级/展示优先级（不改变硬裁决）

**反作弊与“新手保护”（解决本对话提出的 4 个风险）**
- 刷分农场：不对“可脚本刷”的闭环加分；所有加分必须绑定可验证来源（witness 多源/vision/oracle）。
- 死亡螺旋：新机器人有 cold-start 保护（例如最小票权下限/缓慢衰减/需要多次证据才下调资格）。
- 低分攻击成本：低分不触发更多视觉；只会更难推进结论 + 更早预算熔断。
- 狼来了/误伤：被降权/暂停资格的主体仍可提交 evidence_refs（记录在案），但对推进影响受限；严重情况交给园区执行。

**对外接口（其它模块如何接入积分）**
- 说明：对外接口 = 通过 HTTP 暴露给外部系统调用的 API；内部接口 = JoyGate 内部模块调用。
- M16 对其它模块提供“稳定接口桩”（先接入，不强耦合）：
  - `score.get_robot_profile(joykey)` -> `{robot_score, robot_tier, vote_weight, flags}`
  - `score.get_vendor_profile(vendor_id)` -> `{vendor_score_total, vendor_score_robot_mapped, vendor_score_ops}`
  - `score.record_verified_event(event)` -> 写入计分账本（仅可验证事件）

**最小测试（证据写 RUN_LOG）**
1) 触发一次可验证事件（例如 witness 投票成功）→ 积分账本出现一条记录（幂等键生效）  
2) 同一 `points_event_id` 重放 → 不重复记分  
3) vendor 映射分能随机器人变化更新（至少在内存层可见）

**Cursor 自审重点**
- 计分必须幂等（不会重复加分）。
- 不新增未登记字段；展示层需要字段先走 FIELD_REGISTRY。

---

## M16B｜（可选）Oracle 证实的充电奖励（未来增强）
> 你已明确：“充电闭环可未来再说”；先把模块位留出来，避免路线图漂移。

**人话目标**：只有“基础设施 Oracle 证实”的建议执行才奖励；严格防刷分。  

**约束**
- 奖励必须关联 `incident_id`（避免没事刷分）。
- 同一 `incident_id + joykey` 最多奖励一次；有 daily cap。
- accept-but-no-op：不给分，但写入审计（用词典已有字段，不新增枚举）。

---

## M17｜Outbound Webhooks（对外集成）
（保持原路线：事件名只允许词典 enum；投递失败退避；不拖慢同步路径）

---

## M18｜Web UI（评委友好：网格 cell 可视化）
（保持原路线：UI 只读；不造字段；按 cell_x_y 画；不推断坐标系）

---

## C) Demo 建议（最短“评委能看懂”闭环）
最短闭环（当前已具备 M8.1）：
1) reserve 成功 → 2) `POST /v1/incidents/report_blocked` 造事件 → 3) witness 出结论（EVIDENCE_CONFIRMED） →  
4)（冲突/稀疏才触发）vision_audit → 5) hazards 影子层 →  
6) SOFT/HARD 制度化 → 7) HARD 只能靠 work_order DONE 解封 → 8) audit ledger 证明你没黑箱 → 9) UI 展示。

---

## D) 每个模块完成后 RUN_LOG 记录模板（给 Cursor 复制用）
- 记录 X（Mx 模块名）
  - 日期：2026-02-05
  - 变更说明：做了什么 / 没做什么（两句话）
  - 验证测试：
    - 命令 1（成功路径）+ 原始输出
    - 命令 2（失败/边界路径）+ 原始输出
  - 自审清单：
    - FIELD_REGISTRY 对照：✓/✗（列出检查点）
    - 并发/幂等：✓/✗（列出检查点）
    - 状态机边界：✓/✗（列出检查点）

---

## E) 防遗漏：让 Cursor “没法漏”的三道闸（推荐每个模块都用）
1) **先枚举接入点**：本模块会改哪些路由/方法？必须列清单（文件+函数）。  
2) **grep 断言**：为关键 hook 写“必须出现的关键字”（例如 `record_verified_event`），提交前搜索确认每个入口都接上。  
3) **测试兜底**：至少一个 store-level 或 HTTP 集成测试，能证明“这模块对外语义成立”。
