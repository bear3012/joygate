# 🚦 JoyGate  
**Unified Access Gateway for Humans + Autonomous Robot Assets**  
> 🏆 **Track Fit: Launch & Fund — AI meets Robotics (Simulation Track)**

JoyGate is a **control plane** for a campus running **multi-vendor, heterogeneous robots**. In a messy physical world, JoyGate uses **Parallel Healing** to keep robots **moving without interruption** even when chargers are blocked, routes are congested, vendors differ, and evidence is incomplete—while turning “truth + responsibility” into **auditable, traceable** data assets.

> 🛡️ **Hard Safety Boundary**: JoyGate treats humans as **soft actuators** (handle tricky work orders) and robots as **hard actuators** (execute task-level recommendations & scheduling).  
> If JoyGate’s recommendation conflicts with OEM/Sidecar native safety logic, JoyGate **must yield** and degrade to **sidecar observation + post-incident audit**. We **never** interfere with millisecond-level low-level control.

---

## 🎯 1. Commercialization Path (Launch & Fund Ready)

For this hackathon, we deliberately **avoid high-risk real-time physical control** and instead build a **data + trust hub**:

- **📈 Risk-Pricing Data Layer (Insurance / Ops Risk Signals)**
  - **Risk Tier**: Based on verified collaboration behavior and verifiable events, generate signals like `robot_score / robot_tier / vote_weight`.
  - **Claim Evidence Pack**: For disputes/claims postmortems, provide event anchors such as `incident_id` + `evidence_refs`, plus audit views (including `sidecar_safety_events` that record “yield/fallback” behavior).
  - **Business value**: Integrators reduce operational uncertainty and can negotiate better insurance premiums. JoyGate **is not** the insurer, and **not** a liability adjudicator.

- **📦 Verified Data Assets (Auditable Edge Data Products)**
  - Privacy-by-default: **no raw media streams stored**; primarily summaries + references.
  - **Outbound Webhooks** push “verified key state transitions” into downstream systems (supports signatures and replay defense).

---

## 🎮 2. Interactive Simulation Demo (Guide)

We provide a high-fidelity **2D browser sandbox** that visualizes JoyGate scheduling logic and Parallel Healing in action.

### 👁️ Mode A: Judge Mode (Default Read-Only)
- **URL**: `GET /ui`
- **You will see**: a 20×20 grid campus map; 8 robots from 5 different vendors patrolling and returning to charge.
- **Live panels**: `Hazards / Incidents / Audit / Policy / Daily Report`
- **Safety**: In default mode, the UI exposes **no write buttons**. For interaction, use God Mode.

### ⚡ Mode B: God Mode (Interactive Story)
- **URL**: `GET /ui?god=1`
- **Quick experience**: open the right-side `God Controls` and run a full loop:
  1. 🚧 **Simulate Obstacle**: Select a ROAD cell to trigger witness voting by 3 robots. Watch the area transition `OPEN → SOFT_BLOCKED → HARD_BLOCKED`, while other robots immediately reroute (multi-agent consensus + uninterrupted motion).
  2. 🔋 **Charging Dispatch Drama**: Force-dispatch a robot to an occupied charger. On conflict (409), the system reports an incident and re-dispatches to a new charger (failure never blocks the fleet).
  3. 🤖 **Trigger AI Audit**: For disputed incidents, trigger a one-shot cloud AI vision audit (Vultr). If no API key is configured, the system **gracefully degrades** (animation-only).
  4. 🛠️ **Human Fix (Authoritative Unblock)**: Submit `DONE` for a `HARD_BLOCKED` work order; the area immediately becomes passable again (humans are the highest authority).

---

## 🧠 3. Core Technical Idea: Parallel Healing

When the physical world gets blocked, JoyGate runs two paths in parallel to maximize continuity and truth:

1. **Synchronous path (protect continuity, must stay light)**
   - Immediately produce task-level recommendations (reroute / switch charger).
   - The sync API completes in milliseconds and **never waits** for slow AI or human review—robots continue moving.

2. **Asynchronous path (background healing & recertification, protect truth)**
   - **L1**: Peer-to-peer Witness voting (nearby robots vote cheaply).
   - **L2**: Vision Audit (event-driven one-shot AI verification; privacy-preserving).
   - **L3**: Work Orders (dedicated staff handle complex scenes; **HARD states can only be unlocked by human DONE**).

---

## 🚀 4. Quickstart (Local)

> **Dependency**: Designed for deployment on Vultr edge nodes. Local testing requires **Python 3.10+**.

### 4.1 Install dependencies (Windows PowerShell)
```powershell
# Run in the project root
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 4.2 Start the service (MUST be single worker)
This demo uses a **single-process in-memory sandbox** for transactional consistency.

```powershell
$env:PYTHONPATH="src"
python -m uvicorn joygate.main:app --host 127.0.0.1 --port 8000 --workers 1
```

### 4.3 Get the Sandbox Cookie (MUST do this first)
⚠️ Windows PowerShell users: use `curl.exe` (avoid PowerShell’s `curl` alias).

```powershell
curl.exe -c cookies.txt http://127.0.0.1:8000/bootstrap
```

### 4.4 Open the demo UI
- Read-only panel: `http://127.0.0.1:8000/ui`
- Interactive sandbox: `http://127.0.0.1:8000/ui?god=1`

---

## 📖 5. API Architecture Overview

This section is a route index. The **single source of truth** for field constraints and enums is: `docs_control_center/FIELD_REGISTRY.md`.

### 📡 Read Path (State Sync & Snapshots)
- `GET /v1/snapshot` — Global campus snapshot
- `GET /v1/incidents` — Active incidents list
- `GET /v1/audit/ledger` — Core audit ledger view (tamper-resistant)

### ⚡ Write Path (Scheduling, Reporting & Governance)
- `POST /v1/reserve` — Reserve a charger resource
- `POST /v1/incidents/report_blocked` — Report an incident (first report)
- `POST /v1/witness/segment_respond` — Multi-robot voting on a segment
- `POST /v1/work_orders/report` — Human work order channel

### 🤖 AI Layer (Asynchronous Execution)
- `POST /v1/ai/vision_audit` — Trigger vision audit (`202 Accepted`)

### 🔔 Outbound Webhooks (Integrations)
- `POST /v1/webhooks/subscriptions` — Subscribe to verified state transitions

---

## 📎 6. Further Reading (Repository Sources of Truth)
- Full contract & narrative: `docs_control_center/README_HACKATHON_CHARGER.md`
- Official field/enum dictionary: `docs_control_center/FIELD_REGISTRY.md`
- Reproducible run evidence & logs: `docs_control_center/RUN_LOG.md`
