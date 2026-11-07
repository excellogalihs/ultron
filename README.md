# ultron

A local-first AI workspace built for low-end computers. ultron is a lightweight alternative to heavier AI desktops: Flask, SQLite, vanilla JavaScript, and Ollama. No Docker, Electron, React, or cloud services.

```
┌─ ULTRON ───────────────────────────────────────────────┐
│  Home  Chat  Documents  Calendar  Tasks  Memory  Settings │
│                                                          │
│  local SQLite  ──  Flask  ──  Ollama (gemma3:1b / 4b)    │
└──────────────────────────────────────────────────────────┘
```

## What works

- **Home dashboard** — welcome state, workspace totals, recently edited documents, today's events, upcoming events, pending tasks, recent conversations, and a quick prompt that starts a real chat thread.
- **Chat** — persistent conversations, streaming Markdown/code responses, model switching, rename/delete, copy, regenerate, stop, and automatic titles. Ollama's installed models are discovered locally; gemma3:1b and gemma3:4b remain available as built-in choices.
- **Assistant tools** — the model can request validated document reads/creates/edits, bounded workspace text search, task reads/creates, calendar reads/creates, and memory reads/saves through a strict JSON protocol. Calendar creation requires a clear date and start time; ambiguous requests are clarified. Tool calls are application-controlled; there is no shell tool or arbitrary path access.
- **Documents** — create, search, rename, autosave, format as Markdown or plain text, preview, organize into folders, and delete local documents. The AI writing panel streams suggestions for selected text or a whole document; Accept applies them and Reject leaves the document unchanged. Chat-originated edits remain proposals and do not write document contents.
- **Calendar** — monthly, weekly, and daily views with local event creation, editing, deletion, descriptions, times, categories, and upcoming/today dashboard sections.
- **Tasks** — add, edit, categorize, complete/reopen, and delete tasks with priority, notes, and due dates; the assistant can read actual task lists for summaries.
- **Memory** — store facts/preferences, edit and delete them, and toggle their use. Only a small keyword-ranked subset relevant to the current request is included in AI context; the entire memory table is never sent.
- **Settings** — display name, default model, Ollama URL, temperature, system prompt, memory context, live engine connection test, and JSON export of all local data.

All data lives in `instance/ultron.db` and never leaves the machine. The app binds to `127.0.0.1` by default. Workspace file search is read-only and scoped to the app workspace root (the project directory by default); hidden files, dependency/build directories, symlinks, and oversized files are skipped. Set `ULTRON_WORKSPACE_ROOT` to choose another local root.

## Requirements

- Python 3.10+
- [Ollama](https://ollama.com) installed and running
- At least one supported model pulled:

```bash
ollama serve
ollama pull gemma3:1b   # default: fast, low memory
ollama pull gemma3:4b   # optional: smarter, needs more RAM
```

The interface runs even if Ollama is offline; chat replies show a real connection error instead of pretending to work.

## Run

```bash
cd ultron
./run.sh
```

On first launch, `run.sh` creates `.venv` and installs Flask. Open:

**http://localhost:5000**

Manual setup if you prefer:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python app.py
```

For development with auto-reload:

```bash
ULTRON_DEBUG=1 .venv/bin/python app.py
```

## Project structure

```
ultron/
├── app.py                     # entry point
├── run.sh                     # local venv + launch
├── requirements.txt
├── ultron/
│   ├── __init__.py            # app factory, error handlers
│   ├── constants.py           # supported models, defaults
│   ├── db.py                  # SQLite connection + schema bootstrap
│   ├── schema.sql
│   ├── helpers.py             # settings, formatting, nav context
│   ├── services/ollama.py     # stdlib Ollama client (tags, streaming chat)
│   ├── blueprints/            # home, chat, documents, calendar, tasks, memory, settings
│   ├── templates/
│   │   ├── base.html
│   │   ├── components/        # sidebar, topbar, icons, logo, empty states
│   │   └── *.html
│   └── static/
│       ├── css/               # tokens, layout, components, pages
│       ├── js/                # app + one script per feature
│       ├── fonts/             # bundled JetBrains Mono (OFL)
│       └── img/               # logo, favicon
└── instance/ultron.db         # created on first run (gitignored)
```

## Design notes

- Deep space black (`#07070b`), muted violet (`#8c7cf0`), JetBrains Mono.
- Square geometry, minimal outlines, no decorative gradients or flashy motion.
- The mark is a hexagonal AI core with an angular "U" and a single status node. The wordmark uses wide tracking for a terminal/industrial feel.
- CSS is split by responsibility; page scripts are isolated so a broken feature cannot break navigation.
- No build step, no npm, no bundler.

## API surface

| Area | Endpoints |
| --- | --- |
| Chat | `POST /chat/new`, `GET/POST /api/conversations`, `PATCH/DELETE /api/conversations/<id>`, `POST /api/conversations/<id>/stream` (SSE) |
| Documents | `GET/POST /api/documents`, `GET/PATCH/DELETE /api/documents/<id>` |
| Calendar | `GET/POST /api/events`, `GET/PATCH/DELETE /api/events/<id>` |
| Tasks | `GET/POST /api/tasks`, `PATCH/DELETE /api/tasks/<id>` |
| Memory | `GET/POST /api/memories`, `PATCH/DELETE /api/memories/<id>` |
| Engine | `GET /api/ollama/status?url=...` |
| Data | `GET /settings/export` |

Run the local assistant/tool tests with:

```bash
PYTHONPATH=. .venv/bin/python -m unittest discover -s tests -v
```

## Scope

This is a deliberate foundation, not a finished productivity suite. There is no authentication, multi-user support, file upload/search, reminders, or autonomous tool use. Calendar events are single-day; task notes exist in storage but are not edited in the UI yet. Data export is read-only. Those are future layers, not hidden mock features.

## License

Application code: MIT. JetBrains Mono is licensed under the SIL Open Font License 1.1.
