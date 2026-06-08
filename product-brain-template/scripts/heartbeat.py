#!/usr/bin/env python3
"""
Morning heartbeat — surfaces what needs your attention today.
Run manually or schedule with cron (weekdays 8am).

Cron setup:
  crontab -e
  0 8 * * 1-5 python3 ~/ProductBrain/scripts/heartbeat.py >> ~/ProductBrain/daily_logs/heartbeat.log 2>&1

Usage:
  python3 ~/ProductBrain/scripts/heartbeat.py
"""

import os
from datetime import datetime, timedelta

BRAIN_ROOT = os.path.expanduser('~/ProductBrain')
LOGS_DIR = os.path.join(BRAIN_ROOT, 'daily_logs')


def read_file(filename: str) -> str:
    path = os.path.join(BRAIN_ROOT, filename)
    if os.path.exists(path):
        with open(path) as f:
            return f.read()
    return ''


def read_recent_logs(days: int = 3) -> dict:
    logs = {}
    for i in range(1, days + 1):  # skip today — it's just started
        date = (datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')
        path = os.path.join(LOGS_DIR, f'{date}.md')
        if os.path.exists(path):
            with open(path) as f:
                logs[date] = f.read()
    return logs


def main():
    soul = read_file('SOUL.md')
    context = read_file('PRODUCT_CONTEXT.md')
    decisions = read_file('DECISIONS.md')
    logs = read_recent_logs(days=3)

    today = datetime.now().strftime('%A %d %B %Y')

    print(f'\n=== Morning Heartbeat — {today} ===\n')
    print('Paste the prompt below into Claude Code to get your daily priorities.\n')
    print('--- PASTE THIS INTO CLAUDE CODE ---\n')

    recent_logs_text = ''
    if logs:
        for date in sorted(logs.keys(), reverse=True):
            recent_logs_text += f'### {date}\n\n{logs[date]}\n\n'
    else:
        recent_logs_text = 'No recent session logs found.'

    prompt = f"""It's {today}. Based on my context and recent work, tell me what to focus on today.

## My context

### Working style (SOUL.md)
{soul}

### Product context (PRODUCT_CONTEXT.md)
{context}

### Decisions and open questions (DECISIONS.md)
{decisions}

### Recent session logs (last 3 days)
{recent_logs_text}

## What I need

Give me a prioritised list of up to 5 things to focus on today. For each:
- **What**: The specific action or decision
- **Why now**: What makes it urgent or important today
- **Suggested first step**: One concrete thing I can do in the next 30 minutes

Format as a numbered list. Be direct — I don't need preamble.
"""

    print(prompt)
    print('--- END OF PROMPT ---\n')


if __name__ == '__main__':
    main()
