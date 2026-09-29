from prometheus_client import Counter, Gauge


LLM_REQUESTS = Counter(
    "mneme_llm_requests_total", "LLM requests", ["mode", "provider", "outcome"]
)
LLM_FALLBACKS = Counter(
    "mneme_llm_fallbacks_total", "Requests switched to the fallback model", ["mode"]
)
LLM_ACTIVE = Gauge("mneme_llm_active_requests", "Currently running model requests")
LLM_INPUT_TOKENS = Counter(
    "mneme_llm_input_tokens_total", "Estimated input tokens sent to LLM providers", ["provider"]
)
LLM_OUTPUT_TOKENS = Counter(
    "mneme_llm_output_tokens_total", "Estimated output tokens requested from LLM providers", ["provider"]
)
LLM_ESTIMATED_COST = Counter(
    "mneme_llm_estimated_cost_usd_total", "Estimated LLM spend in USD", ["provider"]
)
LLM_BUDGET_BLOCKS = Counter(
    "mneme_llm_budget_blocks_total", "LLM requests rejected by the daily budget"
)

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
