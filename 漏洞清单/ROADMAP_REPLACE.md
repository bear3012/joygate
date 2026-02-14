# JoyGate 模块路线图（Hackathon Charger）

更新日期：2026-02-01  
定位口径以 `README_HACKATHON_CHARGER.md` + `FIELD_REGISTRY.md` 为准：JoyGate 是**园区稀缺资源的“专业证人 + 调度指引”**，不是警察式裁决系统。

---

## 0) 场景边界（写死，避免答辩跑偏）

### 参与者模型
- **真人 JoyKey 账号**：园区身份系统发放；存在人情世故与协商空间。我们追求“体验 + 吞吐”，不追求刑侦级断案。
- **机器人/车队资产**：归属在某个真人 JoyKey 名下；机器人**可以预约/执行任务**，但：
  - **不能发起/接单真相悬赏（Truth Bounty）**
  - 机器人侧异常行为（如恶意脚本导致大量无效预约/违约）产生的治理成本，**计入归属 JoyKey 的信用/积分/Lane**（连带责任）。
  - 解封/申诉/恢复权限：由账号方联系管理员处理（JoyGate 只记录与可观测，不擅自惩罚）。

### 治理原则
- **最大客户是停车/占位的人**：我们的目标是促进遵守规则与提高资源利用率。
- **UNKNOWN/证据不足**：不发奖励、不自动重罚；必要时升级管理员（incident_status=ESCALATED）。
- **JoyGate 不擅自惩罚**：处罚/驱离/解封属于园区治理流程；JoyGate 做“改派/记录/通知”。

---

## 1) 里程碑定义（Done Definition 共通模板）
每个模块完成需满足：
- 服务可启动（本地）
- 至少 1 组 curl / 脚本可复现结果
- 关键输出粘贴进 `RUN_LOG.md`
- 不改名；若新增字段/枚举，先写入 `FIELD_REGISTRY.md`

---

## 2) 已完成（DONE）
> 以 `RUN_LOG.md` 记录 1–7 为证据来源。

### M0 环境与最小可跑通
- 启动服务 + `/v1/reserve` 冒烟测试（200/400）

### M1 占位配额与资源忙
- 同 joykey 单活跃占位（429 QUOTA_EXCEEDED）
- 同 charger 被占返回 409 RESOURCE_BUSY

### M2 状态仓库 + `/v1/snapshot`
- chargers/holds 可观测
- HoldSnapshot 字段对齐（新增字段默认值：is_priority_compensated/compensation_reason/queue_position_drift/incident_id）

### M3 压测脚本（load test）
- 并发 reserve 一致性
- `--check_snapshot` 校验核心不变量 + M2 新增字段默认值

### M5（词典化）时间一致性验证口径落地
- obstacle_type 扩展
- incident_status 新增 UNDER_OBSERVATION / EVIDENCE_CONFIRMED
- Policy Config 新增 vision_audit_* 参数
- README 对齐（AI 旁路，不触发核心状态转移）

---

## 3) 下一步（P0：答辩最值钱且最短路径）

### P0-1 `/v1/incidents` 最小可查询（事件单容器）
**人话目标**：把“发生了什么”变成可查询的事件单，给管理员/运营一个统一入口。  
**接口口径**：`GET /v1/incidents`（IncidentQuery → IncidentList）。  
**重点审查**：
- incident 写入不可拖慢 reserve 主路径
- 并发下 incident 列表一致性

**Done Definition（示例测试）**
- `curl GET /v1/incidents` 返回 200，结构正确（即使为空数组也算）

### P0-2 到场遇阻：`/v1/report_blocked` 自动改派 + 记录事件（不惩罚）
**人话目标**：预约用户到场遇阻时，JoyGate 先把用户送到能充的地方；同时记录 incident 交给管理员。  
**接口口径**：
- `POST /v1/report_blocked`：仍返回 204（NoContent）
- App 通过 `GET /v1/snapshot` 看见是否改派（新 hold_id / 新 charger_id）
- `GET /v1/incidents` 可见 BLOCKED/BLOCKED_BY_OTHER 事件；改派成功记 RESOLVED，无空闲记 ESCALATED

**重点审查（并发/状态机）**
- 改派必须是“原子交换”：释放旧 hold + 创建新 hold + 更新两个 charger 的 slot_state（同锁内完成）
- 任何时刻同 joykey 只允许一个 active hold
- 多人同时改派不可抢到同一个 FREE 桩

**Done Definition（示例测试）**
- Case A：有空闲桩 → report_blocked 后 snapshot 显示改派；incidents 记录 RESOLVED
- Case B：无空闲桩 → incidents 记录 ESCALATED（呼叫管理员）


### P0-3 Courtesy Nudge（英文推送）+ 5min Camera Recheck（单次复核，不惩罚）
**人话目标**：给占位者台阶、提升周转率；5 分钟后做一次摄像头复核：离开则 `charger_state=FREE`，未离开则 `incident_status=ESCALATED` 上报管理员。  
**接口口径**：不新增接口；由 `POST /v1/report_blocked` 触发；结果落在 `GET /v1/incidents` 的 `ai_insights` 与 incident_status（RESOLVED/ESCALATED）。  
**重点审查**：
- 5 分钟复核仅执行一次、且幂等（重复触发不重复升级/不抖动）
- 复核只改 `charger_state` 与事件记录；不基于一次视觉判断强制改 hold/slot_state/credit
- 推送冷却（cooldown），避免骚扰

**Done Definition（示例测试）**
- 触发 report_blocked → incidents 出现一条 `insight_type="courtesy_nudge"` 的英文文案摘要
- 5 分钟后（测试可缩短）出现 `insight_type="recheck"`：
  - 离开：charger_state=FREE，incident_status=RESOLVED
  - 未离开：incident_status=ESCALATED（管理员介入）



### P0-4 Filtering Architecture（分层过滤：L1 Flash → L2 Pro/多采样）
**人话目标**：用低成本模型覆盖绝大多数日常核查，仅在 `HIJACKED / UNKNOWN_OCCUPANCY` 等高风险/不确定时升级为高阈值多采样审计，让成本可控。  
**接口口径**：沿用 `/v1/ai/vision_audit`（202 Accepted）与 Policy Config：`vision_audit_threshold_low`、`vision_audit_threshold_confirm`、`vision_audit_samples_required`、`vision_audit_sample_interval_minutes`。  
**重点审查**：升级触发条件是否严格；高成本路径是否可观测（incidents.ai_insights）；不会触碰 holds/slot_state/credit。  
**Done Definition**：L1 发现风险 → 自动触发 L2；L2 输出写入 incident 的 ai_insights（含 sample_index 与置信度/摘要）。

### P0-5 Atomic Redirect Safety（改派原子性 + 影子占位过滤）
**人话目标**：report_blocked 的改派**绝不**把用户引到“物理已占/已有主人”的桩位，避免次生冲突。  
**口径**：改派搜索范围必须满足：`slot_state=FREE` 且 `charger_state=FREE`，并且该桩不被任何现存 hold 指向（同锁原子检查与更新）。  
**重点审查**：并发下不双分配、不误置 FREE；与 Camera Recheck 的 charger_state 更新不互相打架。



### P0-6 Governance & Privacy（社区公约 + 端侧脱敏 + 证人叙事）
**人话目标**：把 JoyGate 定位为“社区公约协议”而非偷拍插件；证明服务端不持有邻居原图；把邻居定义为独立证人（P2P 核证），并把取证触发限制在高风险/不确定 case。  
**口径**：
- JoyKey 激活时签署《社区资源共享互助协议》（范围限定/目的限定/退出路径）
- 零照片真相悬赏：Witness 只提交结构化回答（`charger_state` + 可选 `obstacle_type`），服务端存 `evidence_refs[]`（结构化引用）与 `ai_insights[]`（摘要）
- 证人叙事：事件驱动、最小采样、可复核（ai_report_id + sample_index）
**重点审查**：不引入新字段/枚举；文案避免“放弃隐私权/不可撤回”的强表述；留存与访问控制有明确边界。



### P0-7 Witness Voting（多人投票核证：一致即确认，冲突再摄像头一次）
**人话目标**：真相悬赏不上传原图，改为多名真人 Witness 提交结构化回答；一致即 `EVIDENCE_CONFIRMED`，冲突才触发一次摄像头复核，降低隐私与成本风险。 若在 `witness_sla_timeout_minutes`（默认 3 分钟）内未达到 `witness_votes_required`，则自动降级触发“摄像头 + AI 审计（L1→L2）”，解决稀疏密度问题。  
**接口口径**：新增 `POST /v1/witness/respond`（204）；冲突时内部触发一次摄像头复核，并把结果写入 `incidents.ai_insights`；必要时 `incident_status=ESCALATED` 上报管理员。  
**重点审查**：
- 每个 witness 每个 incident 仅一次提交（防刷）
- 一致/冲突判定的阈值与幂等（重复提交不改变结论）
- 摄像头复核只执行一次，且不误改 hold/slot_state/credit
- **Sparse Density Problem**：3 分钟内投票不足则降级摄像头+AI 审计，避免流程卡死


---

## 4) 计划（P1：加分项，旁路能力为主）

### P1-1 M13 Gemini Online Assist（旁路证据层）
- `/v1/ai/vision_audit` / `policy_suggest` / `dispatch_explain`（202 Accepted）
- 产物落点：incidents.ai_insights（可追溯、可解释）
- **硬边界**：AI 不触发核心状态转移，不自动惩罚

### P1-2 M14 Truth Bounty（群众核查，真人限定）
- 只允许真人 JoyKey 接单与上传证据（机器人不参与）
- 单用户单次提交；一旦事件确认完成，悬赏停止（首杀结束）
- 虚假证言/恶意注入：扣减信用积分，必要时 Lane → RESTRICTED（治理动作仍由管理员兜底）

---

## 5) 计划（P2：体验与商业闭环增强）
- 预约受害者补偿：让 `is_priority_compensated / compensation_reason / incident_id` 从“可观测字段”升级为“可执行策略”
- Grace slice（切片通知）与外部工单联动（管理员响应效率）
- 更细粒度的调度解释（dispatch_reason_codes）与用户教育

---
