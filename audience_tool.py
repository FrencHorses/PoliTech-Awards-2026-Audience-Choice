#!/usr/bin/env python3
"""
PoliTech Awards 2026 — Audience Ranker
---------------------------------------
A local web app. No terminal needed after launch.

Usage:
    pip install anthropic pandas flask
    python app.py
    Open http://localhost:5000 in your browser

Edit the PROJECTS list and API key below before the event.
"""

import json
import os
import threading
import csv
from dotenv import load_dotenv
load_dotenv()
import time
import io
import anthropic
from flask import Flask, request, jsonify, Response, stream_with_context
from datetime import datetime

app = Flask(__name__)

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
ANTHROPIC_API_KEY  = os.environ.get("ANTHROPIC_API_KEY", "YOUR_KEY_HERE")
CSV_PATH           = os.environ.get("CSV_PATH", "responses.csv")
CANDIDATES_CSV     = os.environ.get("CANDIDATES_CSV", "candidates_with_descriptions.csv")
MODEL              = os.environ.get("MODEL", "claude-haiku-4-5")

NAME_COL      = "Name"
RESPONSE_COL  = "What qualities matter most to you in a civic technology project?"
TOP_N         = 5

# ─────────────────────────────────────────────
# PROJECTS — loaded from CANDIDATES_CSV
# ─────────────────────────────────────────────
def load_projects(path):
    projects = []
    with open(path, newline='', encoding='utf-8') as f:
        for i, row in enumerate(csv.DictReader(f)):
            name = row.get("project_name", "").strip()
            description = row.get("description", "").strip()
            url = row.get("url", "").strip()
            if name:
                projects.append({
                    "id": f"p{i+1:02d}",
                    "name": name,
                    "description": description,
                    "url": url,
                })
    return projects

PROJECTS = load_projects(CANDIDATES_CSV)
PROJECT_MAP = {p["id"]: p for p in PROJECTS}

SYSTEM_PROMPT = (
    "You are helping rank civic technology projects for a grant-making exercise at Newspeak House, "
    "London's college of political technology.\n\n"
    "You will receive a short paragraph from an audience member describing what they value in civic tech. "
    "Rank ALL of the following projects by how well they match those values, scoring each 0–100.\n\nProjects:\n"
    + "\n".join(
        f"- ID: {p['id']} | {p['name']}: {p['description']}"
        for p in PROJECTS
    )
    + "\n\nRespond ONLY with valid JSON, no markdown:\n"
    '{"ranking":[{"id":"p01","score":87,"reason":"One sentence"},...all projects...],"values_summary":"One sentence"}'
)

# ─────────────────────────────────────────────
# RANKING LOGIC
# ─────────────────────────────────────────────
def rank_person(client, response_text):
    msg = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": response_text}],
    )
    raw = msg.content[0].text.strip().replace("```json","").replace("```","").strip()
    return json.loads(raw)

def aggregate(all_rankings):
    scores = {}
    for entry in all_rankings:
        for item in entry["ranking"]["ranking"]:
            pid = item["id"]
            if pid not in scores:
                scores[pid] = {"total": 0, "count": 0}
            scores[pid]["total"] += item["score"]
            scores[pid]["count"] += 1
    result = []
    for pid, data in scores.items():
        avg = data["total"] / data["count"] if data["count"] else 0
        result.append({
            "id": pid,
            "name": PROJECT_MAP[pid]["name"],
            "avg_score": round(avg, 1),
            "vote_count": data["count"],
        })
    return sorted(result, key=lambda x: x["avg_score"], reverse=True)

# ─────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────
@app.route("/")
def index():
    return HTML_PAGE

@app.route("/projects")
def get_projects():
    return jsonify(PROJECTS)

@app.route("/run", methods=["POST"])
def run():
    api_key = ANTHROPIC_API_KEY
    if not api_key or api_key == "YOUR_KEY_HERE":
        return jsonify({"error": "ANTHROPIC_API_KEY is not set"}), 400

    if "csv" in request.files:
        f = request.files["csv"]
        try:
            content = f.stream.read().decode("utf-8")
            reader = csv.DictReader(io.StringIO(content))
            all_rows = list(reader)
            columns = reader.fieldnames or []
        except Exception as e:
            return jsonify({"error": f"Could not read uploaded CSV: {e}"}), 400
    else:
        try:
            with open(CSV_PATH, newline='', encoding='utf-8') as csvfile:
                reader = csv.DictReader(csvfile)
                all_rows = list(reader)
                columns = reader.fieldnames or []
        except Exception as e:
            return jsonify({"error": f"Could not read CSV at {CSV_PATH!r}: {e}"}), 400

    # Find response column — try exact match then fuzzy
    resp_col = None
    for col in columns:
        if col.strip().lower() == RESPONSE_COL.strip().lower():
            resp_col = col
            break
    if resp_col is None:
        for col in columns:
            if any(kw in col.lower() for kw in ("qualit", "value", "care", "matter")):
                resp_col = col
                break
    if resp_col is None:
        text_cols = [c for c in columns if c != NAME_COL]
        resp_col = text_cols[-1] if text_cols else None

    name_col = None
    for col in columns:
        if col.strip().lower() in ("name", "email", "email address", "your name"):
            name_col = col
            break
    if name_col is None:
        name_col = columns[1] if len(columns) > 1 else columns[0]

    rows = []
    for i, row in enumerate(all_rows):
        name = str(row.get(name_col, f"Respondent {i+1}")).strip()
        text = str(row.get(resp_col, "")).strip() if resp_col else ""
        if text and text.lower() not in ("nan", ""):
            rows.append({"name": name, "text": text})

    if not rows:
        return jsonify({"error": f"No valid responses found. Detected columns: {list(columns)}"}), 400

    def generate():
        client = anthropic.Anthropic(api_key=api_key)
        all_rankings = []
        total = len(rows)

        yield f"data: {json.dumps({'type':'start','total':total})}\n\n"

        for i, row in enumerate(rows):
            yield f"data: {json.dumps({'type':'progress','index':i,'name':row['name'],'total':total})}\n\n"
            try:
                ranking = rank_person(client, row["text"])
                entry = {"name": row["name"], "response_text": row["text"], "ranking": ranking}
                all_rankings.append(entry)
                yield f"data: {json.dumps({'type':'person_done','index':i,'name':row['name'],'values_summary':ranking.get('values_summary',''),'top':ranking['ranking'][:TOP_N]})}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'type':'person_error','index':i,'name':row['name'],'error':str(e)})}\n\n"

        agg = aggregate(all_rankings)
        yield f"data: {json.dumps({'type':'complete','aggregate':agg,'people':all_rankings,'generated_at':datetime.now().strftime('%d %b %Y, %H:%M')})}\n\n"

    return Response(stream_with_context(generate()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

# ─────────────────────────────────────────────
# HTML — everything in one string
# ─────────────────────────────────────────────
HTML_PAGE = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PoliTech Awards 2026</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=DM+Mono:ital,wght@0,300;0,400;0,500;1,300&family=Cormorant+Garamond:ital,wght@0,400;0,600;1,400;1,600&display=swap" rel="stylesheet">
<style>
:root {
  --bg: #F9F7F2;
  --card: #FFFFFF;
  --ink: #1E1C18;
  --muted: #6A6760;
  --hint: #A09D98;
  --border: rgba(30,28,24,0.1);
  --border-md: rgba(30,28,24,0.18);
  --tc: #C4512A;
  --tc-bg: #F8EDE8;
  --tc-border: rgba(196,81,42,0.22);
  --gold: #96780A;
  --gold-bg: #F6F2DC;
  --gold-border: rgba(150,120,10,0.25);
  --silver: #7A8FA6;
  --bronze: #A06C3A;
  --green: #2D7A4F;
  --green-bg: #EDF5F0;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
html, body { height: 100%; }
body {
  font-family: 'DM Mono', monospace;
  background: var(--bg);
  color: var(--ink);
  font-size: 13px;
  line-height: 1.6;
}

/* ── LAYOUT ── */
.shell { display: flex; height: 100vh; overflow: hidden; }
.sidebar {
  width: 300px;
  flex-shrink: 0;
  background: var(--card);
  border-right: 1px solid var(--border-md);
  display: flex;
  flex-direction: column;
  overflow-y: auto;
}
.main { flex: 1; overflow-y: auto; }

/* ── SIDEBAR ── */
.sidebar-head {
  padding: 2rem 1.75rem 1.5rem;
  border-bottom: 1px solid var(--border);
}
.wordmark {
  font-family: 'Cormorant Garamond', serif;
  font-size: 20px;
  font-weight: 600;
  color: var(--ink);
  margin-bottom: 4px;
}
.wordmark em { color: var(--tc); font-style: italic; }
.subtitle { font-size: 11px; color: var(--hint); letter-spacing: 0.04em; }

.sidebar-section { padding: 1.25rem 1.75rem; border-bottom: 1px solid var(--border); }
.sidebar-label {
  font-size: 10px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--hint);
  margin-bottom: 10px;
}

/* key input */
.key-input {
  width: 100%;
  padding: 9px 10px;
  font-family: 'DM Mono', monospace;
  font-size: 11px;
  border: 1px solid var(--border-md);
  border-radius: 6px;
  background: var(--bg);
  color: var(--ink);
  outline: none;
  transition: border-color 0.15s;
  letter-spacing: 0.02em;
}
.key-input:focus { border-color: var(--tc); }

/* drop zone */
.drop-zone {
  border: 1.5px dashed var(--border-md);
  border-radius: 8px;
  padding: 1.5rem 1rem;
  text-align: center;
  transition: border-color 0.15s, background 0.15s;
}
.drop-zone.drag { border-color: var(--tc); background: var(--tc-bg); }
.drop-icon { font-size: 24px; margin-bottom: 8px; }
.drop-text { font-size: 11px; color: var(--muted); line-height: 1.6; }
.drop-text strong { color: var(--ink); font-weight: 500; }
.file-chosen {
  margin-top: 8px;
  font-size: 11px;
  color: var(--green);
  display: none;
}

/* run button */
.run-btn {
  width: 100%;
  padding: 12px;
  background: var(--ink);
  color: #F9F7F2;
  font-family: 'DM Mono', monospace;
  font-size: 11px;
  letter-spacing: 0.07em;
  border: none;
  border-radius: 7px;
  cursor: pointer;
  transition: background 0.15s, transform 0.1s;
  margin-top: 1rem;
}
.run-btn:hover:not(:disabled) { background: #3a3830; }
.run-btn:active:not(:disabled) { transform: scale(0.98); }
.run-btn:disabled { background: var(--hint); cursor: not-allowed; }

/* progress feed */
.progress-feed {
  padding: 1rem 1.75rem;
  flex: 1;
  display: none;
}
.feed-item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 6px 0;
  font-size: 11px;
  color: var(--muted);
  border-bottom: 1px solid var(--border);
  animation: fadeSlide 0.25s ease;
}
@keyframes fadeSlide { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: none; } }
.feed-dot {
  width: 6px; height: 6px;
  border-radius: 50%;
  background: var(--hint);
  margin-top: 5px;
  flex-shrink: 0;
}
.feed-dot.done { background: var(--green); }
.feed-dot.err { background: var(--tc); }
.feed-dot.spinning {
  background: transparent;
  border: 1.5px solid var(--tc);
  border-top-color: transparent;
  animation: spin 0.7s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
.feed-name { font-weight: 500; color: var(--ink); }
.feed-val { font-style: italic; color: var(--hint); font-size: 10px; }

/* sidebar nav tabs */
.nav-tabs {
  padding: 1rem 1.75rem 0;
  display: none;
}
.nav-tab {
  display: block;
  width: 100%;
  text-align: left;
  padding: 9px 12px;
  margin-bottom: 3px;
  font-family: 'DM Mono', monospace;
  font-size: 11px;
  letter-spacing: 0.04em;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
  transition: background 0.12s, color 0.12s;
}
.nav-tab:hover { background: var(--bg); color: var(--ink); }
.nav-tab.active { background: var(--tc-bg); color: var(--tc); }

/* ── MAIN AREA ── */
.main-inner { padding: 3rem; max-width: 980px; }

/* splash */
.splash-hero {
  padding: 5rem 0 3rem;
  max-width: 520px;
}
.splash-eyebrow {
  font-size: 10px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--tc);
  margin-bottom: 1rem;
}
.splash-h1 {
  font-family: 'Cormorant Garamond', serif;
  font-size: 52px;
  font-weight: 400;
  line-height: 1.1;
  color: var(--ink);
  margin-bottom: 1.25rem;
}
.splash-h1 em { font-style: italic; color: var(--tc); }
.splash-body { font-size: 13px; color: var(--muted); line-height: 1.85; max-width: 400px; }
.splash-steps {
  margin-top: 2.5rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}
.splash-step {
  display: flex;
  align-items: flex-start;
  gap: 1rem;
}
.step-num {
  font-family: 'Cormorant Garamond', serif;
  font-size: 28px;
  font-weight: 600;
  color: var(--tc);
  line-height: 1;
  min-width: 28px;
}
.step-text { font-size: 12px; color: var(--muted); line-height: 1.7; padding-top: 4px; }
.step-text strong { color: var(--ink); font-weight: 500; }

/* panels */
.panel { display: none; }
.panel.active { display: block; }

/* section header */
.section-eyebrow {
  font-size: 10px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--tc);
  margin-bottom: 0.75rem;
  display: flex;
  align-items: center;
  gap: 10px;
}
.section-eyebrow::after { content: ''; flex: 1; height: 1px; background: var(--tc-border); }

/* ── WINNER ── */
.winner-card {
  background: var(--gold-bg);
  border: 1px solid var(--gold-border);
  border-radius: 14px;
  padding: 3rem 3rem 2.5rem;
  margin-bottom: 2.5rem;
  position: relative;
  overflow: hidden;
}
.winner-card::before {
  content: '★';
  position: absolute;
  right: 2.5rem;
  top: 2rem;
  font-size: 80px;
  color: rgba(150,120,10,0.08);
  line-height: 1;
}
.winner-eyebrow {
  font-size: 10px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--gold);
  margin-bottom: 0.75rem;
}
.winner-name {
  font-family: 'Cormorant Garamond', serif;
  font-size: 54px;
  font-weight: 600;
  color: var(--ink);
  line-height: 1.05;
  margin-bottom: 0.5rem;
}
.winner-meta { font-size: 12px; color: var(--muted); margin-bottom: 1.25rem; }
.winner-desc {
  font-size: 13px;
  color: var(--muted);
  line-height: 1.8;
  max-width: 480px;
  font-style: italic;
  padding-top: 1.25rem;
  border-top: 1px solid var(--gold-border);
}

/* stats row */
.stats-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 1rem;
  margin-bottom: 2.5rem;
}
.stat-card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 1rem 1.25rem;
}
.stat-num {
  font-family: 'Cormorant Garamond', serif;
  font-size: 34px;
  font-weight: 600;
  color: var(--tc);
  display: block;
  line-height: 1;
  margin-bottom: 4px;
}
.stat-label { font-size: 10px; letter-spacing: 0.08em; text-transform: uppercase; color: var(--hint); }

/* ── LEADERBOARD ── */
.lb-wrap {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 10px;
  overflow: hidden;
}
.lb-head {
  display: grid;
  grid-template-columns: 44px 1fr 200px 56px 76px;
  padding: 10px 1.5rem;
  border-bottom: 1px solid var(--border);
  font-size: 10px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--hint);
}
.lb-row {
  display: grid;
  grid-template-columns: 44px 1fr 200px 56px 76px;
  padding: 13px 1.5rem;
  border-bottom: 1px solid var(--border);
  align-items: center;
  transition: background 0.1s;
}
.lb-row:last-child { border-bottom: none; }
.lb-row:hover { background: var(--bg); }
.lb-top { background: rgba(150,120,10,0.03); }
.lb-rank { font-family: 'Cormorant Garamond', serif; font-size: 20px; font-weight: 600; color: var(--hint); }
.lb-rank.gold { color: var(--gold); }
.lb-rank.silver { color: var(--silver); }
.lb-rank.bronze { color: var(--bronze); }
.lb-name { font-size: 13px; font-weight: 500; color: var(--ink); }
.lb-bar-wrap { display: flex; align-items: center; gap: 8px; }
.lb-bar-bg { height: 4px; background: var(--border-md); border-radius: 2px; flex: 1; overflow: hidden; }
.lb-bar-fill { height: 100%; background: var(--tc); border-radius: 2px; transition: width 0.6s ease; }
.lb-score { font-size: 12px; color: var(--muted); text-align: right; }
.lb-votes { font-size: 11px; color: var(--hint); text-align: right; }

/* ── PEOPLE GRID ── */
.people-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 1.25rem;
}
.person-card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 10px;
  overflow: hidden;
  animation: fadeSlide 0.3s ease;
}
.person-head {
  display: flex;
  align-items: center;
  gap: 11px;
  padding: 1.1rem 1.25rem 1rem;
  border-bottom: 1px solid var(--border);
}
.avatar {
  width: 38px; height: 38px;
  border-radius: 50%;
  background: var(--tc-bg);
  color: var(--tc);
  font-size: 13px;
  font-weight: 500;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.p-name { font-size: 13px; font-weight: 500; color: var(--ink); }
.p-summary { font-size: 11px; color: var(--muted); font-style: italic; line-height: 1.5; }
.person-response {
  padding: 0.9rem 1.25rem;
  background: var(--bg);
  border-bottom: 1px solid var(--border);
}
.resp-label { font-size: 10px; letter-spacing: 0.1em; text-transform: uppercase; color: var(--hint); margin-bottom: 5px; }
.resp-text { font-size: 11px; color: var(--muted); line-height: 1.75; font-style: italic; }
.person-rows { padding: 0.5rem 1.25rem 0.75rem; }
.p-row {
  display: flex;
  gap: 9px;
  align-items: flex-start;
  padding: 7px 0;
  border-bottom: 1px solid var(--border);
}
.p-row:last-child { border-bottom: none; }
.p-medal { font-size: 14px; min-width: 22px; flex-shrink: 0; padding-top: 1px; }
.p-row-body { flex: 1; }
.p-proj { font-size: 12px; font-weight: 500; color: var(--ink); margin-bottom: 2px; }
.p-reason { font-size: 11px; color: var(--muted); line-height: 1.5; margin-bottom: 4px; }
.mini-bar { display: flex; align-items: center; gap: 6px; }
.mini-bg { height: 3px; background: var(--border-md); border-radius: 2px; flex: 1; overflow: hidden; }
.mini-fill { height: 100%; background: var(--tc); border-radius: 2px; }
.mini-score { font-size: 10px; color: var(--hint); min-width: 22px; text-align: right; }

/* processing card (placeholder) */
.person-card.processing {
  opacity: 0.6;
  border-style: dashed;
}
.person-card.processing .person-head { background: var(--bg); }

/* error */
.error-banner {
  background: #FDF0EF;
  border: 1px solid rgba(196,81,42,0.25);
  border-radius: 8px;
  padding: 1rem 1.25rem;
  font-size: 12px;
  color: #C0392B;
  margin-bottom: 1.5rem;
  display: none;
}
</style>
</head>
<body>

<div class="shell">

  <!-- SIDEBAR -->
  <aside class="sidebar">
    <div class="sidebar-head">
      <div class="wordmark">PoliTech <em>Awards</em> 2026</div>
      <div class="subtitle">Audience vote analyser</div>
    </div>

    <div class="sidebar-section">
      <div class="sidebar-label">Responses CSV</div>
      <div class="drop-zone" id="drop-zone" onclick="document.getElementById('csv-input').click()">
        <div class="drop-icon">📄</div>
        <div class="drop-text"><strong>Click to upload</strong> or drag &amp; drop<br>Google Form export (.csv)</div>
        <div class="file-chosen" id="file-chosen"></div>
      </div>
      <input type="file" id="csv-input" accept=".csv" style="display:none">
      <button class="run-btn" id="run-btn" onclick="runAnalysis()">
        Analyse responses →
      </button>
    </div>

    <div class="progress-feed" id="progress-feed">
      <div class="sidebar-label">Processing</div>
      <div id="feed-list"></div>
    </div>

    <nav class="nav-tabs" id="nav-tabs">
      <div class="sidebar-label" style="margin-top:0.5rem">Results</div>
      <button class="nav-tab active" onclick="showPanel('winner')">Winner</button>
      <button class="nav-tab" onclick="showPanel('leaderboard')">Full leaderboard</button>
      <button class="nav-tab" onclick="showPanel('people')">By person</button>
    </nav>
  </aside>

  <!-- MAIN -->
  <main class="main">
    <div class="main-inner">

      <div class="error-banner" id="error-banner"></div>

      <!-- SPLASH -->
      <div id="panel-splash" class="panel active">
        <div class="splash-hero">
          <div class="splash-eyebrow">Audience vote · grant-making tool</div>
          <h1 class="splash-h1">Who does<br>the room <em>choose</em>?</h1>
          <p class="splash-body">
            Each audience member's response is read by Claude, which ranks all shortlisted projects
            against their stated values. Hit <strong>Analyse responses</strong> to see who the room picks.
          </p>
        </div>
      </div>

      <!-- WINNER -->
      <div id="panel-winner" class="panel">
        <div id="winner-card-wrap"></div>
        <div class="stats-row" id="stats-row"></div>
      </div>

      <!-- LEADERBOARD -->
      <div id="panel-leaderboard" class="panel">
        <div class="section-eyebrow" style="margin-bottom:1.25rem">All projects · aggregate score</div>
        <div class="lb-wrap">
          <div class="lb-head">
            <div>#</div><div>Project</div><div>Score</div><div style="text-align:right">Avg</div><div style="text-align:right">Votes</div>
          </div>
          <div id="lb-body"></div>
        </div>
      </div>

      <!-- PEOPLE -->
      <div id="panel-people" class="panel">
        <div class="section-eyebrow" style="margin-bottom:1.25rem">Individual rankings</div>
        <div class="people-grid" id="people-grid"></div>
      </div>

    </div>
  </main>
</div>

<script>
const PROJECT_MAP = {};

fetch('/projects').then(r => r.json()).then(ps => {
  ps.forEach(p => PROJECT_MAP[p.id] = p);
});

const csvInput = document.getElementById('csv-input');
const dropZone = document.getElementById('drop-zone');
const fileChosen = document.getElementById('file-chosen');
const runBtn = document.getElementById('run-btn');

csvInput.addEventListener('change', () => {
  if (csvInput.files[0]) {
    fileChosen.textContent = csvInput.files[0].name;
    fileChosen.style.display = 'block';
  }
});

dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('drag'); });
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag'));
dropZone.addEventListener('drop', e => {
  e.preventDefault();
  dropZone.classList.remove('drag');
  const file = e.dataTransfer.files[0];
  if (file) {
    const dt = new DataTransfer();
    dt.items.add(file);
    csvInput.files = dt.files;
    fileChosen.textContent = file.name;
    fileChosen.style.display = 'block';
  }
});


// Panels
function showPanel(name) {
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
  document.getElementById('panel-' + name).classList.add('active');
  event.target.classList.add('active');
}

// Feed
function addFeedItem(text, state, sub) {
  const feed = document.getElementById('feed-list');
  const div = document.createElement('div');
  div.className = 'feed-item';
  div.innerHTML = `<div class="feed-dot ${state}"></div><div><div class="feed-name">${text}</div>${sub ? `<div class="feed-val">${sub}</div>` : ''}</div>`;
  feed.prepend(div);
}

// People grid — add placeholder while processing
function addProcessingCard(name) {
  const grid = document.getElementById('people-grid');
  const initials = name.split(' ').slice(0,2).map(w=>w[0]||'').join('').toUpperCase() || '?';
  const card = document.createElement('div');
  card.className = 'person-card processing';
  card.id = 'card-' + name.replace(/\W/g,'_');
  card.innerHTML = `
    <div class="person-head">
      <div class="avatar">${initials}</div>
      <div><div class="p-name">${name}</div><div class="p-summary">Ranking in progress…</div></div>
    </div>`;
  grid.appendChild(card);
}

function fillPersonCard(name, summary, top) {
  const card = document.getElementById('card-' + name.replace(/\W/g,'_'));
  if (!card) return;
  card.classList.remove('processing');
  const initials = name.split(' ').slice(0,2).map(w=>w[0]||'').join('').toUpperCase() || '?';
  const medals = ['🥇','🥈','🥉','4.','5.'];
  const maxScore = top[0]?.score || 100;
  const rows = top.map((item, i) => {
    const p = PROJECT_MAP[item.id] || {};
    const pct = Math.round(item.score / maxScore * 100);
    return `<div class="p-row">
      <div class="p-medal">${medals[i]}</div>
      <div class="p-row-body">
        <div class="p-proj">${p.name || item.id}</div>
        <div class="p-reason">${item.reason}</div>
        <div class="mini-bar"><div class="mini-bg"><div class="mini-fill" style="width:${pct}%"></div></div><div class="mini-score">${item.score}</div></div>
      </div>
    </div>`;
  }).join('');
  card.innerHTML = `
    <div class="person-head">
      <div class="avatar">${initials}</div>
      <div><div class="p-name">${name}</div><div class="p-summary">"${summary}"</div></div>
    </div>
    <div class="person-rows">${rows}</div>`;
}

// Leaderboard — update live
function renderLeaderboard(agg) {
  const body = document.getElementById('lb-body');
  const max = agg[0]?.avg_score || 100;
  const rankCls = ['gold','silver','bronze'];
  body.innerHTML = agg.map((s,i) => {
    const pct = Math.round(s.avg_score / max * 100);
    return `<div class="lb-row ${i<3?'lb-top':''}">
      <div class="lb-rank ${rankCls[i]||''}">${i+1}</div>
      <div class="lb-name">${s.name}</div>
      <div class="lb-bar-wrap"><div class="lb-bar-bg"><div class="lb-bar-fill" style="width:${pct}%"></div></div></div>
      <div class="lb-score">${s.avg_score}</div>
      <div class="lb-votes">${s.vote_count} votes</div>
    </div>`;
  }).join('');
}

// Winner
function renderWinner(agg, total) {
  const w = agg[0];
  const p = PROJECT_MAP[w.id] || {};
  document.getElementById('winner-card-wrap').innerHTML = `
    <div class="winner-card">
      <div class="winner-eyebrow">Audience winner</div>
      <div class="winner-name">${w.name}</div>
      <div class="winner-meta">Average score ${w.avg_score} · ${w.vote_count} of ${total} voters</div>
      <div class="winner-desc">${p.description || ''}</div>
    </div>`;

  const runner = agg[1];
  document.getElementById('stats-row').innerHTML = `
    <div class="stat-card"><span class="stat-num">${total}</span><span class="stat-label">Respondents</span></div>
    <div class="stat-card"><span class="stat-num">${Object.keys(PROJECT_MAP).length}</span><span class="stat-label">Projects ranked</span></div>
    <div class="stat-card"><span class="stat-num">${w.avg_score}</span><span class="stat-label">Winning avg score</span></div>
    <div class="stat-card"><span class="stat-num">${runner?.name?.split(' ')[0] || '—'}</span><span class="stat-label">Runner-up</span></div>`;
}

function showError(msg) {
  const banner = document.getElementById('error-banner');
  banner.textContent = msg;
  banner.style.display = 'block';
  document.getElementById('panel-splash').classList.add('active');
  runBtn.disabled = false;
  runBtn.textContent = 'Analyse responses →';
}

// Main run
async function runAnalysis() {
  const file = csvInput.files[0];
  if (!file) { showError('Please upload a CSV file first.'); return; }

  // Hide error, show progress
  document.getElementById('error-banner').style.display = 'none';
  document.getElementById('progress-feed').style.display = 'block';
  document.getElementById('feed-list').innerHTML = '';
  document.getElementById('people-grid').innerHTML = '';
  document.getElementById('panel-splash').classList.remove('active');
  document.getElementById('nav-tabs').style.display = 'block';

  runBtn.disabled = true;
  runBtn.textContent = 'Running…';

  let resp;
  try {
    const form = new FormData();
    form.append('csv', file);
    resp = await fetch('/run', { method: 'POST', body: form });
  } catch (e) {
    showError('Could not reach the server. Is the app still running?');
    return;
  }

  if (!resp.ok) {
    try {
      const err = await resp.json();
      showError(err.error || 'Something went wrong.');
    } catch(e) {
      showError('Server returned an error: ' + e.message);
    }
    return;
  }

  try {
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\\n\\n');
      buffer = lines.pop();
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const ev = JSON.parse(line.slice(6));
        handleEvent(ev);
      }
    }
  } catch (e) {
    showError('Error reading results: ' + e.message);
    return;
  }

  runBtn.textContent = 'Analyse responses →';
}

function handleEvent(ev) {
  if (ev.type === 'start') {
    addFeedItem(`Processing ${ev.total} responses`, 'done', null);
    showPanel2('people');
  }
  else if (ev.type === 'progress') {
    addFeedItem(ev.name, 'spinning', 'Ranking…');
    addProcessingCard(ev.name);
  }
  else if (ev.type === 'person_done') {
    // Update feed dot
    const dots = document.querySelectorAll('.feed-dot.spinning');
    if (dots[0]) dots[0].className = 'feed-dot done';
    fillPersonCard(ev.name, ev.values_summary, ev.top);
  }
  else if (ev.type === 'person_error') {
    const dots = document.querySelectorAll('.feed-dot.spinning');
    if (dots[0]) dots[0].className = 'feed-dot err';
  }
  else if (ev.type === 'complete') {
    addFeedItem('Done', 'done', `${ev.aggregate.length} projects scored`);
    renderLeaderboard(ev.aggregate);
    renderWinner(ev.aggregate, ev.people.length);
    showPanel2('winner');
    runBtn.disabled = false;
  }
}

function showPanel2(name) {
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
  document.getElementById('panel-' + name).classList.add('active');
  const tabs = document.querySelectorAll('.nav-tab');
  const map = { winner: 0, leaderboard: 1, people: 2 };
  if (tabs[map[name]]) tabs[map[name]].classList.add('active');
}
</script>
</body>
</html>'''

# ─────────────────────────────────────────────
# LAUNCH
# ─────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    local = os.environ.get("FLY_APP_NAME") is None
    if local:
        import webbrowser
        print("\nPoliTech Awards 2026 — Audience Ranker")
        print("────────────────────────────────────────")
        threading.Timer(1.2, lambda: webbrowser.open(f"http://localhost:{port}")).start()
    app.run(host="0.0.0.0", port=port, debug=False)
