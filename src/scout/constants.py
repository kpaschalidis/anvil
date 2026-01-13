MAX_ENTITIES_FOR_FOLLOWUP = 3
MAX_FOLLOWUP_QUERIES = 2
KNOWLEDGE_CONTEXT_SIZE = 20
NOVELTY_HISTORY_SIZE = 50
KNOWLEDGE_PERSIST_SIZE = 100
CONTENT_TRUNCATION_LIMIT = 8000
VALID_SIGNAL_TYPES = frozenset({
    "complaint",
    "wish",
    "workaround",
    "switch",
    "bug",
    "pricing",
    "support",
    "integration",
    "workflow",
})
SIGNAL_TYPE_COUNT = len(VALID_SIGNAL_TYPES)
