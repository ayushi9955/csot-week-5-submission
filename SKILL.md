# Commit Workflow Skill

## What it does
This skill helps the agent prepare a clean commit.

## Procedure
1. Run `python -m pytest`.
2. Run `git status`.
3. Run `git diff`.
4. Summarize what changed.
5. Suggest a conventional commit message.

## Commit message format
Use:

type(scope): short summary

Examples:
- fix(calculator): correct add function
- docs(submission): expand week 5 writeup