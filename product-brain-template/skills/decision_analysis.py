#!/usr/bin/env python3
"""
Think through a decision before committing to it.

Usage:
  python3 ~/ProductBrain/skills/decision_analysis.py

You'll be prompted interactively.
Or pass arguments:

  python3 ~/ProductBrain/skills/decision_analysis.py \
    --decision "Pause the Dancing Dad redesign for 6 weeks" \
    --areas "timeline,resources,stakeholder"

Areas (comma-separated, pick what applies):
  timeline      — schedule and delivery impact
  resources     — team capacity and budget
  technical     — complexity, debt, architectural impact
  user          — impact on users or product experience
  stakeholder   — org, relationship, or political impact
  strategic     — alignment with longer-term direction
"""

import os
import sys
import argparse

BRAIN_ROOT = os.path.expanduser('~/ProductBrain')

AREA_GUIDANCE = {
    'timeline': 'How does this affect delivery schedules? What gets delayed, accelerated, or dropped?',
    'resources': 'What does this cost in team time or budget? What else gets de-prioritised as a result?',
    'technical': 'What is the technical complexity? Does this create debt, risk, or architectural lock-in?',
    'user': 'How does this affect the people using the product? Better or worse experience? Who wins and who loses?',
    'stakeholder': 'Who cares about this decision? Who will push back? What do they need to hear?',
    'strategic': 'Does this move us closer to or further from where we want to be in 12 months?',
}


def read_file(path: str) -> str:
    if os.path.exists(path):
        with open(path) as f:
            return f.read()
    return ''


def read_memory() -> dict:
    return {
        'context': read_file(os.path.join(BRAIN_ROOT, 'PRODUCT_CONTEXT.md')),
        'decisions': read_file(os.path.join(BRAIN_ROOT, 'DECISIONS.md')),
    }


def build_prompt(decision: str, areas: list, memory: dict) -> str:
    area_lines = '\n'.join(
        f'- **{a.strip().capitalize()}**: {AREA_GUIDANCE.get(a.strip(), "Analyse the impact.")}'
        for a in areas
    )

    return f"""Help me think through this decision before I commit to it.

## My context

### Products and constraints
{memory['context']}

### Past decisions (for consistency)
{memory['decisions']}

## The decision I'm considering

{decision}

## Areas to analyse

{area_lines}

## What I need

For each area above:
1. **Impact**: What actually changes?
2. **Trade-off**: What are we gaining and what are we giving up?
3. **Risk**: What could go wrong?
4. **Mitigation**: How do we reduce that risk?

Then:
- **Recommendation**: Should I do this? (Yes / No / Depends on X)
- **If yes**: What should happen first?
- **If no**: What's the alternative?
- **If depends**: What's the one thing I need to know before deciding?

Be direct. I'm not looking for validation — I want to know what I'd be missing.
"""


def prompt_interactive() -> tuple:
    print('\n=== Decision Analysis ===\n')
    print('Describe the decision you\'re considering:')
    decision = input('Decision: ').strip()
    print('\nAreas: timeline | resources | technical | user | stakeholder | strategic')
    areas_input = input('Which areas apply? (comma-separated): ').strip()
    areas = [a.strip() for a in areas_input.split(',') if a.strip()]
    return decision, areas


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--decision', default=None)
    parser.add_argument('--areas', default=None)
    args, _ = parser.parse_known_args()

    if args.decision and args.areas:
        decision = args.decision
        areas = [a.strip() for a in args.areas.split(',') if a.strip()]
    else:
        decision, areas = prompt_interactive()

    if not decision or not areas:
        print('Error: need --decision and --areas.')
        sys.exit(1)

    memory = read_memory()
    prompt = build_prompt(decision, areas, memory)

    print('\n--- PASTE THIS INTO CLAUDE CODE ---\n')
    print(prompt)
    print('--- END OF PROMPT ---\n')


if __name__ == '__main__':
    main()
