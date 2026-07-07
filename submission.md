# Week 5 Submission – Code Scout Plus

## Introduction

For Week 5, I rebuilt my Week 4 coding agent and extended it into **Code Scout Plus**. The Week 4 version could inspect a repository, run commands, edit files, and verify fixes. The Week 5 version keeps that foundation but adds two important extension mechanisms: **skills** and **MCP configuration**.

The main idea is that the agent should not need code changes every time I want it to learn a new workflow. If I want a commit workflow, a review checklist, or a new repeatable procedure, I can add a markdown file under `skills/`. The agent can discover it, load it, and follow it.

I also added a simple MCP configuration layer so external tool servers can be defined in `config/mcp_config.json`, with API keys read from environment variables instead of being hardcoded.

## What My Agent Can Do Now

Compared to the Week 4 version, this version can now:

* Load reusable skills from a `skills/` directory.
* Show available and loaded skills.
* Follow loaded skill instructions inside the system prompt.
* Store MCP server details in a config file.
* Check MCP server status and whether required keys are available.
* Call a configured MCP server using an HTTP JSON-RPC style request.
* Continue supporting coding-agent features from Week 4:

  * run commands
  * read files
  * edit files
  * search code
  * list definitions
  * maintain todos
  * verify fixes with tests
  * save sessions

## Project Structure

```text
week_5/project/
├── agent.py
├── AGENTS.md
├── requirements.txt
├── .env.example
├── .gitignore
├── SUBMISSION.md
├── config/
│   └── mcp_config.json
├── skills/
│   ├── commit_workflow/
│   │   └── SKILL.md
│   ├── review_checklist/
│   │   └── SKILL.md
│   └── skill_writer/
│       └── SKILL.md
├── target_repo/
│   ├── calculator.py
│   └── test_calculator.py
└── .agent/
    ├── sessions/
    └── loaded_skills.json
```

## Skills Implemented

### 1. Commit Workflow Skill

This skill helps the agent prepare a clean commit. It tells the agent to:

1. Run tests.
2. Check git status.
3. Check git diff.
4. Summarize changes.
5. Suggest a conventional commit message.

I chose this skill because it is something I would actually use after fixing bugs.

### 2. Review Checklist Skill

This skill works like a final submission checklist. It asks the agent to check:

* tests pass
* `.env` is not committed
* `.env.example` exists
* file edits are sandboxed
* verification exit code is reported
* code is readable

I added this because my previous submissions lost marks for missing small packaging and writeup details.

### 3. Skill Writer Skill

This is a small meta-skill. It tells the agent how to create a new skill folder and write a `SKILL.md` file. I added this because Week 5 is about making the agent extendable, and a skill that helps write skills fits that theme.

## How the Skill Loader Works

The agent looks inside the `skills/` directory. Every folder containing a `SKILL.md` file is treated as a skill.

For example:

```text
skills/commit_workflow/SKILL.md
```

The agent has these skill tools:

* `list_skills`
* `load_skill`
* `skill_status`

When a skill is loaded, its name is saved in:

```text
.agent/loaded_skills.json
```

On later turns, the loaded skill text is injected into the system prompt. This means the agent can follow the skill without me changing `agent.py`.

## MCP Configuration

I added MCP server configuration in:

```text
config/mcp_config.json
```

Example:

```json
{
  "servers": {
    "github": {
      "enabled": false,
      "url": "https://api.githubcopilot.com/mcp/",
      "auth_env": "GITHUB_TOKEN",
      "description": "GitHub MCP server. Enable only when token is available."
    }
  }
}
```

The key point is that secrets are not hardcoded. The config only stores the name of the environment variable, such as `GITHUB_TOKEN`.

The actual token would be placed in `.env`, which is ignored by git.

The agent includes:

* `mcp_status`
* `mcp_call`

I kept the GitHub MCP server disabled by default because I did not want to commit any real token or depend on a private account during grading. But the config structure is present and the agent can show whether the required key exists.

## Testing

I tested the agent with a small `target_repo` containing a calculator bug.

Initial code:

```python
def add(a, b):
    return a - b
```

Test:

```python
from calculator import add

def test_add():
    assert add(2, 3) == 5
```

The task I gave the agent was:

```text
Run python -m pytest first, fix the failing calculator test, and verify again.
```

The successful run showed:

1. The agent ran `python -m pytest`.
2. The test failed.
3. It read `calculator.py`.
4. It identified that `return a - b` was wrong.
5. It used `edit_file`.
6. The approval gate appeared before editing.
7. I approved the edit.
8. It changed the code to `return a + b`.
9. It ran `python -m pytest` again.
10. The final result was:

```text
1 passed
exit_code: 0
```

That was my main end-to-end proof that the coding-agent part still works.

## Cool Feature: Review Skill Before Submission

One useful feature I added is the review checklist skill. The exact prompt is:

```text
Load the review_checklist skill and review this project for submission.
```

To reproduce it:

1. Make sure `skills/review_checklist/SKILL.md` exists.
2. Run:

```bash
python agent.py "Load the review_checklist skill."
```

3. Then run:

```bash
python agent.py "Use the review_checklist skill and review this project for submission."
```

The agent then checks whether the project has the required files, whether tests pass, and whether `.env.example` exists. This is useful because it catches the small submission mistakes that are easy to miss.

## Setup Instructions

Create a virtual environment:

```bash
python -m venv .venv
```

Activate it on Windows:

```bash
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\.venv\Scripts\Activate.ps1
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Create `.env`:

```env
OPENROUTER_API_KEY=your_key_here
OPENROUTER_MODEL=google/gemma-4-31b-it:free
GITHUB_TOKEN=optional_for_github_mcp
```

Run the agent:

```bash
python agent.py
```

Run a one-shot task:

```bash
python agent.py "Run python -m pytest and report the exit code."
```

## What Surprised Me

The biggest issue was model reliability. Some free OpenRouter models did not return proper tool calls and instead printed fake tool-call text. I added a fallback parser for simple `<tool_call>` blocks, but the normal tool-calling path is still preferred.

Another issue was Windows compatibility. Some model responses tried Linux commands like `find`, `cat`, or `head`. I added instructions telling the agent to prefer Windows-safe commands and relative paths.

## What I Would Improve Later

If I had more time, I would add:

* real `/mcp enable github` and `/mcp disable github` commands
* a better MCP client using the official MCP Python SDK
* more skills, such as a documentation writer skill and a test-writing skill
* a cleaner UI for showing loaded skills and enabled MCP servers

## Conclusion

This week’s project made my agent more flexible. Instead of adding every workflow directly to `agent.py`, I can now add skills through markdown files. MCP configuration also makes it possible to connect external tools without hardcoding keys.

The final agent is still a coding agent, but now it is also a small platform that can be extended through skills and external tool servers.
