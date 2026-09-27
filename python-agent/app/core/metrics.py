from prometheus_client import Counter, Gauge


LLM_REQUESTS = Counter(
    "mneme_llm_requests_total", "LLM requests", ["mode", "provider", "outcome"]
)
LLM_FALLBACKS = Counter(
    "mneme_llm_fallbacks_total", "Requests switched to the fallback model", ["mode"]
)
LLM_ACTIVE = Gauge("mneme_llm_active_requests", "Currently running model requests")

INPUT_REJECTIONS = Counter(
    "mneme_input_rejections_total",
    "Requests rejected because input validation or safety limits failed",
    ["source", "reason"],
)
REFLECTION_LEASE_ACQUISITIONS = Counter(
    "mneme_reflection_lease_acquisitions_total",
    "Distributed reflection lease acquisitions",
    ["backend"],
)
REFLECTION_LEASE_CONTENTIONS = Counter(
    "mneme_reflection_lease_contentions_total",
    "Reflection lease acquisition attempts blocked by another worker",
)
REFLECTION_LEASE_TAKEOVERS = Counter(
    "mneme_reflection_lease_takeovers_total",
    "Reflection leases acquired after a previous lease expired",
)
