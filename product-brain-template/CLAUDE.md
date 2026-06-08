# ProductBrain — Second Brain Directory

This directory is the memory system for everything [Your Name] does. Read all three files below in full before responding.

## Load on every session

1. [SOUL.md](SOUL.md) — working style, communication preferences, decision-making approach
2. [PRODUCT_CONTEXT.md](PRODUCT_CONTEXT.md) — products, stakeholders, constraints, tools
3. [DECISIONS.md](DECISIONS.md) — decision log and open questions

## Behaviour rules

- Always write in [your preferred language/variant — e.g. British English]
- Never re-explain [your name]'s own context back to them
- When a decision is made during a session, suggest capturing it in DECISIONS.md using the standard format
- When product context changes (new stakeholder, new constraint, product stage change), suggest updating PRODUCT_CONTEXT.md
- When working style feedback is given, suggest updating SOUL.md
- Surface trade-offs — don't make recommendations without naming what's being sacrificed
- If a new action contradicts a past decision in DECISIONS.md, flag it before proceeding
- **Update these files as we work. This system improves through use.**

## Skills available

- [skills/document_review.py](skills/document_review.py) — structured document review against product context
- [skills/stakeholder_comms.py](skills/stakeholder_comms.py) — communication drafting in your voice
- [skills/decision_analysis.py](skills/decision_analysis.py) — decision impact analysis
- [scripts/heartbeat.py](scripts/heartbeat.py) — daily priorities summary

## How this system works

Claude Code reads `CLAUDE.md` automatically at the start of every session. This file tells it to load the other three. The result: every Claude Code session starts with full context about who you are, what you're working on, and what's been decided — without you having to re-explain anything.

**To get the most out of this system:**
- Update the files as decisions are made (Claude will prompt you)
- Run `heartbeat.py` each morning to generate a prioritised daily focus prompt
- Use the skills in `/skills` for structured document reviews, comms drafting, and decision analysis
- Use `graph_viewer.py` to visualise how your files connect (requires Python 3)
