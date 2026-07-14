"""Verify DB migration state."""
from dotenv import load_dotenv
import os

load_dotenv('.env')
url = os.getenv('DATABASE_URL', '').replace('+psycopg2', '')

import psycopg2
conn = psycopg2.connect(url)
cur = conn.cursor()

# Check which old memory tables still exist
tables = [
    'conversation_summaries', 'semantic_memories', 'preference_memories',
    'episodic_memories', 'knowledge_chunks', 'action_history',
    'memory_links', 'memory_embeddings',
]
for t in tables:
    cur.execute(
        "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = %s)",
        (t,)
    )
    exists = cur.fetchone()[0]
    print(f'{t}: {"EXISTS" if exists else "DROPPED"}')

# Check new column
cur.execute(
    "SELECT column_name FROM information_schema.columns "
    "WHERE table_name = 'agent_conversations' AND column_name = 'last_extracted_at'"
)
has_col = cur.fetchone()
print(f'last_extracted_at column: {"EXISTS" if has_col else "MISSING"}')

# Check agent_conversations has summary column
cur.execute(
    "SELECT column_name FROM information_schema.columns "
    "WHERE table_name = 'agent_conversations' AND column_name = 'summary'"
)
has_summary = cur.fetchone()
print(f'summary column: {"EXISTS" if has_summary else "MISSING"}')

cur.close()
conn.close()
print('\nMigration check complete.')
