# DSRT Core — Phase C2 Model Fabric

**Status:** In Progress (C2.1 → C2.2)

# DSRT Core — Phase C2 Model Fabric v1.0

**Status:** Certified Complete (C2.1 → C2.12)  
**Core Version:** `1.0.0`  
**Agent Contract Version:** `1.0`  
**SDK Version:** `1.0.0`  
**Supported Providers:** OpenAI, Google Gemini  

---

## 1. Phase C2 Mission

Build the universal Model Fabric that allows **every DSRT Agent to reason through any supported model without knowing which provider is underneath it**.

> **Agents request intelligence. Core decides how that intelligence is obtained.**

---

## 2. Complete C2 Sub-Phase Summary

| Sub-Phase | Component | Responsibilities |
|---|---|---|
| **C2.1** | Model Contracts | `ModelRequest`, `ModelResponse`, `ToolCall`, `Usage`, `CostBreakdown`, `StreamEvent`, `ProviderHealth` |
| **C2.2** | Provider Registry | Provider & Model catalog, `ModelCapabilityProfile`, `ModelContextConfig`, `ModelPricing` |
| **C2.3** | First Adapter (OpenAI) | `OpenAIAdapter` built on `openai.AsyncOpenAI`, tool calling, vision, error translation |
| **C2.4** | Second Adapter (Gemini) | `GoogleAdapter` built on `google.genai.Client`, proves multi-provider abstraction |
| **C2.5** | Credential Manager | AES-256 Fernet encryption, `CredentialBroker` in-memory decryption, `CredentialReference` |
| **C2.6** | Model Router | Constraint resolution engine, evaluates policy/capabilities, emits `RoutingDecision` audit trails |
| **C2.7** | Context Compiler | `ContextCompiler` token budgeting, priority packing (System > State > Tools > Memory > History), provenance tracking |
| **C2.8** | Session Manager | `ModelSessionManager` & `ModelCheckpoint`, enables mid-task model switching |
| **C2.9** | Retry & Fallback | `RetryEngine` exponential backoff, error classification, `FallbackResolver` |
| **C2.10** | Usage Meter | `CostCalculator` per 1M tokens, `UsageMeter` execution cost aggregation |
| **C2.11** | Model Gateway | `ModelGateway` orchestrator uniting Router, Sessions, Compiler, Broker, Retry, Usage, Telemetry |
| **C2.12** | Agent Integration | Upgraded `ModelSDKImpl`, C2 Golden Test (OpenAI → Gemini mid-task switch), `verify_c2.py` |

---

## 3. The C2 Golden Test

`tests/integration/test_c2_golden_path.py` demonstrates the central proof of Phase C2:

```text
Research Task
     ↓
Research Intelligence Agent
     ↓
Model A (OpenAI) → Step 1 Reasoning → Checkpoint
     ↓
USER SWITCHES MODEL MID-TASK
     ↓
Context Compiler rebuilds canonical state for Model B
     ↓
Model B (Gemini) → Step 2 Reasoning → Artifact

```
## What C2 Delivers
Transforms the abstract Model Gateway into a true intelligence fabric. Agents request reasoning; Core resolves the model, injects credentials, compiles context limits, routes requests securely, manages retries/fallbacks, and tracks usage.

## Sub-Phases Completed

### C2.1 — Model Contracts
- Canonical provider-neutral interfaces: `ModelRequest`, `ModelResponse`, `ToolCall`, `Usage`, `CostBreakdown`, `StreamEvent`
- Native multi-modality via `MessageContentPart`
- Cost reporting immutability (`estimated` vs `reported`)
- Agent requirements & routing policies

### C2.2 — Provider Registry
- Authoritative catalog of intelligence providers and models.
- **ProviderRepository** + **ModelRegistry** services.
- Models declare strict capability profiles (tool calling, vision, context limits, token pricing).
- Resolves the ORM impedance mismatch by packing/unpacking capabilities into `JSONB`.
- REST API: `POST /api/v1/providers`, `POST /api/v1/models`, `GET /api/v1/models/{id}`.


### C2.3 — First Provider Adapter (OpenAI)

- **Provider Adapter Protocol** (`core/providers/base/adapter.py`) — The strict Python `Protocol` defining the `ModelProviderAdapter` interface (`generate`, `stream`, `count_tokens`, `check_health`).
- **Adapter Registry** (`core/providers/registry/registry.py`) — Central factory resolving a provider `slug` to an instantiated adapter class.
- **OpenAI Adapter** (`core/providers/openai/adapter.py`) — The first concrete implementation.
  - Translates `ModelRequest` multi-modal parts into OpenAI Vision formats.
  - Translates `ToolDefinition` into OpenAI Function calling schemas.
  - Executes API calls via `openai.AsyncOpenAI` ensuring no key leakage.
  - Normalizes OpenAI `AuthenticationError`, `RateLimitError`, and `APITimeoutError` into canonical DSRT `ModelError` exceptions.
  - Returns canonical `ModelResponse` with `Usage` strictly populated.
- **Invariants proven**: Agents never touch the `openai` SDK directly; Core owns translation; Cost isolation preserved.

### C2.4 — Second Provider Adapter (Google Gemini)

- **Google Gemini Adapter** (`core/providers/google/adapter.py`) — The second concrete implementation, proving the abstraction holds across radically different provider APIs.
  - Built on `google-genai` SDK.
  - Translates `ModelRequest` into Gemini's `Content` and `Part` objects.
  - Translates `ToolDefinition` into Gemini's `FunctionDeclaration` objects.
  - Handles Gemini's unique `FunctionResponse` requirement for feeding tool results back into context.
  - Normalizes `google.genai.errors.APIError` into canonical DSRT `ModelError` exceptions.
- **Adapter Registry** updated to expose `"google"` alongside `"openai"`.

### C2.7 — Context Compiler

- **Token Counter** (`core/models/context/token_counter.py`) — Provides deterministic token estimation heuristics.
- **Context Compiler Engine** (`core/models/context/compiler.py`) — Assembles provider-ready context by parsing the canonical `SDKAgentContext`, `Memories`, `ToolResults`, and `ConversationHistory`.
- **Budget Enforcement** — Implements priority-based packing (C2 §24):
  1. System & Task Objective (Highest)
  2. Working State
  3. Tool Results (Truncated if necessary)
  4. Memories (Dropped if budget constrained)
  5. Conversation History (Older messages dropped first)
- **Provenance Tracking** (`ContextProvenanceItem`) — Every injected piece of memory or state records its origin and truncation status, ensuring verifiable execution trajectories (C2 §25).


### C2.8 — Session Manager (Model Switching)

- **Session Repository & Schemas** (`schemas/domain/session.py`, `core/repositories/session_repository.py`) — Introduces `model_sessions` and `model_checkpoints` to track intelligence continuity.
- **ModelSessionManager** (`core/models/sessions/manager.py`) — The engine that enables the C2 Golden Test ("Model Switching"). 
  - When an execution requests a model, the manager checks the active session. 
  - If the requested model is different (e.g., fallback triggered, or user explicitly switched from GPT-4o to Gemini 1.5 Pro), the manager closes the old session (status = `switched`) and opens a new one.
  - This guarantees that DSRT never attempts to illegally copy a provider's hidden internal conversation history to a different provider; instead, it relies on DSRT's canonical state and context compiler to rebuild the context fresh for the new model.

### C2.9 — Retry / Fallback Engine

- **Error Classifier** (`core/models/retry/classifier.py`) — Maps every `ModelErrorCode` to a `RetryClassification` (`RETRYABLE`, `RETRYABLE_WITH_BACKOFF`, `NOT_RETRYABLE`, `FALLBACK_ELIGIBLE`).
- **Retry Policy** (`schemas/domain/retry.py`) — Configurable: `max_retries`, `initial_backoff_seconds`, `backoff_multiplier`, `max_backoff_seconds`, `allow_fallback`, `max_fallback_attempts`.
- **Retry Engine** (`core/models/retry/engine.py`) — The core loop:
  1. Attempt generation on selected model.
  2. On failure, classify error code.
  3. If `RETRYABLE` → retry with exponential backoff (up to `max_retries`).
  4. If `FALLBACK_ELIGIBLE` and `allow_fallback` → use `FallbackResolver` to find next eligible model → retry on fallback.
  5. If `NOT_RETRYABLE` → raise immediately (no wasted retries on permanent errors like invalid credentials).
  6. Returns `RetryResult` with full attempt history for observability.
- **Fallback Resolver** (`core/models/fallback/resolver.py`) — Blocks the failed model in the routing policy and re-runs the Model Router to find the next eligible candidate.
- **Invariants proven**: Credential errors never retry; rate limits backoff; provider outages trigger fallback; attempt history is fully auditable.



### C2.10 — Usage Meter

- **Cost Calculator** (`core/models/usage/calculator.py`) — Provides pure, deterministic functions that map token usage to USD based on the `ModelPricing` profiles defined in the Provider Registry. Handles fractional decimals cleanly via `Decimal.quantize()`.
- **Usage Repository** (`core/repositories/usage_repository.py`) — Standardizes DB ingestion of `UsageRecord` and provides live SQL aggregation (`SUM`) across an execution.
- **Usage Meter Service** (`core/models/usage/meter.py`) — The bridge between model execution and accounting. It receives `ModelResponse` objects, dynamically looks up current pricing from the `ModelRegistry`, calculates the cost, and persists the record.
- **Invariants proven**: Estimated cost is cleanly segregated from provider-reported cost (C2 §11). DSRT tracks exact token expenditures across models in a single unified schema.


### C2.11 — Model Fabric Observability & Gateway

- **Model Gateway** (`core/models/gateway/gateway.py`) — The central operational hub unifying Router, Session Manager, Context Compiler, Credential Broker, Retry Engine, Usage Meter, and Event Telemetry into a single call: `execute_request()`.
- **Telemetry Event Types** (`schemas/domain/enums.py`) — Expanded with complete Model Fabric lifecycle events:
  - `MODEL_REQUEST_CREATED`
  - `MODEL_ROUTING_STARTED` / `MODEL_ROUTING_COMPLETED`
  - `MODEL_REQUEST_STARTED` / `MODEL_REQUEST_RETRY` / `MODEL_REQUEST_COMPLETED` / `MODEL_REQUEST_FAILED`
  - `MODEL_FALLBACK_STARTED` / `MODEL_FALLBACK_COMPLETED`
  - `MODEL_SESSION_SWITCHED` / `MODEL_CHECKPOINT_CREATED`
- **Invariants proven**: Every model call creates a complete, auditable trajectory record in Supabase that C8 Arena can consume directly via `/api/v1/executions/{id}/telemetry`.