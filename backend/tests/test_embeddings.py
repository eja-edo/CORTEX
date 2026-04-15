from __future__ import annotations

from app.services.embeddings import parse_embedding, should_embed_text, vectorize_text


def test_should_embed_text_thresholds() -> None:
    assert not should_embed_text('short note')
    assert not should_embed_text('aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa')
    assert should_embed_text('OAuth callback state validation with nonce checks and replay prevention guidance')


def test_parse_embedding_formats() -> None:
    assert parse_embedding('[0.1, 0.2, 0.3]') == [0.1, 0.2, 0.3]
    assert parse_embedding('0.1,0.2,0.3') == [0.1, 0.2, 0.3]
    assert parse_embedding(None) == []
    assert parse_embedding('bad,token') == []


def test_vectorize_text_is_unit_normalized() -> None:
    vector = vectorize_text('oauth state validation callback replay prevention')
    magnitude = sum(value * value for value in vector)

    assert len(vector) == 32
    assert round(magnitude, 4) == 1.0
