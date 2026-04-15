from __future__ import annotations

from app.services.embeddings import parse_embedding, vectorize_text
from app.services.search import SearchService


def test_parse_embedding_supports_json_and_csv() -> None:
    assert parse_embedding('[0.1, 0.2, 0.3]') == [0.1, 0.2, 0.3]
    assert parse_embedding('0.5, 1.5, 2.5') == [0.5, 1.5, 2.5]


def test_vectorize_text_is_deterministic() -> None:
    vector_a = vectorize_text('OAuth state validation')
    vector_b = vectorize_text('OAuth state validation')

    assert vector_a == vector_b
    assert len(vector_a) == 32
    assert round(sum(value * value for value in vector_a), 4) == 1.0


def test_semantic_score_ranks_related_text_higher_than_unrelated_text() -> None:
    service = SearchService(db=None)  # type: ignore[arg-type]
    query = 'oauth state validation'
    query_vector = vectorize_text(query)

    related_text = 'OAuth callback state validation and redirect handling'
    unrelated_text = 'Database migration and background worker retry strategy'

    related_score = service._score_result(
        related_text,
        query,
        semantic=True,
        query_vector=query_vector,
        item_vector=service._resolve_item_vector(related_text, None),
    )
    unrelated_score = service._score_result(
        unrelated_text,
        query,
        semantic=True,
        query_vector=query_vector,
        item_vector=service._resolve_item_vector(unrelated_text, None),
    )

    assert related_score > unrelated_score
    assert 0.0 <= unrelated_score <= 1.0
    assert 0.0 <= related_score <= 1.0


def test_semantic_score_prefers_embedding_when_present() -> None:
    service = SearchService(db=None)  # type: ignore[arg-type]
    query = 'oauth state validation'
    query_vector = vectorize_text(query)
    text = 'completely unrelated text'

    embedded_vector = [0.0] * 32
    embedded_vector[3] = 1.0
    score_with_embedding = service._score_result(
        text,
        query,
        semantic=True,
        query_vector=query_vector,
        item_vector=embedded_vector,
    )
    score_without_embedding = service._score_result(
        text,
        query,
        semantic=True,
        query_vector=query_vector,
        item_vector=service._resolve_item_vector(text, None),
    )

    assert score_with_embedding >= score_without_embedding
