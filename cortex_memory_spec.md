# Cortex Long-Term Memory System
## Implementation Specification for Agent
### Version 2.0 — Python / FastAPI · PostgreSQL + pgvector · Redis

---

> **Đọc phần này trước khi làm bất cứ điều gì.**
>
> Tài liệu này là bản hướng dẫn đầy đủ để bạn chỉnh sửa codebase Cortex hiện tại sang kiến trúc memory mới. Bạn **không** cần tự sáng tạo thêm logic — mọi quyết định thiết kế đã được đưa ra sẵn ở đây. Nhiệm vụ của bạn là đọc kỹ từng phần, hiểu ý đồ, rồi edit codebase cho khớp với spec này.
>
> **Nguyên tắc tối thượng:** Nếu bạn thấy code hiện tại làm khác với spec này → sửa theo spec. Nếu spec chưa đề cập → hỏi lại trước khi tự quyết định.

---

## Mục lục

1. [Tổng quan kiến trúc](#1-tổng-quan-kiến-trúc)
2. [Cấu trúc thư mục đề xuất](#2-cấu-trúc-thư-mục)
3. [Database Setup — pgvector](#3-database-setup)
4. [Layer 0 — Raw Conversation Storage](#4-layer-0--raw-conversation-storage)
5. [Layer 1 — Working Memory](#5-layer-1--working-memory)
6. [Layer 2 — Conversation Memory (Summary Snapshots)](#6-layer-2--conversation-memory)
7. [Layer 3 — Semantic Memory](#7-layer-3--semantic-memory)
8. [Layer 4 — Preference Memory](#8-layer-4--preference-memory)
9. [Layer 5 — Episodic Memory](#9-layer-5--episodic-memory)
10. [Layer 6 — Knowledge Memory](#10-layer-6--knowledge-memory)
11. [Layer 7 — Action Memory](#11-layer-7--action-memory)
12. [Memory Candidate Detector](#12-memory-candidate-detector)
13. [Memory Extraction Pipeline](#13-memory-extraction-pipeline)
14. [Memory Retrieval Architecture](#14-memory-retrieval-architecture)
15. [Prompt Assembly](#15-prompt-assembly)
16. [Nightly Consolidation Jobs](#16-nightly-consolidation-jobs)
17. [API Contracts (Internal Interfaces)](#17-api-contracts)
18. [Migration Plan từ hệ thống cũ](#18-migration-plan)
19. [Monitoring & Metrics](#19-monitoring--metrics)
20. [Error Handling & Failure Scenarios](#20-error-handling--failure-scenarios)
21. [Testing Strategy](#21-testing-strategy)
22. [Implementation Roadmap](#22-implementation-roadmap)

---

## 1. Tổng quan kiến trúc

### 1.1 Vấn đề hiện tại cần sửa

Hệ thống hiện tại đang dùng:
```python
MAX_CONVERSATION_HISTORY = 10  # ← SAI. Phải xóa cái này.
```

Và đang inject toàn bộ conversation history vào prompt mỗi lần. Đây là anti-pattern vì:
- Token waste: inject những tin nhắn không liên quan
- Không scale: conversation dài → prompt phình to
- Không "nhớ" thực sự: agent mất memory khi conversation mới bắt đầu

### 1.2 Kiến trúc mới — 7 Memory Layers

```
User Message
    │
    ▼
┌─────────────────────────────────────────────┐
│         Memory Candidate Detector           │  ← Rule-based, KHÔNG gọi LLM
│  (lọc xem message này có cần extract không) │
└─────────────────┬───────────────────────────┘
                  │ (nếu pass)
                  ▼
┌─────────────────────────────────────────────┐
│         Extraction Queue (Redis)            │  ← Async, KHÔNG block response
└─────────────────┬───────────────────────────┘
                  │ (background worker xử lý)
                  ▼
         ┌────────┴────────┐
         │  Gemini Flash   │  ← CHỈ dùng ở đây, không dùng ở chỗ khác
         └────────┬────────┘
                  ▼
    ┌─────────────────────────┐
    │   Memory Classification │
    │   + Importance Scoring  │
    │   + Deduplication       │
    └────────────┬────────────┘
                 │
    ┌────────────▼────────────┐
    │       Storage           │
    │  Layer 3: semantic_memories
    │  Layer 5: episodic_memories
    └─────────────────────────┘

─────────────── (song song, khi user gửi message) ───────────────

User Query
    │
    ▼
┌─────────────────────────────────────────────┐
│      Rule-based Query Classifier            │  ← KHÔNG gọi LLM (80-90% cases)
└─────────────────┬───────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────┐
│         Multi-layer Retrieval               │
│  L1: Working Memory (dynamic, token-based)  │
│  L2: Conversation Summaries (nếu cần)       │
│  L3: Semantic Memory (SQL lookup)           │
│  L4: Preference Memory (SQL lookup)         │
│  L5: Episodic Memory (SQL + similarity)     │
│  L6: Knowledge Chunks (pgvector search)     │
└─────────────────┬───────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────┐
│         Prompt Assembly                     │
│  (ghép các memory vào prompt với budget)    │
└─────────────────┬───────────────────────────┘
                  │
                  ▼
            Gemini Pro/Flash
                  │
                  ▼
            Response → User
```

### 1.3 Nguyên tắc thiết kế (PHẢI tuân theo)

| # | Nguyên tắc | Ý nghĩa thực tế |
|---|-----------|----------------|
| 1 | Memory ≠ conversation history | KHÔNG inject raw messages vào prompt |
| 2 | Retrieval-based | Chỉ lấy memory **liên quan** đến query hiện tại |
| 3 | Async extraction | Extract memory KHÔNG được block chat response |
| 4 | Rule-first | Dùng rule-based trước, gọi LLM là last resort |
| 5 | Conservative extraction | Thà bỏ sót còn hơn tạo memory rác |
| 6 | Không merge layers | Mỗi layer có bảng riêng, logic riêng |

---

## 2. Cấu trúc thư mục

Tạo cấu trúc thư mục sau trong project (adjust theo project root hiện tại):

```
app/
├── memory/
│   ├── __init__.py
│   ├── detector.py          ← Memory Candidate Detector (rule-based)
│   ├── extractor.py         ← Extraction pipeline (Gemini Flash)
│   ├── retriever.py         ← Multi-layer retrieval
│   ├── assembler.py         ← Prompt assembly với token budgets
│   ├── scorer.py            ← importance_score, retrieval_score
│   ├── deduplicator.py      ← Dedup logic cho semantic memories
│   │
│   ├── layers/
│   │   ├── __init__.py
│   │   ├── working.py       ← Layer 1: Working Memory
│   │   ├── conversation.py  ← Layer 2: Conversation Summaries
│   │   ├── semantic.py      ← Layer 3: Semantic Memory
│   │   ├── preference.py    ← Layer 4: Preference Memory
│   │   ├── episodic.py      ← Layer 5: Episodic Memory
│   │   ├── knowledge.py     ← Layer 6: Knowledge Memory
│   │   └── action.py        ← Layer 7: Action Memory
│   │
│   ├── jobs/
│   │   ├── __init__.py
│   │   ├── consolidation.py ← Nightly consolidation jobs
│   │   └── scheduler.py     ← APScheduler setup
│   │
│   └── models/
│       ├── __init__.py
│       └── schemas.py       ← Pydantic schemas cho tất cả memory types
│
├── workers/
│   └── memory_worker.py     ← Background worker xử lý extraction queue
│
└── migrations/
    └── versions/
        ├── 001_add_pgvector.py
        ├── 002_create_memory_tables.py
        └── 003_migrate_existing_data.py
```

---

## 3. Database Setup — pgvector

### 3.1 Cài đặt extension

```sql
-- Chạy migration đầu tiên này trước mọi thứ khác
CREATE EXTENSION IF NOT EXISTS vector;

-- Verify
SELECT * FROM pg_extension WHERE extname = 'vector';
```

```python
# migrations/versions/001_add_pgvector.py
from alembic import op

def upgrade():
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')

def downgrade():
    op.execute('DROP EXTENSION IF EXISTS vector')
```

### 3.2 Python dependencies cần thêm

```
# requirements.txt — thêm các dòng sau
pgvector==0.2.5
redis==5.0.1
rq==1.16.1          # Redis Queue cho background workers
apscheduler==3.10.4  # Nightly jobs scheduler
tiktoken==0.5.2      # Token counting (dùng cl100k_base cho estimate)
```

### 3.3 Embedding configuration

```python
# app/config.py — thêm vào config hiện có
EMBEDDING_MODEL = "text-embedding-004"  # Google Gemini embedding
EMBEDDING_DIMENSIONS = 768
HNSW_M = 16                    # HNSW index parameter
HNSW_EF_CONSTRUCTION = 64      # Build time accuracy
HNSW_EF_SEARCH = 40            # Query time accuracy (set at runtime)
```

---

## 4. Layer 0 — Raw Conversation Storage

### 4.1 Mục đích

Layer này là **source of truth**. KHÔNG BAO GIỜ:
- Xóa messages
- Overwrite messages bằng summary
- Sửa nội dung messages

### 4.2 Schema hiện tại — GIỮ NGUYÊN

Bảng `agent_messages` hiện có — **không đổi gì**. Layer này chỉ để đọc, không bao giờ dùng để inject thẳng vào prompt (đó là việc của Layer 1).

### 4.3 Điều duy nhất cần thêm

```sql
-- Thêm index để query nhanh hơn nếu chưa có
CREATE INDEX IF NOT EXISTS idx_agent_messages_conversation_id
    ON agent_messages(conversation_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_agent_messages_token_count
    ON agent_messages(conversation_id, token_count);
```

```python
# Nếu bảng agent_messages chưa có cột token_count, thêm vào:
ALTER TABLE agent_messages ADD COLUMN IF NOT EXISTS token_count INTEGER;

# Backfill token_count cho messages cũ (chạy migration)
# app/memory/layers/working.py
import tiktoken

def estimate_tokens(text: str) -> int:
    """Estimate token count. Dùng cl100k_base làm proxy."""
    enc = tiktoken.get_encoding("cl100k_base")
    return len(enc.encode(text))
```

---

## 5. Layer 1 — Working Memory

### 5.1 Mục đích và logic

Working Memory là những messages **gần nhất** trong conversation hiện tại, đủ để agent hiểu context ngay lập tức. Thay thế hoàn toàn `MAX_CONVERSATION_HISTORY = 10`.

**Logic cốt lõi:** Walk backwards từ message mới nhất, cộng dồn token cho đến khi đụng budget.

### 5.2 Configuration

```python
# app/config.py
MAX_WORKING_MEMORY_TOKENS = 8000   # Khoảng 50-80 messages trung bình
```

### 5.3 Implementation

```python
# app/memory/layers/working.py
from typing import List, Dict, Any
from app.config import MAX_WORKING_MEMORY_TOKENS
from app.memory.layers.working import estimate_tokens
import tiktoken

class WorkingMemoryLayer:
    """
    Layer 1: Lấy các messages gần nhất trong budget token.
    KHÔNG dùng fixed message count. LUÔN dùng token budget.
    """

    def __init__(self, db_session):
        self.db = db_session
        self.budget = MAX_WORKING_MEMORY_TOKENS

    def get(self, conversation_id: str) -> List[Dict[str, Any]]:
        """
        Trả về list messages theo thứ tự chronological (cũ → mới),
        tối đa MAX_WORKING_MEMORY_TOKENS tokens.
        """
        # Lấy TẤT CẢ messages của conversation, mới nhất trước
        all_messages = self.db.execute("""
            SELECT id, role, content, token_count, created_at
            FROM agent_messages
            WHERE conversation_id = :conv_id
            ORDER BY created_at DESC
        """, {"conv_id": conversation_id}).fetchall()

        selected = []
        total_tokens = 0

        for msg in all_messages:
            # Dùng token_count đã lưu, hoặc estimate nếu NULL
            msg_tokens = msg.token_count or estimate_tokens(msg.content)

            if total_tokens + msg_tokens > self.budget:
                break  # Dừng — đã đầy budget

            selected.append({
                "role": msg.role,
                "content": msg.content,
                "id": msg.id,
            })
            total_tokens += msg_tokens

        # Đảo ngược để trả về thứ tự chronological (cũ → mới)
        selected.reverse()

        return selected

    def get_token_usage(self, conversation_id: str) -> Dict[str, int]:
        """
        Trả về thông tin token usage của conversation hiện tại.
        Dùng để quyết định có cần trigger Layer 2 summary không.
        """
        result = self.db.execute("""
            SELECT
                COUNT(*) as message_count,
                COALESCE(SUM(token_count), 0) as total_tokens
            FROM agent_messages
            WHERE conversation_id = :conv_id
        """, {"conv_id": conversation_id}).fetchone()

        return {
            "message_count": result.message_count,
            "total_tokens": result.total_tokens,
        }
```

### 5.4 Nơi cần sửa trong codebase hiện tại

Tìm và sửa những chỗ sau:

```python
# TÌM (pattern cũ — có thể có nhiều biến thể):
messages = conversation.messages[-10:]  # hoặc
messages = get_last_n_messages(10)      # hoặc
MAX_CONVERSATION_HISTORY = 10

# THAY BẰNG:
from app.memory.layers.working import WorkingMemoryLayer
working_memory = WorkingMemoryLayer(db_session)
messages = working_memory.get(conversation_id)
```

---

## 6. Layer 2 — Conversation Memory

### 6.1 Mục đích

Khi conversation dài (> 25,000 tokens), tạo **summary snapshots** để không mất context. Đây KHÔNG phải summary duy nhất — là chuỗi snapshots liên tiếp.

**Quan trọng:** Summaries chỉ là compression artifact. Raw messages ở Layer 0 vẫn nguyên vẹn.

### 6.2 Schema

```sql
-- migrations/versions/002_create_memory_tables.py (phần Layer 2)
CREATE TABLE conversation_summaries (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES conversations(id),
    start_message_id UUID NOT NULL,  -- Message đầu tiên của đoạn này
    end_message_id   UUID NOT NULL,  -- Message cuối của đoạn này
    summary         TEXT NOT NULL,
    token_count     INTEGER NOT NULL,  -- Token count của ĐOẠN được summarize
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_conv_summaries_conv_id
    ON conversation_summaries(conversation_id, created_at ASC);
```

### 6.3 Configuration

```python
# app/config.py
SUMMARY_TRIGGER_TOKENS = 25_000   # Trigger summary khi conversation đạt mức này
SUMMARY_SEGMENT_TOKENS = 20_000   # Mỗi lần summary bao nhiêu tokens của messages cũ
```

### 6.4 Logic hoạt động

```
Timeline conversation:
[msg_001...msg_050] = 25,000 tokens → TRIGGER summary_001
    summary_001 covers: msg_001 → msg_040 (20,000 tokens)
    msg_041 → msg_050 vẫn ở Working Memory

Tiếp tục nhắn tin...
[msg_041...msg_120] = thêm 25,000 tokens → TRIGGER summary_002
    summary_002 covers: msg_041 → msg_110 (20,000 tokens)
    msg_111 → msg_120 vẫn ở Working Memory
```

### 6.5 Implementation

```python
# app/memory/layers/conversation.py
from app.config import SUMMARY_TRIGGER_TOKENS, SUMMARY_SEGMENT_TOKENS

class ConversationMemoryLayer:

    SUMMARY_PROMPT = """Bạn là assistant tóm tắt cuộc hội thoại.
Hãy tóm tắt đoạn hội thoại dưới đây theo format:

**Chủ đề chính:** [1-2 câu về nội dung chính]
**Quyết định/Kết luận:** [Các quyết định quan trọng đã được đưa ra]
**Thông tin quan trọng:** [Facts, context cần nhớ cho sau]
**Công việc đang làm:** [Task nào đang dở dang nếu có]

Chỉ ghi những gì thực sự quan trọng. Không ghi lại small talk hay thông tin tạm thời.

---
{messages}
---

Tóm tắt:"""

    def __init__(self, db_session, gemini_client):
        self.db = db_session
        self.gemini = gemini_client

    def check_and_trigger(self, conversation_id: str) -> None:
        """
        Gọi hàm này SAU MỖI MESSAGE để kiểm tra có cần tạo summary không.
        Chạy async — không block response.
        """
        usage = WorkingMemoryLayer(self.db).get_token_usage(conversation_id)

        # Tìm message cuối đã được summarize
        last_summary = self.db.execute("""
            SELECT end_message_id, created_at
            FROM conversation_summaries
            WHERE conversation_id = :conv_id
            ORDER BY created_at DESC
            LIMIT 1
        """, {"conv_id": conversation_id}).fetchone()

        # Tính tokens của phần CHƯA được summarize
        if last_summary:
            unsummarized_tokens = self._count_tokens_after(
                conversation_id, last_summary.end_message_id
            )
        else:
            unsummarized_tokens = usage["total_tokens"]

        if unsummarized_tokens >= SUMMARY_TRIGGER_TOKENS:
            self._create_summary(conversation_id, last_summary)

    def _create_summary(self, conversation_id: str, last_summary) -> None:
        """Tạo summary cho SEGMENT_TOKENS tokens tiếp theo."""

        # Lấy messages chưa summarize, cũ nhất trước
        after_id = last_summary.end_message_id if last_summary else None

        messages_to_summarize = self._get_unsummarized_messages(
            conversation_id, after_id, limit_tokens=SUMMARY_SEGMENT_TOKENS
        )

        if not messages_to_summarize:
            return

        # Format messages để đưa vào prompt
        formatted = "\n".join([
            f"[{msg['role'].upper()}]: {msg['content']}"
            for msg in messages_to_summarize
        ])

        # Gọi Gemini Flash để tóm tắt
        summary_text = self.gemini.generate(
            model="gemini-1.5-flash",
            prompt=self.SUMMARY_PROMPT.format(messages=formatted),
            max_tokens=500,
        )

        # Lưu vào DB
        self.db.execute("""
            INSERT INTO conversation_summaries
                (conversation_id, start_message_id, end_message_id, summary, token_count)
            VALUES (:conv_id, :start_id, :end_id, :summary, :token_count)
        """, {
            "conv_id": conversation_id,
            "start_id": messages_to_summarize[0]["id"],
            "end_id": messages_to_summarize[-1]["id"],
            "summary": summary_text,
            "token_count": sum(m.get("token_count", 0) for m in messages_to_summarize),
        })
        self.db.commit()

    def get_relevant_summaries(self, conversation_id: str) -> List[str]:
        """
        Trả về tất cả summaries của conversation (theo thứ tự thời gian).
        Dùng trong Prompt Assembly.
        """
        rows = self.db.execute("""
            SELECT summary FROM conversation_summaries
            WHERE conversation_id = :conv_id
            ORDER BY created_at ASC
        """, {"conv_id": conversation_id}).fetchall()

        return [row.summary for row in rows]
```

---

## 7. Layer 3 — Semantic Memory

### 7.1 Mục đích

Lưu **facts dài hạn** về user. Đây là "bộ nhớ dài hạn" thực sự của agent.

**Ví dụ nên lưu:**
- "User đang build Cortex AI platform"
- "User dùng Fedora Linux"
- "User prefer FastAPI hơn Django"
- "User có deadline ngày 30 tháng này"

**Ví dụ KHÔNG lưu (trivial information):**
- "Hôm nay trời nóng"
- "Tôi vừa ăn pizza"
- "Tôi đang buồn"

### 7.2 Schema

```sql
-- Thêm vào migration 002
CREATE TABLE semantic_memories (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id          UUID NOT NULL,
    workspace_id     UUID,
    memory_type      VARCHAR(50) NOT NULL,  -- 'fact', 'preference', 'goal', 'relationship', 'identity'
    subject          VARCHAR(200) NOT NULL, -- Chủ thể: 'user', 'project:cortex', 'tool:fastapi'
    value            TEXT NOT NULL,         -- Nội dung fact
    confidence_score FLOAT NOT NULL DEFAULT 0.8,  -- 0.0 → 1.0
    importance_score FLOAT NOT NULL DEFAULT 0.5,  -- 0.0 → 1.0
    memory_class     VARCHAR(20) NOT NULL,  -- 'PERMANENT', 'LONG_TERM', 'TEMPORARY'
    source_message_id UUID,                 -- Tin nhắn nào tạo ra memory này
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    updated_at       TIMESTAMPTZ DEFAULT NOW(),
    expires_at       TIMESTAMPTZ,           -- NULL = không hết hạn (PERMANENT)
    is_active        BOOLEAN DEFAULT TRUE
);

CREATE INDEX idx_semantic_user_id ON semantic_memories(user_id, is_active);
CREATE INDEX idx_semantic_subject ON semantic_memories(subject, user_id);
CREATE INDEX idx_semantic_type ON semantic_memories(memory_type, user_id);
CREATE INDEX idx_semantic_expires ON semantic_memories(expires_at)
    WHERE expires_at IS NOT NULL;
```

### 7.3 Memory classes và retention

```python
# app/memory/layers/semantic.py
from datetime import datetime, timedelta
from enum import Enum

class MemoryClass(str, Enum):
    PERMANENT = "PERMANENT"  # Không hết hạn. VD: "User là developer"
    LONG_TERM = "LONG_TERM"  # 180 ngày. VD: "User đang làm project X"
    TEMPORARY = "TEMPORARY"  # 14 ngày. VD: "User có meeting thứ 6 này"

RETENTION_DAYS = {
    MemoryClass.PERMANENT: None,   # None = không hết hạn
    MemoryClass.LONG_TERM: 180,
    MemoryClass.TEMPORARY: 14,
}

def compute_expires_at(memory_class: MemoryClass) -> datetime | None:
    days = RETENTION_DAYS[memory_class]
    if days is None:
        return None
    return datetime.utcnow() + timedelta(days=days)
```

### 7.4 Extraction Prompt — Gemini Flash

Đây là prompt CHÍNH XÁC phải dùng khi extract semantic memory:

```python
# app/memory/extractor.py
SEMANTIC_EXTRACTION_PROMPT = """Bạn là memory extraction engine. Nhiệm vụ: phân tích message và extract những fact quan trọng về user.

## RULES QUAN TRỌNG:
1. CHỈ extract fact dài hạn, có giá trị. KHÔNG extract thông tin tạm thời.
2. Mỗi memory phải là một fact độc lập, rõ ràng.
3. Nếu không có fact nào đáng extract, trả về list rỗng.

## Các memory_type hợp lệ:
- "fact": thông tin khách quan về user/project/môi trường
- "preference": sở thích, phong cách làm việc
- "goal": mục tiêu, kế hoạch
- "relationship": mối quan hệ với người/tổ chức
- "identity": đặc điểm bản thân (nghề nghiệp, kỹ năng)

## Các memory_class hợp lệ:
- "PERMANENT": fact ổn định lâu dài (nghề nghiệp, tech stack chính)
- "LONG_TERM": fact kéo dài vài tháng (dự án hiện tại, mục tiêu năm nay)
- "TEMPORARY": fact chỉ liên quan vài tuần (deadline gần, event sắp tới)

## Confidence scoring:
- 0.9-1.0: User nói trực tiếp, rõ ràng ("Tôi dùng Fedora")
- 0.7-0.8: Có thể suy luận chắc chắn từ context
- 0.5-0.6: Suy luận có thể đúng nhưng không chắc chắn

## Input:
User message: "{user_message}"
Context (conversation gần đây): "{recent_context}"

## Output (JSON array, KHÔNG có markdown backticks):
[
  {{
    "memory_type": "fact|preference|goal|relationship|identity",
    "subject": "user|project:<name>|tool:<name>|...",
    "value": "nội dung fact ngắn gọn, rõ ràng",
    "confidence_score": 0.0-1.0,
    "importance_score": 0.0-1.0,
    "memory_class": "PERMANENT|LONG_TERM|TEMPORARY"
  }}
]

Nếu không có gì đáng extract: []
"""
```

### 7.5 Deduplication Logic

```python
# app/memory/deduplicator.py

class SemanticDeduplicator:
    """
    Xử lý conflict khi extract memory mới trùng với memory cũ.
    """

    SIMILARITY_THRESHOLD = 0.85  # Cosine similarity để coi là "cùng topic"

    def deduplicate(self, new_memory: dict, user_id: str, db) -> str:
        """
        Returns: 'insert' | 'update' | 'skip'
        """
        # Bước 1: Tìm exact match (cùng subject + memory_type)
        existing = db.execute("""
            SELECT id, value, confidence_score, importance_score
            FROM semantic_memories
            WHERE user_id = :user_id
              AND subject = :subject
              AND memory_type = :memory_type
              AND is_active = TRUE
        """, {
            "user_id": user_id,
            "subject": new_memory["subject"],
            "memory_type": new_memory["memory_type"],
        }).fetchall()

        if not existing:
            return "insert"  # Không có gì trùng → insert mới

        for row in existing:
            # Bước 2: Kiểm tra value có mâu thuẫn không
            if self._is_same_fact(row.value, new_memory["value"]):
                # Cùng fact → update confidence nếu cao hơn
                if new_memory["confidence_score"] > row.confidence_score:
                    self._update_confidence(row.id, new_memory["confidence_score"], db)
                return "skip"  # Đã có, không cần insert

            if self._is_contradicting(row.value, new_memory["value"]):
                # Mâu thuẫn → xử lý theo confidence
                if new_memory["confidence_score"] > row.confidence_score + 0.1:
                    # Memory mới đáng tin hơn → deactivate cũ, insert mới
                    self._deactivate(row.id, db)
                    return "insert"
                else:
                    # Không chắc → giảm confidence của cả hai, giữ nguyên
                    self._reduce_confidence(row.id, db)
                    return "skip"

        return "insert"  # Không trùng → insert mới

    def _is_same_fact(self, value_a: str, value_b: str) -> bool:
        """Simple check: normalized string similarity > 0.8."""
        a = value_a.lower().strip()
        b = value_b.lower().strip()
        # Exact match
        if a == b:
            return True
        # Substring match (một cái contain cái kia)
        if a in b or b in a:
            return True
        return False

    def _is_contradicting(self, value_a: str, value_b: str) -> bool:
        """
        Detect contradiction bằng keyword heuristic.
        VD: "dùng Fedora" vs "dùng Ubuntu" → contradicting
        VD: "thích FastAPI" vs "thích Django" → contradicting
        """
        # Cùng subject nhưng value khác nhau đáng kể
        # Simple heuristic: nếu _is_same_fact = False và cùng loại statement
        return True  # Default: coi là contradicting nếu không phải same fact

    def _update_confidence(self, memory_id: str, new_confidence: float, db):
        db.execute("""
            UPDATE semantic_memories
            SET confidence_score = :conf, updated_at = NOW()
            WHERE id = :id
        """, {"conf": new_confidence, "id": memory_id})

    def _deactivate(self, memory_id: str, db):
        db.execute("""
            UPDATE semantic_memories
            SET is_active = FALSE, updated_at = NOW()
            WHERE id = :id
        """, {"id": memory_id})

    def _reduce_confidence(self, memory_id: str, db):
        db.execute("""
            UPDATE semantic_memories
            SET confidence_score = confidence_score * 0.7, updated_at = NOW()
            WHERE id = :id
        """, {"id": memory_id})
```

---

## 8. Layer 4 — Preference Memory

### 8.1 Mục đích

Lưu **sở thích và phong cách** của user. Layer này dùng **SQL thuần**, không dùng vector search — vì số lượng preference nhỏ (thường < 50 per user) và cần retrieve toàn bộ mỗi lần.

### 8.2 Schema

```sql
CREATE TABLE preference_memories (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id          UUID NOT NULL,
    category         VARCHAR(100) NOT NULL,  -- 'coding_style', 'writing_style', 'communication', 'tools', 'planning'
    key              VARCHAR(200) NOT NULL,  -- 'indentation', 'language', 'verbosity'
    value            TEXT NOT NULL,          -- 'tabs', 'python', 'concise'
    confidence_score FLOAT DEFAULT 0.8,
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    updated_at       TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, category, key)           -- Mỗi user chỉ có 1 preference per key
);

CREATE INDEX idx_pref_user_id ON preference_memories(user_id);
CREATE INDEX idx_pref_category ON preference_memories(user_id, category);
```

### 8.3 Các category hợp lệ

```python
# app/memory/layers/preference.py
PREFERENCE_CATEGORIES = {
    "coding_style": [
        "language",          # python, javascript, go...
        "framework",         # fastapi, django, express...
        "indentation",       # tabs, 2-spaces, 4-spaces
        "comment_style",     # verbose, minimal, docstring-only
        "naming_convention", # snake_case, camelCase...
    ],
    "writing_style": [
        "tone",              # formal, casual, technical
        "length",            # concise, detailed, bullet-points
        "language",          # vietnamese, english, mixed
    ],
    "communication": [
        "verbosity",         # brief, detailed
        "format",            # markdown, plain-text, structured
        "examples",          # always, never, on-request
    ],
    "tools": [
        "editor",            # vscode, neovim, pycharm
        "os",                # fedora, ubuntu, macos, windows
        "terminal",          # bash, zsh, fish
        "version_control",   # git workflow preference
    ],
    "planning": [
        "methodology",       # agile, kanban, waterfall
        "granularity",       # high-level, detailed, step-by-step
        "documentation",     # heavy, minimal, code-comments-only
    ],
}
```

### 8.4 Implementation

```python
class PreferenceMemoryLayer:

    def get_all(self, user_id: str) -> Dict[str, Dict[str, str]]:
        """
        Lấy TẤT CẢ preferences của user, group theo category.
        KHÔNG dùng vector search — SQL thuần.
        """
        rows = self.db.execute("""
            SELECT category, key, value, confidence_score
            FROM preference_memories
            WHERE user_id = :user_id
            ORDER BY category, key
        """, {"user_id": user_id}).fetchall()

        result = {}
        for row in rows:
            if row.category not in result:
                result[row.category] = {}
            result[row.category][row.key] = {
                "value": row.value,
                "confidence": row.confidence_score,
            }
        return result

    def upsert(self, user_id: str, category: str, key: str,
               value: str, confidence: float) -> None:
        """
        Insert hoặc update preference.
        Dùng UPSERT — không cần check trước.
        """
        self.db.execute("""
            INSERT INTO preference_memories (user_id, category, key, value, confidence_score)
            VALUES (:user_id, :category, :key, :value, :confidence)
            ON CONFLICT (user_id, category, key)
            DO UPDATE SET
                value = EXCLUDED.value,
                confidence_score = EXCLUDED.confidence_score,
                updated_at = NOW()
        """, {
            "user_id": user_id, "category": category,
            "key": key, "value": value, "confidence": confidence,
        })
        self.db.commit()

    def format_for_prompt(self, preferences: Dict) -> str:
        """Format preferences thành text ngắn gọn để inject vào prompt."""
        lines = []
        for category, prefs in preferences.items():
            for key, data in prefs.items():
                if data["confidence"] >= 0.7:  # Chỉ inject preference đủ tin cậy
                    lines.append(f"- {category}.{key}: {data['value']}")
        return "\n".join(lines) if lines else "No preferences recorded."
```

---

## 9. Layer 5 — Episodic Memory

### 9.1 Mục đích

Lưu **các sự kiện quan trọng** trong cuộc sống kỹ thuật số của user. Điểm cốt lõi: **không tạo 1 memory per conversation**. Nhiều conversations về cùng một sự kiện → gộp vào 1 episode.

### 9.2 Schema

```sql
CREATE TABLE episodic_memories (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id          UUID NOT NULL,
    event_type       VARCHAR(100) NOT NULL,  -- 'project_work', 'learning', 'decision', 'milestone', 'problem_solved'
    event_title      VARCHAR(300) NOT NULL,  -- "Phát triển hệ thống revert cho Cortex"
    event_summary    TEXT NOT NULL,          -- Summary tổng hợp từ nhiều sessions
    importance_score FLOAT DEFAULT 0.5,
    related_entities JSONB DEFAULT '[]',     -- ["project:cortex", "tool:redis", "person:john"]
    first_seen_at    TIMESTAMPTZ DEFAULT NOW(),
    last_seen_at     TIMESTAMPTZ DEFAULT NOW(),
    occurrence_count INTEGER DEFAULT 1,      -- Số lần conversation đề cập đến event này
    is_active        BOOLEAN DEFAULT TRUE,
    source_conversation_ids JSONB DEFAULT '[]'  -- List conversation IDs liên quan
);

CREATE INDEX idx_episodic_user_id ON episodic_memories(user_id, is_active);
CREATE INDEX idx_episodic_entities ON episodic_memories USING GIN(related_entities);
CREATE INDEX idx_episodic_last_seen ON episodic_memories(user_id, last_seen_at DESC);
```

### 9.3 Episode Aggregation Algorithm

Đây là phần phức tạp nhất của Layer 5. Logic quyết định "đây là episode mới hay tiếp nối episode cũ":

```python
# app/memory/layers/episodic.py

class EpisodicMemoryLayer:

    AGGREGATION_PROMPT = """Bạn đang phân tích xem một conversation có tiếp nối một episode cũ không.

## Episode cũ:
Title: {existing_title}
Summary: {existing_summary}
Entities: {existing_entities}

## Conversation mới vừa kết thúc:
{conversation_summary}
Entities đề cập: {new_entities}

## Câu hỏi:
Conversation mới này có tiếp nối/liên quan đến episode cũ không?

Trả lời JSON (KHÔNG có markdown):
{{
  "is_continuation": true/false,
  "confidence": 0.0-1.0,
  "updated_summary": "summary mới nếu là continuation, null nếu không",
  "reason": "giải thích ngắn gọn"
}}
"""

    NEW_EPISODE_PROMPT = """Bạn là episode extractor. Phân tích conversation và tạo episode nếu có sự kiện quan trọng.

## Conversation summary:
{conversation_summary}

## Tiêu chí tạo episode mới:
- Có milestone quan trọng (hoàn thành feature, fix bug lớn, quyết định architecture)
- Có learning mới đáng kể
- Có quyết định quan trọng được đưa ra
- KHÔNG tạo episode cho: small talk, câu hỏi thông thường, debug nhỏ

## Output JSON (KHÔNG có markdown):
{{
  "should_create": true/false,
  "event_type": "project_work|learning|decision|milestone|problem_solved",
  "event_title": "tiêu đề ngắn gọn mô tả sự kiện",
  "event_summary": "tóm tắt 2-3 câu về sự kiện",
  "importance_score": 0.0-1.0,
  "related_entities": ["project:name", "tool:name", "concept:name"]
}}
"""

    def process_conversation_end(self, conversation_id: str,
                                  user_id: str, db, gemini) -> None:
        """
        Gọi khi conversation kết thúc (user không active 30 phút hoặc explicit end).
        Chạy ASYNC — không block gì.

        Flow:
        1. Lấy summary của conversation vừa xong
        2. Extract entities từ conversation
        3. Kiểm tra có episode nào đang active match không
        4. Nếu có → update episode đó
        5. Nếu không → kiểm tra có nên tạo episode mới không
        """

        # Bước 1: Lấy summary conversation
        conv_summary = self._get_conversation_summary(conversation_id, db)
        if not conv_summary:
            return  # Conversation quá ngắn, bỏ qua

        # Bước 2: Extract entities (simple rule-based)
        new_entities = self._extract_entities_from_summary(conv_summary)

        # Bước 3: Tìm episode candidate (dựa trên entity overlap)
        candidate_episodes = self._find_candidate_episodes(
            user_id, new_entities, db
        )

        for episode in candidate_episodes:
            # Bước 4: Hỏi Gemini xem có phải continuation không
            result = gemini.generate_json(
                self.AGGREGATION_PROMPT.format(
                    existing_title=episode.event_title,
                    existing_summary=episode.event_summary,
                    existing_entities=episode.related_entities,
                    conversation_summary=conv_summary,
                    new_entities=new_entities,
                )
            )

            if result["is_continuation"] and result["confidence"] > 0.7:
                # UPDATE episode cũ
                db.execute("""
                    UPDATE episodic_memories SET
                        event_summary = :summary,
                        last_seen_at = NOW(),
                        occurrence_count = occurrence_count + 1,
                        source_conversation_ids = source_conversation_ids || :conv_id::jsonb
                    WHERE id = :id
                """, {
                    "summary": result["updated_summary"],
                    "conv_id": f'["{conversation_id}"]',
                    "id": episode.id,
                })
                db.commit()
                return  # Đã update, không cần tạo mới

        # Bước 5: Không có episode nào match → kiểm tra có nên tạo mới không
        new_episode_data = gemini.generate_json(
            self.NEW_EPISODE_PROMPT.format(
                conversation_summary=conv_summary
            )
        )

        if new_episode_data["should_create"]:
            db.execute("""
                INSERT INTO episodic_memories
                    (user_id, event_type, event_title, event_summary,
                     importance_score, related_entities, source_conversation_ids)
                VALUES
                    (:user_id, :event_type, :event_title, :event_summary,
                     :importance_score, :entities::jsonb, :conv_ids::jsonb)
            """, {
                "user_id": user_id,
                "event_type": new_episode_data["event_type"],
                "event_title": new_episode_data["event_title"],
                "event_summary": new_episode_data["event_summary"],
                "importance_score": new_episode_data["importance_score"],
                "entities": json.dumps(new_episode_data["related_entities"]),
                "conv_ids": json.dumps([conversation_id]),
            })
            db.commit()

    def _find_candidate_episodes(self, user_id: str,
                                   entities: List[str], db) -> List:
        """
        Tìm episodes có entity overlap với conversation mới.
        Chỉ xét episodes trong 90 ngày gần nhất.
        """
        if not entities:
            return []

        rows = db.execute("""
            SELECT id, event_title, event_summary, related_entities
            FROM episodic_memories
            WHERE user_id = :user_id
              AND is_active = TRUE
              AND last_seen_at > NOW() - INTERVAL '90 days'
              AND related_entities ?| :entities
            ORDER BY last_seen_at DESC
            LIMIT 5
        """, {
            "user_id": user_id,
            "entities": entities,  # pgvector hỗ trợ ?| operator cho JSONB array
        }).fetchall()

        return rows

    def _extract_entities_from_summary(self, summary: str) -> List[str]:
        """
        Rule-based entity extraction từ summary text.
        Format entity: "type:name" (lowercase)
        """
        entities = []

        # Project patterns
        import re
        project_patterns = [
            r'\b(cortex|project\s+\w+)\b',
            r'build(?:ing)?\s+(\w+)',
            r'develop(?:ing)?\s+(\w+)',
        ]

        # Tool/tech patterns
        tech_keywords = [
            "fastapi", "django", "redis", "postgresql", "pgvector",
            "gemini", "python", "docker", "kubernetes", "celery",
            "react", "nextjs", "typescript", "javascript",
        ]

        summary_lower = summary.lower()
        for tech in tech_keywords:
            if tech in summary_lower:
                entities.append(f"tool:{tech}")

        # Action patterns
        if any(word in summary_lower for word in ["migrate", "migration"]):
            entities.append("action:migration")
        if any(word in summary_lower for word in ["deploy", "deployment"]):
            entities.append("action:deployment")
        if any(word in summary_lower for word in ["fix", "bug", "error", "debug"]):
            entities.append("action:debugging")
        if any(word in summary_lower for word in ["design", "architect", "system"]):
            entities.append("action:design")

        return list(set(entities))
```

---

## 10. Layer 6 — Knowledge Memory

### 10.1 Mục đích

Represent user's **owned knowledge base** — từ notes, tasks, recordings, calendar, v.v. Layer này là cái duy nhất dùng **vector search** làm primary retrieval method.

**Key insight:** Tool observations cũng là knowledge. Nếu calendar có exam ngày 25, agent phải biết điều này dù user chưa nói.

### 10.2 Schema

```sql
CREATE TABLE knowledge_chunks (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL,
    source_type VARCHAR(50) NOT NULL,   -- 'note', 'task', 'schedule', 'recording', 'calendar', 'tool_observation'
    source_id   UUID,                   -- ID của entity gốc (nullable cho tool_observations)
    chunk_text  TEXT NOT NULL,
    embedding   VECTOR(768),            -- Google text-embedding-004
    metadata    JSONB DEFAULT '{}',     -- {"title": "...", "date": "...", "tags": [...]}
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW(),
    expires_at  TIMESTAMPTZ,            -- NULL = permanent. Calendar events có expires_at sau event date
    is_active   BOOLEAN DEFAULT TRUE
);

-- HNSW index — quan trọng: phải tạo với params đúng
CREATE INDEX idx_knowledge_embedding
    ON knowledge_chunks
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX idx_knowledge_user_source
    ON knowledge_chunks(user_id, source_type, is_active);

CREATE INDEX idx_knowledge_expires
    ON knowledge_chunks(expires_at)
    WHERE expires_at IS NOT NULL;
```

### 10.3 Chunking Strategy

```python
# app/memory/layers/knowledge.py

CHUNK_CONFIG = {
    "note":              {"chunk_size": 500, "overlap": 50},
    "recording":         {"chunk_size": 300, "overlap": 30},  # Transcript, nhiều lỗi hơn
    "task":              {"chunk_size": 200, "overlap": 0},    # Tasks thường ngắn
    "schedule":          {"chunk_size": 200, "overlap": 0},
    "calendar":          {"chunk_size": 150, "overlap": 0},    # Thường rất ngắn
    "tool_observation":  {"chunk_size": 200, "overlap": 0},
}

def chunk_text(text: str, source_type: str) -> List[str]:
    """
    Split text thành chunks. Words-based để tránh cắt giữa từ.
    """
    config = CHUNK_CONFIG.get(source_type, {"chunk_size": 400, "overlap": 40})
    chunk_size = config["chunk_size"]
    overlap = config["overlap"]

    words = text.split()
    chunks = []
    start = 0

    while start < len(words):
        end = start + chunk_size
        chunk = " ".join(words[start:end])
        chunks.append(chunk)
        start = end - overlap  # Overlap để không mất context ở ranh giới

    return [c for c in chunks if len(c.strip()) > 20]  # Bỏ chunks quá ngắn

class KnowledgeMemoryLayer:

    def embed_and_store(self, user_id: str, source_type: str,
                         source_id: str | None, text: str,
                         metadata: dict = None, expires_at=None) -> None:
        """
        Chunk text, tạo embeddings, lưu vào DB.
        Gọi khi user tạo/update note, task, calendar event, v.v.
        """
        chunks = chunk_text(text, source_type)

        for chunk in chunks:
            embedding = self.embed(chunk)  # Gọi Google text-embedding-004

            self.db.execute("""
                INSERT INTO knowledge_chunks
                    (user_id, source_type, source_id, chunk_text, embedding, metadata, expires_at)
                VALUES
                    (:user_id, :source_type, :source_id, :chunk_text,
                     :embedding, :metadata::jsonb, :expires_at)
            """, {
                "user_id": user_id,
                "source_type": source_type,
                "source_id": source_id,
                "chunk_text": chunk,
                "embedding": embedding,
                "metadata": json.dumps(metadata or {}),
                "expires_at": expires_at,
            })
        self.db.commit()

    def search(self, user_id: str, query: str,
                limit: int = 5, source_types: List[str] = None) -> List[Dict]:
        """
        Vector search với HNSW index.
        """
        # Set ef_search trước khi query (HNSW accuracy parameter)
        self.db.execute("SET hnsw.ef_search = 40")

        query_embedding = self.embed(query)

        # Build filter
        source_filter = ""
        params = {"user_id": user_id, "embedding": query_embedding, "limit": limit}
        if source_types:
            source_filter = "AND source_type = ANY(:source_types)"
            params["source_types"] = source_types

        rows = self.db.execute(f"""
            SELECT
                chunk_text,
                source_type,
                source_id,
                metadata,
                1 - (embedding <=> :embedding::vector) AS similarity_score
            FROM knowledge_chunks
            WHERE user_id = :user_id
              AND is_active = TRUE
              AND (expires_at IS NULL OR expires_at > NOW())
              {source_filter}
            ORDER BY embedding <=> :embedding::vector
            LIMIT :limit
        """, params).fetchall()

        return [
            {
                "text": row.chunk_text,
                "source_type": row.source_type,
                "source_id": row.source_id,
                "metadata": row.metadata,
                "score": row.similarity_score,
            }
            for row in rows if row.similarity_score > 0.65  # Threshold: bỏ kết quả quá kém
        ]

    def invalidate_source(self, source_type: str, source_id: str) -> None:
        """
        Khi note/task bị xóa hoặc update → deactivate chunks cũ.
        Gọi TRƯỚC khi re-embed version mới.
        """
        self.db.execute("""
            UPDATE knowledge_chunks
            SET is_active = FALSE, updated_at = NOW()
            WHERE source_type = :source_type AND source_id = :source_id
        """, {"source_type": source_type, "source_id": source_id})
        self.db.commit()
```

---

## 11. Layer 7 — Action Memory

### 11.1 Mục đích

Lưu lịch sử actions của agent để support **undo** và **audit**. Hai tầng: Redis (fast undo) và PostgreSQL (long-term audit).

### 11.2 Redis (Hot Layer)

```python
# app/memory/layers/action.py
import redis
import json
from datetime import timedelta

REDIS_ACTION_TTL = 86400  # 24 giờ

class ActionHotLayer:
    """Redis layer — cho undo nhanh."""

    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client

    def record(self, action_id: str, user_id: str, tool_name: str,
               action_type: str, before_state: dict, after_state: dict) -> None:
        """Lưu action vào Redis với TTL 24h."""
        key = f"action:{user_id}:{action_id}"
        data = {
            "action_id": action_id,
            "tool_name": tool_name,
            "action_type": action_type,
            "before_state": before_state,
            "after_state": after_state,
        }
        self.redis.setex(key, REDIS_ACTION_TTL, json.dumps(data))

        # Thêm vào list theo user (cho recent actions)
        list_key = f"actions:{user_id}"
        self.redis.lpush(list_key, action_id)
        self.redis.ltrim(list_key, 0, 99)  # Giữ 100 actions gần nhất
        self.redis.expire(list_key, REDIS_ACTION_TTL)

    def get_for_undo(self, user_id: str, action_id: str) -> dict | None:
        """Lấy action để undo. Chỉ khả dụng trong 24h."""
        key = f"action:{user_id}:{action_id}"
        data = self.redis.get(key)
        return json.loads(data) if data else None

    def get_recent(self, user_id: str, limit: int = 10) -> List[dict]:
        """Lấy N actions gần nhất của user."""
        list_key = f"actions:{user_id}"
        action_ids = self.redis.lrange(list_key, 0, limit - 1)

        actions = []
        for action_id in action_ids:
            key = f"action:{user_id}:{action_id.decode()}"
            data = self.redis.get(key)
            if data:
                actions.append(json.loads(data))
        return actions
```

### 11.3 PostgreSQL (Cold Layer)

```sql
CREATE TABLE action_history (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      UUID NOT NULL,
    tool_name    VARCHAR(100) NOT NULL,
    action_type  VARCHAR(50) NOT NULL,   -- 'create', 'update', 'delete', 'execute'
    before_state JSONB,                  -- State trước khi action
    after_state  JSONB,                  -- State sau khi action
    created_at   TIMESTAMPTZ DEFAULT NOW()
);

-- Partition theo tháng để query nhanh hơn (optional, áp dụng khi > 1M rows)
CREATE INDEX idx_action_user_id ON action_history(user_id, created_at DESC);
CREATE INDEX idx_action_tool ON action_history(tool_name, created_at DESC);

-- Auto-delete sau 30 ngày (chạy bằng pg_cron hoặc nightly job)
-- DELETE FROM action_history WHERE created_at < NOW() - INTERVAL '30 days';
```

```python
class ActionColdLayer:
    """PostgreSQL layer — cho audit và long-term recovery."""

    def record(self, action_id: str, user_id: str, tool_name: str,
               action_type: str, before_state: dict, after_state: dict) -> None:
        self.db.execute("""
            INSERT INTO action_history (id, user_id, tool_name, action_type, before_state, after_state)
            VALUES (:id, :user_id, :tool_name, :action_type, :before::jsonb, :after::jsonb)
        """, {
            "id": action_id, "user_id": user_id, "tool_name": tool_name,
            "action_type": action_type,
            "before": json.dumps(before_state),
            "after": json.dumps(after_state),
        })
        self.db.commit()

class ActionMemoryLayer:
    """Facade combining hot + cold layers."""

    def __init__(self, redis_client, db_session):
        self.hot = ActionHotLayer(redis_client)
        self.cold = ActionColdLayer(db_session)

    def record(self, action_id: str, user_id: str, **kwargs) -> None:
        """Ghi vào CẢ HAI layers đồng thời."""
        self.hot.record(action_id, user_id, **kwargs)
        self.cold.record(action_id, user_id, **kwargs)

    def undo(self, user_id: str, action_id: str) -> dict | None:
        """
        Lấy before_state để revert.
        Thử Redis trước (nhanh hơn), fallback sang PostgreSQL.
        """
        action = self.hot.get_for_undo(user_id, action_id)
        if action:
            return action["before_state"]

        # Fallback: tìm trong PostgreSQL (action > 24h tuổi)
        row = self.db.execute("""
            SELECT before_state FROM action_history
            WHERE id = :id AND user_id = :user_id
        """, {"id": action_id, "user_id": user_id}).fetchone()

        return row.before_state if row else None
```

---

## 12. Memory Candidate Detector

### 12.1 Mục đích

**Rule-based filter** — quyết định message nào cần gửi đến extraction pipeline. Mục tiêu: giảm 70–90% LLM calls. Chạy SYNCHRONOUS, TRƯỚC KHI gửi response.

### 12.2 Signal Rules

```python
# app/memory/detector.py
import re
from dataclasses import dataclass
from typing import List, Tuple

@dataclass
class DetectionResult:
    should_extract: bool
    signals: List[str]      # Các signal nào được trigger
    priority: str           # 'high', 'medium', 'low'

class MemoryCandidateDetector:
    """
    Rule-based detector. KHÔNG gọi LLM.
    Nếu pass → đưa vào extraction queue.
    Nếu không pass → skip extraction hoàn toàn.
    """

    # ─── SIGNAL PATTERNS ───────────────────────────────────────────────────────

    # Signal: Identity / Preference statements
    PREFERENCE_PATTERNS = [
        r'\b(tôi|mình|tao)\s+(thích|prefer|dùng|sử dụng|hay dùng)\b',
        r'\b(tôi|mình)\s+(không thích|ghét|tránh|không dùng)\b',
        r'\bi\s+(prefer|like|use|hate|avoid|always|never)\b',
        r'\bmy\s+(preferred|favorite|go-to|usual)\b',
        r'\b(tôi|mình)\s+(thường|hay)\s+(làm|code|viết|dùng)\b',
    ]

    # Signal: Tech stack / Environment facts
    TECH_PATTERNS = [
        r'\b(dùng|using|running|on|with)\s+(python|fastapi|django|redis|postgresql|docker|linux|fedora|ubuntu|macos|windows|vscode|neovim|pycharm)\b',
        r'\bstack\s+(của|hiện tại|tôi dùng)\b',
        r'\b(os|operating system|editor|ide|framework|language)\s+(của|mình|tôi)\b',
    ]

    # Signal: Goals / Projects
    GOAL_PATTERNS = [
        r'\b(đang|am)\s+(build|develop|làm|viết|tạo|xây dựng|thiết kế)\b',
        r'\b(project|dự án|app|application|system|hệ thống)\s+(của|tôi|mình|tên là)\b',
        r'\b(mục tiêu|goal|plan|kế hoạch)\s+(là|của tôi)\b',
        r'\b(muốn|want to|plan to|going to)\s+(build|create|develop|launch)\b',
    ]

    # Signal: Deadlines / Time-sensitive info
    DEADLINE_PATTERNS = [
        r'\b(deadline|due|hạn|phải xong|cần hoàn thành)\b',
        r'\b(ngày|tháng|tuần)\s+(sau|tới|này)\b.*\b(phải|cần|muốn)\b',
        r'\b(by|before|trước)\s+\w+\s+\d{1,2}\b',
        r'\blaunch\s+(on|by|before)\b',
    ]

    # Signal: Relationships / People
    RELATIONSHIP_PATTERNS = [
        r'\b(sếp|manager|boss|teammate|đồng nghiệp|colleague|client|khách hàng)\b',
        r'\b(team|nhóm|group)\s+(của|tôi|mình)\b',
        r'\b(report to|làm việc với|work with)\b',
    ]

    # Signal: Identity facts
    IDENTITY_PATTERNS = [
        r'\b(tôi|mình|i\'m|i am)\s+(là|a|an)\s+\w+(er|or|ist|ist|dev|engineer|designer|manager)\b',
        r'\b(tôi|mình)\s+(làm|work)\s+(ở|at|for)\b',
        r'\b(kinh nghiệm|experience|năm kinh nghiệm|years? of experience)\b',
    ]

    # ─── NEGATIVE PATTERNS (skip ngay cả khi match positive) ──────────────────
    TRIVIAL_PATTERNS = [
        r'\b(hôm nay|today)\s+(trời|weather|nóng|lạnh|đẹp|xấu)\b',
        r'\b(vừa ăn|just ate|ăn gì|what.*eat)\b',
        r'\b(mệt|tired|chán|bored|buồn ngủ|sleepy)\b',
        r'\b(ok|okay|ừ|uh|hmm|à|ờ)\b',
        r'^.{0,20}$',  # Message quá ngắn (< 20 chars) → likely small talk
    ]

    ALL_SIGNAL_GROUPS = [
        ("preference", PREFERENCE_PATTERNS, "high"),
        ("tech_stack", TECH_PATTERNS, "high"),
        ("goal", GOAL_PATTERNS, "high"),
        ("deadline", DEADLINE_PATTERNS, "medium"),
        ("relationship", RELATIONSHIP_PATTERNS, "medium"),
        ("identity", IDENTITY_PATTERNS, "high"),
    ]

    def detect(self, message: str) -> DetectionResult:
        """
        Main detection function.
        Returns DetectionResult với should_extract = True/False.
        """
        message_lower = message.lower().strip()

        # Bước 1: Check trivial patterns → skip ngay
        for pattern in self.TRIVIAL_PATTERNS:
            if re.search(pattern, message_lower, re.IGNORECASE):
                return DetectionResult(
                    should_extract=False,
                    signals=[],
                    priority="none",
                )

        # Bước 2: Check signal patterns
        triggered_signals = []
        highest_priority = "low"

        priority_order = {"high": 3, "medium": 2, "low": 1}

        for group_name, patterns, priority in self.ALL_SIGNAL_GROUPS:
            for pattern in patterns:
                if re.search(pattern, message_lower, re.IGNORECASE):
                    triggered_signals.append(group_name)
                    if priority_order[priority] > priority_order[highest_priority]:
                        highest_priority = priority
                    break  # Chỉ cần 1 pattern trong group match là đủ

        if not triggered_signals:
            return DetectionResult(
                should_extract=False,
                signals=[],
                priority="none",
            )

        return DetectionResult(
            should_extract=True,
            signals=list(set(triggered_signals)),
            priority=highest_priority,
        )
```

---

## 13. Memory Extraction Pipeline

### 13.1 Luồng hoạt động

```
User Message
    │
    ├── [SYNC] MemoryCandidateDetector.detect()
    │              │
    │         pass? ──── NO ──→ skip (không extract gì)
    │              │
    │             YES
    │              │
    │   [ASYNC] Enqueue to Redis Queue
    │              │
    │         (trả response về user ngay lập tức)
    │
    └── [BACKGROUND WORKER] ──────────────────────────────────
                   │
           Dequeue from Redis Queue
                   │
           Gemini Flash: extract memories
                   │
           Classify memory type
                   │
           Score importance
                   │
           Deduplication check
                   │
           Save to appropriate table
```

### 13.2 Redis Queue Setup

```python
# app/workers/memory_worker.py
from rq import Queue
from redis import Redis

redis_conn = Redis(host='localhost', port=6379, db=1)  # DB 1 for queues
memory_queue = Queue('memory_extraction', connection=redis_conn)

# Enqueue (gọi từ main chat handler)
def enqueue_extraction(message: str, user_id: str,
                        conversation_id: str, signals: List[str]) -> None:
    memory_queue.enqueue(
        process_extraction,   # Function được gọi bởi worker
        args=(message, user_id, conversation_id, signals),
        job_timeout=30,       # Timeout 30s — nếu Gemini chậm thì bỏ
        retry=Retry(max=2),   # Retry tối đa 2 lần
    )

# Worker function (chạy trong process riêng)
def process_extraction(message: str, user_id: str,
                        conversation_id: str, signals: List[str]) -> None:
    """
    Được gọi bởi RQ worker. Chạy trong background.
    """
    from app.memory.extractor import MemoryExtractor
    extractor = MemoryExtractor()
    extractor.extract_and_store(message, user_id, conversation_id, signals)
```

### 13.3 Worker process (chạy riêng)

```bash
# Chạy worker (thêm vào Procfile hoặc supervisord)
rq worker memory_extraction --with-scheduler
```

### 13.4 Full Extraction Flow

```python
# app/memory/extractor.py

class MemoryExtractor:

    def extract_and_store(self, message: str, user_id: str,
                           conversation_id: str, signals: List[str]) -> None:
        """Main extraction function, chạy trong background worker."""

        # Lấy recent context để cho Gemini Flash hiểu rõ hơn
        recent_context = self._get_recent_context(conversation_id, limit_messages=5)

        # Gọi Gemini Flash
        raw_memories = self._call_gemini_extract(message, recent_context)

        if not raw_memories:
            return  # Gemini trả về list rỗng → không có gì để lưu

        # Process từng memory
        deduplicator = SemanticDeduplicator()
        for memory_data in raw_memories:

            # Validate schema
            if not self._is_valid(memory_data):
                continue

            # Tính expires_at
            memory_data["expires_at"] = compute_expires_at(
                MemoryClass(memory_data["memory_class"])
            )
            memory_data["source_message_id"] = self._get_message_id(
                conversation_id, message
            )

            # Dedup check
            action = deduplicator.deduplicate(memory_data, user_id, self.db)

            if action == "insert":
                self._insert_semantic_memory(user_id, memory_data)
            # "skip" và "update" đã được xử lý bên trong deduplicator

    def _call_gemini_extract(self, message: str, context: str) -> List[dict]:
        """Gọi Gemini Flash, parse JSON response."""
        prompt = SEMANTIC_EXTRACTION_PROMPT.format(
            user_message=message,
            recent_context=context,
        )

        try:
            response = self.gemini.generate(
                model="gemini-1.5-flash",
                prompt=prompt,
                max_tokens=1000,
                temperature=0.1,  # Low temperature cho extraction task
            )

            # Strip markdown backticks nếu có
            clean = response.strip()
            if clean.startswith("```"):
                clean = re.sub(r"```(?:json)?", "", clean).strip()

            memories = json.loads(clean)
            return memories if isinstance(memories, list) else []

        except (json.JSONDecodeError, Exception) as e:
            # Extraction fail → log và bỏ qua, KHÔNG raise exception
            logger.warning(f"Memory extraction failed for user {user_id}: {e}")
            return []

    def _is_valid(self, memory_data: dict) -> bool:
        """Validate required fields."""
        required = ["memory_type", "subject", "value", "confidence_score",
                    "importance_score", "memory_class"]
        return all(k in memory_data for k in required)
```

---

## 14. Memory Retrieval Architecture

### 14.1 Query Classification (Rule-based)

```python
# app/memory/retriever.py

QUERY_TYPE_RULES = {
    "coding": {
        "keywords": ["code", "function", "bug", "error", "implement", "debug",
                     "viết code", "lỗi", "fix", "refactor", "api", "endpoint",
                     "class", "method", "import", "library", "package"],
        "memory_layers": ["semantic", "preference", "knowledge", "episodic"],
        "knowledge_source_types": ["note", "task"],
    },
    "planning": {
        "keywords": ["plan", "kế hoạch", "schedule", "timeline", "milestone",
                     "task", "deadline", "sprint", "priority", "roadmap",
                     "mục tiêu", "goal", "objective"],
        "memory_layers": ["semantic", "episodic", "knowledge", "preference"],
        "knowledge_source_types": ["task", "schedule", "note"],
    },
    "calendar": {
        "keywords": ["meeting", "cuộc họp", "appointment", "event", "lịch",
                     "schedule", "remind", "nhắc", "ngày", "giờ", "hôm nay",
                     "tuần này", "tomorrow", "next week"],
        "memory_layers": ["knowledge", "semantic"],
        "knowledge_source_types": ["calendar", "schedule"],
    },
    "notes": {
        "keywords": ["note", "ghi chú", "tài liệu", "document", "wrote",
                     "viết", "saved", "lưu", "recorded", "remember writing"],
        "memory_layers": ["knowledge", "semantic"],
        "knowledge_source_types": ["note", "recording"],
    },
    "project": {
        "keywords": ["project", "dự án", "cortex", "app", "system", "feature",
                     "release", "deploy", "launch", "build", "develop"],
        "memory_layers": ["episodic", "semantic", "knowledge", "preference"],
        "knowledge_source_types": ["note", "task", "schedule"],
    },
    "general": {  # Fallback
        "keywords": [],
        "memory_layers": ["semantic", "preference", "episodic", "knowledge"],
        "knowledge_source_types": None,  # None = tất cả types
    },
}

class QueryClassifier:

    def classify(self, query: str) -> str:
        """
        Returns query type string.
        80-90% queries sẽ được classify bằng rules này — không cần LLM.
        """
        query_lower = query.lower()
        scores = {}

        for query_type, config in QUERY_TYPE_RULES.items():
            if query_type == "general":
                continue
            score = sum(1 for kw in config["keywords"] if kw in query_lower)
            if score > 0:
                scores[query_type] = score

        if not scores:
            return "general"  # Không match gì → dùng general fallback

        # Trả về type có nhiều keyword match nhất
        return max(scores, key=scores.get)
```

### 14.2 Multi-layer Retrieval

```python
class MemoryRetriever:
    """
    Retrieves relevant memories từ tất cả layers liên quan.
    """

    def __init__(self, db_session, redis_client, gemini_client):
        self.db = db_session
        self.classifier = QueryClassifier()
        self.working = WorkingMemoryLayer(db_session)
        self.conversation = ConversationMemoryLayer(db_session, gemini_client)
        self.semantic = SemanticMemoryLayer(db_session)
        self.preference = PreferenceMemoryLayer(db_session)
        self.episodic = EpisodicMemoryLayer(db_session)
        self.knowledge = KnowledgeMemoryLayer(db_session, gemini_client)

    def retrieve(self, query: str, user_id: str,
                 conversation_id: str) -> "RetrievalResult":
        """
        Main retrieval function. Gọi trước mỗi LLM response.
        """
        # Bước 1: Classify query (không gọi LLM)
        query_type = self.classifier.classify(query)
        config = QUERY_TYPE_RULES[query_type]

        result = RetrievalResult(query_type=query_type)

        # Bước 2: Layer 1 — Working Memory (luôn lấy)
        result.working_memory = self.working.get(conversation_id)

        # Bước 3: Layer 2 — Conversation Summaries (nếu conversation dài)
        result.conversation_summaries = self.conversation.get_relevant_summaries(
            conversation_id
        )

        # Bước 4: Retrieve từ các layers theo config
        layers_to_retrieve = config["memory_layers"]

        if "semantic" in layers_to_retrieve:
            result.semantic_memories = self.semantic.search(user_id, query)

        if "preference" in layers_to_retrieve:
            result.preferences = self.preference.get_all(user_id)

        if "episodic" in layers_to_retrieve:
            result.episodic_memories = self.episodic.search(user_id, query)

        if "knowledge" in layers_to_retrieve:
            source_types = config.get("knowledge_source_types")
            result.knowledge_chunks = self.knowledge.search(
                user_id, query,
                source_types=source_types,
                limit=8,
            )

        return result

@dataclass
class RetrievalResult:
    query_type: str
    working_memory: List[dict] = field(default_factory=list)
    conversation_summaries: List[str] = field(default_factory=list)
    semantic_memories: List[dict] = field(default_factory=list)
    preferences: dict = field(default_factory=dict)
    episodic_memories: List[dict] = field(default_factory=list)
    knowledge_chunks: List[dict] = field(default_factory=list)
```

### 14.3 Retrieval Scoring

```python
# app/memory/scorer.py

def compute_retrieval_score(similarity: float, created_at: datetime,
                             importance: float) -> float:
    """
    retrieval_score = 0.60 * similarity + 0.20 * recency + 0.20 * importance

    Giải thích:
    - similarity: cosine similarity từ vector search (0.0-1.0)
    - recency: normalized age (mới hơn = điểm cao hơn)
    - importance: importance_score đã lưu trong DB
    """
    # Recency score: decay theo ngày
    age_days = (datetime.utcnow() - created_at).days
    recency = max(0.0, 1.0 - (age_days / 180))  # 180 ngày = về 0

    score = (0.60 * similarity) + (0.20 * recency) + (0.20 * importance)
    return round(score, 4)
```

---

## 15. Prompt Assembly

### 15.1 Token Budgets

```python
# app/config.py
PROMPT_TOKEN_BUDGETS = {
    "working_memory":    8_000,
    "conv_summaries":    1_000,  # Summaries thường ngắn
    "semantic_memory":   1_500,
    "preference_memory":   500,
    "episodic_memory":   1_000,
    "knowledge_memory":  3_000,
    "system_prompt":     1_000,  # Reserve cho system prompt
    "response_buffer":   2_000,  # Reserve cho response của model
}
# Tổng: ~18,000 tokens — phù hợp với Gemini Flash (1M context) và Gemini Pro (128K)
```

### 15.2 Prompt Assembly

```python
# app/memory/assembler.py

SYSTEM_PROMPT_TEMPLATE = """Bạn là Cortex AI — personal assistant thông minh của người dùng.

Bạn có khả năng nhớ thông tin về người dùng qua nhiều conversations.

## Thông tin bạn biết về người dùng:

### Sở thích & cài đặt:
{preferences}

### Facts quan trọng:
{semantic_memories}

### Lịch sử sự kiện liên quan:
{episodic_memories}

### Knowledge base (từ notes, tasks, calendar):
{knowledge_chunks}

---
Khi trả lời:
- Sử dụng những gì bạn biết về user để cá nhân hóa response
- Không nhắc lại "theo thông tin tôi có..." — hãy tự nhiên như bạn đã biết những điều này
- Nếu thấy mâu thuẫn với những gì user nói, hãy hỏi làm rõ
"""

class PromptAssembler:

    def __init__(self, budgets: dict = None):
        self.budgets = budgets or PROMPT_TOKEN_BUDGETS

    def assemble(self, retrieval_result: RetrievalResult,
                 current_query: str) -> List[dict]:
        """
        Trả về list messages để đưa thẳng vào Gemini API.
        Format: [{"role": "system", "content": "..."}, {"role": "user", ...}, ...]
        """

        # ── Build system prompt ──────────────────────────────────────────────
        system_content = SYSTEM_PROMPT_TEMPLATE.format(
            preferences=self._format_preferences(
                retrieval_result.preferences
            ),
            semantic_memories=self._format_semantic(
                retrieval_result.semantic_memories
            ),
            episodic_memories=self._format_episodic(
                retrieval_result.episodic_memories
            ),
            knowledge_chunks=self._format_knowledge(
                retrieval_result.knowledge_chunks
            ),
        )

        # ── Build conversation messages ─────────────────────────────────────
        messages = [{"role": "system", "content": system_content}]

        # Thêm summaries nếu có (như context bridge)
        if retrieval_result.conversation_summaries:
            summary_text = "\n\n---\n".join(retrieval_result.conversation_summaries)
            messages.append({
                "role": "system",
                "content": f"[Tóm tắt các phần conversation trước]\n{summary_text}",
            })

        # Thêm working memory (messages gần nhất)
        for msg in retrieval_result.working_memory:
            messages.append({
                "role": msg["role"],
                "content": msg["content"],
            })

        return messages

    def _format_semantic(self, memories: List[dict]) -> str:
        if not memories:
            return "Chưa có thông tin."

        # Sort theo retrieval_score, lấy top theo budget
        sorted_memories = sorted(memories, key=lambda x: x.get("score", 0), reverse=True)

        lines = []
        token_used = 0
        budget = self.budgets["semantic_memory"]

        for m in sorted_memories:
            line = f"- [{m['memory_type']}] {m['subject']}: {m['value']}"
            line_tokens = estimate_tokens(line)
            if token_used + line_tokens > budget:
                break
            lines.append(line)
            token_used += line_tokens

        return "\n".join(lines)

    def _format_preferences(self, preferences: dict) -> str:
        if not preferences:
            return "Chưa có thông tin sở thích."
        lines = []
        for category, prefs in preferences.items():
            for key, data in prefs.items():
                if data.get("confidence", 0) >= 0.7:
                    lines.append(f"- {category} → {key}: {data['value']}")
        return "\n".join(lines) if lines else "Chưa có thông tin sở thích."

    def _format_episodic(self, episodes: List[dict]) -> str:
        if not episodes:
            return "Chưa có sự kiện quan trọng nào được ghi nhận."
        lines = []
        for ep in episodes[:3]:  # Tối đa 3 episodes trong prompt
            lines.append(
                f"- [{ep['event_type']}] {ep['event_title']}: {ep['event_summary']}"
                f" (xuất hiện {ep['occurrence_count']} lần)"
            )
        return "\n".join(lines)

    def _format_knowledge(self, chunks: List[dict]) -> str:
        if not chunks:
            return "Không có thông tin liên quan từ knowledge base."
        lines = []
        token_used = 0
        budget = self.budgets["knowledge_memory"]

        for chunk in sorted(chunks, key=lambda x: x.get("score", 0), reverse=True):
            source_label = f"[{chunk['source_type']}]"
            line = f"{source_label} {chunk['text']}"
            line_tokens = estimate_tokens(line)
            if token_used + line_tokens > budget:
                break
            lines.append(line)
            token_used += line_tokens

        return "\n".join(lines)
```

---

## 16. Nightly Consolidation Jobs

### 16.1 Mục đích

Các job này chạy khi user không active (ban đêm). Dùng Gemini Flash để:
1. Merge duplicate semantic memories
2. Compress episodic memories cũ
3. Expire và cleanup stale data
4. Re-rank importance scores

### 16.2 Scheduler Setup

```python
# app/memory/jobs/scheduler.py
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

scheduler = AsyncIOScheduler()

# Chạy lúc 2:00 AM mỗi ngày
scheduler.add_job(
    consolidation_job,
    CronTrigger(hour=2, minute=0),
    id="nightly_consolidation",
    replace_existing=True,
)

scheduler.start()
```

### 16.3 Consolidation Logic

```python
# app/memory/jobs/consolidation.py

MAX_GEMINI_CALLS_PER_NIGHT = 500  # Hard limit để kiểm soát chi phí

class NightlyConsolidationJob:

    def run(self, db, gemini) -> None:
        """Main nightly job. Chạy theo thứ tự priority."""
        gemini_calls_used = 0

        # Task 1: Expire old memories (không cần Gemini)
        self._expire_old_memories(db)

        # Task 2: Merge duplicate semantic memories
        gemini_calls_used += self._merge_duplicates(
            db, gemini,
            budget=MAX_GEMINI_CALLS_PER_NIGHT // 3
        )

        # Task 3: Compress old episodic memories (nếu còn budget)
        remaining = MAX_GEMINI_CALLS_PER_NIGHT - gemini_calls_used
        if remaining > 50:
            self._compress_old_episodes(db, gemini, budget=remaining // 2)

        # Task 4: Cleanup action_history > 30 ngày (không cần Gemini)
        self._cleanup_old_actions(db)

        # Task 5: Deactivate expired knowledge chunks (không cần Gemini)
        self._cleanup_expired_knowledge(db)

    def _expire_old_memories(self, db) -> None:
        """Deactivate memories đã quá expires_at."""
        db.execute("""
            UPDATE semantic_memories
            SET is_active = FALSE, updated_at = NOW()
            WHERE expires_at IS NOT NULL
              AND expires_at < NOW()
              AND is_active = TRUE
        """)
        db.commit()

    def _merge_duplicates(self, db, gemini, budget: int) -> int:
        """
        Tìm semantic memories có thể là duplicate và merge.
        Trả về số Gemini calls đã dùng.
        """
        calls_used = 0

        # Tìm pairs có cùng user + memory_type + subject nhưng value khác nhau
        duplicate_candidates = db.execute("""
            SELECT a.id as id_a, a.value as val_a,
                   b.id as id_b, b.value as val_b,
                   a.user_id, a.memory_type, a.subject
            FROM semantic_memories a
            JOIN semantic_memories b ON (
                a.user_id = b.user_id
                AND a.memory_type = b.memory_type
                AND a.subject = b.subject
                AND a.id < b.id  -- Tránh pair trùng
                AND a.is_active = TRUE
                AND b.is_active = TRUE
            )
            LIMIT :budget
        """, {"budget": budget}).fetchall()

        for pair in duplicate_candidates:
            if calls_used >= budget:
                break

            # Hỏi Gemini: 2 memories này có phải cùng fact không?
            result = gemini.generate_json(f"""
Hai memories sau đây về cùng user có phải là thông tin giống nhau không?

Memory A: "{pair.val_a}"
Memory B: "{pair.val_b}"
Subject: {pair.subject}
Type: {pair.memory_type}

Trả lời JSON: {{"is_duplicate": true/false, "merged_value": "giá trị gộp nếu là duplicate, null nếu không"}}
            """)
            calls_used += 1

            if result.get("is_duplicate") and result.get("merged_value"):
                # Merge: update A, deactivate B
                db.execute("""
                    UPDATE semantic_memories
                    SET value = :value, updated_at = NOW()
                    WHERE id = :id
                """, {"value": result["merged_value"], "id": pair.id_a})

                db.execute("""
                    UPDATE semantic_memories SET is_active = FALSE
                    WHERE id = :id
                """, {"id": pair.id_b})

                db.commit()

        return calls_used

    def _cleanup_old_actions(self, db) -> None:
        """Xóa action_history > 30 ngày."""
        db.execute("""
            DELETE FROM action_history
            WHERE created_at < NOW() - INTERVAL '30 days'
        """)
        db.commit()

    def _cleanup_expired_knowledge(self, db) -> None:
        """Deactivate knowledge chunks đã expired."""
        db.execute("""
            UPDATE knowledge_chunks
            SET is_active = FALSE, updated_at = NOW()
            WHERE expires_at IS NOT NULL
              AND expires_at < NOW()
              AND is_active = TRUE
        """)
        db.commit()
```

---

## 17. API Contracts

### 17.1 Internal Interface — MemoryRetriever

```python
# Mọi nơi cần lấy memory đều gọi qua interface này
class IMemoryRetriever(Protocol):
    def retrieve(self,
                 query: str,
                 user_id: str,
                 conversation_id: str) -> RetrievalResult: ...

# Mọi nơi cần assemble prompt đều gọi qua interface này
class IPromptAssembler(Protocol):
    def assemble(self,
                 retrieval_result: RetrievalResult,
                 current_query: str) -> List[dict]: ...
```

### 17.2 Redis Queue Message Format

```python
# Format của message trong extraction queue
@dataclass
class ExtractionQueueMessage:
    message_id: str          # ID của agent_message gốc
    user_id: str
    conversation_id: str
    content: str             # Nội dung tin nhắn
    signals: List[str]       # Signals đã detect được
    enqueued_at: str         # ISO timestamp
    priority: str            # 'high' | 'medium' | 'low'

# Serialize:
json.dumps(asdict(msg))

# Deserialize:
ExtractionQueueMessage(**json.loads(raw))
```

### 17.3 Chat Handler Integration

Đây là nơi kết nối tất cả lại. Tìm file chat handler hiện tại và sửa theo pattern này:

```python
# app/api/chat.py (hoặc tương đương trong project)

async def handle_message(user_id: str, conversation_id: str,
                          message: str, db, redis) -> str:
    """
    Main chat handler — sửa theo pattern này.
    """

    # ── Bước 1: Lưu message vào Layer 0 ─────────────────────────────────────
    message_id = save_message(conversation_id, "user", message, db)

    # ── Bước 2: Memory Candidate Detection (SYNC, nhanh) ────────────────────
    detector = MemoryCandidateDetector()
    detection = detector.detect(message)

    # ── Bước 3: Enqueue extraction nếu cần (ASYNC, không block) ─────────────
    if detection.should_extract:
        enqueue_extraction(
            message=message,
            user_id=user_id,
            conversation_id=conversation_id,
            signals=detection.signals,
        )

    # ── Bước 4: Retrieve relevant memories ──────────────────────────────────
    retriever = MemoryRetriever(db, redis, gemini_client)
    retrieval = retriever.retrieve(message, user_id, conversation_id)

    # ── Bước 5: Assemble prompt ──────────────────────────────────────────────
    assembler = PromptAssembler()
    prompt_messages = assembler.assemble(retrieval, message)

    # ── Bước 6: Gọi Gemini ──────────────────────────────────────────────────
    response = await gemini_client.generate(
        model="gemini-1.5-pro",  # hoặc flash tuỳ config
        messages=prompt_messages,
    )

    # ── Bước 7: Lưu response ─────────────────────────────────────────────────
    save_message(conversation_id, "assistant", response, db)

    # ── Bước 8: Check nếu cần trigger conversation summary (ASYNC) ───────────
    # Chạy trong background, không block
    asyncio.create_task(
        ConversationMemoryLayer(db, gemini_client).check_and_trigger(conversation_id)
    )

    return response
```

---

## 18. Migration Plan

### 18.1 Thứ tự migration (PHẢI làm đúng thứ tự này)

```
Phase 1: Infrastructure (không ảnh hưởng production)
  ├── 1.1 Cài pgvector extension
  ├── 1.2 Tạo tất cả tables mới (KHÔNG đụng tables cũ)
  ├── 1.3 Thêm cột token_count vào agent_messages
  └── 1.4 Setup Redis Queue + RQ workers

Phase 2: Backfill (chạy song song với production)
  ├── 2.1 Backfill token_count cho agent_messages cũ
  ├── 2.2 Embed và index knowledge sources hiện có (notes, tasks, calendar)
  └── 2.3 Chạy extraction trên conversation history cũ (optional, best-effort)

Phase 3: Cutover (deploy new code)
  ├── 3.1 Deploy với feature flag: USE_NEW_MEMORY_SYSTEM = False
  ├── 3.2 Chạy shadow mode: new system chạy nhưng không inject vào prompt
  ├── 3.3 Kiểm tra metrics 48h (extraction rate, retrieval latency, quality)
  └── 3.4 Enable USE_NEW_MEMORY_SYSTEM = True cho 10% users → 50% → 100%

Phase 4: Cleanup (sau 2 tuần ổn định)
  ├── 4.1 Xóa code conversation_history cũ
  ├── 4.2 Remove MAX_CONVERSATION_HISTORY constant
  └── 4.3 Remove old summary implementation
```

### 18.2 Rollback Plan

```python
# Feature flag — implement trước khi deploy
USE_NEW_MEMORY_SYSTEM = os.getenv("USE_NEW_MEMORY_SYSTEM", "false").lower() == "true"

# Trong chat handler:
if USE_NEW_MEMORY_SYSTEM:
    # New memory system
    retrieval = retriever.retrieve(message, user_id, conversation_id)
    prompt_messages = assembler.assemble(retrieval, message)
else:
    # Old system (giữ nguyên, không xóa cho đến Phase 4)
    prompt_messages = get_old_conversation_history(conversation_id)
```

---

## 19. Monitoring & Metrics

### 19.1 Metrics cần track (implement từ ngày 1)

```python
# app/memory/monitoring.py
# Dùng bất kỳ metrics library nào đang có trong project (Prometheus, Datadog, v.v.)

METRICS = {
    # Extraction pipeline
    "memory_extraction_total":      Counter,   # Tổng số extractions
    "memory_extraction_skipped":    Counter,   # Số lần detector skip
    "memory_extraction_duration":   Histogram, # Latency của Gemini extraction
    "memory_extraction_errors":     Counter,   # Số lần extraction fail

    # Retrieval
    "memory_retrieval_duration":    Histogram, # Latency của toàn bộ retrieval
    "memory_retrieval_by_type":     Counter,   # Breakdown theo query_type
    "knowledge_search_duration":    Histogram, # Riêng pgvector search latency

    # Memory counts
    "semantic_memories_created":    Counter,
    "semantic_memories_deduplicated": Counter,  # Số lần dedup skip
    "episodic_memories_created":    Counter,
    "episodic_memories_aggregated": Counter,    # Số lần aggregate vào episode cũ

    # Token budgets
    "prompt_token_usage":           Histogram,  # Tổng tokens per request
    "working_memory_token_usage":   Histogram,
    "knowledge_memory_token_usage": Histogram,

    # Queue health
    "extraction_queue_length":      Gauge,      # Số jobs đang chờ
    "extraction_queue_lag":         Gauge,      # Oldest job age (seconds)
}
```

### 19.2 Alerts cần setup

| Alert | Condition | Action |
|-------|-----------|--------|
| Extraction queue lag cao | Queue lag > 60s | Scale up workers |
| Extraction error rate cao | Error > 10% in 5min | Check Gemini API |
| pgvector search chậm | P95 > 500ms | Check index, VACUUM |
| Semantic memories tăng bất thường | > 50 memories/user/day | Check detector logic |
| Token budget overflow | Prompt > 20K tokens | Check working memory |

---

## 20. Error Handling & Failure Scenarios

### 20.1 Các failure phải handle

| Scenario | Behavior | Code |
|----------|----------|------|
| Gemini extraction timeout | Log warning, skip extraction. Chat response không bị ảnh hưởng. | `try/except` trong worker |
| pgvector search fail | Trả về empty knowledge chunks, vẫn có semantic + preference. | Fallback trong retriever |
| Redis down | Hot layer fail → vẫn ghi cold layer (PostgreSQL). Undo chỉ work từ PostgreSQL. | `try/except` trong ActionMemoryLayer |
| Extraction queue full | Log error, drop message. Không retry vô hạn. | RQ `job_timeout` |
| Embedding API fail | Retry 1 lần sau 5s, sau đó skip. Chunk không được lưu. | Retry decorator |
| Memory mâu thuẫn | Reduce confidence cả hai, không xóa gì. | Deduplicator logic |

### 20.2 Circuit Breaker cho Gemini calls

```python
# app/memory/extractor.py
from functools import wraps
import time

class GeminiCircuitBreaker:
    """
    Nếu Gemini liên tục fail, tạm thời stop gọi để tránh cascade failure.
    """
    def __init__(self, failure_threshold=5, timeout=60):
        self.failures = 0
        self.threshold = failure_threshold
        self.timeout = timeout
        self.last_failure_time = None
        self.is_open = False

    def call(self, func, *args, **kwargs):
        if self.is_open:
            if time.time() - self.last_failure_time > self.timeout:
                self.is_open = False  # Try again
            else:
                raise Exception("Circuit breaker open — Gemini unavailable")

        try:
            result = func(*args, **kwargs)
            self.failures = 0  # Reset on success
            return result
        except Exception as e:
            self.failures += 1
            self.last_failure_time = time.time()
            if self.failures >= self.threshold:
                self.is_open = True
            raise
```

---

## 21. Testing Strategy

### 21.1 Unit Tests — MemoryCandidateDetector

```python
# tests/memory/test_detector.py

import pytest
from app.memory.detector import MemoryCandidateDetector

detector = MemoryCandidateDetector()

class TestShouldExtract:
    def test_preference_statement(self):
        result = detector.detect("Tôi thích dùng FastAPI hơn Django")
        assert result.should_extract == True
        assert "preference" in result.signals

    def test_tech_stack(self):
        result = detector.detect("Tôi đang dùng Python với Redis")
        assert result.should_extract == True
        assert "tech_stack" in result.signals

    def test_goal(self):
        result = detector.detect("Tôi đang build một AI assistant")
        assert result.should_extract == True
        assert "goal" in result.signals

class TestShouldSkip:
    def test_trivial_weather(self):
        result = detector.detect("Hôm nay trời nóng quá")
        assert result.should_extract == False

    def test_short_message(self):
        result = detector.detect("ok")
        assert result.should_extract == False

    def test_question_without_facts(self):
        result = detector.detect("Hàm này hoạt động như thế nào?")
        assert result.should_extract == False
```

### 21.2 Integration Tests — Extraction Pipeline

```python
# tests/memory/test_extraction_pipeline.py

class TestExtractionPipeline:
    def test_full_pipeline_preference(self, db, mock_gemini):
        """Test toàn bộ flow từ message → memory saved."""
        mock_gemini.return_value = json.dumps([{
            "memory_type": "preference",
            "subject": "user",
            "value": "thích FastAPI",
            "confidence_score": 0.9,
            "importance_score": 0.7,
            "memory_class": "PERMANENT",
        }])

        extractor = MemoryExtractor(db, mock_gemini)
        extractor.extract_and_store(
            message="Tôi thích dùng FastAPI",
            user_id="user_123",
            conversation_id="conv_456",
            signals=["preference"],
        )

        # Verify memory was saved
        memory = db.execute("""
            SELECT * FROM semantic_memories WHERE user_id = 'user_123'
        """).fetchone()
        assert memory is not None
        assert memory.memory_type == "preference"
        assert "FastAPI" in memory.value
```

### 21.3 Benchmark — Retrieval Latency

```python
# tests/memory/test_retrieval_benchmark.py

def test_retrieval_latency(db, redis, benchmark):
    """P95 retrieval phải < 200ms."""
    retriever = MemoryRetriever(db, redis, mock_gemini)

    def do_retrieval():
        return retriever.retrieve(
            query="show me my notes about the project",
            user_id="benchmark_user",
            conversation_id="bench_conv",
        )

    result = benchmark(do_retrieval)
    assert benchmark.stats["mean"] < 0.200  # 200ms
```

---

## 22. Implementation Roadmap

### Week 1: Foundation
- [ ] Setup pgvector extension + migrations
- [ ] Tạo tất cả DB tables (Layer 0-7 schemas)
- [ ] Implement WorkingMemoryLayer (Layer 1)
- [ ] Implement MemoryCandidateDetector với basic rules
- [ ] Setup Redis Queue + RQ worker process
- [ ] Backfill token_count cho agent_messages

### Week 2: Core Memory Layers
- [ ] Implement SemanticMemoryLayer + Deduplicator (Layer 3)
- [ ] Implement PreferenceMemoryLayer (Layer 4)
- [ ] Implement KnowledgeMemoryLayer với pgvector search (Layer 6)
- [ ] Implement ActionMemoryLayer Redis + PostgreSQL (Layer 7)
- [ ] Unit tests cho Detector và Deduplicator

### Week 3: Extraction + Retrieval
- [ ] Implement MemoryExtractor với Gemini Flash
- [ ] Implement QueryClassifier (rule-based)
- [ ] Implement MemoryRetriever (multi-layer)
- [ ] Implement PromptAssembler với token budgets
- [ ] Integration test toàn bộ pipeline

### Week 4: Episodic + Conversation + Polish
- [ ] Implement EpisodicMemoryLayer với aggregation algorithm (Layer 5)
- [ ] Implement ConversationMemoryLayer với summary snapshots (Layer 2)
- [ ] Implement NightlyConsolidationJob
- [ ] Implement monitoring metrics
- [ ] Deploy với feature flag (shadow mode)
- [ ] Backfill knowledge sources (notes, tasks, calendar)

### Week 5: Cutover
- [ ] Enable cho 10% users → monitor 48h
- [ ] Enable cho 50% users → monitor 24h
- [ ] Enable cho 100% users
- [ ] Remove old conversation_history code
- [ ] Retrospective + fine-tune token budgets dựa trên production data

---

*Tài liệu này là source of truth. Mọi quyết định thiết kế đã được đưa ra ở đây. Nếu có ambiguity, hỏi lại trước khi implement.*