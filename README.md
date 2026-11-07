# ultron

A local-first AI workspace built for low-end computers. ultron is a lightweight alternative to heavier AI desktops: Flask, SQLite, vanilla JavaScript, and Ollama. No Docker, Electron, React, or cloud services.

```
┌─ ULTRON ───────────────────────────────────────────────────────────────────┐
│  Home  Chat  Documents  Calendar  Tasks  Memory  Settings                  │
│                                                                            │
│  local SQLite  ──  Flask  ──  Ollama (gemma3:1b / 4b)  ──  Web Search     │
└────────────────────────────────────────────────────────────────────────────┘
```

## What works

- **Home dashboard** — welcome state, workspace totals, recently edited documents, today's events, upcoming events, pending tasks, recent conversations, and a quick prompt that starts a real chat thread.
- **Chat with Voice & Search** — persistent conversations, streaming Markdown/code responses, model switching, rename/delete, copy, regenerate, stop, and automatic titles.
  - **Voice Input (Speech-to-Text)**: Click the microphone in the composer to dictate messages using the browser's Web Speech API.
  - **Read Aloud (Text-to-Speech)**: Audio playback on assistant responses with auto-speak preference.
  - **DuckDuckGo Web Search**: Model can query DuckDuckGo for live internet information, cite sources with clickable markdown links, and fetch webpage content without any third-party dependencies. Toggle search on/off directly from the composer.
- **Assistant tools** — strict application-controlled JSON tool execution loop:
  - Document read/create/edit proposals (with mandatory user approval before writing).
  - Bounded workspace file search, local file reading (`read_local_file`), and local text creation (`create_local_file`) restricted to authorized directories. Path traversal and unauthorized extensions are strictly blocked.
  - Calendar read/create with clear date/time validation.
  - Task read/create/update.
  - Memory read/save with relevance-filtered context injection.
  - DuckDuckGo search (`web_search`) and webpage text reading (`fetch_webpage`).
- **Documents & File Management** — create, search, rename, autosave, format as Markdown or plain text, preview, and organize into folders.
  - **Import**: Upload text, Markdown, JSON, CSV, or code files directly into your workspace.
  - **Export**: Export individual documents as `.md`/`.txt`, or export all documents in structured JSON.
  - **AI Writing Panel**: Streams suggestions for selected text or whole documents with one-click Accept/Reject.
- **Calendar** — monthly, weekly, and daily views with local event creation, editing, deletion, descriptions, times, categories, and upcoming/today dashboard sections.
- **Tasks** — add, edit, categorize, complete/reopen, and delete tasks with priority, notes, and due dates; assistant can read actual task lists for summaries.
- **Memory** — store facts/preferences, edit and delete them, and toggle their use. Only a small keyword-ranked subset relevant to the current request is included in AI context; the entire memory table is never sent.
- **Customization & Themes** — choose between Dark Onyx, OLED Black, Light Paper, and Nord Dim themes, multiple accent colors (Violet, Emerald, Cyan, Amber, Rose, Monochrome), and typography (JetBrains Mono, Modern Sans, IBM Plex Mono).
- **Settings, Backup & Restore** — customize operator name, default model, Ollama URL, temperature, system prompt, memory, web search, voice options, and chat shortcuts. Export full workspace JSON backups or restore previous backups with atomic SQLite rollback protection.

All data lives in `instance/ultron.db` and never leaves the machine. The app binds to `127.0.0.1` by default. Workspace file operations are strictly scoped to the workspace root (`ULTRON_WORKSPACE_ROOT` or project directory by default); hidden files, dependency/build directories, symlinks, and oversized files are skipped.

## Requirements

- Python 3.10+
- [Ollama](https://ollama.com) installed and running
- At least one supported model pulled:

```bash
ollama serve
ollama pull gemma3:1b   # default: fast, low memory (~1 GB VRAM / RAM)
ollama pull gemma3:4b   # optional: smarter, needs more RAM (~3 GB)
```

The interface runs even if Ollama is offline; chat replies show a clear connection error instead of pretending to work.

## Quick Start

### Linux & macOS

```bash
cd ultron
chmod +x run.sh
./run.sh
```

### Windows

Double-click `run.bat` or run in Command Prompt / PowerShell:

```cmd
cd ultron
run.bat
```

On first launch, the script creates `.venv` and installs dependencies. Open:

**http://localhost:5000**

### Manual setup

```bash
python3 -m venv .venv
# On Linux/macOS:
source .venv/bin/activate
# On Windows:
# .venv\Scripts\activate

pip install -r requirements.txt
python app.py
```

For development with auto-reload:

```bash
ULTRON_DEBUG=1 python app.py
```

## Project Structure

```
ultron/
├── app.py                     # entry point
├── run.sh                     # Linux / macOS launcher
├── run.bat                    # Windows launcher
├── requirements.txt           # lightweight dependencies (Flask only)
├── ultron/
│   ├── __init__.py            # app factory, error handlers
│   ├── constants.py           # supported models, defaults, themes
│   ├── db.py                  # SQLite connection + schema bootstrap
│   ├── schema.sql
│   ├── helpers.py             # settings, formatting, nav context
│   ├── services/
│   │   ├── ollama.py          # stdlib Ollama client (streaming chat & tags)
│   │   ├── web_search.py      # zero-dependency DuckDuckGo search & page reader
│   │   └── workspace_tools.py # bounded tool execution & security checks
│   ├── blueprints/            # home, chat, documents, calendar, tasks, memory, settings
│   ├── templates/
│   │   ├── base.html
│   │   ├── components/        # sidebar, topbar, icons, logo, empty states
│   │   └── *.html
│   └── static/
│       ├── css/               # tokens, layout, components, pages
│       ├── js/                # app + modular scripts per feature
│       ├── fonts/             # bundled JetBrains Mono (OFL)
│       └── img/               # logo, favicon
└── instance/ultron.db         # created on first run (gitignored)
```

## API Surface

| Area | Endpoints |
| --- | --- |
| Chat | `POST /chat/new`, `GET/POST /api/conversations`, `PATCH/DELETE /api/conversations/<id>`, `POST /api/conversations/<id>/stream` (SSE) |
| Documents | `GET/POST /api/documents`, `GET/PATCH/DELETE /api/documents/<id>`, `POST /api/documents/import`, `GET /api/documents/<id>/export`, `GET /api/documents/export-all` |
| Calendar | `GET/POST /api/events`, `GET/PATCH/DELETE /api/events/<id>` |
| Tasks | `GET/POST /api/tasks`, `PATCH/DELETE /api/tasks/<id>` |
| Memory | `GET/POST /api/memories`, `PATCH/DELETE /api/memories/<id>` |
| Engine | `GET /api/ollama/status?url=...` |
| Data | `GET /settings/export`, `POST /settings/restore` |

## Testing

Run the automated test suite with:

```bash
PYTHONPATH=. .venv/bin/python -m unittest discover -s tests -v
```
