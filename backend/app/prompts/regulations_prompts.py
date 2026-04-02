"""Versioned prompts for regulatory document enrichment (single structured JSON output)."""

PROMPT_VERSION = "v1"

SYSTEM = """You are a senior bank regulatory analyst. You read Federal Register documents and extract structured metadata for compliance teams at mid-size banks.

Rules:
- Output a single JSON object only. No markdown fences, no commentary outside JSON.
- Use only the allowed enum values provided in the schema description.
- Ground tags in the document: do not invent obligations not supported by the text.
- If unsure about severity, prefer "medium" and explain in severity_rationale.
- Dates must be ISO format YYYY-MM-DD or null if unknown or not stated."""

CANONICAL_PRODUCTS = (
    "mortgage_lending",
    "credit_cards",
    "auto_lending",
    "student_lending",
    "personal_lending",
    "deposit_accounts",
    "commercial_lending",
    "wealth_management",
    "payments",
    "digital_banking",
    "small_business_lending",
)

CANONICAL_FUNCTIONS = (
    "bsa_aml",
    "kyc_cdd",
    "fair_lending",
    "consumer_complaints",
    "privacy",
    "capital_requirements",
    "liquidity",
    "cybersecurity",
    "vendor_management",
    "model_risk",
    "sanctions",
)
