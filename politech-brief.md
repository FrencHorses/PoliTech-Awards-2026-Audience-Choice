# PoliTech Awards 2026 — Audience Vote Tool
## Context & Brief

---

### What this is

An interactive audience participation exercise for the PoliTech Awards 2026 final presentation event at Newspeak House. The PoliTech Awards is a grant-making exercise that evaluates and ranks civic technology projects using a structured methodology. At the final event, alongside the jury's decision, we want to surface a separate **audience winner** chosen by the people in the room.

---

### The problem it solves

Standard audience voting (show of hands, polling apps) treats all votes as equal and captures no reasoning. We want something richer — a way for each audience member to express *what they value* in civic tech, and have those values reflected in how projects are ranked for them personally. The aggregate of those individual value-based rankings produces a winner that genuinely reflects the room's collective priorities, not just popularity.

---

### How it works

1. **Before the event:** Organisers finalise a shortlist of 30–50 civic tech projects and load them into the tool with short descriptions.

2. **During the event:** A Google Form is shared with the audience (via QR code or link). Each person writes a short paragraph describing what they care about most in civic technology — open source, accountability, community participation, deployment scale, global reach, etc. No word limit; typically 2–5 sentences.

3. **After responses are collected:** The organiser exports the Google Form responses as a CSV and runs the tool locally. The tool sends each person's paragraph to Claude (Anthropic's AI) along with the full project list. Claude scores every project 0–100 based on how well it matches that person's stated values, and produces a ranked list for them.

4. **Aggregation:** Each project's scores are averaged across all respondents. The project with the highest average score is the audience winner.

5. **Output:** A single HTML file opens in the browser showing three views:
   - **Winner** — the audience's top project, with score and description
   - **Full leaderboard** — all projects ranked by aggregate average score
   - **By person** — each respondent's name, their paragraph, a one-sentence AI summary of their values, and their personal top 5 projects with rationales

---

### What makes this interesting

- The ranking is **value-driven**, not just preference-driven. Two people who both care about transparency might rank different projects first depending on whether they prioritise parliamentary accountability vs. corporate accountability — the LLM picks this up.
- It produces **a story**, not just a result. The by-person view lets the presenter say "here's what the room cared about" with specificity.
- It's **low friction** for the audience — writing a paragraph is faster and more natural than navigating a ranked-choice interface for 30+ projects.
- The AI reasoning is **legible** — every ranking comes with a one-sentence rationale, so the output isn't a black box.

---

### Current technical approach

A single Python file (`app.py`) that runs a local web server. The organiser:

1. Runs `python3 app.py` in Terminal
2. Opens `http://127.0.0.1:5000` in their browser
3. Enters their Anthropic API key and the path to the CSV
4. Clicks Analyse — results stream in live as each person is processed
5. Views and presents results from the browser

No cloud infrastructure, no deployment, no data leaves the organiser's machine except for the API calls to Anthropic (which receive only the response text and project descriptions — no names or identifying information).

**Dependencies:** Python 3, plus `anthropic`, `pandas`, and `flask` (installed via pip).

**Cost:** Approximately £0.10–0.15 total for 50 respondents using Claude Sonnet.

---

### Key design decisions

- **Free text over structured input** — sliders or multiple choice would be faster but would constrain what values people can express. A paragraph captures nuance a dropdown cannot.
- **Local tool over web app** — keeps it simple, avoids deployment complexity, and means no audience data is stored anywhere.
- **Average score as aggregation method** — straightforward and explainable to an audience. Alternative approaches (e.g. Borda count, ranked pairs) could be explored in future.
- **Per-person output** — originally the brief was winner-only, but surfacing individual rankings adds narrative richness and lets the presenter highlight interesting divergences in what the room valued.

---

### What still needs doing

- [ ] Replace placeholder project list with the real shortlist from `nwspk/politech-awards-2026`
- [ ] Fix browser-side file path input activation bug (current blocker)
- [ ] Test end-to-end with real API key and synthetic CSV
- [ ] Decide on event flow: will the form be open during the presentations, or only at the end?
- [ ] Prepare a short verbal explanation for the audience of how the tool works
