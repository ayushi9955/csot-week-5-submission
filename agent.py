import argparse
import json
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from tools.exec import run_command
from tools.files import list_files, read_file, write_file, edit_file
from tools.search import grep, list_definitions
from tools.plan import add_todos, get_todos, mark_todo

import requests
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

ROOT = Path(".").resolve()
TARGET_ROOT = (ROOT / "target_repo").resolve()
AGENT_DIR = ROOT / ".agent"
SESSION_DIR = AGENT_DIR / "sessions"
SKILLS_DIR = ROOT / "skills"
LOADED_SKILLS_PATH = AGENT_DIR / "loaded_skills.json"
MCP_CONFIG_PATH = ROOT / "config" / "mcp_config.json"

READ_ONLY_COMMANDS = [
    "dir",
    "type",
    "git status",
    "git diff",
    "git log",
    "python -m pytest",
    "pytest",
]

RISKY_WORDS = [
    "del",
    "rmdir",
    "move",
    "copy",
    "git reset",
    "git clean",
    "pip install",
    "npm install",
    ">",
]


def ensure_dirs():
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    AGENT_DIR.mkdir(parents=True, exist_ok=True)
    TARGET_ROOT.mkdir(parents=True, exist_ok=True)


def safe_target_path(path="."):
    path = str(path or ".").replace("\\", "/").strip()

    if path in ["", ".", "/", "/target_repo", "target_repo"]:
        path = "."

    if path.startswith("/target_repo/"):
        path = path.replace("/target_repo/", "", 1)

    if path.startswith("target_repo/"):
        path = path.replace("target_repo/", "", 1)

    full_path = (TARGET_ROOT / path).resolve()

    if not str(full_path).startswith(str(TARGET_ROOT)):
        raise ValueError("Path outside target_repo is not allowed.")

    return full_path


def list_files(path="."):
    folder = safe_target_path(path)

    if not folder.exists():
        return {"error": "Path not found."}

    files = []

    for root, dirs, names in os.walk(folder):
        root_path = Path(root)

        dirs[:] = [
            d for d in dirs
            if d not in [".git", "__pycache__", ".pytest_cache"]
        ]

        for name in names:
            if name.endswith(".pyc"):
                continue

            rel = Path(root_path / name).relative_to(TARGET_ROOT)
            files.append(str(rel))

    return {"files": files[:100]}


def read_file(path, start_line=1, read_lines=80):
    file_path = safe_target_path(path)

    if not file_path.exists():
        return {"error": "File not found."}

    lines = file_path.read_text(encoding="utf-8", errors="ignore").splitlines()

    start = max(int(start_line) - 1, 0)
    end = min(start + int(read_lines), len(lines))

    content = "\n".join(
        f"{i + 1}: {lines[i]}"
        for i in range(start, end)
    )

    return {
        "path": path,
        "content": content,
        "start_line": start_line,
        "has_more": end < len(lines)
    }


def write_file(path, content):
    file_path = safe_target_path(path)

    print("\nApproval required to write file:")
    print(path)
    choice = input("Write this file? (y/n): ").strip().lower()

    if choice != "y":
        return {"approved": False, "status": "write denied"}

    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")

    return {"approved": True, "status": "written", "path": path}


def edit_file(path, start_line, end_line, new_text):
    file_path = safe_target_path(path)

    if not file_path.exists():
        return {"error": "File not found."}

    lines = file_path.read_text(encoding="utf-8", errors="ignore").splitlines(True)

    old_text = "".join(lines[int(start_line) - 1:int(end_line)])
    new_lines = [line + "\n" for line in str(new_text).split("\n")]

    print("\nApproval required to edit file:")
    print(path)
    print("\nOLD:")
    print(old_text)
    print("\nNEW:")
    print(new_text)

    choice = input("Apply this edit? (y/n): ").strip().lower()

    if choice != "y":
        return {"approved": False, "status": "edit denied"}

    lines[int(start_line) - 1:int(end_line)] = new_lines
    file_path.write_text("".join(lines), encoding="utf-8")

    return {
        "approved": True,
        "status": "edited",
        "path": path,
        "diff_preview": {
            "old": old_text,
            "new": new_text
        }
    }


def is_read_only(command):
    command = command.lower().strip()
    return any(command.startswith(prefix) for prefix in READ_ONLY_COMMANDS)


def is_risky(command):
    command = command.lower().strip()
    return any(word in command for word in RISKY_WORDS)


def run_command(command, timeout=30):
    command = str(command)

    risky = is_risky(command) or not is_read_only(command)

    if risky:
        print("\nApproval required before running command:")
        print(command)
        choice = input("Run this command? (y/n): ").strip().lower()

        if choice != "y":
            return {
                "approved": False,
                "command": command,
                "stdout": "",
                "stderr": "User denied command.",
                "exit_code": None
            }

    try:
        result = subprocess.run(
            command,
            cwd=TARGET_ROOT,
            shell=True,
            capture_output=True,
            text=True,
            timeout=int(timeout)
        )

        return {
            "approved": True,
            "command": command,
            "stdout": result.stdout[-6000:],
            "stderr": result.stderr[-6000:],
            "exit_code": result.returncode
        }

    except subprocess.TimeoutExpired:
        return {
            "approved": True,
            "command": command,
            "stdout": "",
            "stderr": "Command timed out.",
            "exit_code": -1
        }


def grep(pattern, path="."):
    folder = safe_target_path(path)
    matches = []

    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if d not in [".git", "__pycache__", ".pytest_cache"]]

        for filename in files:
            if not filename.endswith((".py", ".md", ".txt", ".json")):
                continue

            file_path = Path(root) / filename
            rel = file_path.relative_to(TARGET_ROOT)

            try:
                lines = file_path.read_text(encoding="utf-8", errors="ignore").splitlines()
            except Exception:
                continue

            for idx, line in enumerate(lines, start=1):
                if pattern.lower() in line.lower():
                    matches.append({
                        "file": str(rel),
                        "line": idx,
                        "text": line.strip()
                    })

    return {"matches": matches[:50]}


def list_definitions(path):
    import ast

    file_path = safe_target_path(path)

    if not file_path.exists():
        return {"error": "File not found."}

    source = file_path.read_text(encoding="utf-8", errors="ignore")

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {"error": "Could not parse Python file."}

    definitions = []

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            definitions.append({
                "type": "function",
                "name": node.name,
                "line": node.lineno
            })

        if isinstance(node, ast.ClassDef):
            definitions.append({
                "type": "class",
                "name": node.name,
                "line": node.lineno
            })

    return {"definitions": definitions}


def load_todos():
    path = AGENT_DIR / "todos.json"

    if not path.exists():
        return []

    return json.loads(path.read_text(encoding="utf-8"))


def save_todos(todos):
    AGENT_DIR.mkdir(exist_ok=True)
    (AGENT_DIR / "todos.json").write_text(
        json.dumps(todos, indent=2),
        encoding="utf-8"
    )


def add_todos(items):
    todos = load_todos()

    for item in items:
        todos.append({
            "title": item.get("title"),
            "description": item.get("description"),
            "verification": item.get("verification"),
            "status": "pending",
            "evidence": ""
        })

    save_todos(todos)
    return {"todos": todos}


def get_todos():
    return {"todos": load_todos()}


def mark_todo(index, status, evidence=""):
    todos = load_todos()

    if index < 0 or index >= len(todos):
        return {"error": "Invalid todo index."}

    todos[index]["status"] = status
    todos[index]["evidence"] = evidence
    save_todos(todos)

    return {"todos": todos}


def list_skills():
    skills = []

    if not SKILLS_DIR.exists():
        return {"skills": []}

    for folder in SKILLS_DIR.iterdir():
        skill_file = folder / "SKILL.md"

        if skill_file.exists():
            text = skill_file.read_text(encoding="utf-8", errors="ignore")
            first_line = text.splitlines()[0] if text.splitlines() else folder.name

            skills.append({
                "name": folder.name,
                "title": first_line.replace("#", "").strip(),
                "path": str(skill_file)
            })

    return {"skills": skills}


def load_loaded_skills():
    if not LOADED_SKILLS_PATH.exists():
        return []

    return json.loads(LOADED_SKILLS_PATH.read_text(encoding="utf-8"))


def save_loaded_skills(skills):
    AGENT_DIR.mkdir(exist_ok=True)
    LOADED_SKILLS_PATH.write_text(json.dumps(skills, indent=2), encoding="utf-8")


def load_skill(name):
    skill_file = SKILLS_DIR / name / "SKILL.md"

    if not skill_file.exists():
        return {"error": f"Skill not found: {name}"}

    text = skill_file.read_text(encoding="utf-8", errors="ignore")
    loaded = load_loaded_skills()

    if name not in loaded:
        loaded.append(name)
        save_loaded_skills(loaded)

    return {
        "name": name,
        "content": text
    }


def skill_status():
    return {
        "available": list_skills().get("skills", []),
        "loaded": load_loaded_skills()
    }


def load_mcp_config():
    if not MCP_CONFIG_PATH.exists():
        return {"servers": {}}

    return json.loads(MCP_CONFIG_PATH.read_text(encoding="utf-8"))


def mcp_status():
    config = load_mcp_config()
    servers = config.get("servers", {})

    output = {}

    for name, server in servers.items():
        auth_env = server.get("auth_env")
        output[name] = {
            "enabled": server.get("enabled", False),
            "url": server.get("url"),
            "auth_env": auth_env,
            "has_key": bool(os.getenv(auth_env)) if auth_env else False
        }

    return output


def mcp_call(server, tool, arguments=None):
    config = load_mcp_config()
    servers = config.get("servers", {})

    if server not in servers:
        return {"error": f"MCP server not found: {server}"}

    info = servers[server]

    if not info.get("enabled", False):
        return {"error": f"MCP server disabled: {server}"}

    url = info.get("url")
    auth_env = info.get("auth_env")
    token = os.getenv(auth_env) if auth_env else None

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    if token:
        headers["Authorization"] = f"Bearer {token}"

    payload = {
        "jsonrpc": "2.0",
        "id": "agent-call-1",
        "method": "tools/call",
        "params": {
            "name": tool,
            "arguments": arguments or {}
        }
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=20)

        return {
            "server": server,
            "tool": tool,
            "status_code": response.status_code,
            "response": response.text[:5000]
        }

    except Exception as e:
        return {"error": str(e)}


class Agent:
    def __init__(self, session_id="default"):
        ensure_dirs()

        self.session_id = session_id
        self.session_path = SESSION_DIR / f"{session_id}.json"

        self.client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=os.getenv("OPENROUTER_API_KEY")
        )

        self.model = os.getenv("OPENROUTER_MODEL", "openrouter/free")

        self.messages = []
        self.load_session()

        self.tool_map = {
            "run_command": run_command,
            "list_files": list_files,
            "read_file": read_file,
            "write_file": write_file,
            "edit_file": edit_file,
            "grep": grep,
            "list_definitions": list_definitions,
            "add_todos": add_todos,
            "get_todos": get_todos,
            "mark_todo": mark_todo,
            "list_skills": list_skills,
            "load_skill": load_skill,
            "skill_status": skill_status,
            "mcp_status": mcp_status,
            "mcp_call": mcp_call,
        }

        self.tools = self.build_tools()

    def build_tools(self):
        return [
            self.schema("run_command", "Run a shell command inside target_repo.", {
                "command": {"type": "string"},
                "timeout": {"type": "integer"}
            }, ["command"]),

            self.schema("list_files", "List files inside target_repo.", {
                "path": {"type": "string"}
            }, []),

            self.schema("read_file", "Read a file with line numbers.", {
                "path": {"type": "string"},
                "start_line": {"type": "integer"},
                "read_lines": {"type": "integer"}
            }, ["path"]),

            self.schema("write_file", "Write a file inside target_repo after approval.", {
                "path": {"type": "string"},
                "content": {"type": "string"}
            }, ["path", "content"]),

            self.schema("edit_file", "Edit a line range inside target_repo after approval.", {
                "path": {"type": "string"},
                "start_line": {"type": "integer"},
                "end_line": {"type": "integer"},
                "new_text": {"type": "string"}
            }, ["path", "start_line", "end_line", "new_text"]),

            self.schema("grep", "Search file contents.", {
                "pattern": {"type": "string"},
                "path": {"type": "string"}
            }, ["pattern"]),

            self.schema("list_definitions", "List Python functions and classes in a file.", {
                "path": {"type": "string"}
            }, ["path"]),

            self.schema("add_todos", "Add todo items.", {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "description": {"type": "string"},
                            "verification": {"type": "string"}
                        },
                        "required": ["title", "description", "verification"]
                    }
                }
            }, ["items"]),

            self.schema("get_todos", "Get current todos.", {}, []),

            self.schema("mark_todo", "Mark a todo item.", {
                "index": {"type": "integer"},
                "status": {"type": "string"},
                "evidence": {"type": "string"}
            }, ["index", "status"]),

            self.schema("list_skills", "List available skills.", {}, []),

            self.schema("load_skill", "Load a skill by name.", {
                "name": {"type": "string"}
            }, ["name"]),

            self.schema("skill_status", "Show available and loaded skills.", {}, []),

            self.schema("mcp_status", "Show configured MCP servers and status.", {}, []),

            self.schema("mcp_call", "Call a configured MCP server tool.", {
                "server": {"type": "string"},
                "tool": {"type": "string"},
                "arguments": {"type": "object"}
            }, ["server", "tool"])
        ]

    def schema(self, name, description, properties, required):
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required
                }
            }
        }

    def load_session(self):
        if self.session_path.exists():
            try:
                data = json.loads(self.session_path.read_text(encoding="utf-8"))
                self.messages = data.get("messages", [])
            except json.JSONDecodeError:
                self.messages = []

    def save_session(self):
        data = {
            "id": self.session_id,
            "title": self.generate_title(),
            "timestamp": datetime.now().isoformat(),
            "messages": self.messages
        }

        self.session_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def generate_title(self):
        for message in self.messages:
            if message.get("role") == "user":
                return message.get("content", "session")[:50]
        return "untitled"

    def load_agents_md(self):
        path = ROOT / "AGENTS.md"

        if path.exists():
            return path.read_text(encoding="utf-8", errors="ignore")

        return ""

    def loaded_skill_text(self):
        parts = []

        for name in load_loaded_skills():
            result = load_skill(name)

            if "content" in result:
                parts.append(result["content"])

        return "\n\n".join(parts)

    def system_prompt(self):
        return f"""
You are Code Scout Plus, an extendable coding agent.

Rules:
- Use real tool calls. Do not fake tool calls in text.
- Work inside target_repo for code tasks.
- Use Windows-compatible commands.
- Use relative paths such as calculator.py, not /target_repo/calculator.py.
- Search before editing.
- Use todos for multi-step tasks.
- Run python -m pytest to verify.
- Do not claim success unless exit_code is 0.
- Load skills when they are useful.
- Use MCP only through configured servers and environment keys.

Project instructions:
{self.load_agents_md()}

Loaded skills:
{self.loaded_skill_text()}
"""

    def dispatch(self, name, args):
        if name not in self.tool_map:
            return {"error": f"Unknown tool: {name}"}

        try:
            return self.tool_map[name](**args)
        except Exception as e:
            return {"error": str(e)}

    def parse_fake_tool_call(self, text):
        match = re.search(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", text or "", re.DOTALL)

        if not match:
            return None

        try:
            data = json.loads(match.group(1))
            return data.get("name"), data.get("arguments", {})
        except json.JSONDecodeError:
            return None

    def quick_route(self, user_input):
        text = user_input.lower().strip()

        if "list all files" in text or "list files" in text:
            result = self.dispatch("list_files", {"path": "."})
            files = result.get("files", [])
            return "Files in target_repo:\n" + "\n".join(f"- {f}" for f in files)

        if "list definitions" in text:
            path = "calculator.py"
            parts = user_input.split("in")
            if len(parts) > 1:
                path = parts[-1].strip().strip(".")

            result = self.dispatch("list_definitions", {"path": path})
            definitions = result.get("definitions", [])

            lines = [f"Definitions in {path}:"]
            for item in definitions:
                lines.append(f"- {item['type']}: {item['name']} at line {item['line']}")

            return "\n".join(lines)

        if text.startswith("read "):
            path = user_input.replace("Read", "").replace("read", "").strip()
            result = self.dispatch("read_file", {"path": path})
            return result.get("content", str(result))

        return None

    def chat(self, user_input, max_steps=15):

        quick = self.quick_route(user_input)
        if quick is not None:
            return quick

        self.messages.append({
            "role": "user",
            "content": user_input
        })

        for _ in range(max_steps):

            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {
                            "role": "system",
                            "content": self.system_prompt()
                        },
                        *self.messages[-20:]
                    ],
                    tools=self.tools,
                    tool_choice="auto"
                )

                if response is None or not response.choices:
                    continue

            except Exception as e:
                return f"API Error: {e}"

            message = response.choices[0].message

            if not message.tool_calls:
                fake = self.parse_fake_tool_call(message.content or "")

                if fake:
                    tool_name, args = fake
                    result = self.dispatch(tool_name, args)

                    print(f"\n[Parsed fake tool call]: {tool_name}")
                    print(f"[Arguments]: {args}")
                    print(f"[Tool result]: {result}\n")

                    self.messages.append({"role": "assistant", "content": message.content})
                    self.messages.append({
                        "role": "tool",
                        "tool_call_id": f"fake_{tool_name}",
                        "content": json.dumps(result)
                    })

                    continue

                answer = message.content
                self.messages.append({"role": "assistant", "content": answer})
                self.save_session()
                return answer

            self.messages.append(message.model_dump())

            for tool_call in message.tool_calls:
                name = tool_call.function.name

                try:
                    args = json.loads(tool_call.function.arguments or "{}")
                except json.JSONDecodeError:
                    result = {
                        "error": "Invalid JSON arguments",
                        "raw": tool_call.function.arguments
                    }

                    self.messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result)
                    })

                    continue

                print(f"\n[Tool called]: {name}")
                print(f"[Arguments]: {args}")

                result = self.dispatch(name, args)

                print(f"[Tool result]: {result}\n")

                self.messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result)
                })

        answer = "Step limit reached. Continue with another prompt."
        self.messages.append({"role": "assistant", "content": answer})
        self.save_session()
        return answer

    def run(self):
        print("Code Scout Plus started.")
        print("Type exit to stop.\n")

        while True:
            user_input = input("You: ")

            if user_input.lower() in ["exit", "quit"]:
                print("Goodbye!")
                break

            print(self.chat(user_input))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("task", nargs="*")
    parser.add_argument("--session", default="default")

    args = parser.parse_args()
    agent = Agent(session_id=args.session)

    if args.task:
        task = " ".join(args.task)
        print(agent.chat(task))
    else:
        agent.run()


if __name__ == "__main__":
    main()