## JoyGate 对外 API 摘要（Hackathon 提交版）
唯一真相源：`docs_control_center/FIELD_REGISTRY.md`（字段名/类型/枚举以此为准，禁止改名）。  
说明：本摘要只覆盖**对外 `/v1/*` 契约**与关键枚举；`/bootstrap` 属于 demo 运行行为（非 /v1 契约），但本地演示通常需要先拿到 sandbox cookie。

---

## 0) 运行前置（demo 语义，非 /v1 契约）
- `GET /bootstrap`：初始化沙盒并 Set-Cookie `joygate_sandbox=...`（后续请求需携带 cookie）。
- 若未携带有效 sandbox cookie 调用 `POST /v1/*`：可能返回 **400**（实现细节见项目文档）。

---

## 1) Read-Path（快照与面板查询）

### 1.1 `GET /v1/snapshot` → 200 `SnapshotOK`
- `snapshot_at` (timestamp)
- `chargers` (list[`ChargerSlot`])
- `holds` (list[`HoldSnapshot`])
- `hazards` (list[`HazardSnapshot`])  
  - **始终返回 list**（无数据为 `[]`，不省略）
- `segment_passed_signals` (list[`SegmentPassedSignal`])  
  - **始终返回 list**（无数据为 `[]`，不省略）
  - **不改变** `hazard_status`，**绝不用于解封** `HARD_BLOCKED`
  - 同一 `segment_id` 只保留最新（以 `event_occurred_at` 最大者为准）；乱序旧事件忽略
  - 输出按 `segment_id` 排序；最多 200 条（可截断）

#### `ChargerSlot`
- `charger_id` (string)
- `slot_state` (enum `slot_state`: `FREE|HELD|CHARGING`)
- `hold_id` (string | null)
- `joykey` (string | null)

#### `HoldSnapshot`
- `hold_id` (string)
- `charger_id` (string)
- `joykey` (string)
- `expires_at` (timestamp)
- `incident_id` (string | null)
- `is_priority_compensated` (bool)
- `compensation_reason` (string | null)
- `queue_position_drift` (int | null)

#### `HazardSnapshot`（experimental）
- `hazard_id` (string)
- `segment_id` (string) 例如 `cell_12_34`
- `hazard_status` (enum `hazard_status`: `OPEN|SOFT_BLOCKED|HARD_BLOCKED`)
- `hazard_lock_mode` (enum `hazard_lock_mode`: `SOFT_RECHECK|HARD_MANUAL`)
- `recheck_due_at` (timestamp | null)
- `recheck_interval_minutes` (int | null)
- `soft_recheck_consecutive_blocked` (int | null)
- `incident_id` (string | null)
- `work_order_id` (string | null)

#### `SegmentPassedSignal`（experimental）
- `segment_id` (string)
- `last_passed_at` (string ISO8601 UTC)
- `joykey` (string)
- `truth_input_source` (enum `truth_input_source`)
- `fleet_id` (string | null)

### 1.2 `GET /v1/hazards` → 200 `HazardsList`（experimental）
- `hazards` (list[`HazardItem`])（按 `segment_id` 排序）

#### `HazardItem`
- `segment_id` (string)
- `hazard_status` (enum `hazard_status`: `OPEN|SOFT_BLOCKED|HARD_BLOCKED`)
- `obstacle_type` (string | null)（enum `obstacle_type`）
- `evidence_refs` (list[string] | null)
- `updated_at` (string ISO8601)

> 注意：`/v1/witness/segment_respond` 的 `hazard_status=BLOCKED/CLEAR` 仅为 observation，禁止与此处正式 `hazard_status` 混用。

### 1.3 `GET /v1/incidents` → 200 `IncidentList`（experimental）
- `incidents` (list[`IncidentItem`])

#### `IncidentItem`
- `incident_id` (string)
- `incident_type` (enum `incident_type`)
- `incident_status` (enum `incident_status`)
- `charger_id` (string | null)
- `segment_id` (string | null)
- `snapshot_ref` (string | null)
- `evidence_refs` (list[string] | null)
- `ai_insights` (list[`AIInsight`] | null)

#### `AIInsight`
- `insight_type` (string；项目约定固定值：`WITNESS_TALLY|VISION_AUDIT_REQUESTED|VISION_AUDIT_RESULT`)
- `summary` (string)
- `confidence` (int 0-100 | null)
- `obstacle_type` (string | null)（enum `obstacle_type`）
- `sample_index` (int | null)
- `ai_report_id` (string | null)

### 1.4 `GET /v1/audit/ledger` → 200 `AuditLedgerOK`（experimental）
- `audit_status` (`AuditStatus`)
- `decisions` (list[`AuditDecisionItem`])
- `sidecar_safety_events` (list[`SidecarSafetyEvent`])

#### `AuditStatus`
- `audit_data_mode` (enum `audit_data_mode`)
- `retention_seconds` (int)
- `frame_disposition` (enum `frame_disposition`)
- `last_vision_audit_at` (timestamp | null)

#### `AuditDecisionItem`
- `decision_id` (string)
- `decision_type` (enum `decision_type`)
- `decision_basis` (enum `decision_basis`)
- `incident_id` (string | null)
- `hold_id` (string | null)
- `charger_id` (string | null)
- `segment_id` (string | null)
- `ai_report_id` (string | null)
- `evidence_refs` (list[string] | null)
- `summary` (string | null)
- `prev_bundle_hash` (string | null)
- `bundle_hash` (string)
- `created_at` (timestamp)

#### `SidecarSafetyEvent`
- `sidecar_event_id` (string)
- `suggestion_id` (string | null)
- `joykey` (string | null)
- `fleet_id` (string | null)
- `oem_result` (enum `oem_result`)
- `fallback_reason` (string | null)
- `observed_by` (enum `safety_observed_by`)
- `observed_at` (timestamp)  # 输出为 JSON number（epoch seconds）

### 1.5 `GET /v1/policy` → 200（Policy Config）
返回字段集合见 `FIELD_REGISTRY.md` 的 **“Policy Config（制度参数｜默认值）”** 小节（例如 `slot_duration_minutes / witness_votes_required / soft_hazard_recheck_interval_minutes / webhook_timeout_seconds` 等）。

### 1.6 `GET /v1/reputation` / `GET /v1/score_events` / `GET /v1/vendor_scores`（experimental）
字段口径见 `FIELD_REGISTRY.md` 的 M16 条目（本摘要不复述）。

---

## 2) Write-Path（占位 / 上报 / 核证 / 工单 / 遥测）

### 2.1 `POST /v1/reserve`
请求 `ReserveRequest`
- `resource_type` (string) 例如 `"charger"`
- `resource_id` (string) 例如 `"charger-001"`
- `joykey` (string)
- `action` (string enum) 例如 `"HOLD"`

响应：
- 200 `ReserveOK`：`hold_id` (string), `ttl_seconds` (int)
- 409 `Error409`：`error`=`RESOURCE_BUSY`, `message` (string)
- 429 `Error429`：`error`=`QUOTA_EXCEEDED`, `message` (string)

### 2.2 `POST /v1/oracle/start_charging` / `POST /v1/oracle/stop_charging`
请求：
- `hold_id` (string)
- `charger_id` (string)
- `meter_session_id` (string)
- `event_occurred_at` (timestamp)

### 2.3 `POST /v1/incidents/report_blocked` → 200
请求 `IncidentsReportBlockedRequest`
- `charger_id` (string) **required**
- `incident_type` (enum `incident_type`) **required**
- `snapshot_ref` (string | null, len≤256 when present) optional
- `evidence_refs` (list[string] | null) optional

响应 `IncidentsReportBlockedOK (200)`：
- `incident_id` (string)

### 2.4 `POST /v1/incidents/update_status` → 204
请求 `IncidentsUpdateStatusRequest`
- `incident_id` (string, len≤64)
- `incident_status` (enum `incident_status`)

成功：204 No Content  
失败：400/404（FastAPI 默认 `{"detail": "..."}`）

### 2.5 `POST /v1/witness/respond` → 204
请求 `WitnessResponseRequest`
- `incident_id` (string)
- `charger_id` (string)
- `charger_state` (enum `charger_state`: `FREE|OCCUPIED|UNKNOWN_OCCUPANCY`)
- `obstacle_type` (enum `obstacle_type` | null) optional
- `evidence_refs` (list[string] | null) optional
- `points_event_id` (string | null) optional

> 提交者身份来自鉴权上下文（joykey / fleet_id），不在请求体重复。

### 2.6 `POST /v1/witness/segment_respond` → 204（experimental）
请求 `SegmentWitnessResponseRequest`
- `segment_id` (string) 例如 `cell_12_34`
- `segment_state` (enum `segment_state`: `PASSABLE|BLOCKED|UNKNOWN`)（推荐使用：通行观察）
- `hazard_status` (string enum) 例如 `BLOCKED/CLEAR`（兼容字段；仅表示 observation，**不是**正式 `hazard_status` 状态机）
- `obstacle_type` (string | null) optional
- `evidence_refs` (list[string] | null) optional（cap 5，单条≤120）
- `points_event_id` (string) **required**（幂等去重 token；长度≤64；禁止首尾空白）
- `incident_id` (string) optional

### 2.9 `POST /v1/audit/sidecar_safety_event` → 204（experimental，demo-only）
请求 `SidecarSafetyEventIn`
- `suggestion_id` (string | null)
- `joykey` (string | null)
- `fleet_id` (string | null)
- `oem_result` (enum `oem_result`)（`ACCEPTED|IGNORED|REJECTED|SAFETY_FALLBACK|FAILED`）
- `fallback_reason` (string | null)
- `observed_by` (enum `safety_observed_by`)（`TELEMETRY|TIMEOUT|OEM_CALLBACK`）
- `observed_at` (timestamp)  # **仅接受 JSON number（epoch seconds）**，拒绝字符串与布尔值

说明：该端点用于 hackathon/demo 注入“可查账本”的 sidecar 回退记录；数据会出现在 `GET /v1/audit/ledger.sidecar_safety_events[]`。

### 2.7 `POST /v1/work_orders/report` → 204（experimental）
请求 `WorkOrderReportRequest`
- `work_order_id` (string)
- `incident_id` (string | null) optional
- `segment_id` (string | null) optional
- `charger_id` (string | null) optional
- `work_order_status` (enum `work_order_status`)
- `event_occurred_at` (timestamp)
- `evidence_refs` (list[string] | null) optional

**硬规则**：当 `work_order_status=DONE` 且关联 `segment_id` 存在时，才允许解封该 `segment_id` 的 `HARD_BLOCKED`（唯一入口）。

### 2.8 `POST /v1/telemetry/segment_passed` → 204（experimental）
请求 `SegmentPassedTelemetryRequest`
- `joykey` (string, len≤128)
- `fleet_id` (string | null) optional
- `segment_ids` (list[string], len>=1) 例如 `["cell_12_34"]`
- `event_occurred_at` (timestamp；兼容 epoch seconds(number) 与 ISO8601 string)
- `truth_input_source` (enum `truth_input_source`；建议 `SIMULATOR`)

---

## 3) AI Layer（异步，202 Accepted）

### 3.1 `POST /v1/ai/vision_audit` → 202
请求 `VisionAuditRequest`
- `snapshot_ref` (string | null, len≤256) optional（strip）
- `evidence_refs` (list[string] | null) optional（cap 5，单条≤120，strip/非空）
- `incident_id` (string | null, len≤64) optional
- `model_tier` (enum `ai_model_tier` | null) optional（不传默认 `FLASH`）

响应（202）：
- `ai_report_id` (string)
- `status` (enum `ai_job_status`)

### 3.2 `POST /v1/ai/dispatch_explain` → 202
请求 `DispatchExplainRequest`
- `hold_id` (string, len≤64，strip)
- `obstacle_type` (enum `obstacle_type` | null)
- `audience` (enum `audience`，len≤64)
- `dispatch_reason_codes` (list[string])（recommended = enum `dispatch_reason_code`）
- `context_ref` (string | null)（不透明引用；长度≤256；命中敏感模式则 400；服务端仅保存 `context_ref_sha256`）
- `model_tier` (enum `ai_model_tier` | null) optional（不传默认 `FLASH`）

响应（202）：`ai_report_id` (string), `status` (enum `ai_job_status`)

### 3.3 `POST /v1/ai/policy_suggest` → 202
请求 `PolicySuggestRequest`
- `incident_id` (string | null, len≤64) optional
- `context_ref` (string | null)（同上：不透明引用与敏感校验）
- `model_tier` (enum `ai_model_tier` | null) optional（不传默认 `PRO`）

响应（202）：`ai_report_id` (string), `status` (enum)

### 3.4 `POST /v1/admin/apply_policy_suggestion` → 202
请求 `ApplyPolicyRequest`
- `ai_report_id` (string)
- `confirm` (bool)

响应（202）：`status` (string enum)

---

## 4) Outbound Webhooks（对外事件推送，experimental）

### 4.1 `POST /v1/webhooks/subscriptions`
请求 `WebhookSubscriptionCreateRequest`
- `target_url` (string)
- `event_types` (list[string enum])（enum `webhook_event_type`）
- `secret` (string | null)
- `is_enabled` (bool | null)

响应 `WebhookSubscriptionCreated`
- `subscription_id` (string)
- `target_url` (string)
- `event_types` (list[string enum])
- `is_enabled` (bool)
- `created_at` (timestamp)

### 4.2 `GET /v1/webhooks/subscriptions`
响应 `WebhookSubscriptionListOK`
- `subscriptions` (list[`WebhookSubscription`])

### 4.3 `GET /v1/webhooks/deliveries`
响应 `WebhookDeliveriesListOK`
- `deliveries` (list[`WebhookDeliveryItem`])（默认按 `created_at` 倒序）

#### `webhook_delivery_status`（枚举）
- `PENDING|DELIVERED|FAILED`

#### `WebhookEventPayload`
- `event_id` (string)
- `event_type` (string enum)
- `occurred_at` (timestamp)
- `object_type` (string)
- `object_id` (string)
- `data` (object)

#### Outbound headers
- `X-JoyGate-Timestamp`
- `X-JoyGate-Signature`: `sha256=<hex>`

---

## 5) 核心枚举（节选）
- `incident_type`: `NO_PLUG|BLOCKED_BY_OTHER|BLOCKED|HIJACKED|UNKNOWN_OCCUPANCY|OVERSTAY|NO_SHOW|OTHER`
- `incident_status`: `OPEN|RESOLVED|ESCALATED|UNDER_OBSERVATION|EVIDENCE_CONFIRMED`
- `hazard_status`: `OPEN|SOFT_BLOCKED|HARD_BLOCKED`
- `work_order_status`: `OPEN|IN_PROGRESS|DONE|FAILED|ESCALATED`
- `segment_state`: `PASSABLE|BLOCKED|UNKNOWN`
- `truth_input_source`: `SIMULATOR|OCPP|THIRD_PARTY_API|QR_SCAN|VISION`
- `oem_result`: `ACCEPTED|IGNORED|REJECTED|SAFETY_FALLBACK|FAILED`
- `webhook_event_type`: `INCIDENT_CREATED|INCIDENT_STATUS_CHANGED|HAZARD_STATUS_CHANGED|WORK_ORDER_STATUS_CHANGED|AI_JOB_STATUS_CHANGED|HOLD_CREATED|HOLD_EXPIRED|OTHER`
- `ai_model_tier`: `FLASH|PRO`
- `ai_job_status`: `ACCEPTED|IN_PROGRESS|COMPLETED|FAILED`

---

## 6) 路线图提示（避免误解为已实现）
- `POST /v1/report_blocked`：已登记为 **当前未实现**（事件创建请使用 `POST /v1/incidents/report_blocked`）。

