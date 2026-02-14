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
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>JoyGate Campus Sandbox</title>
<style>
:root { --cream: #faf8f5; --glass: rgba(255,255,255,0.65); --border: rgba(0,0,0,0.06); --radius: 16px; --shadow: 0 8px 32px rgba(0,0,0,0.06); }
* { box-sizing: border-box; }
body { margin: 0; font-family: system-ui, sans-serif; background: linear-gradient(135deg, #fdfcfb 0%, #f5f0e8 100%); min-height: 100vh; color: #333; }
.layout { display: flex; flex-direction: column; height: 100vh; }
.top { display: flex; flex: 1; min-height: 0; }
.left { flex: 6; padding: 12px; min-width: 0; display: flex; flex-direction: column; gap: 12px; }
.right { flex: 4; padding: 12px; overflow-y: auto; display: flex; flex-direction: column; gap: 12px; }
.bottom { flex: 0 0 auto; padding: 8px 12px; border-top: 1px solid var(--border); background: var(--glass); backdrop-filter: blur(10px); display: none; }
.card { background: var(--glass); backdrop-filter: blur(10px); border: 1px solid var(--border); border-radius: var(--radius); box-shadow: var(--shadow); padding: 12px; }
.card h3 { margin: 0 0 8px 0; font-size: 14px; }
#canv { display: block; width: 100%; height: 100%; min-height: 520px; background: #f0ede8; border-radius: var(--radius); }
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
.demo-health-row { display: flex; justify-content: space-between; gap: 8px; padding: 2px 0; font-size: 12px; }
.demo-badge { border-radius: 999px; padding: 1px 8px; font-size: 11px; }
.demo-ok { background: rgba(70,160,90,0.2); color: #2f7d47; }
.demo-run { background: rgba(80,120,210,0.2); color: #3557a7; }
.demo-wait { background: rgba(110,110,110,0.16); color: #5b5b5b; }
.demo-fail { background: rgba(190,70,70,0.2); color: #9e2f2f; }
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
  </div>
  <div class="right">
    <div class="card"><h3>Narrative Guide (Judge)</h3><div id="narrativeFeed">—</div></div>
    <div class="card"><h3>Incidents</h3><div id="incidents">—</div></div>
    <div class="card"><h3>Hazards + Policy</h3><div id="hazards">—</div></div>
    <div class="card"><h3>Audit</h3><div id="audit">—</div></div>
    <div class="card"><h3>JoyGate Interventions</h3><div id="interventions">—</div></div>
    <div class="card god-only"><h3>Controls</h3>
      <div class="btns">
        <button type="button" id="btnSoft">Generate SOFT</button>
        <button type="button" id="btnLockCharger">Lock Charger</button>
        <button type="button" id="btnCharging">B Charging Dispatch</button>
        <label><input type="checkbox" id="telemetrySync" /> Sync Telemetry (slow)</label>
      </div>
    </div>
  </div>
</div>
<div class="bottom" style="display:none;">
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
var SOFT_WITNESS_DETECT_MS = 30000;
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
var botsVisible = false;
var demoHealth = {
  active: false,
  stage: "IDLE",
  failed: false,
  stages: { A: "WAIT", B: "WAIT", C: "WAIT", D: "WAIT" },
  updatedAt: ""
};
var recentAuditNotes = [];
var interventionLines = [];
var interventionFeed = [];
var flashMarks = [];
var chargerFlashUntil = {};
var eventMarks = [];
var statusMarksBySeg = {};
var voteHints = [];
var narrativeFeed = [];
var witnessAllowlist = ["w1","w2","charlie_01"];
var tempEventBlocks = {};
var eventRuntimeBySeg = {};
var hazardSuppressUntilBySeg = {};
var autoHumanDoneScheduledBySeg = {};
var demoStrictMode = false;
var JUDGE_DEMO_POINTS = { obstacleCell: [10, 9], chargingBotId: "echo_01", chargerId: "charger-001" };
var JUDGE_DEMO_LEADS = { A: "charlie_01", B: "echo_01", C: "w2", D: "delta_01" };
var JUDGE_DEMO_BOT_ANCHORS = {
  "w1":[8,9], "w2":[12,9], "charlie_01":[10,11],
  "alpha_02":[4,3], "charlie_02":[15,10], "delta_01":[10,15], "echo_01":[1,12], "echo_02":[18,12]
};
var JUDGE_DEMO_BOT_PATHS = {
  "w1": [[8,9],[9,9],[10,9],[9,9]],
  "w2": [[12,9],[11,9],[10,9],[11,9]],
  "charlie_01": [[10,11],[10,10],[10,9],[10,10]],
  "alpha_02": [[4,3],[5,3],[6,3],[5,3]],
  "charlie_02": [[15,10],[14,10],[13,10],[14,10]],
  "delta_01": [[10,15],[11,15],[12,15],[11,15]],
  "echo_01": [[1,12],[2,12],[3,12],[2,12]],
  "echo_02": [[18,12],[17,12],[16,12],[17,12]]
};
var demoRouteIndexByBot = {};

function loadGodToken(){ try { godToken = (sessionStorage.getItem("joygate_god_token")||"").trim(); } catch(e) { godToken = ""; } }
function setGodToken(v){ var s = (v||"").trim(); godToken = s; try { if (s) sessionStorage.setItem("joygate_god_token", s); else sessionStorage.removeItem("joygate_god_token"); } catch(e) {} updateGodUiState(); }
function clearGodToken(){ godToken = ""; try { sessionStorage.removeItem("joygate_god_token"); } catch(e) {} var el = document.getElementById("godToken"); if (el) el.value = ""; updateGodUiState(); }
function updateGodUiState(){
  var canWrite = isGodMode;
  var btns = ["btnSoft","btnLockCharger","btnCharging"];
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
function hhmmssNow(){
  var t = new Date();
  return t.getHours().toString().padStart(2, "0") + ":" + t.getMinutes().toString().padStart(2, "0") + ":" + t.getSeconds().toString().padStart(2, "0");
}
function resetDemoHealth(){
  demoHealth.active = false;
  demoHealth.stage = "IDLE";
  demoHealth.failed = false;
  demoHealth.stages = { A: "WAIT", B: "WAIT", C: "WAIT", D: "WAIT" };
  demoHealth.updatedAt = hhmmssNow();
}
function setDemoStage(code, status){
  if (!demoHealth.stages[code]) return;
  demoHealth.stages[code] = status;
  demoHealth.updatedAt = hhmmssNow();
}
function renderDemoHealth(){
  var el = document.getElementById("demoHealth");
  if (!el) return;
  var title = demoHealth.failed ? "FAILED" : (demoHealth.active ? ("RUNNING: " + demoHealth.stage) : "READY");
  el.textContent = "";
  var head = document.createElement("div");
  head.className = "demo-health-row";
  var left = document.createElement("span");
  left.textContent = "State";
  var right = document.createElement("span");
  var cls = demoHealth.failed ? "demo-fail" : (demoHealth.active ? "demo-run" : "demo-ok");
  right.className = "demo-badge " + cls;
  right.textContent = title;
  head.appendChild(left);
  head.appendChild(right);
  el.appendChild(head);
  ["A","B","C","D"].forEach(function(k){
    var row = document.createElement("div");
    row.className = "demo-health-row";
    var label = document.createElement("span");
    label.textContent = k + " Stage";
    var badge = document.createElement("span");
    var st = demoHealth.stages[k] || "WAIT";
    badge.className = "demo-badge " + (st === "DONE" ? "demo-ok" : st === "RUNNING" ? "demo-run" : st === "FAILED" ? "demo-fail" : "demo-wait");
    badge.textContent = st;
    row.appendChild(label);
    row.appendChild(badge);
    el.appendChild(row);
  });
  var time = document.createElement("div");
  time.style.fontSize = "11px";
  time.style.opacity = "0.75";
  time.textContent = "updated: " + (demoHealth.updatedAt || "—");
  el.appendChild(time);
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
  // Judge demo must be reproducible: always use the fixed storyboard cell.
  return [JUDGE_DEMO_POINTS.obstacleCell[0], JUDGE_DEMO_POINTS.obstacleCell[1]];
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
    b.lowBatteryNoted = false;
    // Freeze demo randomness: all bots start with fixed high battery.
    b.battery = 0.92;
    b.moveStartMs = Date.now();
  });
  // Scripted actor for Step B.
  var cb = JUDGE_DEMO_POINTS.chargingBotId;
  if (botState[cb]) botState[cb].battery = 0.18;
  resetDemoRouteIndices();
  redraw();
}
function syncDemoRouteIndex(id){
  var path = JUDGE_DEMO_BOT_PATHS[id];
  if (!path || !path.length) { demoRouteIndexByBot[id] = 0; return; }
  var b = botState[id];
  var cur = (b && b.currentCell) ? b.currentCell : (robotSpawn[id] || path[0]);
  var best = 0;
  var bestD = 1e9;
  for (var i = 0; i < path.length; i++) {
    var d = manhattan(cur, path[i]);
    if (d < bestD) { bestD = d; best = i; }
  }
  demoRouteIndexByBot[id] = best;
}
function resetDemoRouteIndices(){
  Object.keys(robotToRoute).forEach(function(id){ syncDemoRouteIndex(id); });
}
function nextDemoPathCell(id){
  var path = JUDGE_DEMO_BOT_PATHS[id];
  if (!path || !path.length) return null;
  var idx = (demoRouteIndexByBot[id] === undefined) ? 0 : (demoRouteIndexByBot[id] | 0);
  var nextIdx = (idx + 1) % path.length;
  demoRouteIndexByBot[id] = nextIdx;
  return [path[nextIdx][0], path[nextIdx][1]];
}
function setBotMoveTarget(id, toCell, durationMs){
  var b = botState[id] || (botState[id] = {});
  var cur = (b.currentCell || robotSpawn[id] || [0,0]).slice(0);
  b.currentCell = [cur[0], cur[1]];
  b.nextCell = [toCell[0], toCell[1]];
  b.pathCells = [];
  b.moveStartMs = Date.now();
  b.moveDurationMs = durationMs || 800;
}
async function demoMoveBotTo(id, toCell, durationMs){
  var dur = durationMs || 800;
  setBotMoveTarget(id, toCell, dur);
  await sleepMs(dur + 40);
  var b = botState[id];
  if (!b) return;
  b.currentCell = [toCell[0], toCell[1]];
  b.nextCell = [toCell[0], toCell[1]];
  b.moveStartMs = Date.now();
  syncDemoRouteIndex(id);
}
async function demoMoveAllBots(frameIdx, durationMs, excludeId){
  var dur = durationMs || 800;
  var jobs = [];
  Object.keys(robotToRoute).forEach(function(id){
    if (excludeId && id === excludeId) return;
    var cell = nextDemoPathCell(id);
    if (!cell) return;
    jobs.push(demoMoveBotTo(id, cell, dur));
  });
  await Promise.all(jobs);
}
async function demoAdvanceAll(frameState, durationMs, excludeId){
  var idx = (frameState && typeof frameState.idx === "number") ? frameState.idx : 0;
  await demoMoveAllBots(idx, durationMs, excludeId);
  if (frameState) frameState.idx = (idx + 1) % 4;
}
async function demoCruiseFor(totalMs, stepMs, frameState, excludeId){
  var step = stepMs || 320;
  var loops = Math.max(1, Math.ceil((totalMs || step) / step));
  for (var i = 0; i < loops; i++) {
    await demoAdvanceAll(frameState, step, excludeId);
  }
}
async function demoMoveBotAlong(id, toCell, stepMs, frameState){
  var b = botState[id];
  if (!b) return;
  var from = (b.currentCell || robotSpawn[id] || [0,0]).slice(0);
  var path = bfs(from, toCell, true);
  var dur = stepMs || 520;
  if (!path || path.length < 2) {
    // Never "teleport" across multiple cells in demo fallback.
    await demoCruiseFor(dur, Math.max(260, dur - 140), frameState, id);
    return;
  }
  for (var i = 1; i < path.length; i++) {
    await Promise.all([
      demoMoveBotTo(id, [path[i][0], path[i][1]], dur),
      demoAdvanceAll(frameState, Math.max(260, dur - 140), id)
    ]);
  }
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
  Object.keys(autoHumanDoneScheduledBySeg).forEach(function(k){ delete autoHumanDoneScheduledBySeg[k]; });
  localHazards = {};
  snapshot.hazards = [];
  redraw();
}
function upsertLocalHazard(seg, status){
  if (isHazardSuppressed(seg) && status !== "OPEN") return;
  if (status === "OPEN") {
    delete localHazards[seg];
    delete statusMarksBySeg[seg];
    delete autoHumanDoneScheduledBySeg[seg];
  } else {
    localHazards[seg] = { segment_id: seg, hazard_status: status, hazard_id: "haz_ui_" + seg + "_" + Date.now() };
    var p = parseCell(seg);
    if (p) {
      if (status === "SOFT_BLOCKED") statusMarksBySeg[seg] = { cell: [p[0], p[1]], text: "SOFT", color: "rgba(200,60,60,0.55)" };
      else if (status === "HARD_BLOCKED") statusMarksBySeg[seg] = { cell: [p[0], p[1]], text: "HARD", color: "rgba(200,80,80,0.65)" };
    }
    if (status === "HARD_BLOCKED") scheduleAutoHumanDoneForHard(seg);
  }
  // snapshot.hazards no longer modified directly to avoid race with polling
  recomputeAllPaths();
  redraw();
}
function ensureEventTimeoutClear(seg, durationMs){
  var ttl = (typeof durationMs === "number" && durationMs > 0) ? durationMs : EVENT_CLEAR_MS;
  setTimeout(function(){
    delete tempEventBlocks[seg];
    if (eventRuntimeBySeg[seg]) eventRuntimeBySeg[seg].resolved = true;
    // Suppress rebound from backend polling for a short window after forced clear.
    hazardSuppressUntilBySeg[seg] = Date.now() + 10000;
    delete localHazards[seg];
    delete statusMarksBySeg[seg];
    clearEventVisuals();
    pushNarrative("Event auto-cleared in " + Math.round(ttl/1000) + "s: " + seg);
    recomputeAllPaths();
    redraw();
  }, ttl);
}
function botCellApproxNow(id){
  // Use an approximate cell based on movement progress so "within 2 cells"
  // matches what users see on screen while bots are moving.
  var b = botState[id];
  var cur = (b && b.currentCell) ? b.currentCell : (robotSpawn[id] || null);
  if (!cur) return null;
  var nxt = (b && b.nextCell) ? b.nextCell : cur;
  var now = Date.now();
  var startMs = (b && typeof b.moveStartMs === "number") ? b.moveStartMs : now;
  var dur = (b && b.moveDurationMs !== undefined) ? b.moveDurationMs : MOVE_DURATION_MS;
  if (!dur || dur < 1) return [cur[0], cur[1]];
  var t = (cur[0]===nxt[0] && cur[1]===nxt[1]) ? 1 : Math.min(1, Math.max(0, (now - startMs) / dur));
  var x = cur[0] + (nxt[0] - cur[0]) * t;
  var y = cur[1] + (nxt[1] - cur[1]) * t;
  return [Math.round(x), Math.round(y)];
}
function botMinDistToCellNow(id, cell){
  // More robust than a single rounded cell: use min dist of currentCell/nextCell.
  if (!cell) return 999;
  var b = botState[id];
  var cur = (b && b.currentCell) ? b.currentCell : (robotSpawn[id] || null);
  if (!cur) return 999;
  var nxt = (b && b.nextCell) ? b.nextCell : cur;
  var d1 = manhattan([cur[0], cur[1]], cell);
  var d2 = manhattan([nxt[0], nxt[1]], cell);
  return Math.min(d1, d2);
}
function getNearbyWitnesses(cell){
  var maxDist = 2;
  var candidates = witnessAllowlist.filter(function(id){
    return botMinDistToCellNow(id, cell) <= maxDist;
  });
  return candidates;
}
function isWitnessWithinOneCell(id, cell){
  return botMinDistToCellNow(id, cell) <= 2;
}
function ensureEventClearScheduled(seg, durationMs){
  var rt = eventRuntimeBySeg[seg];
  if (!rt || rt.clearScheduled) return;
  rt.clearScheduled = true;
  ensureEventTimeoutClear(seg, durationMs);
}

var chargerCells = {"charger-001":[6,18],"charger-002":[8,18],"charger-003":[10,18],"charger-004":[12,18],"charger-005":[14,18]};
// Grid size constants (used by event pickers)
var GW = 20, GH = 20;
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
var buildings = [[3,5,3,5],[12,14,3,5],[3,5,12,14],[12,14,12,14],[8,9,4,5]];
var roadRects = [[1,18,1,1],[1,18,17,17],[1,1,1,17],[18,18,1,17],[9,10,1,17],[1,18,8,9],[1,18,16,17]];
var parkRect = [7,12,10,14];
function isRoad(x,y){ return roadRects.some(function(r){ return x>=r[0]&&x<=r[1]&&y>=r[2]&&y<=r[3]; }); }
function isBuilding(x,y){ return buildings.some(function(b){ return x>=b[0]&&x<=b[1]&&y>=b[2]&&y<=b[3]; }); }
function isPark(x,y){ return x>=parkRect[0]&&x<=parkRect[1]&&y>=parkRect[2]&&y<=parkRect[3]; }
function isChargerPad(x,y){
  if (y !== 18) return false;
  return x===6 || x===8 || x===10 || x===12 || x===14;
}
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
  return isBuilding(x,y) || isChargerPad(x,y) || st === "HARD_BLOCKED" || st === "SOFT_BLOCKED" || isTempEventBlocked(cellId(x,y));
}
function cellCost(x,y){
  if (isBlocked(x,y)) return 99999;
  var st = getHazardStatus(x,y);
  if (st === "SOFT_BLOCKED") return 8;
  if (isRoad(x,y)) return 1;
  if (isPark(x,y)) return 3;
  return 2;
}
function bfs(from, to, allowTargetBlocked){
  var fx=from[0], fy=from[1], tx=to[0], ty=to[1];
  if (fx===tx&&fy===ty) return [];
  if (isBlocked(tx,ty) && !allowTargetBlocked) return [];
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
      if (isBlocked(nx,ny) && !(allowTargetBlocked && nx===tx && ny===ty)) continue;
      var nk = key(nx,ny);
      var cost = u.c + cellCost(nx,ny);
      if (dist[nk] === undefined || cost < dist[nk]) { dist[nk]=cost; prev[nk]=[u.x,u.y]; q.push({x:nx,y:ny,c:cost}); }
    }
  }
  return [];
}

function log(level, msg){
  // Hidden in judge-focused mode: keep UI clean and narrative-first.
  return;
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
  var p = Array.isArray(pathCells) ? pathCells.slice(0) : [];
  if (p.length < 2) return;
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
function pauseBotsNearCell(cell, maxDist, ms){
  if (!cell) return;
  var now = Date.now();
  var dist = (typeof maxDist === "number") ? maxDist : 2;
  Object.keys(botState).forEach(function(id){
    var b = botState[id]; if (!b) return;
    var p = (b && b.currentCell) ? b.currentCell : (robotSpawn[id] || null);
    if (!p) return;
    if (manhattan([p[0], p[1]], cell) > dist) return;
    var start = b.moveStartMs || now;
    b.moveStartMs = Math.max(start, now) + (ms || 120);
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
      path = bfs(cur, chargerCells[cid], true);
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
      for (var seg in allSegs) {
        if (prevMap[seg] !== currMap[seg]) {
          log("INFO", "hazard " + seg + " " + (prevMap[seg]||"") + " -> " + (currMap[seg]||""));
          hazardChanged = true;
          if (currMap[seg] === "HARD_BLOCKED" && prevMap[seg] !== "HARD_BLOCKED") scheduleAutoHumanDoneForHard(seg);
        }
      }
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
  renderDemoHealth();
}

var canvas = document.getElementById("canv"); var ctx = canvas.getContext("2d"); var W = 400; var H = 400; var CS = Math.min(W,H)/20; var CSX = W/20; var CSY = H/20;
var offStatic = null;
function resizeCanvas(){
  var parent = canvas.parentElement;
  var w = Math.floor(Math.max(640, (parent ? parent.clientWidth : 640)));
  var hRaw = parent ? parent.clientHeight : 620;
  var h = Math.floor(Math.max(520, hRaw));
  var dpr = window.devicePixelRatio || 1;
  canvas.style.width = w + "px";
  canvas.style.height = h + "px";
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  W = w; H = h; CSX = W / 20; CSY = H / 20; CS = Math.min(CSX, CSY);
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
    var px = x*CSX; var py = y*CSY;
    if (isBuilding(x,y)) { c.fillStyle = "#c4b8a8"; c.fillRect(px,py,CSX,CSY); c.strokeRect(px,py,CSX,CSY); }
    else if (isChargerPad(x,y)) { c.fillStyle = "#b8b0a3"; c.fillRect(px,py,CSX,CSY); c.strokeStyle = "#968e80"; c.strokeRect(px,py,CSX,CSY); }
    else if (isPark(x,y)) { c.fillStyle = "rgba(168,214,175,0.62)"; c.fillRect(px,py,CSX,CSY); }
    else if (isRoad(x,y)) { c.fillStyle = "#dfe7f0"; c.fillRect(px,py,CSX,CSY); if ((x+y)%2===0) { c.fillStyle = "rgba(255,255,255,0.38)"; c.fillRect(px+CSX*0.35, py+CSY*0.46, CSX*0.3, CSY*0.08); } }
    else { c.fillStyle = "#f0ede8"; c.fillRect(px,py,CSX,CSY); }
    c.strokeStyle = "#ddd"; c.strokeRect(px,py,CSX,CSY);
  }
  c.fillStyle = "#6f655b"; c.font = "bold 10px sans-serif";
  c.fillText("ADMIN", 3.4*CSX, 4.0*CSY);
  c.fillText("LAB", 12.6*CSX, 4.1*CSY);
  c.fillText("DORM", 3.6*CSX, 14.0*CSY);
  c.fillText("WAREHOUSE", 12.2*CSX, 14.0*CSY);
  c.fillText("SECURITY", 8.1*CSX, 5.2*CSY);
  c.fillStyle = "#5e8f5a"; c.fillText("CENTRAL PARK", 7.0*CSX, 11.2*CSY);
  c.fillStyle = "#6f655b"; c.fillText("CHARGING APRON", 10.8*CSX, 16.6*CSY);
  ctx.drawImage(offStatic,0,0,W,H);
}
function isChargerRealOccupied(id){
  // UI-only occupancy: do not treat backend holds/slot_state as "locked"
  // to keep chargers idle at page start. Only local overrides (lock event / 409) mark occupied.
  var ov = chargerOverrides[id];
  if (!ov) return false;
  if (!ov.expiresAtMs) return false;
  if (Date.now() >= ov.expiresAtMs) return false;
  return (ov.state || "").toUpperCase() === "OCCUPIED";
}
function drawChargers(){
  var now = Date.now();
  for (var id in chargerCells) {
    var p = chargerCells[id];
    var ov = chargerOverrides[id];
    var useOverride = ov && (ov.expiresAtMs > now);
    var occupied = (useOverride ? ((ov.state || "").toUpperCase() === "OCCUPIED") : false);
    var hi = chargerFlashUntil[id] && chargerFlashUntil[id] > now;
    ctx.fillStyle = occupied ? "rgba(100,100,100,0.8)" : "#4a90d9";
    ctx.beginPath(); ctx.arc((p[0]+0.5)*CSX,(p[1]+0.5)*CSY,CS*0.45,0,6.28); ctx.fill();
    if (hi) {
      ctx.strokeStyle = "rgba(255,70,70,0.95)";
      ctx.lineWidth = 3;
      ctx.beginPath(); ctx.arc((p[0]+0.5)*CSX,(p[1]+0.5)*CSY,CS*0.44,0,6.28); ctx.stroke();
    }
    ctx.fillStyle = "#000"; ctx.textAlign = "center"; ctx.font = "10px sans-serif"; ctx.fillText(id, (p[0]+0.5)*CSX, (p[1]+1)*CSY);
  }
}
function drawHazards(){
  var h = (snapshot.hazards || []).concat(Object.keys(localHazards).map(function(k){ return localHazards[k]; }));
  h.forEach(function(z){
    if (isHazardSuppressed(z.segment_id || "")) return;
    var p = parseCell(z.segment_id); if (!p) return;
    var px = p[0]*CSX, py = p[1]*CSY;
    var st = (z.hazard_status||"").toUpperCase();
    if (st === "HARD_BLOCKED") { ctx.fillStyle = "rgba(200,80,80,0.6)"; ctx.fillRect(px,py,CSX,CSY); ctx.strokeStyle = "#a55"; for (var i = 0; i < 4; i++) ctx.strokeRect(px+i*2,py,CSX-i*4,CSY); }
    else if (st === "SOFT_BLOCKED") { ctx.fillStyle = "rgba(255,230,150,0.7)"; ctx.fillRect(px,py,CSX,CSY); ctx.strokeRect(px,py,CSX,CSY); }
    else if (st === "OPEN") { ctx.fillStyle = "rgba(150,200,150,0.2)"; ctx.fillRect(px,py,CSX,CSY); }
  });
}
function drawFreshness(){
  var sig = snapshot.segment_passed_signals || [];
  sig.forEach(function(s){
    var p = parseCell(s.segment_id); if (!p) return;
    ctx.fillStyle = "rgba(100,200,255,0.25)"; ctx.fillRect(p[0]*CSX,p[1]*CSY,CSX,CSY);
  });
}
function drawRobotsDerived(){
  if (!botsVisible) return;
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
      var baseX = (cellX+0.5)*CSX, baseY = (cellY+0.5)*CSY;
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
      ctx.beginPath(); ctx.arc(x,y,CS*0.24,0,6.28); ctx.fill();
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
    ctx.moveTo((pts[0][0]+0.5)*CSX, (pts[0][1]+0.5)*CSY);
    for (var i = 1; i < pts.length; i++) ctx.lineTo((pts[i][0]+0.5)*CSX, (pts[i][1]+0.5)*CSY);
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
    ctx.lineWidth = 2;
    ctx.shadowColor = it.color || "#ffffff";
    ctx.shadowBlur = 10;
    ctx.beginPath();
    ctx.moveTo((it.path[0][0]+0.5)*CSX, (it.path[0][1]+0.5)*CSY);
    for (var i = 1; i < it.path.length; i++) ctx.lineTo((it.path[i][0]+0.5)*CSX, (it.path[i][1]+0.5)*CSY);
    ctx.stroke();
    var last = it.path[it.path.length - 1];
    var tx = (last[0]+0.5)*CSX + 5;
    var ty = (last[1]+0.5)*CSY - 6;
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
    ctx.strokeRect(p[0]*CSX, p[1]*CSY, CSX, CSY);
  });
}
function drawEventMarks(){
  var now = Date.now();
  eventMarks = eventMarks.filter(function(m){ return now < m.untilMs; });
  eventMarks.forEach(function(m){
    var p = m.cell; if (!p) return;
    ctx.fillStyle = m.color;
    ctx.fillRect(p[0]*CSX, p[1]*CSY, CSX, CSY);
    ctx.fillStyle = "#fff";
    ctx.font = "bold 9px sans-serif";
    ctx.textAlign = "center";
    ctx.fillText((m.text||"EVENT").slice(0, 10), (p[0]+0.5)*CSX, (p[1]+0.62)*CSY);
  });
}
function drawStatusMarks(){
  Object.keys(statusMarksBySeg).forEach(function(seg){
    var m = statusMarksBySeg[seg];
    if (!m || !m.cell) return;
    var st = getHazardStatus(m.cell[0], m.cell[1]);
    if (st !== "SOFT_BLOCKED" && st !== "HARD_BLOCKED") {
      delete statusMarksBySeg[seg];
      return;
    }
    var p = m.cell;
    ctx.fillStyle = m.color || "rgba(20,20,20,0.75)";
    ctx.fillRect(p[0]*CSX, p[1]*CSY, CSX, CSY);
    ctx.fillStyle = "#fff";
    ctx.font = "bold 9px sans-serif";
    ctx.textAlign = "center";
    ctx.fillText((m.text||"STATE").slice(0, 10), (p[0]+0.5)*CSX, (p[1]+0.62)*CSY);
  });
}
function drawVoteHints(){
  var now = Date.now();
  voteHints = voteHints.filter(function(v){ return now < v.untilMs; });
  voteHints.forEach(function(v){
    var p = v.cell; if (!p) return;
    var cx = (p[0]+0.5)*CSX, cy = (p[1]+0.5)*CSY;
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
    var path = bfs(cur, p, true);
    if (path && path.length && path.length < bestLen) { bestLen = path.length; best = { cid: cid, path: path }; }
  });
  return best;
}
function botLogicTick(){
  if (demoStrictMode) return;
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
          var path = bfs(b.currentCell, pc, true);
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
              var path = bfs(b.currentCell, chargerCells[nextId], true);
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
  drawStatusMarks();
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
  var x = Math.floor(sx/CSX); var y = Math.floor(sy/CSY);
  if (x>=0&&x<20&&y>=0&&y<20) { selectedCell = [x,y]; redraw(); }
});

function doBootstrap(){
  fetch("/bootstrap", { credentials: "include" }).then(function(r){
    if (!r.ok) { log("ERROR", "bootstrap failed " + r.status); return; }
    return r.json().then(function(d){
      sandboxId = (d&&d.sandbox_id) || "anon";
      if ((d&&d.sandbox_id) === null) { capacityReached = true; log("WARN", "bootstrap sandbox_id null (capacity reached)"); pushNarrative("System capacity reached, retry later"); loadState(); updateCards(); updateGodUiState(); setTimeout(runPolling, 60000); return; }
      loadState(); runPolling(); updateCards(); updateGodUiState();
      pushNarrative("System ready in " + (isGodMode ? "God Mode" : "Judge Mode"));
      // Auto-start full simulation: all robots move immediately on page load.
      startRealRun();
    });
  }).catch(function(e){ log("ERROR", "bootstrap " + e); });
}

function startRealRun(){
  botsVisible = true;
  if (Object.keys(botState).length === 0) initBots();
  // Ensure chargers start visually idle on page open (do not restore old lock overlays).
  chargerOverrides = {};
  chargerFlashUntil = {};
  Object.keys(botState).forEach(function(id){
    var b = botState[id]; if (!b) return;
    if (!b.currentCell) b.currentCell = (robotSpawn[id] || [0,0]).slice(0);
    b.mode = "PATROL";
    b.targetChargerId = null;
    b.negotiating = false;
    b.moveStartMs = Date.now();
  });
  demoStrictMode = false;
  demoRunning = false;
  clearEventVisuals();
  recomputeAllPaths();
  renderDemoHealth();
  redraw();
  pushNarrative("Real run started");
}

function scheduleAutoHumanDoneForHard(seg){
  if (!seg || autoHumanDoneScheduledBySeg[seg]) return;
  autoHumanDoneScheduledBySeg[seg] = true;
  var p = parseCell(seg) || [0,0];
  pushNarrative("HARD confirmed @" + seg + ", auto human DONE in 5s");
  markEvent([p[0], p[1]], "AUTO_HUMAN_5S", 1800, "rgba(170,90,40,0.58)");
  setTimeout(function(){
    if (getHazardStatus(p[0], p[1]) !== "HARD_BLOCKED") {
      delete autoHumanDoneScheduledBySeg[seg];
      return;
    }
    showToast("Auto human handling @" + seg, true);
    postJson("/v1/work_orders/report", {
      work_order_id: "wo_auto_" + Date.now() + "_" + seg,
      work_order_status: "DONE",
      segment_id: seg,
      event_occurred_at: Date.now() / 1000
    }).then(function(){
      upsertLocalHazard(seg, "OPEN");
      markEvent([p[0], p[1]], "HUMAN_DONE", 2000, "rgba(60,160,80,0.55)");
      pushNarrative("Auto human DONE applied @" + seg);
      delete autoHumanDoneScheduledBySeg[seg];
    }).catch(function(){
      upsertLocalHazard(seg, "OPEN");
      markEvent([p[0], p[1]], "HUMAN_DONE_LOCAL", 2000, "rgba(60,160,80,0.55)");
      pushNarrative("Auto human DONE fallback @" + seg);
      delete autoHumanDoneScheduledBySeg[seg];
    });
  }, 5000);
}

function scheduleFiveSecondResolution(seg, cell){
  // NOTE: despite the name, this schedules the "8s AI audit" fallback.
  // Requirement: the 8 seconds must start AFTER vote starts (not after SOFT creation).
  if (demoStrictMode) return;
  var rt0 = eventRuntimeBySeg[seg];
  if (!rt0 || !rt0.voteStarted) return;
  if (rt0.voteTimeoutScheduled) return;
  rt0.voteTimeoutScheduled = true;
  rt0.voteStartedAt = rt0.voteStartedAt || Date.now();
  setTimeout(function(){
    var rt = eventRuntimeBySeg[seg];
    if (!rt) return;
    if (rt.resolved) return;
    // If vote never actually started, do nothing (timer should not be armed).
    if (!rt.voteStarted) return;
    var st = getHazardStatus(cell[0], cell[1]);
    var unresolved = isTempEventBlocked(seg) || st === "SOFT_BLOCKED" || st === "HARD_BLOCKED";
    if (!unresolved) { rt.resolved = true; return; }
    var successVotes = (typeof rt.successVotes === "number") ? rt.successVotes : 0;
    if (st === "HARD_BLOCKED") { rt.resolved = true; return; }
    if (successVotes >= 2) { rt.resolved = true; return; }
    // Vote not enough: one mock AI audit after 8s from vote start, then 50/50 OPEN vs HARD.
    pushNarrative("Votes not enough 8s after vote start -> trigger mock AI audit");
    showToast("8s after vote start, AI audit", true);
    var n = Date.now();
    var aiSaysBlocked = ((n + seg.length) % 2) === 0;
    var aiReason = aiSaysBlocked
      ? "AI reason: lane remains blocked from witness inconsistency"
      : "AI reason: no persistent blockage seen in recent evidence";
    markEvent(cell, "AI_AUDIT", 2200, "rgba(95,75,180,0.55)");
    pushAuditNote(aiReason + " | decision=" + (aiSaysBlocked ? "HARD_BLOCKED" : "OPEN"));
    if (aiSaysBlocked) {
      upsertLocalHazard(seg, "HARD_BLOCKED");
      markEvent(cell, "HARD", 2200, "rgba(200,80,80,0.65)");
      pushNarrative("Mock AI decision -> HARD_BLOCKED @" + seg);
    } else {
      upsertLocalHazard(seg, "OPEN");
      markEvent(cell, "OPEN", 2200, "rgba(70,160,90,0.55)");
      pushNarrative("Mock AI decision -> OPEN @" + seg);
    }
    recomputeAllPaths();
    rt.resolved = true;
  }, 8000);
}

// God buttons — all check isGodMode and godToken before any POST
function pickSoftHazardCellForRandomEvent(){
  var cells = [];
  for (var y = 0; y < GH; y++) {
    for (var x = 0; x < GW; x++) {
      // allow SOFT event anywhere except buildings/chargers/blocked; only distance guard applies
      if (isBuilding(x, y) || isChargerPad(x, y) || isBlocked(x, y)) continue;
      var minD = 999;
      Object.keys(robotToRoute).forEach(function(id){
        var b = botState[id];
        var p = (b && b.currentCell) ? b.currentCell : (robotSpawn[id] || null);
        if (!p) return;
        var d = manhattan([x, y], p);
        if (d < minD) minD = d;
      });
      // distance constraint: must be within 5 cells, but not adjacent
      if (minD >= 2 && minD < 5) cells.push([x, y]);
    }
  }
  if (!cells.length) return null;
  return cells[Math.floor(Math.random() * cells.length)];
}
function listFreeChargers(excludeCid){
  var now = Date.now();
  return Object.keys(chargerCells).filter(function(cid){
    if (excludeCid && cid === excludeCid) return false;
    if (isChargerRealOccupied(cid)) return false;
    if (hasBotHeadingToCharger(cid)) return false;
    var ov = chargerOverrides[cid];
    if (ov && ov.expiresAtMs && ov.expiresAtMs > now) return false;
    return true;
  });
}
function assignBotToCharger(botId, cid, mode){
  var b = botState[botId] || (botState[botId] = {});
  var cur = (b.currentCell || robotSpawn[botId] || [0,0]).slice(0);
  b.currentCell = [cur[0], cur[1]];
  b.mode = mode || "TO_CHARGER";
  b.targetChargerId = cid;
  b.negotiating = false;
  var path = bfs(cur, chargerCells[cid], true);
  b.pathCells = path && path.length ? path.slice(1) : [];
  b.nextCell = b.pathCells[0] ? [b.pathCells[0][0], b.pathCells[0][1]] : cur.slice(0);
  b.moveStartMs = Date.now();
}
function triggerChargerLockEvent(){
  var freeNow = listFreeChargers(null);
  if (!freeNow.length) {
    log("WARN", "Random event skipped: no free charger");
    showToast("Random event skipped (no free charger)", true);
    return;
  }
  var lockedCid = freeNow[Math.floor(Math.random() * freeNow.length)];
  chargerOverrides[lockedCid] = { state: "OCCUPIED", expiresAtMs: Date.now() + 7000 };
  chargerFlashUntil[lockedCid] = Date.now() + 3000;
  markEvent(chargerCells[lockedCid], "LOCKED", 2600, "rgba(180,60,60,0.55)");
  pushNarrative("Random Event: charger locked @" + lockedCid);
  showToast("Random event: charger locked", true);

  var botIds = Object.keys(robotToRoute);
  if (!botIds.length) return;
  var victim = botIds[Math.floor(Math.random() * botIds.length)];
  assignBotToCharger(victim, lockedCid, "TO_CHARGER");
  addIntervention(victim, "CHARGING_DISPATCH", lockedCid, (botState[victim].pathCells || []).slice(0, 10));
  pushNarrative("Dispatch " + victim + " -> " + lockedCid + " (locked target)");

  setTimeout(function(){
    var b = botState[victim];
    if (!b) return;
    var alts = listFreeChargers(lockedCid);
    if (!alts.length) {
      pushNarrative("Reroute skipped: no alternate charger for " + victim);
      showToast("No alternate charger for reroute", true);
      return;
    }
    var cur = (b.currentCell || robotSpawn[victim] || [0,0]).slice(0);
    var best = alts.map(function(cid){ return { cid: cid, d: manhattan(cur, chargerCells[cid]) }; })
      .sort(function(a,b2){ return a.d - b2.d; })[0];
    assignBotToCharger(victim, best.cid, "REROUTE");
    addIntervention(victim, "CONFLICT_REROUTE", best.cid, (botState[victim].pathCells || []).slice(0, 10));
    markEvent(chargerCells[best.cid], "REROUTE", 2200, "rgba(90,120,200,0.50)");
    pushNarrative("JoyGate reroute after 2s: " + victim + " -> " + best.cid);
    showToast("JoyGate reroute executed", false);
  }, 2000);
}
function doSoftHazardEventAt(cell){
  var seg = cellId(cell[0], cell[1]);
  var witnessWatchMs = SOFT_WITNESS_DETECT_MS;
  // Avoid global stutter: only pause bots near the soft event.
  pauseBotsNearCell(cell, 3, EVENT_PRE_FREEZE_MS);
  statusMarksBySeg[seg] = { cell: [cell[0], cell[1]], text: "SOFT", color: "rgba(200,60,60,0.55)" };
  flashMarks.push({ cell: [cell[0], cell[1]], untilMs: Date.now() + 3000 });
  tempEventBlocks[seg] = Date.now() + witnessWatchMs;
  eventRuntimeBySeg[seg] = { startedAt: Date.now(), candidateVotes: 0, successVotes: 0, voteStarted: false, clearScheduled: false, resolved: false, voteDoneByWitness: {}, voteInFlightByWitness: {} };
  upsertLocalHazard(seg, "SOFT_BLOCKED");
  ensureEventClearScheduled(seg, witnessWatchMs);
  pushNarrative("Hazard state -> SOFT_BLOCKED @" + seg);
  pushNarrative("Step A: SOFT detected at " + seg + ", witness voting starts");
  showToast("SOFT detected, witnesses voting", true);
  function tryDispatchWitnessVotes(){
    var rt = eventRuntimeBySeg[seg];
    if (!rt || rt.resolved) return;
    var keys = getNearbyWitnesses(cell);
    rt.candidateVotes = keys.length;
    if (!keys.length) return;
    keys.forEach(function(who, idx){
      if (rt.voteDoneByWitness[who]) return;
      if (rt.voteInFlightByWitness[who]) return;
      rt.voteInFlightByWitness[who] = true;
      postJson("/v1/witness/segment_respond", { segment_id: seg, segment_state: "BLOCKED", points_event_id: "pe_ui_"+Date.now()+"_"+idx }, { "X-JoyKey": who })
        .then(function(r){
          log(r.status>=400?"WARN":"INFO", "POST /v1/witness/segment_respond " + r.status);
          if (!r.ok) return;
          if (!isWitnessWithinOneCell(who, cell)) return;
          var rt2 = eventRuntimeBySeg[seg];
          if (!rt2 || rt2.resolved) return;
          rt2.voteDoneByWitness[who] = true;
          if (!rt2.voteStarted) {
            rt2.voteStarted = true;
            rt2.voteStartedAt = Date.now();
            // Arm the 8s fallback timer only after vote starts.
            scheduleFiveSecondResolution(seg, cell);
          }
          ensureEventClearScheduled(seg, witnessWatchMs);
          addVoteHint(who, cell);
          pushNarrative(who + " vote -> BLOCKED @" + seg);
          showToast(who + " vote", false);
          rt2.successVotes += 1;
          var succNow = rt2.successVotes || 0;
          if (succNow >= 2 && !rt2.resolved) {
            upsertLocalHazard(seg, "HARD_BLOCKED");
            pushNarrative("Hazard state -> HARD_BLOCKED @" + seg);
            pushNarrative("Witness threshold met, hazard escalated");
            rt2.resolved = true;
          }
        })
        .finally(function(){
          var rt3 = eventRuntimeBySeg[seg];
          if (rt3 && rt3.voteInFlightByWitness) delete rt3.voteInFlightByWitness[who];
        });
    });
  }

  // Witness selection must not be a one-shot at SOFT creation time.
  // If no witness is within 2 cells now, keep checking for a short window and start voting when one enters range.
  var keys0 = getNearbyWitnesses(cell);
  if (eventRuntimeBySeg[seg]) eventRuntimeBySeg[seg].candidateVotes = keys0.length;
  if (!keys0.length) pushNarrative("No nearby witness within 2-cell yet; keep detecting for 30s");
  tryDispatchWitnessVotes();
  var startedWaitAt = Date.now();
  var waitTimer = setInterval(function(){
    var rt3 = eventRuntimeBySeg[seg];
    if (!rt3 || rt3.resolved) { clearInterval(waitTimer); return; }
    if (Date.now() - startedWaitAt > witnessWatchMs) { clearInterval(waitTimer); return; }
    tryDispatchWitnessVotes();
  }, 320);
  setTimeout(function(){
    var rt4 = eventRuntimeBySeg[seg];
    if (rt4 && rt4.resolved) return;
    var succ = (eventRuntimeBySeg[seg] && typeof eventRuntimeBySeg[seg].successVotes === "number") ? eventRuntimeBySeg[seg].successVotes : 0;
    if (succ < 2) {
      pushAuditNote("AI audit pending: successful witness votes=" + succ + " (will trigger 8s after vote start if still insufficient)");
      pushNarrative("Votes insufficient, waiting (8s after vote start) fallback");
    }
  }, 2200);
}
function doSoftHazard(){
  if (!isGodMode) return;
  var cell = pickSoftHazardCellForRandomEvent();
  if (!cell) {
    log("WARN", "Generate SOFT skipped: no valid cell at distance 2-3");
    showToast("Generate SOFT skipped (no valid cell)", true);
    return;
  }
  selectedCell = [cell[0], cell[1]];
  doSoftHazardEventAt(cell);
}
function doLockCharger(){
  if (!isGodMode) return;
  triggerChargerLockEvent();
}
function doObstacle(){
  if (!isGodMode) return;
  if (Math.random() < 0.5) {
    triggerChargerLockEvent();
    return;
  }
  var cell = pickSoftHazardCellForRandomEvent();
  if (!cell) {
    triggerChargerLockEvent();
    return;
  }
  selectedCell = [cell[0], cell[1]];
  doSoftHazardEventAt(cell);
}
function doCharging(){
  if (!isGodMode) return;
  var bid = "echo_01"; var cid = "charger-001";
  var b = botState[bid]; if (!b) return;
  b.mode = "TO_CHARGER"; b.targetChargerId = cid;
  var cur = b.currentCell || robotSpawn[bid] || [0,0];
  var path = bfs(cur, chargerCells[cid], true);
  b.pathCells = path && path.length ? path.slice(1) : [];
  b.nextCell = b.pathCells[0] ? [b.pathCells[0][0],b.pathCells[0][1]] : cur;
  b.moveStartMs = Date.now();
  addIntervention(bid, "LOW_BATTERY", cid, b.pathCells.slice(0, 10));
  markEvent(cur, "TO_CHARGE", 2200, "rgba(60,110,180,0.52)");
  pushNarrative("Step B: dispatch charging task " + bid + " -> " + cid);
  showToast("Charging dispatch started", false);
  log("INFO", "Charging dispatch: " + bid + " -> " + cid);
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
  postJson("/v1/work_orders/report", { work_order_id: "wo_ui_"+Date.now()+"_"+seg, work_order_status: "DONE", segment_id: seg, event_occurred_at: Date.now() / 1000 })
    .then(function(r){ log(r.ok?"INFO":"WARN", "POST /v1/work_orders/report " + r.status); markEvent([selectedCell[0], selectedCell[1]], "HUMAN_FIX", 2200, "rgba(60,160,80,0.55)"); if (r.ok) setTimeout(function(){ poll("/v1/snapshot","snapshot",function(d){ snapshot = d || snapshot; redraw(); }); }, 500); });
}

// Judge demo script removed; keep full real-run mode only.

document.getElementById("btnSoft").addEventListener("click", doSoftHazard);
document.getElementById("btnLockCharger").addEventListener("click", doLockCharger);
document.getElementById("btnCharging").addEventListener("click", doCharging);
document.getElementById("btnCloseEvidence").addEventListener("click", hideEvidenceModal);

function saveState(){
  try {
    // Do not persist chargerOverrides: chargers should be idle on fresh page open.
    var toSave = { selectedCell: selectedCell, botState: {} };
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
    // Always start with empty overrides; do not restore old lock overlays.
    chargerOverrides = {};
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
    if (Math.random() < 0.5) {
      doSoftHazard();
      pushNarrative("[Auto] Generate SOFT");
    } else {
      doLockCharger();
      pushNarrative("[Auto] Lock Charger");
    }
  }, 200);
}, 15000);
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
