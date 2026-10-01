"""Request routing fields are never document metadata predicates."""

RESERVED_FILTER_FIELDS = {'knowledge_base_id', 'conversation_id', 'history', 'text'}


def document_filters(filters):
    return {key: value for key, value in filters.items() if key not in RESERVED_FILTER_FIELDS}
