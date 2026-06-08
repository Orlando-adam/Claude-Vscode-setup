#!/usr/bin/env python3
"""
Draft stakeholder communication in your voice.

Usage:
  python3 ~/ProductBrain/skills/stakeholder_comms.py

You'll be prompted for: who, what type, and context.
Or pass arguments directly:

  python3 ~/ProductBrain/skills/stakeholder_comms.py \
    --to "Alice" \
    --type "status_update" \
    --context "[Product] sprint completed, delayed by one week due to API changes"

Types:
  status_update     — progress update on a product or feature
  request_decision  — you need a call made by someone above you
  communicate_change — something is changing that affects them
  escalate_issue    — something is blocked or going wrong
  follow_up         — chasing a previous conversation or request
  decline_request   — saying no (or not yet) to something they asked for
"""

import os
import sys
import argparse

BRAIN_ROOT = os.path.expanduser('~/ProductBrain')


def read_file(path: str) -> str:
    if os.path.exists(path):
        with open(path) as f:
            return f.read()
    return ''


def read_memory() -> dict:
    return {
        'soul': read_file(os.path.join(BRAIN_ROOT, 'SOUL.md')),
        'context': read_file(os.path.join(BRAIN_ROOT, 'PRODUCT_CONTEXT.md')),
        'decisions': read_file(os.path.join(BRAIN_ROOT, 'DECISIONS.md')),
    }


TYPE_GUIDANCE = {
    'status_update': 'What has happened, what\'s next, and whether we\'re on track. No surprises.',
    'request_decision': 'What decision is needed, what the options are, what you recommend, and what happens if nothing is decided.',
    'communicate_change': 'What is changing, why, what the impact is on them, and what (if anything) you need from them.',
    'escalate_issue': 'What the problem is, what you\'ve already tried, what\'s blocked, and what you need to unblock it.',
    'follow_up': 'What you\'re following up on, what you need, and a clear ask.',
    'decline_request': 'Acknowledge the request, explain why it\'s not happening (or not now), offer an alternative if there is one.',
}


def build_prompt(to: str, comm_type: str, context: str, memory: dict) -> str:
    guidance = TYPE_GUIDANCE.get(comm_type, 'Be clear about what you want and what action is needed.')

    return f"""Draft a {comm_type.replace('_', ' ')} communication to {to}.

## My working style (for tone and voice)
{memory['soul']}

## My product context (for accuracy)
{memory['context']}

## Relevant decisions (for consistency)
{memory['decisions']}

## What to communicate

**To:** {to}
**Type:** {comm_type.replace('_', ' ')}
**Context:** {context}

**Guidance for this type:** {guidance}

## Requirements

- British English
- Maximum 3 short paragraphs — shorter is better
- Professional but human — not robotic or overly formal
- Match the communication style from SOUL.md
- End with a clear, specific ask or next step (if one is needed)
- Do NOT include a subject line unless I ask for one
- Do NOT send — I will review and edit before using

Draft the message now.
"""


def prompt_interactive() -> tuple:
    print('\n=== Stakeholder Comms ===\n')
    to = input('Who is this to? (name or role): ').strip()
    print('\nTypes: status_update | request_decision | communicate_change | escalate_issue | follow_up | decline_request')
    comm_type = input('Communication type: ').strip()
    print('\nBriefly describe what you need to communicate:')
    context = input('Context: ').strip()
    return to, comm_type, context


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--to', default=None)
    parser.add_argument('--type', dest='comm_type', default=None)
    parser.add_argument('--context', default=None)
    args, _ = parser.parse_known_args()

    if args.to and args.comm_type and args.context:
        to, comm_type, context = args.to, args.comm_type, args.context
    else:
        to, comm_type, context = prompt_interactive()

    if not to or not comm_type or not context:
        print('Error: need --to, --type, and --context.')
        sys.exit(1)

    memory = read_memory()
    prompt = build_prompt(to, comm_type, context, memory)

    print('\n--- PASTE THIS INTO CLAUDE CODE ---\n')
    print(prompt)
    print('--- END OF PROMPT ---\n')


if __name__ == '__main__':
    main()
