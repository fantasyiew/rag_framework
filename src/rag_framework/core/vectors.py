"""Provider-independent embedding response validation."""

import math


class EmbeddingError(RuntimeError):
    pass


def validate_vectors(vectors, count: int, dimensions: int):
    if len(vectors) != count:
        raise EmbeddingError("Embedding response count does not match input")
    for vector in vectors:
        if len(vector) != dimensions or any(
            isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
            for v in vector
        ):
            raise EmbeddingError("Embedding dimensions or numeric values are invalid")
    return vectors
