PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL DEFAULT 'New conversation',
    model TEXT NOT NULL DEFAULT 'gemma3:1b',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation
    ON messages (conversation_id, id);

CREATE TABLE IF NOT EXISTS document_folders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL DEFAULT 'Untitled document',
    content TEXT NOT NULL DEFAULT '',
    folder_id INTEGER REFERENCES document_folders(id) ON DELETE SET NULL,
    format TEXT NOT NULL DEFAULT 'markdown' CHECK (format IN ('markdown', 'text')),
    file_type TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_documents_updated
    ON documents (updated_at DESC);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    start_at TEXT NOT NULL,
    end_at TEXT,
    category TEXT NOT NULL DEFAULT 'general',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_start
    ON events (start_at);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'completed')),
    priority TEXT NOT NULL DEFAULT 'normal' CHECK (priority IN ('low', 'normal', 'high')),
    category TEXT NOT NULL DEFAULT 'general',
    due_date TEXT,
    due_time TEXT,
    project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_tasks_status
    ON tasks (status, due_date);

CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    description TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
    deadline TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_projects_status ON projects (status, updated_at DESC);

CREATE TABLE IF NOT EXISTS project_documents (
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    PRIMARY KEY (project_id, document_id)
);

CREATE TABLE IF NOT EXISTS project_conversations (
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    PRIMARY KEY (project_id, conversation_id)
);

CREATE TABLE IF NOT EXISTS knowledge_collections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS knowledge_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    collection_id INTEGER REFERENCES knowledge_collections(id) ON DELETE SET NULL,
    filename TEXT NOT NULL,
    title TEXT NOT NULL,
    file_type TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    content_hash TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'indexed' CHECK (status IN ('indexed', 'error')),
    imported_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_knowledge_collection ON knowledge_files (collection_id, imported_at DESC);

CREATE TABLE IF NOT EXISTS project_knowledge_files (
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    knowledge_file_id INTEGER NOT NULL REFERENCES knowledge_files(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    PRIMARY KEY (project_id, knowledge_file_id)
);

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_type TEXT NOT NULL CHECK (source_type IN ('task', 'event')),
    source_id INTEGER NOT NULL,
    schedule_key TEXT NOT NULL,
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    due_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    read_at TEXT,
    UNIQUE (source_type, source_id, schedule_key)
);

CREATE INDEX IF NOT EXISTS idx_notifications_created
    ON notifications (created_at DESC);

CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'general',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    approved INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS experiences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'general productivity',
    original_request TEXT NOT NULL,
    task_description TEXT NOT NULL DEFAULT '',
    execution_steps TEXT NOT NULL DEFAULT '[]',
    tools_used TEXT NOT NULL DEFAULT '[]',
    successful_methods TEXT NOT NULL DEFAULT '',
    mistakes_solutions TEXT NOT NULL DEFAULT '',
    parameters TEXT NOT NULL DEFAULT '{}',
    confidence REAL NOT NULL DEFAULT 0.5 CHECK (confidence >= 0 AND confidence <= 1),
    successful_uses INTEGER NOT NULL DEFAULT 1,
    archived INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_used_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_experiences_category ON experiences(category, archived, last_used_at DESC);

CREATE TABLE IF NOT EXISTS learning_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    record_type TEXT NOT NULL,
    title TEXT NOT NULL,
    details TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS automations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    instruction TEXT NOT NULL,
    schedule_type TEXT NOT NULL CHECK (schedule_type IN ('once','daily','weekly','monthly','custom')),
    schedule_value TEXT NOT NULL DEFAULT '{}',
    timezone TEXT NOT NULL DEFAULT 'Asia/Jakarta',
    next_run_at TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_automations_due ON automations(enabled, next_run_at);

CREATE TABLE IF NOT EXISTS automation_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    automation_id INTEGER REFERENCES automations(id) ON DELETE SET NULL,
    automation_name TEXT NOT NULL,
    trigger_type TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running','completed','failed')),
    actions TEXT NOT NULL DEFAULT '[]',
    result TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT '',
    experience_id INTEGER REFERENCES experiences(id) ON DELETE SET NULL,
    scheduled_for TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_automation_runs_started ON automation_runs(started_at DESC);

CREATE TABLE IF NOT EXISTS local_notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    message TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    read_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_local_notifications_created ON local_notifications(created_at DESC);

CREATE TABLE IF NOT EXISTS scheduler_lease (
    id INTEGER PRIMARY KEY CHECK (id=1),
    lease_until TEXT NOT NULL DEFAULT ''
);
INSERT OR IGNORE INTO scheduler_lease(id,lease_until) VALUES(1,'');
