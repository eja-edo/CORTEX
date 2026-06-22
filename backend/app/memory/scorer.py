from datetime import datetime


def compute_retrieval_score(similarity: float, created_at: datetime,
                             importance: float) -> float:
    age_days = (datetime.utcnow() - created_at).days
    recency = max(0.0, 1.0 - (age_days / 180))

    score = (0.60 * similarity) + (0.20 * recency) + (0.20 * importance)
    return round(score, 4)
