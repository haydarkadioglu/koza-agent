# Koza Agent Improvement Roadmap & Progress Notes

This document tracks planned, in-progress, and completed improvements to the Koza Agent codebase to enhance execution speed, reliability, and usability.

## Completed Tasks

### 1. Tool Selection & Registry Optimization
- [x] **Adaptive Tool Schema Injection**:
  - Registered all core capabilities (178 tools) when running with cloud-based/remote providers (e.g. OpenRouter, OpenAI, Gemini) to leverage their large context windows and advanced routing.
  - Retained strict keyword/IntentRouter filtering for local providers (Ollama, LM Studio) to minimize context token usage.
- [x] **Registry Initialization Fix**:
  - Modified `core.py` to call `rebuild_registry(force=True)` on agent startup, ensuring user configuration overrides for `disabled_skills` are immediately applied.
- [x] **Smart Heuristic Routing**:
  - Added regex heuristics to the local router to instantly route email queries, messaging tasks, and git/github actions without triggering unnecessary LLM routing calls, dramatically improving response speed.

### 2. Task Execution Reliability ("zar zor yaptırıyorum")
- [x] **SMTP & Email Config Pre-flight checks**:
  - Added environment variable overrides for email configuration in `config.py`, loading variables directly from `~/.Koza/.env`.
  - Allowed integers (like `SMTP_PORT`) and variable nesting levels to map safely to the configuration dictionary.
- [x] **Integration/Credential Status in System Prompt**:
  - Injected an active credentials status snippet at the end of the system prompt (`prompt.py`), making the agent fully aware of whether SMTP, Telegram, Discord, Twilio, and GitHub are configured and ready.

### 3. Language & Localization Adaptation
- [x] **CLI Localization Helper**:
  - Developed `cli/i18n.py` to dynamically localize command-line interface outputs between Turkish and English based on the `language` config key or the host system locale.
  - Updated `cli/chat.py` to wrap key terminal output nodes using the localization utility.

---

- [x] **From Hermes**:
  - Integrated `uv` dependency checking for dynamic skills (`plugin_loader.py`).
  - Implemented detailed trajectory tracking in ShareGPT format (`skills/agents/trajectory.py` & `core.py`).
- [x] **From OpenClaw**:
  - Implemented robust channel handler patterns (redirecting stderr to logs, JSON-RPC filtering).
  - Implemented dynamic MCP client registration for stdio and HTTP/SSE transports (`skills/mcp_skill.py` & `tools/registry.py`).

---

### 4. Dynamic Tool Selection, Email/Messaging Prompt Sections, Adaptive i18n & CLI Enhancements
- [x] **Dynamic Tool Selection for Cloud Models**: Optimized `core.py` to filter the schema down to active/necessary tool groups dynamically, falling back to a safe subset when no keywords match. This prevents context window bloating and keeps calls fast.
- [x] **Prompt Section Mapping & System Integration**: Added custom sections `prompts/sections/email.md` and `prompts/sections/message.md` to instruct the agent on SMTP/IMAP credential errors, app password setups, and messaging configuration.
- [x] **Heuristic Routing Alignment**: Updated the local router in `router.py` to correctly flag these new prompt sections alongside tool groups for direct injection.
- [x] **Adaptive i18n Normalization**: Updated `cli/i18n.py` to normalize full language names (`turkish`), regional codes (`tr-TR`), and other locales, ensuring robust adaptive translation fallbacks.
- [x] **CLI Execution Feedback**: Added friendly tool labels to `cli/ui/_stream_renderer.py` for all email, WhatsApp, and Twilio tools, displaying readable progress feedback on the console.

---

*Note: All changes are tested locally. Do NOT push directly to GitHub; manual review and push will be performed by the user.*

## Active Task List (Current Session)

### 1. Refined Routing & Tool Availability
- [x] **Accumulative Heuristic Routing**: Modified `router.py` to collect all tool groups and prompt sections across all matched keyword patterns instead of early-returning. This enables hybrid commands (e.g. scheduling + email) to have all their necessary capabilities loaded.
- [x] **Expanded Default Core Tools**: Added general-purpose utilities (`list_dir`, `create_dir`, `get_config`, `set_config`, `wm_list`, `wm_get`, `wm_add`) to `_CORE_TOOL_NAMES` in `core.py` to ensure key directory and memory/config features are always available.
- [x] **Cloud Provider Tool Access**: Configured remote/cloud LLMs to receive all tools by default, while retaining the client option to toggle dynamic filtering via `dynamic_tool_selection_cloud: true` if desired to minimize token usage.
- [x] **Unit Testing validation**: Verified that the new routing and tool selection logic passes all unit tests successfully.
- [x] **YAML Catalog-based i18n Migration**: Migrated the hardcoded translations dictionary in `cli/i18n.py` to dynamic YAML locale catalogs loaded from a newly created `locales/` directory. Added `locales/en.yaml` and `locales/tr.yaml` with the baseline English and Turkish catalogs. Verified all unit tests for localization and normalization pass successfully.
- [x] **Dynamic Skill Activation instructions**: Discovered the catch-22 where the agent was unaware of disabled capabilities since they are excluded from the tool registry. Injected instructions into the core system prompt (`prompts/core/system.md` and `prompt.py` fallback) detailing how the agent can dynamically enable required core skills (e.g. `email_skill`, `browser_control`) via `enable_core_skill` on demand.
- [x] **Empty Response Recovery**: Implemented nudge mechanism in `core.py` to steer model recovery after tool calls; implemented automatic cleanup of synthetic messages in `finally` block to prevent history poisoning.
- [x] **Message Sequence Repair**: Added `_repair_message_sequence` in `core_context.py` to drop stray tool messages and merge consecutive user messages inside `ContextWindow.trim()` to ensure API-compliant histories.
- [x] **UI/UX Consistency**: Standardized status labels ("Reasoning..." and "Reasoning…") across `_stream_renderer.py`, `_spinner_widget.py`, and the test suite, protecting status bar state mutations with mutex lock and resolving thread race conditions.
- [x] **Link-Understanding Adaptation**: Adapted the safe URL detection and pre-fetching pattern from OpenClaw, allowing the agent to automatically extract, validate, and download public HTTP/HTTPS URLs before running classification and the main conversation loop, maximizing performance and roundtrip speed.
- [x] **English-only Interface Enforcement**: Configured `cli/i18n.py` to always return `"en"` and discard localization changes to Turkish, keeping the terminal user interface English-only. Mapped Turkish keys in the English catalog to ensure legacy strings auto-translate. Updated `tests/test_i18n_normalization.py` to match the new behavior.
- [x] **Dynamic Auto Skill Activation**: Added `enable_core_skill`, `disable_core_skill`, and `list_core_skills` to `_CORE_TOOL_NAMES` and the `skill` group in `core.py`. Modified `_select_tools` to dynamically detect when a tool group requires a disabled core skill and automatically enable it in `config.yaml` on-the-fly, allowing immediate execution without requiring manual activation by the user.
- [x] **Live Progress Indicator for Fallback Layout**: Extended `_PlainLayout` in `cli/chat.py` to support real-time animated status and progress updates on stdout using carriage return (`\r`) carriage control. It automatically clears the temporary status bar when writing new response tokens or finalizing.
- [x] **Granular Progress Callback Integration**: Integrated `tool_progress_callback` in `core.py` and `cli/chat.py`. The execution loop now forwards progress updates ("tool.started" and "tool.completed") with parsed arguments and elapsed times to the main UI layout/spinner, driving the progress bar dynamically and smoothly towards a target percentage.
- [x] **Immediate Tool Execution Prompting**: Refactored the core system prompts (`prompt.py`, `prompts/core/system.md`, and `prompts/sections/skill.md`) to instruct the agent to invoke tools immediately upon availability rather than calling `enable_core_skill` and waiting for a turn transition, resolving the multi-turn latency issue when triggering task execution (like email/automation).

### 5. Advanced Credential Resolution, SSRFGuard & Test Suite Success
- [x] **Universal Dynamic Credential Resolution**: Extended the robust fallback credential resolution mechanism to `skills/messaging/telegram.py` and `skills/messaging/twilio_skill.py`. Credentials are dynamically resolved from environment variables and the shared memory credential pool (`~/.Koza/.env`) on-demand, resolving execution issues.
- [x] **DNS-Aware SSRFGuard Validation**: Replaced regex URL checking with a robust `is_safe_url` helper in `skills/web.py` that performs DNS resolution and blocks connections resolving to private, loopback, link-local, multicast, or reserved IPs.
- [x] **Tool-Level Security Enforcement**: Added `is_safe_url` verification directly to the `fetch_url` tool in `skills/web.py` to protect all browser and static requests.
- [x] **Full Test Suite Success**: Verified all changes by running the entire test suite of 481 tests, which passed with 100% success.

### 6. Hermes-adapted Type Coercion & English-Only Output Persona
- [x] **JSON Schema-based Tool Argument Coercion**: Integrated `coerce_tool_args` from Hermes into `tools/registry.py` and connected it in `core.py`'s `_execute_tool` loop. This resolves common model invocation failures (e.g. sending integers/booleans as strings or arrays as raw JSON strings) by coercing them to target schema types prior to handler execution.
- [x] **Robust Argument Validation Tests**: Wrote `tests/test_coerce_args.py` validating that integers, floats, booleans, and list wrapping function perfectly under schema coercion.
- [x] **Enforce English output responses**: Replaced the system prompt's language matching rule to mandate outputting responses and interface messages exclusively in English, while remaining adaptive and understanding of user inputs in other languages (such as Turkish).

### 7. Transient API Error Recovery & Email Alignment (Hermes Adaptation)
- [x] **Jittered Exponential Backoff for Stream Failures**: Adapted error-recovery patterns from Hermes, implementing a transient failure recovery handler in `core.py`'s `stream_chat` loop. If streaming fails with transient network or service errors (such as 429 rate limit, 503 overloaded, 500/502/504 server errors, timeouts, or connection issues), the agent applies a randomized exponential backoff delay before retrying up to 3 times.
- [x] **Stream Retry Unit Tests**: Created `tests/test_stream_retry.py` validating recovery and failure exhaustion for transient network errors.
- [x] **Proactive Email Credential Guidance**: Enriched instructions in `prompts/sections/email.md` to guide the model on instructing the user about `/email-setup` or Gmail App Passwords when SMTP/IMAP credentials fail or are absent.

### 8. Priority Schema Ordering, Heuristic Triggers & Streaming Progress Bar
- [x] **Priority Static Tool & Handler Schema Registration**: Reordered the registry concatenation in `tools/registry.py` to list all critical core, shell, filesystem, web, browser, code runner, email, and messaging modules first. This guarantees these essential tools are never truncated when remote model contexts are capped to a 128-tool limit.
- [x] **Enriched Local Routing & Keyword Map Synonyms**: Added messaging and notification synonyms (e.g., `notify`, `ping`, `inform`, `timer`, `reminder`, `yaz`, `ilet`, `haber ver`) to the heuristics in `router.py` and keyword map in `core.py` to trigger prompt sections and toolsets instantly in the first turn.
- [x] **Relaxed System Prompt Constraint**: Modified the absolute prohibitions rule in `prompts/core/system.md` to replace the rigid prohibition of any text before tool execution with a guideline to avoid chatty filler but allow structured reasoning. This eliminates validation/parsing errors during model tool calls.
- [x] **Strict English Output Rules**: Replaced the system prompt language matching rule in both `prompt.py` and `prompts/core/system.md` to guarantee that all outputs and UI text are in English, while remaining adaptive and understanding of user inputs in other languages (such as Turkish).
- [x] **Persistent Streaming Progress Bar**: Modified the text event handler in `cli/ui/_stream_renderer.py` to keep the progress bar active, animating, and displaying token counts in the status bar during text streaming rather than stopping it. Updated the corresponding integration tests in `tests/test_stream_renderer_spinner.py` and verified they pass successfully.

### 9. Dynamic Credential Hot-Reloading & Router Streamlining
- [x] **Dynamic Configuration Loading for Email/Messaging**: Modified credential resolution in `email_skill.py`, `telegram.py`, `discord.py`, `twilio_skill.py`, and `whatsapp.py` to dynamically reload configuration from the file system on demand using `load_config()`. This guarantees credential setup changes (e.g. via `/email-setup` or manual edits) take effect immediately without requiring a daemon/process restart.
- [x] **Local Heuristic Router Streamlining**: Removed the restrictive, early-returning heuristics for email, messaging, git, and cron tasks in `router.py`. This ensures that complex, hybrid user commands (such as "search the web and email me the summary") are successfully categorized by the LLM routing classifier with all required toolsets loaded, instead of being overly restricted to email tools.
- [x] **Verified English-Only UI Integrity**: Verified that the application remains strictly in English under all commands while retaining adaptive understanding of Turkish and other user inputs.

## Active Task List (Session Checkpoint 1)

**Progress: [██████████████████████████] 100%**

### 10. Refined Heuristic Routing & Email Auto-Extraction
- [x] **Hybrid Query Bypass**: Added `_is_hybrid_query` helper in `router.py` to bypass keyword heuristic routing for complex/hybrid messages containing web search, file operations, finance, or research keywords, ensuring the LLM router classifies them and loads all necessary toolsets.
- [x] **Email Credential Auto-Saving**: Implemented email address and password/app password auto-detection in `core.py`'s `_auto_save_credentials` method. When a user provides their email and password/app password in chat, it automatically configures the SMTP/IMAP settings using presets and loads the config on the fly.
- [x] **Unit Testing Validation**: Added `test_heuristic_routing_hybrid_bypass` to `tests/test_select_tools.py` and created `tests/test_email_auto_extract.py` to verify both the hybrid query bypass and the email credential auto-extraction logic. All tests passed with 100% success.

## Active Task List (Session Checkpoint 2)

**Progress: [██████████████████████████] 100%**

### 11. Persistent Session Progress & Visual Error Reporting
- [x] **SSRFGuard and Dynamic credential updates**: Ensured security mechanisms and credential resolutions load configurations dynamically to execute tasks reliably.
- [x] **Visual Tool Failure Indication in CLI**: Updated `cli/ui/_stream_renderer.py`'s `tool_done` handler. When a tool fails (indicated by `ERROR:` prefix, `Exit code:` non-zero, `❌` symbol, or keyword errors like `failed`, `not configured`), the terminal renderer renders a red cross (`✗`) and red text instead of a misleading green checkmark (`✓`), enhancing visual reliability.
- [x] **Persistent Session Progress Bar**: Integrated configuration loading and saving for `_session_progress` in `core.py` and `cli/ui/_stream_renderer.py`. The progress bar now loads its previous value from `config.yaml` on startup and writes the updated progress back to disk on finalization, ensuring the agent's progress bar state persists across multiple commands and CLI restarts ("yaptıklarını unutma").
- [x] **Unit Testing Validation**: Verified that all core agent workflows, UI rendering, and spinner/progress bar integrations pass the unit test suite without regression.

## Active Task List (Session Checkpoint 3)

**Progress: [██████████████████████████] 100%**

### 12. Structured Error Classification & API Failover
- [x] **Adoption of Hermes Error Classifier**: Designed and implemented `providers/error_classifier.py` implementing the centralized `classify_api_error` function and `FailoverReason` enumeration to classify raw exception/HTTP status data into structured error reasons (e.g. rate limit, billing/quota, overloaded, server error, timeout, authentication, context overflow).
- [x] **Robust Key Rotation & Exception Recovery**: Integrated the classifier into `core.py`'s `stream_chat` exception handler, allowing key rotation to trigger not only on rate limits but also on billing/quota exhaustion errors.
- [x] **Error Classifier Unit Tests**: Authored `tests/test_error_classifier.py` validating correct classification of rate limit, billing (including HTTP 402), overloaded (including HTTP 503), authentication (HTTP 401/403), context overflow, and timeout exceptions.
- [x] **Verified Stream Retry Integration**: Verified that the new classification schema is fully compatible with stream retry recovery and property-based streaming test suites.

## Active Task List (Session Checkpoint 4)

**Progress: [██████████████████████████] 100%**

### 13. Safe Connection Timeouts for SMTP & IMAP
- [x] **SMTP & IMAP Fail-Safe Connection Timeouts**: Added `timeout=15` parameters to `smtplib.SMTP`, `smtplib.SMTP_SSL`, and `imaplib.IMAP4_SSL` calls in `skills/email_skill.py`. This prevents the agent from hanging indefinitely when mail/IMAP servers are unresponsive or blocked by firewalls.
- [x] **Enforced Strict English Rules**: Standardized the system prompts and fallback rules in `prompt.py` and `prompts/core/system.md` to exclusively output English, ensuring consistent i18n behavior.
- [x] **Validated against entire test suite**: Ran `pytest tests` and verified 100% of 492 tests passed successfully without regressions.

