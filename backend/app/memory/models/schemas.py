from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from datetime import datetime


@dataclass
class DetectionResult:
    should_extract: bool
    signals: List[str]
    priority: str


@dataclass
class RetrievalResult:
    query_type: str
    working_memory: List[Dict[str, Any]] = field(default_factory=list)
    conversation_summaries: List[str] = field(default_factory=list)
    semantic_memories: List[Dict[str, Any]] = field(default_factory=list)
    preferences: Dict[str, Any] = field(default_factory=dict)
    episodic_memories: List[Dict[str, Any]] = field(default_factory=list)
    knowledge_chunks: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class ExtractionQueueMessage:
    message_id: str
    user_id: str
    conversation_id: str
    content: str
    signals: List[str]
    enqueued_at: str
    priority: str
