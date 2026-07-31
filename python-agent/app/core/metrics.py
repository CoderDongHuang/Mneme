from prometheus_client import Counter, Gauge


LLM_REQUESTS = Counter(
    "mneme_llm_requests_total", "LLM requests", ["mode", "provider", "outcome"]
)
LLM_FALLBACKS = Counter(
    "mneme_llm_fallbacks_total", "Requests switched to the fallback model", ["mode"]
)
LLM_ACTIVE = Gauge("mneme_llm_active_requests", "Currently running model requests")
