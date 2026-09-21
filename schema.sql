-- Empty application schema only; no production rows. / 仅空表结构，不包含生产数据。
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    token_hash TEXT NOT NULL UNIQUE,
    text_chain_variant TEXT NOT NULL DEFAULT 'claude'
        CHECK (text_chain_variant IN ('claude', 'claude_coach'))
);
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    client_id TEXT NOT NULL,
    user_id TEXT NOT NULL REFERENCES users(id),
    title TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS conversations_owner ON conversations(user_id, updated_at);
CREATE TABLE IF NOT EXISTS chat_messages (
    id BIGSERIAL PRIMARY KEY,
    client_id TEXT NOT NULL,
    user_id TEXT NOT NULL REFERENCES users(id),
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    request_id TEXT NOT NULL,
    card JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(conversation_id, request_id, role)
);
CREATE INDEX IF NOT EXISTS messages_owner ON chat_messages(user_id, conversation_id, id);
CREATE TABLE IF NOT EXISTS patient_clinical_record (
    id BIGSERIAL PRIMARY KEY,
    client_id TEXT NOT NULL,
    user_id TEXT NOT NULL UNIQUE REFERENCES users(id),
    relationship_memory JSONB NOT NULL DEFAULT '{}',
    basic_info TEXT NOT NULL DEFAULT '',
    recent_session_summaries JSONB NOT NULL DEFAULT '[]',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS knowledge_patterns (
    chunk_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    embedding JSONB NOT NULL
);
