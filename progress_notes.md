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

