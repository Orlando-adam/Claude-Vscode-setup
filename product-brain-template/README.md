# ProductBrain Template

A personal second-brain system for product managers and product owners, designed to work with [Claude Code](https://claude.ai/code).

The idea: give Claude full context about who you are, what you're working on, and what's been decided — once, in files — so you never have to re-explain yourself at the start of a session.

---

## How it works

Claude Code automatically reads `CLAUDE.md` at the start of every session. That file tells it to load your other context files. From that point on, Claude knows:

- **Who you are** and how you like to work (`ME.md`, `SOUL.md`)
- **What you're building** and who the stakeholders are (`PRODUCT_CONTEXT.md`)
- **What's been decided** and what's still open (`DECISIONS.md`)

As you work, Claude prompts you to keep these files updated. Over time, the system gets smarter about your context.

---

## File structure

```
ProductBrain/
├── CLAUDE.md               ← Claude reads this automatically on every session start
├── ME.md                   ← Who you are, your background, your goals
├── SOUL.md                 ← How you think and like to work
├── PRODUCT_CONTEXT.md      ← Your products, stakeholders, constraints, tools
├── DECISIONS.md            ← Decision log + open questions
├── daily_logs/             ← Optional session notes, one file per day
│   └── YYYY-MM-DD.md
├── scripts/
│   └── heartbeat.py        ← Morning script: generates a daily priorities prompt
└── skills/
    ├── document_review.py  ← Review a doc against your product context
    ├── stakeholder_comms.py ← Draft comms in your voice
    └── decision_analysis.py ← Analyse a decision's impact
```

---

## Setup

1. Copy this folder to your machine (e.g. `~/ProductBrain/`)
2. Fill in each `.md` file with your own details — use the placeholder text as a guide
3. Open the folder in [Claude Code](https://claude.ai/code)
4. Claude will read `CLAUDE.md` automatically and load your context

That's it. No installs, no config, no API keys needed for the core system.

### Optional: daily heartbeat

Run each morning to get a prioritised focus prompt:

```bash
python3 ~/ProductBrain/scripts/heartbeat.py
```

Paste the output into Claude Code and you'll get a prioritised list of what to work on today, based on your context and recent session logs.

### Optional: graph viewer

Visualise how your files connect using the Brain Graph viewer (included separately in this repo):

```bash
python3 ~/ProductBrain/graph_viewer.py
# then open http://localhost:4322
```

---

## Tips

- **Keep the files short.** Claude reads them every session — dense files slow things down and dilute focus.
- **Update as you go.** Claude will prompt you to log decisions and context changes. Do it — the system compounds.
- **One decision per entry** in `DECISIONS.md`. The format exists for a reason: Why + Trade-offs + Status tells a future version of you (and Claude) everything needed.
- **Daily logs are optional** but useful if you work across multiple threads and need to pick up context the next day.

---

## What this is not

- Not a project management tool (use Jira, Linear, etc. for that)
- Not a note-taking app (use Notion, Obsidian, etc. for that)
- Not a replacement for documentation — it's context for an AI assistant, not a wiki

---

Shared as a template — adapt it to how you work.
