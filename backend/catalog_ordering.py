"""SQL ordering policy for the public LLM model catalog."""


def model_order_by(sort_by: str) -> str:
    """Return a deterministic ORDER BY clause for a supported catalog sort."""
    if sort_by == "representative":
        return """
            ORDER BY
                CASE
                    WHEN p.type = 'local' OR LOWER(p.name) = 'uc gateway local' THEN 0
                    WHEN LOWER(p.name) = 'openrouter' THEN 2
                    ELSE 1
                END,
                LOWER(p.name),
                avg_cost ASC NULLS LAST,
                LOWER(m.name),
                m.id
        """
    if sort_by == "cost":
        return " ORDER BY avg_cost ASC"
    if sort_by == "latency":
        return " ORDER BY m.avg_latency_ms ASC NULLS LAST"
    if sort_by == "context":
        return " ORDER BY m.context_length DESC"
    if sort_by == "popularity":
        # Sort by name until usage statistics are joined into this query.
        return " ORDER BY m.name"
    return " ORDER BY m.name"
