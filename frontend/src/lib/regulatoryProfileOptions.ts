/** Mirrors backend `regulations_prompts` + institution types used in enrichment / schemas. */

export const INSTITUTION_TYPES = [
  "commercial_bank",
  "credit_union",
  "mortgage_servicer",
  "broker_dealer",
  "fintech",
  "insurance",
  "other",
] as const;

export const CANONICAL_PRODUCTS = [
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
] as const;

export const CANONICAL_FUNCTIONS = [
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
] as const;

export function formatRegTagLabel(tag: string): string {
  return tag.replace(/_/g, " ");
}
