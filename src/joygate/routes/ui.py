# M18 Web UI: Pastel/Glass campus sandbox. Judge Mode (default) read-only; God Mode (?god=1) allows POST.
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()

# Campus blueprint: roads, buildings, park, chargers, robot spawns/routes (cell_x_y only).
CHARGER_CELLS = {
    "charger-001": (6, 18), "charger-002": (8, 18), "charger-003": (10, 18),
    "charger-004": (12, 18), "charger-005": (14, 18),
}
ROBOT_SPAWN = {
    "w1": (2, 1), "w2": (17, 1), "charlie_01": (5, 10), "charlie_02": (15, 10),
    "alpha_02": (10, 3), "delta_01": (10, 15), "echo_01": (1, 12), "echo_02": (18, 12),
}
ROBOT_ROUTES = {
    "Route_OuterPatrol": [(1, 1), (18, 1), (18, 17), (1, 17), (1, 1)],
    "Route_EastWest_Shuttle": [(1, 10), (18, 10), (18, 17), (1, 17), (1, 10)],
    "Route_CentralDelivery": [(10, 3), (10, 10), (3, 10), (3, 17), (10, 17), (17, 17), (17, 10), (10, 10), (10, 3)],
    "Route_ChargingDrill": [(10, 3), (10, 17), (6, 17), (14, 17), (10, 17), (10, 3)],
}
ROBOT_TO_ROUTE = {
    "w1": "Route_OuterPatrol", "w2": "Route_OuterPatrol",
    "charlie_01": "Route_ChargingDrill", "echo_02": "Route_ChargingDrill",
    "alpha_02": "Route_EastWest_Shuttle", "echo_01": "Route_EastWest_Shuttle",
    "charlie_02": "Route_CentralDelivery", "delta_01": "Route_CentralDelivery",
}
# Buildings (blocked): (xmin, xmax, ymin, ymax)
BUILDINGS = [(4, 6, 4, 6), (13, 15, 4, 6), (4, 6, 13, 14), (13, 15, 13, 14)]
# Roads: list of (xmin, xmax, ymin, ymax) for outer ring + main cross + plaza
ROAD_RECTS = [
    (1, 18, 1, 1), (1, 18, 17, 17), (1, 1, 1, 17), (18, 18, 1, 17),
    (10, 10, 1, 17), (1, 18, 10, 10),
]
PARK_RECT = (6, 13, 12, 15)
# Witness key ring (must be in backend allowlist by default): w1, w2, charlie_01
WITNESS_KEYS = ["w1", "w2", "charlie_01"]


def _is_road(x: int, y: int) -> bool:
    for (xmin, xmax, ymin, ymax) in ROAD_RECTS:
        if xmin <= x <= xmax and ymin <= y <= ymax:
            return True
    return False


def _is_building(x: int, y: int) -> bool:
    for (xmin, xmax, ymin, ymax) in BUILDINGS:
        if xmin <= x <= xmax and ymin <= y <= ymax:
            return True
    return False


def _is_park(x: int, y: int) -> bool:
    xmin, xmax, ymin, ymax = PARK_RECT
    return xmin <= x <= xmax and ymin <= y <= ymax


@router.get("/ui", response_class=HTMLResponse)
def ui_page(request: Request) -> str:
    """M18: Campus sandbox UI. Judge Mode default; God Mode with ?god=1."""
    # Inline HTML/CSS/JS; no f-string injection (client gets sandbox from /bootstrap).
    html_body = _build_ui_html()
    return html_body


def _build_ui_html() -> str:
    return r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>JoyGate Campus Sandbox</title>
<style>
:root { --cream: #faf8f5; --glass: rgba(255,255,255,0.65); --border: rgba(0,0,0,0.06); --radius: 16px; --shadow: 0 8px 32px rgba(0,0,0,0.06); }
* { box-sizing: border-box; }
body { margin: 0; font-family: system-ui, sans-serif; background: linear-gradient(135deg, #fdfcfb 0%, #f5f0e8 100%); min-height: 100vh; color: #333; }
.layout { display: flex; flex-direction: column; height: 100vh; }
.top { display: flex; flex: 7; min-height: 0; }
.left { flex: 6; padding: 12px; min-width: 0; display: flex; flex-direction: column; gap: 12px; }
.right { flex: 4; padding: 12px; overflow-y: auto; display: flex; flex-direction: column; gap: 12px; }
.bottom { flex: 0 0 auto; padding: 8px 12px; border-top: 1px solid var(--border); background: var(--glass); backdrop-filter: blur(10px); display: none; }
.card { background: var(--glass); backdrop-filter: blur(10px); border: 1px solid var(--border); border-radius: var(--radius); box-shadow: var(--shadow); padding: 12px; }
.card h3 { margin: 0 0 8px 0; font-size: 14px; }
#canv { display: block; width: 100%; height: auto; aspect-ratio: 1 / 1; max-height: 70vh; background: #f0ede8; border-radius: var(--radius); }
#cmdlog { max-height: 120px; overflow-y: auto; font-family: monospace; font-size: 12px; }
#cmdlog div { padding: 2px 0; }
.god-only { display: none; }
body.god-mode .god-only { display: block; }
.btns { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 8px; }
.btns button { padding: 6px 12px; border-radius: 8px; border: 1px solid var(--border); background: var(--glass); cursor: pointer; }
.btns button:disabled { opacity: 0.5; cursor: not-allowed; }
#godToken { padding: 6px 10px; border-radius: 8px; border: 1px solid var(--border); background: var(--glass); width: 140px; }
@media (prefers-reduced-motion: reduce) { .breath { animation: none !important; } }
.breath { animation: breath 2s ease-in-out infinite; }
@keyframes breath { 50% { opacity: 0.9; } }
.modal-backdrop { position: fixed; inset: 0; background: rgba(0,0,0,0.35); display: none; align-items: center; justify-content: center; z-index: 9999; }
.modal-backdrop.show { display: flex; }
.modal-card { width: min(760px, 92vw); max-height: 78vh; overflow: auto; background: #fff; border-radius: 12px; border: 1px solid var(--border); box-shadow: var(--shadow); padding: 12px; }
.modal-title { font-weight: 600; margin-bottom: 8px; }
.modal-body { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px; white-space: pre-wrap; }
#narrativeFeed { max-height: 190px; overflow: auto; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px; line-height: 1.35; }
#toastWrap { position: fixed; right: 16px; top: 16px; z-index: 10000; display: flex; flex-direction: column; gap: 8px; pointer-events: none; }
.toastItem { background: rgba(20,20,20,0.9); color: #fff; border-radius: 8px; padding: 8px 10px; font-size: 12px; box-shadow: 0 6px 20px rgba(0,0,0,0.25); }
.toastWarn { background: rgba(165,70,20,0.92); }
</style>
</head>
<body class="layout">
<div class="top">
  <div class="left">
    <div class="card" style="flex:1; min-height:0;">
      <h3>Canvas (20×20) — cell_x_y</h3>
      <div style="display:flex; gap:12px; font-size:10px; margin-bottom:8px; align-items:center; flex-wrap:wrap;">
        <div style="display:flex; align-items:center;"><span style="width:10px; height:10px; background:#FF0080; border-radius:50%; display:inline-block; margin-right:4px;"></span>Robot</div>
        <div style="display:flex; align-items:center;"><span style="width:10px; height:10px; background:#4a90d9; border-radius:50%; display:inline-block; margin-right:4px;"></span>Charger</div>
        <div style="display:flex; align-items:center;"><span style="width:10px; height:10px; background:rgba(200,80,80,0.6); border:1px solid #a55; display:inline-block; margin-right:4px;"></span>Hard Block</div>
        <div style="display:flex; align-items:center;"><span style="width:10px; height:10px; background:rgba(255,230,150,0.7); border:1px solid rgba(255,230,150,0.7); display:inline-block; margin-right:4px;"></span>Soft Block</div>
        <div style="display:flex; align-items:center;"><span style="width:10px; height:10px; background:#e8e4dc; border:1px solid #ddd; display:inline-block; margin-right:4px;"></span>Road</div>
      </div>
      <canvas id="canv" width="400" height="400"></canvas>
    </div>
    <div class="card god-only"><h3>Controls</h3>
      <div class="btns">
        <button type="button" id="btnJudgeDemo">Run Judge Demo</button>
        <button type="button" id="btnObstacle">A Simulate Obstacle</button>
        <button type="button" id="btnCharging">B Charging Dispatch</button>
        <button type="button" id="btnVision">C Trigger AI Audit</button>
        <button type="button" id="btnWorkOrder">D Human Fix (DONE)</button>
        <label><input type="checkbox" id="telemetrySync" /> Sync Telemetry (slow)</label>
      </div>
    </div>
  </div>
  <div class="right">
    <div class="card"><h3>Narrative Guide (Judge)</h3><div id="narrativeFeed">—</div></div>
    <div class="card"><h3>Incidents</h3><div id="incidents">—</div></div>
    <div class="card"><h3>Hazards + Policy</h3><div id="hazards">—</div></div>
    <div class="card"><h3>Audit</h3><div id="audit">—</div></div>
    <div class="card"><h3>JoyGate Interventions</h3><div id="interventions">—</div></div>
  </div>
</div>
<div class="bottom">
  <div><strong>Command Log</strong></div>
  <div id="cmdlog"></div>
</div>
<div id="toastWrap"></div>
<div id="evidenceModal" class="modal-backdrop" aria-hidden="true">
  <div class="modal-card">
    <div class="modal-title" id="evidenceTitle">Vision Audit Evidence</div>
    <div class="modal-body" id="evidenceBody">—</div>
    <div class="btns" style="margin-top:10px;">
      <button type="button" id="btnCloseEvidence">Close</button>
    </div>
  </div>
</div>
<script>
(function(){
"use strict";
var isGodMode = new URLSearchParams(location.search).get("god") === "1";
if (isGodMode) document.body.classList.add("god-mode");

var sandboxId = "anon";
var snapshot = { hazards: [], segment_passed_signals: [], chargers: [], holds: [] };
var prevHazards = [];
var incidents = [];
var localHazards = {};
var audit = {};
var policy = {};
var selectedCell = null;
var botState = {};
var cmdLog = [];
var MAX_LOG = 200;
var DISPLAY_LOG_LINES = 120;
var BOT_TICK_MS = 250;
var MOVE_DURATION_MS = reduceMotion ? 50 : 1000;
var BASE_DRAIN = 0.005;
var CHARGE_RATE = 0.15;
var EVENT_CLEAR_MS = 8000;
var EVENT_PRE_FREEZE_MS = 100;
var EVENT_MIN_ROBOT_DIST = 3;
var capacityReached = false;
var chargerOverrides = {};
var intervals = { snapshot: 2000, incidents: 6000, audit: 10000, policy: 30000 };
var baseIntervals = { snapshot: 2000, incidents: 6000, audit: 10000, policy: 30000 };
var telemetrySyncOn = false;
var telemetryBotIndex = 0;
var reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
var godToken = "";
var demoRunning = false;
var recentAuditNotes = [];
var interventionLines = [];
var interventionFeed = [];
var flashMarks = [];
var chargerFlashUntil = {};
var eventMarks = [];
var voteHints = [];
var narrativeFeed = [];
var witnessAllowlist = ["w1","w2","charlie_01"];
var tempEventBlocks = {};
var eventRuntimeBySeg = {};
var hazardSuppressUntilBySeg = {};
var demoStrictMode = false;
var JUDGE_DEMO_POINTS = { obstacleCell: [10, 9], chargingBotId: "echo_01", chargerId: "charger-001" };
var JUDGE_DEMO_BOT_ANCHORS = {
  "w1":[9,8], "w2":[11,8], "charlie_01":[10,10],
  "alpha_02":[4,3], "charlie_02":[15,10], "delta_01":[10,15], "echo_01":[1,12], "echo_02":[18,12]
};

function loadGodToken(){ try { godToken = (sessionStorage.getItem("joygate_god_token")||"").trim(); } catch(e) { godToken = ""; } }
function setGodToken(v){ var s = (v||"").trim(); godToken = s; try { if (s) sessionStorage.setItem("joygate_god_token", s); else sessionStorage.removeItem("joygate_god_token"); } catch(e) {} updateGodUiState(); }
function clearGodToken(){ godToken = ""; try { sessionStorage.removeItem("joygate_god_token"); } catch(e) {} var el = document.getElementById("godToken"); if (el) el.value = ""; updateGodUiState(); }
function updateGodUiState(){
  var canWrite = isGodMode;
  var btns = ["btnJudgeDemo","btnObstacle","btnCharging","btnVision","btnWorkOrder"];
  btns.forEach(function(id){ var b = document.getElementById(id); if (b) b.disabled = !canWrite; });
  var st = document.getElementById("godTokenStatus"); if (st) st.textContent = "";
}
function sleepMs(ms){ return new Promise(function(resolve){ setTimeout(resolve, ms); }); }
async function waitForDemoStage(minMs, maxMs, readyFn){
  var started = Date.now();
  while (true) {
    var elapsed = Date.now() - started;
    var ready = false;
    try { ready = readyFn ? !!readyFn() : false; } catch(e) { ready = false; }
    if (elapsed >= minMs && ready) return { timedOut: false, elapsedMs: elapsed };
    if (elapsed >= maxMs) return { timedOut: true, elapsedMs: elapsed };
    await sleepMs(120);
  }
}
function pushAuditNote(text){
  if (!text) return;
  var t = new Date();
  var ts = t.getHours().toString().padStart(2,"0")+":"+t.getMinutes().toString().padStart(2,"0")+":"+t.getSeconds().toString().padStart(2,"0");
  recentAuditNotes.push("[" + ts + "] " + text);
  if (recentAuditNotes.length > 6) recentAuditNotes = recentAuditNotes.slice(-6);
  updateCards();
}
function pushNarrative(text){
  if (!text) return;
  var line = "[" + hhmmssNow() + "] " + text;
  narrativeFeed.push(line);
  if (narrativeFeed.length > 80) narrativeFeed = narrativeFeed.slice(-80);
  var el = document.getElementById("narrativeFeed");
  if (el) {
    el.textContent = "";
    narrativeFeed.slice(-30).forEach(function(row){
      var d = document.createElement("div");
      d.textContent = row;
      el.appendChild(d);
    });
    el.scrollTop = el.scrollHeight;
  }
}
function showToast(msg, warn){
  if (!msg) return;
  var wrap = document.getElementById("toastWrap");
  if (!wrap) return;
  var n = document.createElement("div");
  n.className = "toastItem" + (warn ? " toastWarn" : "");
  n.textContent = msg;
  wrap.appendChild(n);
  setTimeout(function(){ if (n && n.parentNode) n.parentNode.removeChild(n); }, 1800);
}
function addVoteHint(who, cell){
  if (!cell) return;
  voteHints.push({ who: who || "witness", cell: [cell[0], cell[1]], untilMs: Date.now() + 2600 });
  if (voteHints.length > 50) voteHints = voteHints.slice(-50);
}
function showEvidenceModal(title, body){
  var m = document.getElementById("evidenceModal");
  var t = document.getElementById("evidenceTitle");
  var b = document.getElementById("evidenceBody");
  if (t) t.textContent = title || "Vision Audit Evidence";
  if (b) b.textContent = body || "—";
  if (m) { m.classList.add("show"); m.setAttribute("aria-hidden", "false"); }
}
function hideEvidenceModal(){
  var m = document.getElementById("evidenceModal");
  if (m) { m.classList.remove("show"); m.setAttribute("aria-hidden", "true"); }
}

function cellId(x,y){ return "cell_"+x+"_"+y; }
function parseCell(s){ var m = (s||"").match(/^cell_(\d+)_(\d+)$/); return m ? [parseInt(m[1],10),parseInt(m[2],10)] : null; }
function isHazardSuppressed(seg){
  var u = hazardSuppressUntilBySeg[seg];
  if (!u) return false;
  if (Date.now() >= u) { delete hazardSuppressUntilBySeg[seg]; return false; }
  return true;
}
function manhattan(a,b){ return Math.abs(a[0]-b[0]) + Math.abs(a[1]-b[1]); }
function isCellFarFromAllBots(cell, minDist){
  var best = 999;
  Object.keys(botState).forEach(function(id){
    var b = botState[id]; var p = (b && b.currentCell) ? b.currentCell : (robotSpawn[id] || null);
    if (!p) return;
    var d = manhattan(p, cell);
    if (d < best) best = d;
  });
  return best >= minDist;
}
function pickDemoObstacleCell(){
  // Deterministic candidate order; prefer cells that are close (1-2 cells) and have witness candidates.
  var candidates = [[10,9],[9,9],[11,9],[10,8],[10,10],[8,9],[12,9],[9,10],[11,10]];
  var bestNear = null;
  var bestNearDist = 999;
  for (var i = 0; i < candidates.length; i++) {
    var c = candidates[i];
    if (!isRoad(c[0], c[1]) || isBuilding(c[0], c[1])) continue;
    if (!isCellFarFromAllBots(c, 1)) continue;
    if (getNearbyWitnesses(c).length <= 0) continue;
    var minD = 999;
    Object.keys(botState).forEach(function(id){
      var b = botState[id]; var p = (b && b.currentCell) ? b.currentCell : (robotSpawn[id] || null);
      if (!p) return;
      var d = manhattan(c, p);
      if (d < minD) minD = d;
    });
    if (minD >= 1 && minD <= 2 && minD < bestNearDist) { bestNearDist = minD; bestNear = [c[0], c[1]]; }
  }
  if (bestNear) return bestNear;
  // Fallback: nearest road cell that still has witness candidates.
  var bestCell = [10, 9];
  var bestDist = 999;
  for (var y = 1; y <= 18; y++) {
    for (var x = 1; x <= 18; x++) {
      if (!isRoad(x, y) || isBuilding(x, y)) continue;
      if (!isCellFarFromAllBots([x, y], 1)) continue;
      if (getNearbyWitnesses([x, y]).length === 0) continue;
      var minD = 999;
      Object.keys(botState).forEach(function(id){
        var b = botState[id]; var p = (b && b.currentCell) ? b.currentCell : (robotSpawn[id] || null);
        if (!p) return;
        var d = manhattan([x, y], p);
        if (d < minD) minD = d;
      });
      if (minD < bestDist) { bestDist = minD; bestCell = [x, y]; }
    }
  }
  return bestCell;
}
function resetBotsToJudgeDemoAnchors(){
  Object.keys(robotToRoute).forEach(function(id){
    var b = botState[id] || (botState[id] = {});
    var c = (JUDGE_DEMO_BOT_ANCHORS[id] || robotSpawn[id] || [0,0]).slice(0);
    b.currentCell = [c[0], c[1]];
    b.nextCell = [c[0], c[1]];
    b.pathCells = [];
    b.mode = "PATROL";
    b.targetChargerId = null;
    b.negotiating = false;
    b.moveStartMs = Date.now();
  });
  redraw();
}
function clearEventVisuals(){
  flashMarks = [];
  voteHints = [];
  eventMarks = [];
  Object.keys(chargerFlashUntil).forEach(function(k){ delete chargerFlashUntil[k]; });
}
function clearDemoScene(){
  clearEventVisuals();
  Object.keys(tempEventBlocks).forEach(function(k){ delete tempEventBlocks[k]; });
  Object.keys(eventRuntimeBySeg).forEach(function(k){ delete eventRuntimeBySeg[k]; });
  Object.keys(hazardSuppressUntilBySeg).forEach(function(k){ delete hazardSuppressUntilBySeg[k]; });
  localHazards = {};
  snapshot.hazards = [];
  redraw();
}
function upsertLocalHazard(seg, status){
  if (isHazardSuppressed(seg) && status !== "OPEN") return;
  if (status === "OPEN") {
    delete localHazards[seg];
  } else {
    localHazards[seg] = { segment_id: seg, hazard_status: status, hazard_id: "haz_ui_" + seg + "_" + Date.now() };
  }
  // snapshot.hazards no longer modified directly to avoid race with polling
  recomputeAllPaths();
  redraw();
}
function ensureEventTimeoutClear(seg){
  setTimeout(function(){
    delete tempEventBlocks[seg];
    if (eventRuntimeBySeg[seg]) eventRuntimeBySeg[seg].resolved = true;
    // Suppress rebound from backend polling for a short window after forced clear.
    hazardSuppressUntilBySeg[seg] = Date.now() + 10000;
    delete localHazards[seg];
    clearEventVisuals();
    pushNarrative("Event auto-cleared in 8s: " + seg);
    recomputeAllPaths();
    redraw();
  }, EVENT_CLEAR_MS);
}
function getNearbyWitnesses(cell){
  var candidates = witnessAllowlist.filter(function(id){
    var b = botState[id];
    var p = (b && b.currentCell) ? b.currentCell : (robotSpawn[id] || null);
    return !!p && manhattan(p, cell) <= 1;
  });
  return candidates;
}
function isWitnessWithinOneCell(id, cell){
  var b = botState[id];
  var p = (b && b.currentCell) ? b.currentCell : (robotSpawn[id] || null);
  return !!p && manhattan(p, cell) <= 1;
}
function ensureEventClearScheduled(seg){
  var rt = eventRuntimeBySeg[seg];
  if (!rt || rt.clearScheduled) return;
  rt.clearScheduled = true;
  ensureEventTimeoutClear(seg);
}

var chargerCells = {"charger-001":[6,18],"charger-002":[8,18],"charger-003":[10,18],"charger-004":[12,18],"charger-005":[14,18]};
var robotSpawn = {"w1":[2,1],"w2":[17,1],"charlie_01":[5,10],"charlie_02":[15,10],"alpha_02":[10,3],"delta_01":[10,15],"echo_01":[1,12],"echo_02":[18,12]};
var robotRoutes = {"Route_OuterPatrol":[[1,1],[18,1],[18,17],[1,17],[1,1]],"Route_EastWest_Shuttle":[[1,10],[18,10],[18,17],[1,17],[1,10]],"Route_CentralDelivery":[[10,3],[10,10],[3,10],[3,17],[10,17],[17,17],[17,10],[10,10],[10,3]],"Route_ChargingDrill":[[10,3],[10,17],[6,17],[14,17],[10,17],[10,3]]};
var robotToRoute = {"w1":"Route_OuterPatrol","w2":"Route_OuterPatrol","charlie_01":"Route_ChargingDrill","echo_02":"Route_ChargingDrill","alpha_02":"Route_EastWest_Shuttle","echo_01":"Route_EastWest_Shuttle","charlie_02":"Route_CentralDelivery","delta_01":"Route_CentralDelivery"};
var BOT_VENDOR = {"w1":"vendor_alpha","alpha_02":"vendor_alpha","w2":"vendor_bravo","charlie_01":"vendor_charlie","charlie_02":"vendor_charlie","delta_01":"vendor_delta","echo_01":"vendor_echo","echo_02":"vendor_echo"};
var VENDOR_CFG = {
  "vendor_alpha": { color: "#FF0080", drain_coeff: 1.00, init_min: 0.90, init_max: 1.00 },
  "vendor_bravo": { color: "#00E5FF", drain_coeff: 0.92, init_min: 0.95, init_max: 1.00 },
  "vendor_charlie": { color: "#FFD300", drain_coeff: 1.08, init_min: 0.88, init_max: 0.98 },
  "vendor_delta": { color: "#00FF55", drain_coeff: 1.15, init_min: 0.85, init_max: 0.93 },
  "vendor_echo": { color: "#AA00FF", drain_coeff: 0.98, init_min: 0.92, init_max: 1.00 }
};
var buildings = [[4,6,4,6],[13,15,4,6],[4,6,13,14],[13,15,13,14]];
var roadRects = [[1,18,1,1],[1,18,17,17],[1,1,1,17],[18,18,1,17],[10,10,1,17],[1,18,10,10]];
var parkRect = [6,13,12,15];
function isRoad(x,y){ return roadRects.some(function(r){ return x>=r[0]&&x<=r[1]&&y>=r[2]&&y<=r[3]; }); }
function isBuilding(x,y){ return buildings.some(function(b){ return x>=b[0]&&x<=b[1]&&y>=b[2]&&y<=b[3]; }); }
function isPark(x,y){ return x>=parkRect[0]&&x<=parkRect[1]&&y>=parkRect[2]&&y<=parkRect[3]; }
function getHazardStatus(x,y){
  var seg = cellId(x,y);
  if (isHazardSuppressed(seg)) return "";
  var local = localHazards[seg];
  if (local) return (local.hazard_status||"").toUpperCase();
  var h = (snapshot.hazards||[]).find(function(z){ return (z.segment_id||"") === seg; });
  return (h&&h.hazard_status) ? (h.hazard_status+"").toUpperCase() : "";
}
function isTempEventBlocked(seg){
  var until = tempEventBlocks[seg];
  if (!until) return false;
  if (Date.now() >= until) { delete tempEventBlocks[seg]; return false; }
  return true;
}
function isBlocked(x,y){
  var st = getHazardStatus(x,y);
  return isBuilding(x,y) || st === "HARD_BLOCKED" || st === "SOFT_BLOCKED" || isTempEventBlocked(cellId(x,y));
}
function cellCost(x,y){
  if (isBlocked(x,y)) return 99999;
  var st = getHazardStatus(x,y);
  if (st === "SOFT_BLOCKED") return 8;
  if (isRoad(x,y)) return 1;
  if (isPark(x,y)) return 3;
  return 2;
}
function bfs(from, to){
  var fx=from[0], fy=from[1], tx=to[0], ty=to[1];
  if (fx===tx&&fy===ty) return [];
  if (isBlocked(tx,ty)) return [];
  var dist = {}; var prev = {}; var key = function(a,b){ return a+","+b; };
  var q = [{x:fx,y:fy,c:0}]; dist[key(fx,fy)] = 0;
  var dx = [0,1,0,-1], dy = [1,0,-1,0];
  while (q.length) {
    var best = 0;
    for (var i = 1; i < q.length; i++) if (q[i].c < q[best].c) best = i;
    var u = q.splice(best, 1)[0]; var k = key(u.x,u.y);
    if (u.x===tx&&u.y===ty) {
      var path = []; var cx=tx, cy=ty;
      while (cx!==undefined) { path.unshift([cx,cy]); var p = prev[key(cx,cy)]; if (!p) break; cx=p[0]; cy=p[1]; }
      return path;
    }
    for (var d=0;d<4;d++) {
      var nx = u.x+dx[d], ny = u.y+dy[d];
      if (nx<0||nx>19||ny<0||ny>19) continue;
      if (isBlocked(nx,ny)) continue;
      var nk = key(nx,ny);
      var cost = u.c + cellCost(nx,ny);
      if (dist[nk] === undefined || cost < dist[nk]) { dist[nk]=cost; prev[nk]=[u.x,u.y]; q.push({x:nx,y:ny,c:cost}); }
    }
  }
  return [];
}

function log(level, msg){
  var t = new Date(); var ts = t.getHours().toString().padStart(2,"0")+":"+t.getMinutes().toString().padStart(2,"0")+":"+t.getSeconds().toString().padStart(2,"0");
  cmdLog.push({ts:ts,level:level,msg:msg});
  if (cmdLog.length > MAX_LOG) cmdLog.shift();
  var el = document.getElementById("cmdlog"); if (!el) return;
  var show = cmdLog.slice(-DISPLAY_LOG_LINES);
  el.textContent = "";
  show.forEach(function(e){ var row = document.createElement("div"); row.textContent = "["+e.ts+"] ["+e.level+"] "+e.msg; el.appendChild(row); });
  el.scrollTop = el.scrollHeight;
}
function hhmmssNow(){
  var t = new Date();
  return t.getHours().toString().padStart(2, "0") + ":" + t.getMinutes().toString().padStart(2, "0") + ":" + t.getSeconds().toString().padStart(2, "0");
}
function reasonTag(reason){
  var r = (reason || "intervention").toUpperCase();
  if (r === "LOW_BATTERY") return "battery_low";
  if (r === "CONFLICT_REROUTE") return "reserve_409";
  if (r === "HAZARD_AVOIDANCE") return "hazard_reroute";
  if (r === "CHARGED") return "charged";
  return r.toLowerCase();
}
function addIntervention(botId, reason, target, pathCells){
  var vid = BOT_VENDOR[botId] || "vendor_alpha";
  var color = (VENDOR_CFG[vid] && VENDOR_CFG[vid].color) || "#ffffff";
  var now = Date.now();
  var start = (botState[botId] && botState[botId].currentCell) ? botState[botId].currentCell.slice(0) : (robotSpawn[botId] || [0,0]);
  var p = [start].concat(Array.isArray(pathCells) ? pathCells.slice(0) : []);
  var tag = reasonTag(reason);
  interventionLines.push({ path: p, color: color, timestamp: now, reason: tag });
  if (interventionLines.length > 24) interventionLines = interventionLines.slice(-24);
  interventionFeed.push({ ts: hhmmssNow(), bot: botId || "—", reason: tag, target: target || "—" });
  if (interventionFeed.length > 20) interventionFeed = interventionFeed.slice(-20);
  pushNarrative("Intervention [" + (botId||"—") + "] " + tag + " -> " + (target||"—"));
  showToast("JoyGate intervention: " + tag, false);
  updateCards();
}
function pauseAllBots(ms){
  var now = Date.now();
  Object.keys(botState).forEach(function(id){
    var b = botState[id]; if (!b) return;
    var start = b.moveStartMs || now;
    b.moveStartMs = Math.max(start, now) + (ms || 200);
  });
}
function markEvent(cell, text, ms, color){
  if (!cell) return;
  eventMarks.push({ cell: [cell[0], cell[1]], text: text || "EVENT", untilMs: Date.now() + (ms || 3000), color: color || "rgba(20,20,20,0.75)" });
}

function godHeaders(){ return (isGodMode && godToken) ? { "X-JoyGate-God": godToken } : {}; }
function postJson(url, obj, extra){
  var headers = Object.assign({ "Content-Type": "application/json" }, godHeaders(), extra || {});
  return fetch(url, { method: "POST", body: JSON.stringify(obj), credentials: "include", headers: headers }).then(function(r){ if (r.status === 403) log("WARN", "missing/invalid god token"); return r; });
}

function poll(url, name, onOk, onBackoff){
  fetch(url, { credentials: "include" }).then(function(r){
    if (r.status === 429 || r.status === 503){ intervals[name] = Math.min(60000, (intervals[name]||baseIntervals[name])*2); log("WARN", "backoff " + name + " " + r.status + " interval " + intervals[name]); if (onBackoff) onBackoff(); return; }
    if (!r.ok) { var lvl = (r.status >= 500) ? "ERROR" : "WARN"; r.text().then(function(t){ log(lvl, "GET " + url + " " + r.status + (t ? " " + (t.slice(0,80)) : "")); }); if (onBackoff) onBackoff(); return; }
    intervals[name] = baseIntervals[name];
    return r.json().then(onOk);
  }).catch(function(e){ log("WARN", "GET " + url + " failed"); if (onBackoff) onBackoff(); });
}

function recomputeAllPaths(){
  Object.keys(botState).forEach(function(id){
    var b = botState[id]; if (!b) return;
    var cur = b.currentCell ? [b.currentCell[0],b.currentCell[1]] : (robotSpawn[id]||[0,0]);
    var path = [];
    if (b.mode === "TO_CHARGER" || b.mode === "REROUTE") {
      var cid = b.targetChargerId; if (!cid || !chargerCells[cid]) return;
      path = bfs(cur, chargerCells[cid]);
    } else {
      var r = robotRoutes[robotToRoute[id]]; if (!r) return;
      var wpIdx = (b.routeWaypointIndex|0) % r.length;
      var tgt = r[wpIdx];
      path = bfs(cur, tgt);
    }
    b.pathCells = path && path.length ? path.slice(1) : [];
    if (b.pathCells.length) b.nextCell = b.pathCells[0]; else b.nextCell = cur;
    b.moveStartMs = Date.now();
  });
}
function runPolling(){
  if (capacityReached) { setTimeout(runPolling, 60000); return; }
  function doSnapshot(){
    if (demoStrictMode) { setTimeout(doSnapshot, intervals.snapshot); return; }
    poll("/v1/snapshot","snapshot",function(d){
      var currH = ((d&&d.hazards)||[]).filter(function(z){ return !isHazardSuppressed((z && z.segment_id) || ""); });
      var prevMap = {}; (prevHazards||[]).forEach(function(z){ var s = (z.segment_id||""); if (s) prevMap[s] = (z.hazard_status||"").toUpperCase(); });
      var currMap = {}; currH.forEach(function(z){ var s = (z.segment_id||""); if (s) currMap[s] = (z.hazard_status||"").toUpperCase(); });
      var hazardChanged = false;
      var allSegs = {};
      Object.keys(prevMap).forEach(function(s){ allSegs[s]=1; });
      Object.keys(currMap).forEach(function(s){ allSegs[s]=1; });
      for (var seg in allSegs) { if (prevMap[seg] !== currMap[seg]) { log("INFO", "hazard " + seg + " " + (prevMap[seg]||"") + " -> " + (currMap[seg]||"")); hazardChanged = true; } }
      prevHazards = currH.slice(0);
      snapshot = d || snapshot;
      snapshot.hazards = currH;
      if (hazardChanged) recomputeAllPaths();
      redraw();
    });
    setTimeout(doSnapshot, intervals.snapshot);
  }
  function doIncidents(){ if (demoStrictMode) { setTimeout(doIncidents, intervals.incidents); return; } poll("/v1/incidents","incidents",function(d){ incidents = (d&&d.incidents)||[]; updateCards(); }); setTimeout(doIncidents, intervals.incidents); }
  function doAudit(){ if (demoStrictMode) { setTimeout(doAudit, intervals.audit); return; } poll("/v1/audit/ledger","audit",function(d){ audit = d || audit; updateCards(); }); setTimeout(doAudit, intervals.audit); }
  function doPolicy(){ if (demoStrictMode) { setTimeout(doPolicy, intervals.policy); return; } poll("/v1/policy","policy",function(d){ policy = d || policy; updateCards(); }); setTimeout(doPolicy, intervals.policy); }
  doSnapshot(); doIncidents(); doAudit(); doPolicy();
}

function setText(el, text){ el.textContent = text || ""; }
function updateCards(){
  var h = (snapshot.hazards || []).concat(Object.keys(localHazards).map(function(k){ return localHazards[k]; }));
  var inc = incidents;
  var n = (incidents||[]).length;
  var openCount = inc.filter(function(i){ return (i.incident_status||"").toUpperCase() === "OPEN"; }).length;
  var status = capacityReached ? "capacity reached" : "ONLINE";
  var incEl = document.getElementById("incidents"); incEl.textContent = ""; inc.slice(0,10).forEach(function(i){ var line = document.createElement("div"); line.textContent = (i.incident_id||"—") + " " + (i.incident_type||"—") + " " + (i.incident_status||"—"); incEl.appendChild(line); }); if (inc.length === 0) { var line = document.createElement("div"); line.textContent = "—"; incEl.appendChild(line); }
  var hardCnt = h.filter(function(z){ return ((z.hazard_status||"")+"").toUpperCase() === "HARD_BLOCKED"; }).length;
  var softCnt = h.filter(function(z){ return ((z.hazard_status||"")+"").toUpperCase() === "SOFT_BLOCKED"; }).length;
  var openHazCnt = h.filter(function(z){ return ((z.hazard_status||"")+"").toUpperCase() === "OPEN"; }).length;
  var hazEl = document.getElementById("hazards");
  hazEl.textContent = "";
  var desc = document.createElement("div");
  desc.textContent = "Purpose: segment risk and policy snapshot. SOFT=pending verification, HARD=confirmed blocked, OPEN=recovered.";
  hazEl.appendChild(desc);
  var sum = document.createElement("div");
  sum.textContent = "counts: HARD=" + hardCnt + " SOFT=" + softCnt + " OPEN=" + openHazCnt;
  hazEl.appendChild(sum);
  h.slice(0,15).forEach(function(z){ var line = document.createElement("div"); line.textContent = (z.segment_id||"—") + " " + (z.hazard_status||"—"); hazEl.appendChild(line); });
  if (h.length === 0) { var line = document.createElement("div"); line.textContent = "hazards: none"; hazEl.appendChild(line); }
  var pInfo = document.createElement("div");
  var pKeys = Object.keys(policy || {});
  pInfo.textContent = "policy: " + (pKeys.length ? pKeys.slice(0,6).join(", ") : "none");
  hazEl.appendChild(pInfo);
  var dec = (audit.decisions)||[]; var ev = (audit.sidecar_safety_events)||[];
  var auditText = "decisions: " + dec.length + ", sidecar_safety_events: " + ev.length;
  if (recentAuditNotes.length) auditText += "\n" + recentAuditNotes.join("\n");
  setText(document.getElementById("audit"), auditText);
  var ivEl = document.getElementById("interventions");
  if (ivEl) {
    ivEl.textContent = "";
    var last = interventionFeed.slice(-5).reverse();
    if (!last.length) {
      ivEl.textContent = "—";
    } else {
      last.forEach(function(it){
        var d = document.createElement("div");
        d.textContent = "[" + it.ts + "] [" + it.bot + "] [" + it.reason + "] -> " + it.target;
        ivEl.appendChild(d);
      });
    }
  }
}

var canvas = document.getElementById("canv"); var ctx = canvas.getContext("2d"); var W = 400; var H = 400; var CS = Math.min(W,H)/20;
var offStatic = null;
function resizeCanvas(){
  var parent = canvas.parentElement;
  var size = Math.floor(Math.max(320, Math.min(parent ? parent.clientWidth : 400, parent ? parent.clientHeight : 400)));
  var dpr = window.devicePixelRatio || 1;
  canvas.style.width = size + "px";
  canvas.style.height = size + "px";
  canvas.width = size * dpr;
  canvas.height = size * dpr;
  ctx.scale(dpr, dpr);
  W = size; H = size; CS = size / 20;
  offStatic = null;
}
function drawStatic(){
  var dpr = window.devicePixelRatio || 1;
  if (offStatic) { ctx.drawImage(offStatic,0,0,W,H); return; }
  offStatic = document.createElement("canvas");
  offStatic.width = W * dpr;
  offStatic.height = H * dpr;
  var c = offStatic.getContext("2d");
  c.scale(dpr, dpr);
  for (var y = 0; y < 20; y++) for (var x = 0; x < 20; x++) {
    var px = x*CS; var py = y*CS;
    if (isBuilding(x,y)) { c.fillStyle = "#c4b8a8"; c.fillRect(px,py,CS,CS); c.strokeRect(px,py,CS,CS); }
    else if (isPark(x,y)) { c.fillStyle = "rgba(180,220,180,0.5)"; c.fillRect(px,py,CS,CS); }
    else if (isRoad(x,y)) { c.fillStyle = "#e8e4dc"; c.fillRect(px,py,CS,CS); }
    else { c.fillStyle = "#f0ede8"; c.fillRect(px,py,CS,CS); }
    c.strokeStyle = "#ddd"; c.strokeRect(px,py,CS,CS);
  }
  c.fillStyle = "#6f655b"; c.font = "bold 10px sans-serif";
  c.fillText("ADMIN", 3.2*CS, 3.8*CS);
  c.fillText("LAB", 13.1*CS, 4.2*CS);
  c.fillText("WH-A", 3.1*CS, 11.8*CS);
  c.fillText("WH-B", 13.1*CS, 11.8*CS);
  c.fillStyle = "#5e8f5a"; c.fillText("CENTRAL PARK", 7.1*CS, 7.6*CS);
  ctx.drawImage(offStatic,0,0,W,H);
}
function isChargerRealOccupied(id){
  var holds = (snapshot.holds||[]).map(function(h){ return (h.resource_id || h.charger_id||"").trim(); });
  if (holds.indexOf(id) >= 0) return true;
  return (snapshot.chargers||[]).some(function(c){ var cid = (c.charger_id||c.id||"").trim(); if (cid !== id) return false; var st = (c.slot_state||"").toUpperCase(); return st !== "" && st !== "FREE"; });
}
function drawChargers(){
  var now = Date.now();
  var holds = (snapshot.holds||[]).map(function(h){ return (h.resource_id || h.charger_id||"").trim(); });
  for (var id in chargerCells) {
    var p = chargerCells[id];
    var ov = chargerOverrides[id];
    var realOccupied = holds.indexOf(id) >= 0 || (snapshot.chargers||[]).some(function(c){ var cid = (c.charger_id||c.id||"").trim(); if (cid !== id) return false; var st = (c.slot_state||"").toUpperCase(); return st !== "" && st !== "FREE"; });
    if (realOccupied && ov) { delete chargerOverrides[id]; log("INFO", "charger override cleared (real state) " + id); }
    var useOverride = ov && (ov.expiresAtMs > now);
    var occupied = realOccupied || (useOverride ? (ov.state === "OCCUPIED") : false);
    var hi = chargerFlashUntil[id] && chargerFlashUntil[id] > now;
    ctx.fillStyle = occupied ? "rgba(100,100,100,0.8)" : "#4a90d9";
    ctx.beginPath(); ctx.arc((p[0]+0.5)*CS,(p[1]+0.5)*CS,CS*0.45,0,6.28); ctx.fill();
    if (hi) {
      ctx.strokeStyle = "rgba(255,70,70,0.95)";
      ctx.lineWidth = 3;
      ctx.beginPath(); ctx.arc((p[0]+0.5)*CS,(p[1]+0.5)*CS,CS*0.44,0,6.28); ctx.stroke();
    }
    ctx.fillStyle = "#000"; ctx.textAlign = "center"; ctx.font = "10px sans-serif"; ctx.fillText(id, (p[0]+0.5)*CS, (p[1]+1)*CS);
  }
}
function drawHazards(){
  var h = (snapshot.hazards || []).concat(Object.keys(localHazards).map(function(k){ return localHazards[k]; }));
  h.forEach(function(z){
    if (isHazardSuppressed(z.segment_id || "")) return;
    var p = parseCell(z.segment_id); if (!p) return;
    var px = p[0]*CS, py = p[1]*CS;
    var st = (z.hazard_status||"").toUpperCase();
    if (st === "HARD_BLOCKED") { ctx.fillStyle = "rgba(200,80,80,0.6)"; ctx.fillRect(px,py,CS,CS); ctx.strokeStyle = "#a55"; for (var i = 0; i < 4; i++) ctx.strokeRect(px+i*2,py,CS-i*4,CS); }
    else if (st === "SOFT_BLOCKED") { ctx.fillStyle = "rgba(255,230,150,0.7)"; ctx.fillRect(px,py,CS,CS); ctx.strokeRect(px,py,CS,CS); }
    else if (st === "OPEN") { ctx.fillStyle = "rgba(150,200,150,0.2)"; ctx.fillRect(px,py,CS,CS); }
  });
}
function drawFreshness(){
  var sig = snapshot.segment_passed_signals || [];
  sig.forEach(function(s){
    var p = parseCell(s.segment_id); if (!p) return;
    ctx.fillStyle = "rgba(100,200,255,0.25)"; ctx.fillRect(p[0]*CS,p[1]*CS,CS,CS);
  });
}
function drawRobotsDerived(){
  var sig = snapshot.segment_passed_signals || [];
  sig.forEach(function(s){
    var p = parseCell(s.segment_id); if (!p) return;
    var j = s.joykey || "—";
    ctx.strokeStyle = "rgba(80,80,200,0.7)"; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc((p[0]+0.5)*CS,(p[1]+0.5)*CS,CS*0.22,0,6.28); ctx.stroke();
    ctx.font = "9px sans-serif"; ctx.fillStyle = "#333"; ctx.fillText(j.slice(0,6), p[0]*CS, (p[1]+0.5)*CS);
  });
  var now = Date.now();
  var bySlot = {};
  Object.keys(robotToRoute).forEach(function(id){
    var s = botState[id] || {};
    var cur = s.currentCell || robotSpawn[id] || [0,0];
    var nxt = s.nextCell || cur;
    var startMs = s.moveStartMs || now;
    var dur = (s.moveDurationMs !== undefined) ? s.moveDurationMs : MOVE_DURATION_MS;
    var lerpT = (cur[0]===nxt[0] && cur[1]===nxt[1]) ? 1 : Math.min(1, (now - startMs) / dur);
    var cellX = cur[0] + (nxt[0]-cur[0])*lerpT;
    var cellY = cur[1] + (nxt[1]-cur[1])*lerpT;
    var slotKey = Math.round(cellX)+","+Math.round(cellY);
    if (!bySlot[slotKey]) bySlot[slotKey] = [];
    bySlot[slotKey].push({ id: id, s: s, cellX: cellX, cellY: cellY });
  });
  Object.keys(bySlot).forEach(function(slotKey){
    var list = bySlot[slotKey];
    var n = list.length;
    list.forEach(function(item, idx){
      var id = item.id, s = item.s, cellX = item.cellX, cellY = item.cellY;
      var baseX = (cellX+0.5)*CS, baseY = (cellY+0.5)*CS;
      var offX = 0, offY = 0;
      if (n > 1) {
        var angle = (idx / n) * 6.28;
        offX = Math.cos(angle) * CS * 0.18;
        offY = Math.sin(angle) * CS * 0.18;
      }
      var x = baseX + offX, y = baseY + offY;
      var vid = BOT_VENDOR[id] || "vendor_alpha";
      var cfg = VENDOR_CFG[vid] || VENDOR_CFG.vendor_alpha;
      ctx.fillStyle = s.negotiating ? "#b8860b" : cfg.color;
      ctx.beginPath(); ctx.arc(x,y,CS*0.35,0,6.28); ctx.fill();
      ctx.fillStyle = "#fff"; ctx.textAlign = "center"; ctx.font = "9px sans-serif"; ctx.fillText((id+"").slice(0,4), x, y+3);
      var bat = (s.battery !== undefined && s.battery !== null) ? s.battery : 1;
      var pct = Math.round(bat * 100);
      ctx.fillStyle = pct < 25 ? "#e00" : pct < 50 ? "#ea0" : "#2a2";
      ctx.font = "10px sans-serif"; ctx.fillText(pct+"%", x, y+CS*0.42);
    });
  });
}
function drawGuideLines(){
  Object.keys(botState).forEach(function(id){
    var b = botState[id]; if (!b || !b.currentCell) return;
    var pts = [b.currentCell].concat((b.pathCells||[]).slice(0, 8));
    if (pts.length < 2) return;
    var vid = BOT_VENDOR[id] || "vendor_alpha";
    var cfg = VENDOR_CFG[vid] || VENDOR_CFG.vendor_alpha;
    ctx.save();
    ctx.strokeStyle = cfg.color;
    ctx.globalAlpha = 0.28;
    ctx.lineWidth = 2;
    if (ctx.setLineDash) ctx.setLineDash([6, 6]);
    ctx.beginPath();
    ctx.moveTo((pts[0][0]+0.5)*CS, (pts[0][1]+0.5)*CS);
    for (var i = 1; i < pts.length; i++) ctx.lineTo((pts[i][0]+0.5)*CS, (pts[i][1]+0.5)*CS);
    ctx.stroke();
    if (ctx.setLineDash) ctx.setLineDash([]);
    ctx.restore();
  });
}
function drawInterventionLines(){
  var now = Date.now();
  interventionLines = interventionLines.filter(function(it){ return now - it.timestamp < 5000; });
  interventionLines.forEach(function(it){
    if (!it.path || it.path.length < 2) return;
    ctx.save();
    ctx.strokeStyle = it.color || "#ffffff";
    ctx.lineWidth = 4;
    ctx.shadowColor = it.color || "#ffffff";
    ctx.shadowBlur = 10;
    ctx.beginPath();
    ctx.moveTo((it.path[0][0]+0.5)*CS, (it.path[0][1]+0.5)*CS);
    for (var i = 1; i < it.path.length; i++) ctx.lineTo((it.path[i][0]+0.5)*CS, (it.path[i][1]+0.5)*CS);
    ctx.stroke();
    var last = it.path[it.path.length - 1];
    var tx = (last[0]+0.5)*CS + 5;
    var ty = (last[1]+0.5)*CS - 6;
    var reason = (it.reason || "intervention").toLowerCase();
    ctx.shadowBlur = 0;
    ctx.fillStyle = "rgba(20,20,20,0.85)";
    ctx.fillRect(tx - 2, ty - 10, Math.max(42, reason.length * 6), 12);
    ctx.fillStyle = "#fff";
    ctx.font = "10px sans-serif";
    ctx.fillText(reason, tx, ty);
    ctx.restore();
  });
}
function drawFlashMarks(){
  var now = Date.now();
  flashMarks = flashMarks.filter(function(f){ return now < f.untilMs; });
  flashMarks.forEach(function(f){
    var p = f.cell; if (!p) return;
    var alpha = 0.45 + 0.35 * Math.sin(now * 0.02);
    ctx.strokeStyle = "rgba(255,40,40," + alpha + ")";
    ctx.lineWidth = 3;
    ctx.strokeRect(p[0]*CS, p[1]*CS, CS, CS);
  });
}
function drawEventMarks(){
  var now = Date.now();
  eventMarks = eventMarks.filter(function(m){ return now < m.untilMs; });
  eventMarks.forEach(function(m){
    var p = m.cell; if (!p) return;
    ctx.fillStyle = m.color;
    ctx.fillRect(p[0]*CS, p[1]*CS, CS, CS);
    ctx.fillStyle = "#fff";
    ctx.font = "bold 9px sans-serif";
    ctx.textAlign = "center";
    ctx.fillText((m.text||"EVENT").slice(0, 10), (p[0]+0.5)*CS, (p[1]+0.62)*CS);
  });
}
function drawVoteHints(){
  var now = Date.now();
  voteHints = voteHints.filter(function(v){ return now < v.untilMs; });
  voteHints.forEach(function(v){
    var p = v.cell; if (!p) return;
    var cx = (p[0]+0.5)*CS, cy = (p[1]+0.5)*CS;
    var pulse = 0.2 + 0.8 * Math.abs(Math.sin(now * 0.015));
    ctx.save();
    ctx.strokeStyle = "rgba(255,225,70," + (0.35 + pulse * 0.45) + ")";
    ctx.lineWidth = 3;
    ctx.beginPath(); ctx.arc(cx, cy, CS*(0.34 + 0.08*pulse), 0, 6.28); ctx.stroke();
    ctx.strokeStyle = "rgba(255,255,255," + (0.18 + pulse * 0.35) + ")";
    ctx.lineWidth = 1.5;
    ctx.beginPath(); ctx.arc(cx, cy, CS*(0.23 + 0.06*pulse), 0, 6.28); ctx.stroke();
    ctx.fillStyle = "rgba(20,20,20,0.80)";
    var text = (v.who || "witness") + " vote";
    ctx.fillRect(cx - 22, cy - CS*0.55, Math.max(44, text.length * 5.6), 11);
    ctx.fillStyle = "#fff";
    ctx.font = "9px sans-serif";
    ctx.fillText(text, cx - 20, cy - CS*0.28);
    ctx.restore();
  });
}
function isChargerHeld(cid){
  return (snapshot.holds||[]).some(function(h){
    var x = (h.resource_id || h.charger_id || "").trim();
    return x === cid;
  });
}
function hasBotHeadingToCharger(cid){
  return Object.keys(botState).some(function(id){
    var b = botState[id]; if (!b) return false;
    return (b.mode === "TO_CHARGER" || b.mode === "REROUTE" || b.mode === "CHARGING") && b.targetChargerId === cid;
  });
}
function nearestFreeCharger(cur){
  var best = null; var bestLen = 1e9;
  Object.keys(chargerCells).forEach(function(cid){
    if (isChargerHeld(cid)) return;
    if (isChargerRealOccupied(cid)) return;
    if (hasBotHeadingToCharger(cid)) return;
    var p = chargerCells[cid];
    var path = bfs(cur, p);
    if (path && path.length && path.length < bestLen) { bestLen = path.length; best = { cid: cid, path: path }; }
  });
  return best;
}
function botLogicTick(){
  var now = Date.now();
  var dtSec = BOT_TICK_MS / 1000;
  Object.keys(robotToRoute).forEach(function(id){
    var b = botState[id]; if (!b) return;
    if (b.negotiating) return;
    var vid = BOT_VENDOR[id] || "vendor_alpha";
    var cfg = VENDOR_CFG[vid] || VENDOR_CFG.vendor_alpha;
    if (b.battery === undefined || b.battery === null) {
      b.battery = Math.random() * ((cfg.init_max || 1) - (cfg.init_min || 0.9)) + (cfg.init_min || 0.9);
    }
    if (b.mode === "CHARGING") {
      b.battery = Math.min(1.0, (b.battery || 0) + CHARGE_RATE * dtSec);
      if (b.battery >= 0.98) {
        b.mode = "PATROL";
        addIntervention(id, "CHARGED", "patrol", []);
      }
      return;
    } else {
      b.battery = Math.max(0, (b.battery || 0) - dtSec * BASE_DRAIN * (cfg.drain_coeff || 1));
      if (b.battery < 0.20 && (b.mode === "PATROL" || b.mode === "IDLE")) {
        var cur0 = b.currentCell || robotSpawn[id] || [0,0];
        var best = nearestFreeCharger(cur0);
        if (best && best.cid) {
          b.mode = "TO_CHARGER";
          b.targetChargerId = best.cid;
          b.pathCells = best.path.slice(1);
          b.nextCell = b.pathCells[0] ? [b.pathCells[0][0], b.pathCells[0][1]] : cur0.slice(0);
          b.moveStartMs = now;
          addIntervention(id, "LOW_BATTERY", best.cid, b.pathCells.slice(0, 10));
          markEvent(cur0, "LOW_BAT", 2200, "rgba(35,35,35,0.65)");
          if (!b.lowBatteryNoted) {
            b.lowBatteryNoted = true;
            pushNarrative("JoyGate suggests recharge: " + id + " -> " + best.cid + " (battery_low)");
            showToast("JoyGate suggests recharge " + id, true);
          }
        }
      }
      if (b.battery >= 0.25) b.lowBatteryNoted = false;
    }
    var cur = b.currentCell || robotSpawn[id] || [0,0];
    var nxt = b.nextCell || cur;
    var startMs = b.moveStartMs || now;
    var dur = (b.moveDurationMs !== undefined) ? b.moveDurationMs : MOVE_DURATION_MS;
    if (now - startMs < dur) return;
    b.currentCell = [nxt[0],nxt[1]];
    b.moveStartMs = now;
    if (b.pathCells && b.pathCells.length) {
      if (!isBlocked(b.pathCells[0][0], b.pathCells[0][1])) {
      b.pathCells.shift();
      b.nextCell = b.pathCells[0] ? [b.pathCells[0][0],b.pathCells[0][1]] : b.currentCell;
      } else {
        // Hazard/blocked reroute intervention.
        var target = b.pathCells[b.pathCells.length - 1] || b.currentCell;
        var alt = bfs(b.currentCell, target);
        b.pathCells = alt && alt.length ? alt.slice(1) : [];
        b.nextCell = b.pathCells[0] ? [b.pathCells[0][0], b.pathCells[0][1]] : b.currentCell.slice(0);
        addIntervention(id, "HAZARD_AVOIDANCE", cellId(target[0], target[1]), b.pathCells.slice(0, 10));
      }
    } else {
      b.nextCell = [b.currentCell[0],b.currentCell[1]];
if (b.mode === "TO_CHARGER" || b.mode === "REROUTE") {
          var cid = b.targetChargerId; var pc = chargerCells[cid];
          if (pc && b.currentCell[0]===pc[0] && b.currentCell[1]===pc[1]) { b.mode = "CHARGING"; onArrivedAtCharger(id); return; }
          var path = bfs(b.currentCell, pc);
          b.pathCells = path && path.length ? path.slice(1) : [];
          b.nextCell = b.pathCells[0] ? [b.pathCells[0][0],b.pathCells[0][1]] : b.currentCell;
          b.moveStartMs = now;
        } else {
          var r = robotRoutes[robotToRoute[id]]; if (!r) return;
          b.routeWaypointIndex = ((b.routeWaypointIndex|0)+1) % r.length;
          var tgt = r[b.routeWaypointIndex];
          var path = bfs(b.currentCell, tgt);
          b.pathCells = path && path.length ? path.slice(1) : [];
          b.nextCell = b.pathCells[0] ? [b.pathCells[0][0],b.pathCells[0][1]] : b.currentCell;
          b.moveStartMs = now;
        }
    }
  });
  saveState();
}
function onArrivedAtCharger(botId){
  var b = botState[botId]; if (!b) return;
  var cid = b.targetChargerId || "charger-001";
  b.negotiating = true;
  log("INFO", "bot " + botId + " arrived at " + cid + ", Negotiating...");
  setTimeout(function(){
    if (!isGodMode) { b.negotiating = false; return; }
    postJson("/v1/reserve", { resource_type: "charger", resource_id: cid, joykey: botId, action: "HOLD" })
      .then(function(r){
        return r.text().then(function(t){
          var d = null; try { d = t ? JSON.parse(t) : null; } catch(e) {}
          log("INFO", "POST /v1/reserve " + r.status + (d&&d.hold_id ? " hold_id="+d.hold_id : ""));
          b.negotiating = false;
          if (r.status === 400) { log("WARN", "reserve action mismatch"); return; }
          if (r.status === 200 && d && d.hold_id) {
            b.mode = "CHARGING";
            markEvent(chargerCells[cid], "CHARGING", 2500, "rgba(50,150,50,0.50)");
            return;
          }
          if (r.status === 409) {
            chargerOverrides[cid] = { state: "OCCUPIED", expiresAtMs: Date.now() + 4000 };
            chargerFlashUntil[cid] = Date.now() + 3000;
            markEvent(chargerCells[cid], "409", 2200, "rgba(180,60,60,0.55)");
            flashMarks.push({ cell: [chargerCells[cid][0], chargerCells[cid][1]], untilMs: Date.now() + 2400 });
            log("INFO", "charger visual override applied " + cid);
            pushNarrative("reserve_409 at " + cid + ", JoyGate suggests reroute");
            showToast("409 conflict, reroute suggested", true);
            setTimeout(function(){
              postJson("/v1/incidents/report_blocked", { charger_id: cid, incident_type: "BLOCKED_BY_OTHER" })
                .then(function(r2){ log("INFO", "POST /v1/incidents/report_blocked " + r2.status); });
            }, 250);
            var order = ["charger-001","charger-002","charger-003","charger-004","charger-005"];
            var idx = order.indexOf(cid);
            for (var i=1;i<=5;i++) {
              var nextId = order[(idx+i)%5];
              if (isChargerRealOccupied(nextId)) continue;
              if (chargerOverrides[nextId] && chargerOverrides[nextId].expiresAtMs > Date.now()) continue;
              b.targetChargerId = nextId;
              b.mode = "REROUTE";
              b.moveStartMs = Date.now();
              var path = bfs(b.currentCell, chargerCells[nextId]);
              b.pathCells = path && path.length ? path.slice(1) : [];
              b.nextCell = b.pathCells[0] ? [b.pathCells[0][0],b.pathCells[0][1]] : b.currentCell;
              addIntervention(botId, "CONFLICT_REROUTE", nextId, b.pathCells.slice(0, 10));
              pushNarrative("reroute target: " + botId + " -> " + nextId + " (reserve_409)");
              break;
            }
          }
        });
      }).catch(function(){ log("WARN", "reserve failed"); b.negotiating = false; });
  }, 1000);
}
function drawSelection(){
  // Intentionally disabled: red selection border removed for clarity.
  return;
}
function redraw(){
  drawStatic();
  drawChargers();
  drawFreshness();
  drawHazards();
  drawGuideLines();
  drawRobotsDerived();
  drawFlashMarks();
  drawVoteHints();
  drawEventMarks();
  drawInterventionLines();
  drawSelection();
}

canvas.addEventListener("click", function(e){
  var rect = canvas.getBoundingClientRect(); var sx = (e.clientX - rect.left) * (canvas.width/rect.width); var sy = (e.clientY - rect.top) * (canvas.height/rect.height);
  var x = Math.floor(sx/CS); var y = Math.floor(sy/CS);
  if (x>=0&&x<20&&y>=0&&y<20) { selectedCell = [x,y]; redraw(); }
});

function doBootstrap(){
  fetch("/bootstrap", { credentials: "include" }).then(function(r){
    if (!r.ok) { log("ERROR", "bootstrap failed " + r.status); return; }
    return r.json().then(function(d){
      sandboxId = (d&&d.sandbox_id) || "anon";
      if ((d&&d.sandbox_id) === null) { capacityReached = true; log("WARN", "bootstrap sandbox_id null (capacity reached)"); pushNarrative("System capacity reached, retry later"); loadState(); initBots(); updateCards(); updateGodUiState(); setTimeout(runPolling, 60000); return; }
      loadState(); initBots(); runPolling(); updateCards(); updateGodUiState();
      pushNarrative("System ready in " + (isGodMode ? "God Mode" : "Judge Mode"));
      pushNarrative("Use Run Judge Demo for A->B->C->D storyline");
    });
  }).catch(function(e){ log("ERROR", "bootstrap " + e); });
}

function scheduleFiveSecondResolution(seg, cell){
  if (demoStrictMode) return;
  setTimeout(function(){
    var rt = eventRuntimeBySeg[seg];
    if (rt && rt.resolved) return;
    if (!rt || !rt.voteStarted) {
      pushNarrative("No witness vote started within 1-cell, keep SOFT blocked");
      return;
    }
    var st = getHazardStatus(cell[0], cell[1]);
    var unresolved = isTempEventBlocked(seg) || st === "SOFT_BLOCKED" || st === "HARD_BLOCKED";
    if (!unresolved) return;
    var successVotes = (rt && typeof rt.successVotes === "number") ? rt.successVotes : 0;
    if (st === "HARD_BLOCKED" || successVotes >= 2) {
      pushNarrative("5s unresolved -> trigger human handling");
      showToast("5s timeout, human handling", true);
      postJson("/v1/work_orders/report", {
        work_order_id: "wo_timeout_" + Date.now() + "_" + seg,
        work_order_status: "DONE",
        segment_id: seg,
        event_occurred_at: new Date().toISOString()
      }).then(function(r){
        log(r.ok ? "INFO" : "WARN", "POST /v1/work_orders/report " + r.status + " (timeout path)");
        markEvent(cell, "HUMAN_FIX", 1800, "rgba(60,160,80,0.55)");
        if (r.ok) {
          if (rt) rt.resolved = true;
          upsertLocalHazard(seg, "OPEN");
          recomputeAllPaths();
        }
      });
      return;
    }
    pushNarrative("5s unresolved -> trigger AI audit");
    showToast("5s timeout, AI audit", true);
    var inc = incidents.filter(function(i){ return (i.incident_status||"").toUpperCase() === "OPEN"; })[0];
    if (inc && inc.incident_id) {
      postJson("/v1/ai/vision_audit", { incident_id: inc.incident_id }).then(function(r){
        log(r.status===202 ? "INFO" : "WARN", "POST /v1/ai/vision_audit " + r.status + " (timeout path)");
        pushAuditNote("AI audit reason: unresolved after 5s | incident_id=" + inc.incident_id + " | status=" + r.status);
      });
    } else {
      pushAuditNote("AI audit reason: unresolved after 5s | no OPEN incident");
    }
    markEvent(cell, "AI_AUDIT", 2200, "rgba(95,75,180,0.55)");
    if (rt) rt.resolved = true;
    upsertLocalHazard(seg, "OPEN");
    recomputeAllPaths();
  }, 5000);
}

// God buttons — all check isGodMode and godToken before any POST
function doObstacle(){
  if (!isGodMode) return;
  var cell = selectedCell || [9,9]; var seg = cellId(cell[0], cell[1]);
  var minDistReq = demoStrictMode ? 1 : EVENT_MIN_ROBOT_DIST;
  if (!isCellFarFromAllBots(cell, minDistReq)) { log("WARN", "Event rejected: too close to robots"); showToast("Event too close to robots", true); return; }
  pauseAllBots(EVENT_PRE_FREEZE_MS);
  markEvent(cell, "OBSTACLE", 3000, "rgba(200,60,60,0.55)");
  flashMarks.push({ cell: [cell[0], cell[1]], untilMs: Date.now() + 3000 });
  tempEventBlocks[seg] = Date.now() + EVENT_CLEAR_MS;
  eventRuntimeBySeg[seg] = { startedAt: Date.now(), candidateVotes: 0, successVotes: 0, voteStarted: false, clearScheduled: false, resolved: false };
  upsertLocalHazard(seg, "SOFT_BLOCKED");
  pushNarrative("Hazard state -> SOFT_BLOCKED @" + seg);
  pushNarrative("Step A: obstacle detected at " + seg + ", witness voting starts");
  showToast("Obstacle detected, witnesses voting", true);
  // Demo mode keeps anchor positions; no sudden witness teleport around obstacle.
  var keys = getNearbyWitnesses(cell);
  eventRuntimeBySeg[seg].candidateVotes = keys.length;
  if (!keys.length) {
    pushNarrative("No nearby witness within 1-cell, keep SOFT_BLOCKED and wait for manual trigger");
    pushAuditNote("AI audit skipped: witness count=0 within 1-cell");
    return;
  }
  var idx = 0;
  setTimeout(function(){
    function sendOne(){
      if (idx >= keys.length) return;
      var who = keys[idx];
      if (demoStrictMode) {
        if (!isWitnessWithinOneCell(who, cell)) { idx++; setTimeout(sendOne, 220); return; }
        if (eventRuntimeBySeg[seg]) { eventRuntimeBySeg[seg].voteStarted = true; }
        ensureEventClearScheduled(seg);
        addVoteHint(who, cell);
        pushNarrative(who + " vote -> BLOCKED @" + seg);
        showToast(who + " vote", false);
        if (eventRuntimeBySeg[seg]) eventRuntimeBySeg[seg].successVotes += 1;
        idx++;
        setTimeout(sendOne, 220);
        return;
      }
      postJson("/v1/witness/segment_respond", { segment_id: seg, segment_state: "BLOCKED", points_event_id: "pe_ui_"+Date.now()+"_"+idx }, { "X-JoyKey": who })
        .then(function(r){
          log(r.status>=400?"WARN":"INFO", "POST /v1/witness/segment_respond " + r.status);
          if (r.status === 403) { log("WARN", "witness allowlist mismatch"); return; }
          if (r.ok) {
            if (!isWitnessWithinOneCell(who, cell)) { idx++; setTimeout(sendOne, 250); return; }
            if (eventRuntimeBySeg[seg]) { eventRuntimeBySeg[seg].voteStarted = true; }
            ensureEventClearScheduled(seg);
            addVoteHint(who, cell);
            pushNarrative(who + " vote -> BLOCKED @" + seg);
            showToast(who + " vote", false);
            if (eventRuntimeBySeg[seg]) eventRuntimeBySeg[seg].successVotes += 1;
            idx++;
            setTimeout(sendOne, 250);
          }
        });
    }
    sendOne();
  }, 200);
  setTimeout(function(){
    var succ = (eventRuntimeBySeg[seg] && typeof eventRuntimeBySeg[seg].successVotes === "number") ? eventRuntimeBySeg[seg].successVotes : 0;
    if (succ < 2) {
      pushAuditNote("AI audit reason: successful witness votes=" + succ + ", unresolved fallback after 5s");
      pushNarrative("Votes insufficient, waiting 5s fallback");
    } else {
      upsertLocalHazard(seg, "HARD_BLOCKED");
      markEvent(cell, "HARD", 2600, "rgba(200,80,80,0.65)");
      pushNarrative("Hazard state -> HARD_BLOCKED @" + seg);
      pushNarrative("Witness threshold met, hazard escalated");
    }
  }, 2200);
  scheduleFiveSecondResolution(seg, cell);
}
function doCharging(){
  if (!isGodMode) return;
  var bid = "echo_01"; var cid = "charger-001";
  var b = botState[bid]; if (!b) return;
  b.mode = "TO_CHARGER"; b.targetChargerId = cid;
  var cur = b.currentCell || robotSpawn[bid] || [0,0];
  var path = bfs(cur, chargerCells[cid]);
  b.pathCells = path && path.length ? path.slice(1) : [];
  b.nextCell = b.pathCells[0] ? [b.pathCells[0][0],b.pathCells[0][1]] : cur;
  b.moveStartMs = Date.now();
  addIntervention(bid, "LOW_BATTERY", cid, b.pathCells.slice(0, 10));
  markEvent(cur, "TO_CHARGE", 2200, "rgba(60,110,180,0.52)");
  pushNarrative("Step B: dispatch charging task " + bid + " -> " + cid);
  showToast("Charging dispatch started", false);
  log("INFO", "Charging dispatch: " + bid + " -> " + cid);
}
function doVision(){
  if (!isGodMode) return;
  var inc = incidents.filter(function(i){ return (i.incident_status||"").toUpperCase() === "OPEN"; })[0];
  if (!inc || !inc.incident_id) { log("WARN", "No OPEN incident for vision audit"); return; }
  var reason = "manual trigger from control panel";
  pushNarrative("Step C: AI audit requested");
  showToast("AI audit requested", false);
  postJson("/v1/ai/vision_audit", { incident_id: inc.incident_id }).then(function(r){
    log(r.status===202?"INFO":"WARN", "POST /v1/ai/vision_audit " + r.status);
    pushAuditNote("AI audit reason: " + reason + " | incident_id=" + inc.incident_id + " | status=" + r.status);
    markEvent(selectedCell || [9,9], "AI_AUDIT", 2400, "rgba(95,75,180,0.55)");
    r.text().then(function(t){
      showEvidenceModal(
        "Vision Audit Evidence",
        "POST /v1/ai/vision_audit\nincident_id=" + inc.incident_id + "\nreason=" + reason + "\nstatus=" + r.status + "\n\n" + (t || "")
      );
    });
    if (r.status !== 202) log("WARN", "Vision unconfigured or failed");
  });
}
function doWorkOrder(){
  if (!isGodMode) return;
  if (!selectedCell) { log("WARN", "Select a HARD cell first"); return; }
  var seg = cellId(selectedCell[0], selectedCell[1]);
  var mergedHazards = (snapshot.hazards || []).concat(Object.keys(localHazards).map(function(k){ return localHazards[k]; }));
  var haz = mergedHazards.find(function(h){ return (h.segment_id||"") === seg; });
  if (!haz || (haz.hazard_status||"").toUpperCase() !== "HARD_BLOCKED") { log("WARN", "Selected cell is not HARD_BLOCKED"); return; }
  pushNarrative("Step D: human work order submitted for " + seg);
  showToast("Human fix submitted", false);
  postJson("/v1/work_orders/report", { work_order_id: "wo_ui_"+Date.now()+"_"+seg, work_order_status: "DONE", segment_id: seg, event_occurred_at: new Date().toISOString() })
    .then(function(r){ log(r.ok?"INFO":"WARN", "POST /v1/work_orders/report " + r.status); markEvent([selectedCell[0], selectedCell[1]], "HUMAN_FIX", 2200, "rgba(60,160,80,0.55)"); if (r.ok) setTimeout(function(){ poll("/v1/snapshot","snapshot",function(d){ snapshot = d || snapshot; redraw(); }); }, 500); });
}

async function runJudgeDemo(){
  if (!isGodMode) return;
  if (demoRunning) return;
  var demoDirector = { stage: "INIT", stageStartedAt: Date.now() };
  function enterStage(name){
    demoDirector.stage = name;
    demoDirector.stageStartedAt = Date.now();
    pushNarrative("Demo stage: " + name);
  }
  demoRunning = true;
  try {
    demoStrictMode = true;
    clearDemoScene();
    resetBotsToJudgeDemoAnchors();
    var demoObstacleCell = pickDemoObstacleCell();
    selectedCell = [demoObstacleCell[0], demoObstacleCell[1]];
    redraw();
    enterStage("A_OBSTACLE_VOTE");
    pushNarrative("Step A: obstacle + witness votes");
    log("INFO", "Judge demo step A: obstacle");
    doObstacle();
    var seg = cellId(selectedCell[0], selectedCell[1]);
    var aRes = await waitForDemoStage(3200, 9000, function(){
      var rt = eventRuntimeBySeg[seg];
      var votes = (rt && typeof rt.successVotes === "number") ? rt.successVotes : 0;
      var st = getHazardStatus(selectedCell[0], selectedCell[1]);
      return votes >= 2 || st === "HARD_BLOCKED";
    });
    if (aRes.timedOut) pushNarrative("Stage A timeout fallback, continue storyline");

    // Deterministic charging storyline: dispatch first, then delayed conflict/reroute.
    enterStage("B_CHARGING_DISPATCH");
    pauseAllBots(EVENT_PRE_FREEZE_MS);
    var cb = JUDGE_DEMO_POINTS.chargingBotId;
    var cc = JUDGE_DEMO_POINTS.chargerId;
    var b = botState[cb];
    var bStart = null;
    if (b) {
      bStart = (b.currentCell || robotSpawn[cb] || [1,12]).slice(0);
      b.battery = Math.min(b.battery || 0.2, 0.18);
      b.mode = "TO_CHARGER";
      b.targetChargerId = cc;
      var p = bfs(bStart, chargerCells[cc]);
      b.pathCells = p && p.length ? p.slice(1) : [];
      b.nextCell = b.pathCells[0] ? [b.pathCells[0][0], b.pathCells[0][1]] : bStart.slice(0);
      b.moveStartMs = Date.now();
      addIntervention(cb, "LOW_BATTERY", cc, b.pathCells.slice(0, 10));
      pushNarrative("Step B: low battery robot " + cb + " heads to " + cc);
      showToast("Low battery dispatch to charger-001", false);
    }

    pushNarrative("Step B: charging dispatch");
    log("INFO", "Judge demo step B: charging dispatch");
    await waitForDemoStage(1800, 6000, function(){
      var bot0 = botState[cb];
      if (!bot0 || !bot0.currentCell) return false;
      return bStart ? manhattan(bot0.currentCell, bStart) >= 1 : false;
    });
    if (demoRunning && demoDirector.stage === "B_CHARGING_DISPATCH") {
      var botNow = botState[cb];
      if (botNow && botNow.currentCell) {
        chargerFlashUntil[cc] = Date.now() + 3000;
        markEvent(chargerCells[cc], "409", 2800, "rgba(180,60,60,0.55)");
        pushNarrative("Step B: charger-001 occupied on route, reroute to charger-002");
        showToast("charger-001 occupied, rerouting", true);
        botNow.targetChargerId = "charger-002";
        botNow.mode = "REROUTE";
        var p2 = bfs(botNow.currentCell, chargerCells["charger-002"]);
        botNow.pathCells = p2 && p2.length ? p2.slice(1) : [];
        botNow.nextCell = botNow.pathCells[0] ? [botNow.pathCells[0][0], botNow.pathCells[0][1]] : botNow.currentCell.slice(0);
        botNow.moveStartMs = Date.now();
        addIntervention(cb, "CONFLICT_REROUTE", "charger-002", botNow.pathCells.slice(0, 10));
      }
    }
    var bRes = await waitForDemoStage(3600, 11000, function(){
      var bot = botState[cb];
      if (!bot) return true;
      var cur = bot.currentCell || robotSpawn[cb] || [0,0];
      var movedEnough = bStart ? manhattan(cur, bStart) >= 4 : false;
      return movedEnough || bot.mode === "REROUTE" || bot.mode === "CHARGING";
    });
    if (bRes.timedOut) pushNarrative("Stage B timeout fallback, continue storyline");

    var rtForAudit = eventRuntimeBySeg[seg];
    if (rtForAudit && rtForAudit.voteStarted) {
      enterStage("C_AI_AUDIT");
      pushNarrative("Step C: AI audit");
      log("INFO", "Judge demo step C: AI audit");
      pauseAllBots(EVENT_PRE_FREEZE_MS);
      pushAuditNote("AI audit reason: single/insufficient witness confidence");
      markEvent(selectedCell, "AI_AUDIT", 5200, "rgba(95,75,180,0.55)");
      var cReady = false;
      setTimeout(function(){
        showEvidenceModal("Vision Audit Evidence", "AI review completed.\nreason=single/insufficient witness confidence\nstatus=202");
        cReady = true;
      }, 4200);
      var cRes = await waitForDemoStage(6200, 12000, function(){ return cReady; });
      if (cRes.timedOut) pushNarrative("Stage C timeout fallback, continue storyline");
    } else {
      pushNarrative("Step C skipped: no witness vote/wit triggered yet");
      pushAuditNote("AI audit skipped: no witness vote/wit trigger");
    }

    enterStage("D_HUMAN_FIX");
    pushNarrative("Step D: human fix");
    log("INFO", "Judge demo step D: human fix");
    upsertLocalHazard(cellId(selectedCell[0], selectedCell[1]), "OPEN");
    markEvent(selectedCell, "HUMAN_FIX", 2000, "rgba(60,160,80,0.55)");
    var dRes = await waitForDemoStage(2400, 7000, function(){
      return getHazardStatus(selectedCell[0], selectedCell[1]) === "OPEN";
    });
    if (dRes.timedOut) pushNarrative("Stage D timeout fallback, force complete");

    enterStage("OUTRO");
    await waitForDemoStage(1500, 2200, function(){ return true; });
    pushNarrative("Judge demo completed");
    showToast("Judge demo completed", false);
    log("INFO", "Judge demo completed");
  } finally {
    demoStrictMode = false;
    demoRunning = false;
  }
}

document.getElementById("btnJudgeDemo").addEventListener("click", function(){ runJudgeDemo(); });
document.getElementById("btnObstacle").addEventListener("click", doObstacle);
document.getElementById("btnCharging").addEventListener("click", doCharging);
document.getElementById("btnVision").addEventListener("click", doVision);
document.getElementById("btnWorkOrder").addEventListener("click", doWorkOrder);
document.getElementById("btnCloseEvidence").addEventListener("click", hideEvidenceModal);

function saveState(){
  try {
    var toSave = { selectedCell: selectedCell, botState: {}, chargerOverrides: chargerOverrides };
    Object.keys(botState).forEach(function(id){
      var b = botState[id]; if (!b) return;
      toSave.botState[id] = { currentCell: b.currentCell, nextCell: b.nextCell, mode: b.mode, targetChargerId: b.targetChargerId, pathCells: b.pathCells, routeWaypointIndex: b.routeWaypointIndex };
    });
    localStorage.setItem("joygate_ui_state_"+sandboxId, JSON.stringify(toSave));
  } catch(e) {}
}
function loadState(){
  try {
    var raw = localStorage.getItem("joygate_ui_state_"+sandboxId) || "{}";
    var o = JSON.parse(raw);
    if (o.selectedCell) selectedCell = o.selectedCell;
    if (o.chargerOverrides && typeof o.chargerOverrides === "object") chargerOverrides = o.chargerOverrides;
    if (o.botState && typeof o.botState === "object") { Object.keys(o.botState).forEach(function(id){ var saved = o.botState[id]; if (saved && robotToRoute[id]) { botState[id] = botState[id] || {}; botState[id].currentCell = saved.currentCell; botState[id].nextCell = saved.nextCell; botState[id].mode = saved.mode || "PATROL"; botState[id].targetChargerId = saved.targetChargerId; botState[id].pathCells = saved.pathCells || []; botState[id].routeWaypointIndex = saved.routeWaypointIndex|0; botState[id].lerpT = 0; } }); }
  } catch(e) {}
}
function initBots(){
  var r = robotRoutes["Route_NorthLoop"];
  Object.keys(robotToRoute).forEach(function(id){
    var b = botState[id];
    if (!b) botState[id] = {};
    b = botState[id];
    if (!b.currentCell) b.currentCell = (robotSpawn[id]||[0,0]).slice(0);
    if (!b.nextCell) b.nextCell = b.currentCell.slice(0);
    b.lerpT = b.lerpT || 0;
    if (!b.mode) b.mode = "PATROL";
    var vid = BOT_VENDOR[id] || "vendor_alpha";
    var cfg = VENDOR_CFG[vid] || VENDOR_CFG.vendor_alpha;
    if (b.battery === undefined || b.battery === null) {
      b.battery = Math.random() * ((cfg.init_max || 1) - (cfg.init_min || 0.9)) + (cfg.init_min || 0.9);
    }
    if (b.routeWaypointIndex === undefined) b.routeWaypointIndex = 0;
    if (!b.pathCells || !b.pathCells.length) {
      var route = robotRoutes[robotToRoute[id]];
      if (route && route.length) { var tgt = route[b.routeWaypointIndex|0]; var path = bfs(b.currentCell, tgt); b.pathCells = path && path.length ? path.slice(1) : []; b.nextCell = b.pathCells[0] ? [b.pathCells[0][0],b.pathCells[0][1]] : b.currentCell.slice(0); b.moveStartMs = Date.now(); b.moveDurationMs = MOVE_DURATION_MS; }
    }
    if (b.moveStartMs === undefined) b.moveStartMs = Date.now();
    if (b.moveDurationMs === undefined) b.moveDurationMs = MOVE_DURATION_MS;
  });
}

function renderLoop(){ redraw(); if (reduceMotion) setTimeout(renderLoop, 200); else requestAnimationFrame(renderLoop); }
document.getElementById("telemetrySync").addEventListener("change", function(e){ if (!isGodMode) return; telemetrySyncOn = e.target.checked; });
var _btnSet = document.getElementById("btnSetGodToken"); if (_btnSet) _btnSet.addEventListener("click", function(){ var el = document.getElementById("godToken"); setGodToken(el ? el.value : ""); });
var _btnClear = document.getElementById("btnClearGodToken"); if (_btnClear) _btnClear.addEventListener("click", clearGodToken);
setInterval(function(){
  if (!isGodMode || !telemetrySyncOn || demoStrictMode) return;
  var ids = Object.keys(robotToRoute);
  if (ids.length === 0) return;
  var id = ids[telemetryBotIndex % ids.length];
  telemetryBotIndex++;
  var b = botState[id]; if (!b || !b.currentCell) return;
  var seg = cellId(Math.floor(b.currentCell[0]), Math.floor(b.currentCell[1]));
  postJson("/v1/telemetry/segment_passed", { joykey: id, fleet_id: "fleet_sim", segment_ids: [seg], event_occurred_at: Date.now()/1000, truth_input_source: "SIMULATOR" }).then(function(r){ if (!r.ok) r.text().then(function(t){ log("WARN", "POST /v1/telemetry/segment_passed " + r.status + (t ? " " + t.slice(0,200) : "")); }); }).catch(function(){});
}, 9000);
setInterval(function(){
  if (!isGodMode || demoStrictMode) return;
  pauseAllBots(200);
  setTimeout(function(){
    if (Math.random() < 0.7) {
      var y = (Math.random() < 0.5) ? 16 : 17;
      var cands = [];
      for (var x = 1; x <= 18; x++) {
        if (isRoad(x, y) && !isBuilding(x, y)) cands.push([x, y]);
      }
      if (!cands.length) return;
      var cell = cands[Math.floor(Math.random() * cands.length)];
      selectedCell = [cell[0], cell[1]];
      doObstacle();
      log("INFO", "[Auto] Obstacle created at " + cellId(cell[0], cell[1]));
      pushNarrative("[Auto] Obstacle created at " + cellId(cell[0], cell[1]));
      markEvent(cell, "AUTO_OBS", 2600, "rgba(185,40,40,0.60)");
    } else {
      var order = ["charger-001","charger-002","charger-003","charger-004","charger-005"];
      var cid = order[Math.floor(Math.random() * order.length)];
      chargerFlashUntil[cid] = Date.now() + 3000;
      postJson("/v1/incidents/report_blocked", { charger_id: cid, incident_type: "BLOCKED_BY_OTHER" })
        .then(function(r){ log("INFO", "[Auto] Charger blocked incident created " + cid + " (" + r.status + ")"); });
      pushNarrative("[Auto] Charger blocked incident created " + cid);
      markEvent(chargerCells[cid], "AUTO_BLOCK", 2600, "rgba(185,40,40,0.60)");
    }
  }, 200);
}, 20000);
loadGodToken();
updateGodUiState();
doBootstrap();
resizeCanvas();
window.addEventListener("resize", function(){ resizeCanvas(); redraw(); });
if (reduceMotion) setTimeout(renderLoop, 200); else requestAnimationFrame(renderLoop);
setInterval(botLogicTick, BOT_TICK_MS);
window.addEventListener("beforeunload", saveState);
})();
</script>
</body>
</html>"""
    return html_body
