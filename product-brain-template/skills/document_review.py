#!/usr/bin/env python3
"""
Review a document against your product context.

Usage:
  python3 ~/ProductBrain/skills/document_review.py <path-to-doc> [review_type]

review_type: prd | design | stakeholder_request | spec | proposal | contract
             (defaults to 'document' if not specified)

Examples:
  python3 ~/ProductBrain/skills/document_review.py ~/Downloads/smype-prd.md prd
  python3 ~/ProductBrain/skills/document_review.py ~/Documents/partner-proposal.pdf proposal
"""

import os
import sys

BRAIN_ROOT = os.path.expanduser('~/ProductBrain')


def read_file(path: str) -> str:
    expanded = os.path.expanduser(path)
    if not os.path.exists(expanded):
        return ''
    with open(expanded) as f:
        return f.read()


def read_memory() -> dict:
    return {
        'context': read_file(os.path.join(BRAIN_ROOT, 'PRODUCT_CONTEXT.md')),
        'decisions': read_file(os.path.join(BRAIN_ROOT, 'DECISIONS.md')),
        'soul': read_file(os.path.join(BRAIN_ROOT, 'SOUL.md')),
    }


def build_prompt(doc_path: str, review_type: str, doc_content: str, memory: dict) -> str:
    type_guidance = {
        'prd': 'Focus on: scope clarity, missing requirements, technical feasibility signals, alignment with current roadmap.',
        'design': 'Focus on: user experience consistency, alignment with product vision, edge cases missed, developer handoff clarity.',
        'stakeholder_request': 'Focus on: what they actually want vs. what they said, urgency, effort vs. value, whether it conflicts with existing direction.',
        'spec': 'Focus on: completeness, ambiguities a developer would get stuck on, missing acceptance criteria.',
        'proposal': 'Focus on: what they\'re asking for, what we\'d be committing to, risks, whether it fits our direction.',
        'contract': 'Focus on: obligations on our side, timelines, exit clauses, anything unusual. (Note: I\'m not a lawyer — flag anything that needs legal review.)',
    }.get(review_type, 'Focus on: relevance to my products, required action, and key questions to ask.')

    return f"""Review the following {review_type} document for me.

## My context

### Product context
{memory['context']}

### Past decisions
{memory['decisions']}

## Document to review

**File:** {doc_path}
**Type:** {review_type}

---

{doc_content}

---

## What I need

{type_guidance}

Provide:

1. **Summary** (2–3 sentences): What is this, and what does it want from me?
2. **Alignment** (bullet points): How does it fit — or conflict — with my current direction and past decisions?
3. **Gaps / concerns** (bullet points): What's missing, unclear, or risky?
4. **Questions to ask** (up to 3): What should I clarify before making any decision?
5. **Recommended next action**: One clear sentence — approve, reject, request changes, escalate, or defer.

Be concise. I know my own context — don't repeat it back to me.
"""


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    doc_path = sys.argv[1]
    review_type = sys.argv[2] if len(sys.argv) > 2 else 'document'

    expanded = os.path.expanduser(doc_path)
    if not os.path.exists(expanded):
        print(f'Error: File not found: {doc_path}')
        sys.exit(1)

    # Basic text read — works for .md, .txt, .py, etc.
    # For PDFs, user should convert first or paste content manually
    try:
        with open(expanded) as f:
            doc_content = f.read()
    except UnicodeDecodeError:
        print(f'Error: Cannot read {doc_path} as text.')
        print('For PDFs or Word docs, export to .txt or .md first, then run this script.')
        sys.exit(1)

    memory = read_memory()
    prompt = build_prompt(doc_path, review_type, doc_content, memory)

    print('\n=== Document Review Prompt ===')
    print(f'Document: {doc_path}')
    print(f'Type: {review_type}\n')
    print('--- PASTE THIS INTO CLAUDE CODE ---\n')
    print(prompt)
    print('--- END OF PROMPT ---\n')


if __name__ == '__main__':
    main()
