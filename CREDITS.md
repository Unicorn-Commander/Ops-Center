# Unicorn Commander Credit Unit

**Status:** authoritative unit definition
**Effective:** 2026-08-06
**Owner:** Aaron Stransky / Magic Unicorn

## Definition

**ONE CREDIT = ONE US DOLLAR of metered provider-equivalent cost.**

## Debit path

The debit path writes `amount == cost` on the ledger (provider-equivalent USD cost is
the credit amount). Do **not** change that equality without changing this document
first.

## Sell floor

**Credits are never sold below $1.00.**

---

## Cost function (task 11, 2026-08-07)

### How a chat is priced

1. Chat handler (`litellm_api.py`) records `prompt_tokens` / `completion_tokens` from the provider usage block (and the original `request.model`).
2. `CreditSystem.calculate_cost` resolves **per-model input and output rates** (USD per 1M tokens) from, in order:
   - free short-circuit if either billed model or request model ends with `:free`
   - local short-circuit (`is_local` → free unless the tier's metered-local gate
     selects the catalog split-rate path)
   - `llm_models.cost_per_1m_input_tokens` / `cost_per_1m_output_tokens` (catalog)
   - static `MODEL_RATES_USD_PER_MTOK` table in `litellm_credit_system.py`
   - **conservative default** (`CONSERVATIVE_DEFAULT_USD_PER_MTOK`, labelled `conservative_default_unknown_model`) — never a silent provider-prefix flat rate
3. `cost = (prompt/1e6)*input_rate + (completion/1e6)*output_rate`
4. `cost *= CREDIT_MARKUP_MULTIPLIER`
5. Ledger writes `amount == -cost` (debit) with `cost` stored positive.

### CREDIT_MARKUP_MULTIPLIER

**Single, named, configurable margin lever.**

| Name | Default | Meaning |
|---|---|---|
| `CREDIT_MARKUP_MULTIPLIER` | `1.0` | Pass-through: 1 credit = $1 of provider-equivalent cost |

Set via environment variable `CREDIT_MARKUP_MULTIPLIER` on the ops-center process. Do not scatter other markups. Power-level cost multipliers and per-tier `llm_markup_percentage` are **not** applied on the debit path (they previously flattened every cloud call into a false ~$2.50–$3.75/Mtok band).

Aaron sets any non-1.0 value. Do not invent one.

### Local models

Local is free for exempt and `free_unlimited` tiers. When `LOCAL_PRICING_ENABLED=true`
and a tier's `local_pricing_mode` is `metered`, the same `calculate_cost` function uses
the local model's `llm_models.cost_per_1m_input_tokens` and
`cost_per_1m_output_tokens`, then applies the single `CREDIT_MARKUP_MULTIPLIER`.
There is no separate local rate or debit mechanism.

### Free variants (`:free`)

A model id ending in `:free` costs **0** at every site, including the post-call path where providers often echo the model **without** the `:free` suffix. Both `model` and `request_model` are checked.

### Unknown models

Policy (explicit): **charge a clearly-labelled conservative default** rather than refuse the call. Rates are frontier-class ($5 / $15 per 1M in/out) and every hit is logged as `UNKNOWN_MODEL_PRICING`. Add the model to `llm_models` (preferred) or `MODEL_RATES_USD_PER_MTOK` to clear the warning.

### Historical ledger

Task 11 does **not** rewrite historical `credit_transactions`. Pre-fix rows are the evidence of the bug. `credit_purchases = 0`, so there is nothing to refund.
