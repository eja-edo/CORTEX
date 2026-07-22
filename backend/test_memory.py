"""
Integration test for memory extraction pipeline.
Uses real DB, mocks LLM to verify pipeline logic.
"""
import asyncio, json, os, uuid
from datetime import datetime, timedelta
from unittest.mock import patch, AsyncMock
from dotenv import load_dotenv

load_dotenv('.env')
os.environ['ASYNC_DATABASE_URL'] = os.getenv('ASYNC_DATABASE_URL', 'postgresql+asyncpg://cortex:cortex@localhost:5434/cortex_db')

MOCK_RESPONSE = json.dumps({
    "episodic_summary": "### Context\nBuilding Cortex AI assistant with FastAPI, React, PostgreSQL.\n\n### Key Decisions\n- Redis Streams over Celery\n- WebSocket over polling\n- Docker on 8GB RAM VPS\n\n### Next Actions\n- Design notification schema",
    "semantic_memories": [
        {"category": "project", "content": "Building Cortex AI assistant", "confidence": 0.95, "expected_lifetime": "long"},
        {"category": "preference", "content": "Prefers PostgreSQL over MongoDB", "confidence": 0.9, "expected_lifetime": "permanent"},
        {"category": "preference", "content": "Prefers Redis Streams over Celery", "confidence": 0.85, "expected_lifetime": "long"},
        {"category": "environment", "content": "Uses Docker on VPS 8GB RAM", "confidence": 0.8, "expected_lifetime": "medium"},
        {"category": "decision_pattern", "content": "Chooses simpler solutions", "confidence": 0.75, "expected_lifetime": "long"},
    ],
    "title": "Building Cortex AI Assistant"
})

INCREMENTAL_RESPONSE = json.dumps({
    "episodic_summary": "### Context\nBuilding Cortex AI assistant with notification system.\n\n### Key Decisions\n- SendGrid for email\n- Slack webhook for team notifications\n\n### Next Actions\n- Begin implementation",
    "semantic_memories": [
        {"category": "preference", "content": "Uses SendGrid for email", "confidence": 0.85, "expected_lifetime": "long"},
    ],
    "title": "Building Cortex AI Assistant"
})


async def main():
    from app.database_async import AsyncSessionLocal
    from app.database import SessionLocal
    from app.models import AgentConversation, AgentMessage, User
    from app.ai.agents.conversation_summarizer import ConversationSummarizer
    from app.services.memory_extraction_service import extract_and_store, _model_client
    from sqlalchemy import select

    db = AsyncSessionLocal()
    passed = 0

    try:
        # Get a real user
        sync_db = SessionLocal()
        user = sync_db.query(User).first()
        sync_db.close()
        if not user:
            print('ERROR: No users in DB.')
            return
        user_id = user.id
        print(f'User: {user.email}')

        # Create conversation
        ws_id = uuid.UUID('ed991939-cf72-4fe9-9f24-2140333bf465')
        conv_id = uuid.uuid4()
        conv = AgentConversation(id=conv_id, user_id=user_id, workspace_id=ws_id, title='Test', message_count=0)
        db.add(conv)
        await db.flush()
        print(f'Conversation: {conv_id}')

        # ── Insert 22 messages ──
        msgs = [
            ("user", f"Test message {i} about Cortex AI project using Python and FastAPI.")
            for i in range(22)
        ]
        now = datetime.utcnow()
        for i, (role, content) in enumerate(msgs):
            db.add(AgentMessage(
                id=uuid.uuid4(), conversation_id=conv_id,
                role=role, content=content,
                created_at=now + timedelta(seconds=i),
            ))
        conv.message_count = len(msgs)
        await db.flush()
        print(f'Inserted {len(msgs)} messages')

        # ── TEST 1: First extraction ──
        print('\n=== TEST 1: First extraction ===')
        with patch.object(_model_client, 'generate', new=AsyncMock(return_value=(
                'mock-model', type('R', (), {'content': MOCK_RESPONSE})()))):
            result = await extract_and_store(conv_id, db)

        assert result['success'] is True, f'Failed: {result}'
        assert result['episodic_stored'] is True
        assert result['semantic_count'] == 5
        assert result['title'] == 'Building Cortex AI Assistant'
        print(f'  episodic_stored={result["episodic_stored"]}, semantic_count={result["semantic_count"]}')
        print(f'  model={result["model_used"]}, title={result["title"]}')

        r = await db.execute(select(AgentConversation).where(AgentConversation.id == conv_id))
        c = r.scalar_one()
        assert c.summary is not None, 'Summary not stored'
        assert c.last_extracted_at is not None, 'last_extracted_at not set'
        print(f'  Summary: {len(c.summary)} chars')
        print(f'  last_extracted_at: {c.last_extracted_at}')
        passed += 1
        print('  ✅ TEST 1 PASSED')

        # ── TEST 2: Context injection ──
        print('\n=== TEST 2: Context injection ===')
        summarizer = ConversationSummarizer(db)
        ctx = await summarizer.get_conversation_context(conv_id)
        assert 'PREVIOUS CONVERSATION CONTEXT' in ctx
        assert 'Cortex' in ctx
        print(f'  Context: {len(ctx)} chars')
        passed += 1
        print('  ✅ TEST 2 PASSED')

        # ── TEST 3: Incremental extraction ──
        print('\n=== TEST 3: Incremental extraction ===')
        old_extracted_at = c.last_extracted_at

        new_msgs = [
            ("user", "I decided to use SendGrid for email."),
            ("assistant", "Good choice, SendGrid is reliable."),
            ("user", "Also need Slack webhook integration."),
            ("assistant", "I'll help you with that."),
            ("user", "When can we start implementing?"),
            ("assistant", "We can start right away."),
        ]
        import time
        time.sleep(1)  # ensure clear gap between extractions
        new_now = datetime.utcnow()
        for i, (role, content) in enumerate(new_msgs):
            db.add(AgentMessage(
                id=uuid.uuid4(), conversation_id=conv_id,
                role=role, content=content,
                created_at=new_now + timedelta(seconds=i),
            ))
        conv.message_count = len(msgs) + len(new_msgs)
        await db.flush()
        print(f'  Added {len(new_msgs)} messages')

        with patch.object(_model_client, 'generate', new=AsyncMock(return_value=(
                'mock-model', type('R', (), {'content': INCREMENTAL_RESPONSE})()))):
            result2 = await extract_and_store(conv_id, db)

        assert result2['success'] is True, f'Failed: {result2}'
        assert result2['new_messages'] >= len(new_msgs), \
            f'Expected at least {len(new_msgs)} new messages, got {result2["new_messages"]}'
        assert result2['new_messages'] < len(msgs) + len(new_msgs), \
            f'Expected fewer than all messages ({len(msgs)+len(new_msgs)}), got {result2["new_messages"]}'
        assert result2['episodic_stored'] is True

        r = await db.execute(select(AgentConversation).where(AgentConversation.id == conv_id))
        c2 = r.scalar_one()
        assert c2.last_extracted_at != old_extracted_at, 'Timestamp not updated'
        print(f'  old_extracted_at: {old_extracted_at}')
        print(f'  new_extracted_at: {c2.last_extracted_at}')
        print(f'  new_messages: {result2["new_messages"]}')
        print(f'  semantic_count: {result2["semantic_count"]}')
        passed += 1
        print('  ✅ TEST 3 PASSED')

        await db.commit()
        print(f'\n🎉 ALL {passed}/3 TESTS PASSED')

    except AssertionError as e:
        print(f'\n❌ FAILED: {e}')
        await db.rollback()
    except Exception as e:
        print(f'\n❌ ERROR: {type(e).__name__}: {e}')
        import traceback; traceback.print_exc()
        await db.rollback()
    finally:
        await db.close()

asyncio.run(main())
