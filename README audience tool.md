# PoliTech Awards 2026 — Audience Ranker

A local web app. No deployment, no terminal interaction after launch.

## Setup

```bash
pip install anthropic pandas flask
```

## Run

```bash
python audience_tool.py
```

Your browser opens automatically at http://localhost:5000.

## Before the event — edit audience_tool.py

Two things at the top of the file:

**1. PROJECTS list** — replace the placeholder entries with your real shortlist.
   Richer descriptions = better rankings. Aim for 2–3 sentences per project.

**2. RESPONSE_COL** — paste in the exact text of your Google Form question.
   This becomes the column header in the CSV export. The app also tries to
   auto-detect it if the match isn't exact.

The API key is entered in the browser UI — no need to hardcode it.

## Day-of flow

1. `python audience_tool.py` → browser opens
2. Paste your Anthropic API key into the sidebar field
3. Download Google Form responses as CSV (Responses tab → ⋮ → Download .csv)
4. Drop the CSV into the upload zone
5. Click "Analyse responses →"
6. Watch each person get ranked live in the By Person tab
7. When done, the Winner tab opens automatically

## Cost

~$0.003 per response on claude-sonnet-4.
50 respondents ≈ $0.15 total.
