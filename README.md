# SYSTEM ARCHITECTURE ANALYSIS REPORT

## SYSTEM IDENTIFICATION

**System Name:** Three-Body Hierarchy AI Agent System  
**Architecture Pattern:** Hierarchical Multi-Agent Command Structure  
**Operation Modes:** Dual-mode (Visual Desktop Automation / Text Document Analysis)  
**Target Platform:** Windows 11 Pro, Python 3.12.10  
**AI Model:** Qwen3-VL (qwen3-vl-4b-instruct) via LM Studio OpenAI API  

---

## ARCHITECTURAL OVERVIEW

### Three-Tier Command Hierarchy

The system implements a military-inspired command structure with three distinct agent tiers operating in a stateless LLM environment with application-layer memory management.

**TIER 1: STRATEGIST (Command Staff)**
- **Invocation:** Once at initialization, on-demand during BLOCKED state
- **Input:** Mission objective + initial visual/text context
- **Output:** Strategic doctrine (plain text OPORD-style document)
- **Responsibilities:** 
  - Define mission intent and global objectives
  - Establish definition-of-done (DOD) criteria per objective
  - Define verification rubrics
  - Set rules of engagement and contingencies
  - Issue doctrine updates when operations stall

**TIER 2: TACTICIAN (Field Commander)**
- **Invocation:** Turn 1, every 5 turns, on loop detection, on objective state change
- **Input:** Mission + doctrine + memory context + current visual/text state
- **Output:** Tool calls (spawn_executor_prompt, update_phase_tools)
- **Responsibilities:**
  - Maintain explicit CURRENT OBJECTIVE tracking (objective_id, objective_dod, objective_status)
  - Manage macro phase transitions (RECONNAISSANCE → EXECUTION → VERIFICATION)
  - Generate/update Executor system prompts
  - Define tool subsets for Executor
  - Enforce progress reporting requirements
  - Prevent objective regression

**TIER 3: EXECUTOR (Operator)**
- **Invocation:** Every turn when configured
- **Input:** Dynamically generated system prompt + memory context + current state
- **Output:** Single tool call per turn + SITREP
- **Responsibilities:**
  - Execute ONE atomic action per turn
  - Provide structured SITREP (OBJ/DOD/OBS/NEXT)
  - Report progress at milestones
  - Escalate BLOCKED status when stalled
  - Avoid action repetition (max 2x same target)

---

## FILE STRUCTURE AND RESPONSIBILITIES

### 1. windows_primitives.py
**Role:** Hardware abstraction layer and low-level system interface

**Configuration Management:**
- `SystemConfig`: LM Studio endpoint, model parameters, image dimensions, operational limits
- `Timing`: Hardcoded delays for UI stabilization (cursor settle, drag steps, UI render)
- `Features`: Toggle switches for loop recovery, full archive, detection thresholds

**Windows API Integration:**
- DPI awareness configuration (Per-Monitor V2)
- Screen capture with HALFTONE stretching and cursor overlay
- RGB to PNG encoding (zlib compression, manual chunk packing)
- Input simulation via SendInput (mouse, keyboard, Unicode text)
- Virtual key code mapping with auto-extension for a-z, 0-9, F1-F12

**Primitive Operations:**
- `capture_png(tw, th)`: Capture screen at target resolution with cursor, return PNG bytes
- `move_mouse(x, y)`, `click()`, `double_click()`, `right_click()`
- `drag(x1, y1, x2, y2)`: 20-step interpolated drag with timing delays
- `scroll_action(direction)`: Mouse wheel simulation (±120 delta)
- `type_text(text)`: Unicode character-by-character input with KEYEVENTF_UNICODE
- `press_key(key)`: Combo key support (e.g., "ctrl+shift+esc")

**Data Structures:**
- `Coordinate`: Normalized 0-1000 scale with `to_pixels()` conversion and `signature()` for loop detection
- `TextDocument`: Document wrapper with excerpt generation for context limits

**Critical Design Notes:**
- All timing values are empirical for Windows 11 125% scaling
- VK_MAP auto-extends at module load to prevent key lookup failures
- PNG encoding is custom (no PIL/Pillow dependency)

---

### 2. memory_and_tools.py
**Role:** Memory subsystem, tool schema definitions, context generation

**Tool Schema Definitions:**
- **TACTICIAN_TOOLS:** spawn_executor_prompt, update_phase_tools
- **VISUAL_TOOLS:** 10 tools (click variants, drag, type_text, press_key, scroll, report_progress, report_completion)
- **TEXT_TOOLS:** 3 tools (analyze_text, report_progress, report_completion)
- Tool registries (VISUAL_TOOL_REGISTRY, TEXT_TOOL_REGISTRY) for dynamic lookup

**Tool Argument Classes:**
- Dataclasses with `from_dict()` factories for type-safe deserialization
- `ClickArgs`, `DragArgs`, `TypeTextArgs`, `PressKeyArgs`, `ScrollArgs`
- `ReportProgressArgs`: Carries objective_id, status (IN_PROGRESS/DONE/BLOCKED), evidence
- `ReportCompletionArgs`: Terminal completion with evidence (min 100 chars enforced in agent_system.py)
- `SpawnExecutorArgs`: Contains prompt, phase, rationale, objective_id, objective_dod, objective_status
- `UpdatePhaseToolsArgs`: tool_names list with rationale

**ToolCall Parsing:**
- `ToolCall.from_api_response()`: Handles both string JSON and dict arguments from LM Studio
- Validates tool names against arg_map, raises ValueError on unknown tools

**Phase Management:**
- `normalize_phase()`: Canonicalizes phase strings to RECONNAISSANCE/EXECUTION/VERIFICATION
- `apply_tool_floor()`: Enforces minimum required tools per phase (e.g., report_progress always included)
- `ensure_tools_for_phase()`: Returns defaults if Tactician provides empty list
- `DEFAULT_TOOLS_BY_PHASE_VISUAL/TEXT`: Full recommended tool sets
- `MIN_TOOLS_BY_PHASE_VISUAL/TEXT`: Safety floor to prevent tool starvation

**Memory System:**

`ActionRecord`:
- Stores turn, tool name, args, justification, result, screenshot path, sitrep
- Methods: `get_target_label()`, `get_position_signature()`, `get_action_signature()` for loop detection

`AgentMemory`:
- **Configuration:** max_recent_items (10), max_context_items (8), loop_detection_window (5), loop_detection_threshold (3)
- **Storage:**
  - `recent`: Rolling window of last 10 actions
  - `archive`: Optional full history (enabled via FEATURES.ENABLE_FULL_ARCHIVE)
- **Loop Detection:** Signature-based (tool + position + label), counts repetitions in window
- **Recovery Tracking:** Stores last_recovery_turn to enforce cooldown (3 turns default)
- **Progress Tracking:** `get_last_progress_for_objective()` searches recent for report_progress calls

`ContextBuilder`:
- `build_history_context()`: Generates compressed history prompt
  - Mission + doctrine excerpt (400 chars max)
  - Current phase, turn, objective_id, objective_dod, objective_status
  - Recent actions (8 items) with turn, tool, target, outcome, SITREP
  - Loop detection warnings with position and repetition count
  - Stagnation detection: No progress for current objective in 10+ turns
  - Phase-specific stagnation warnings: RECONNAISSANCE >15 turns, EXECUTION >25 turns, VERIFICATION >15 turns

---

### 3. agent_system.py
**Role:** Core orchestration, LLM invocation, tool execution, main control loop

**Debug Infrastructure:**
- `DEBUG_PROMPTS`: Controlled by env var `AGENT_DEBUG_PROMPTS` (default: enabled)
- `dump_debug_json()`: Redacts base64 image payloads, dumps request/response per LM call
- `dump_debug_text()`: Saves spawned executor prompts with phase tags
- Sequential numbering per turn (_LM_CALL_SEQ) for request/response correlation

**Agent Prompts:**

`STRATEGIST_VISUAL/TEXT`:
- Output format: MISSION, INTENT, OBJECTIVES (with ID/DOD/VERIFY/LIKELY_BLOCKERS), RULES OF ENGAGEMENT, FAILURE CONTINGENCIES, HANDOFF TO FIELD COMMANDER
- Temperature: 0.3, max_tokens: 1200

`STRATEGIST_REVIEW`:
- Invoked when objective_status == BLOCKED and cooldown elapsed (6 turns)
- Reviews mission + doctrine + SITREP log
- Output: UPDATED INTENT, CURRENT/NEXT OBJECTIVE, UPDATED OBJECTIVES, UPDATED ROE, UPDATED CONTINGENCIES, DIRECTIVES

`TACTICIAN_TEMPLATE`:
- Formatted with {mission} and {doctrine}
- Critical instruction: BOTH spawn_executor_prompt AND update_phase_tools MUST be called together when changing configuration
- Enforces objective_id/objective_dod/objective_status tracking
- Allows Executor respawn without phase change (same macro phase, new objective)

`EXECUTOR_BASE`:
- Rules: ONE tool per turn, max 2x same target, report_progress at milestones and DOD satisfaction
- SITREP format: OBJ, DOD, OBS, NEXT (mandatory in assistant content)
- Coordinates: [x,y] in 0-1000 scale
- Justification length: 30-60 words

`EXECUTOR_FALLBACK`:
- Used when Tactician fails to provide prompt on turn 1
- Minimal instructions: single action, visible elements only, max 2x repetition

**AgentState:**
- **Core State:** task, screenshot/document, screen_dims, turn
- **Memory:** AgentMemory instance, ContextBuilder instance
- **Doctrine:** strategist_doctrine, tactician_prompt
- **Executor Config:** current_executor_prompt, current_phase, current_tool_names
- **Objective Tracking:** objective_id, objective_dod, objective_status
- **Control Flags:** needs_tactician (triggers immediate Tactician call), last_strategist_review_turn
- **Methods:**
  - `apply_executor_updates()`: Updates prompt/phase/tools with automatic tool floor enforcement
  - `apply_objective_update()`: Updates objective tracking, sets needs_tactician on changes
  - `get_executor_tools()`: Returns tool schemas from registry based on current_tool_names
  - `get_history_context()`: Delegates to ContextBuilder

**LLM Communication:**

`post_json()`:
- Synchronous urllib.request POST to LM Studio
- Timeout: 240 seconds (CONFIG.LMSTUDIO_TIMEOUT)
- Debug dumps before/after each call
- Returns parsed JSON response

`invoke_strategist()`:
- Mode-specific payloads (text-only vs visual)
- Visual: System prompt + user message with text + base64 image
- Text: System prompt + user message with mission + document content
- Temperature: 0.3, max_tokens: 1200

`invoke_strategist_review()`:
- Checks cooldown (6 turns since last review)
- Passes full history context + request for updated objectives with DOD/VERIFY
- Updates state.strategist_doctrine and state.tactician_prompt on success
- Returns None if cooldown not elapsed

`invoke_tactician()`:
- Passes history context + current screenshot/document + explicit task list
- Tools: TACTICIAN_TOOLS (spawn_executor_prompt, update_phase_tools)
- Temperature: 0.4, max_tokens: 800
- Parses tool calls, extracts executor_prompt, phase_name, tool_names
- **Auto-heal:** If spawn_executor_prompt called WITHOUT update_phase_tools, fills tools automatically via ensure_tools_for_phase()
- Updates state via apply_executor_updates() and apply_objective_update()

`invoke_executor()`:
- Checks state.current_executor_prompt, falls back if missing
- Dynamic tool schema: state.get_executor_tools() or defaults
- **Loop detection temperature boost:** Multiplies LMSTUDIO_TEMPERATURE by 1.5 if loop detected
- Passes history context + current screenshot/document + "EXECUTE: ONE tool call + SITREP"
- Temperature: 0.5 (0.75 if looping), max_tokens: 1024
- Returns (ToolCall, sitrep_text)

**Tool Execution:**

`execute_visual_tool()`:
- Translates Coordinate to pixels via to_pixels(sw, sh)
- Calls windows_primitives functions with timing delays
- Click variants: move_mouse + CURSOR_SETTLE + click/double_click/right_click + UI_RENDER
- Drag: move + DRAG_PREPARE + LEFTDOWN + interpolated movement + LEFTUP
- type_text: Per-character with INPUT_CHAR delay
- press_key: Validates all parts in VK_MAP before execution
- Scroll: Moves to center, settles cursor, calls scroll_action()
- report_progress: Returns formatted string, no hardware action
- Returns result string (success message or "Error: ...")

`execute_text_tool()`:
- analyze_text: Returns formatted acknowledgment
- report_progress: Same as visual mode
- No hardware interaction

**Loop Recovery:**

`loop_recovery_action()`:
- Triggered when memory.should_recover() returns True (cooldown elapsed)
- Executes: ESC key, cursor wiggle, optional Start menu click (FEATURES.LOOP_RECOVERY_CLICK_START), Ctrl+Esc
- Marks recovery in memory with turn and reason
- Skipped in TEXT_ONLY_MODE

**Main Control Loop:**

`run_agent()`:
- Iterates up to MAX_STEPS (30 default)
- Each turn:
  1. Increment turn counter
  2. Detect loop via memory.detect_loop()
  3. Capture screenshot (LOOP_IMAGE_W/H if looping, else AGENT_IMAGE_W/H) or skip if TEXT_ONLY_MODE
  4. Execute loop recovery if conditions met
  5. **Strategist Review:** If objective_status == BLOCKED and cooldown elapsed
  6. **Tactician Invocation:** If turn==1 OR turn % TACTICIAN_INTERVAL == 0 OR loop_detected OR needs_tactician
     - Auto-heal executor prompt on turn 1 if Tactician fails
     - Auto-fill tools if prompt exists but tools missing
  7. **Executor Invocation:** If current_executor_prompt exists
     - Parse tool call
     - Handle report_completion (check evidence length >= 100 chars, terminate if valid)
     - Execute tool (visual or text mode)
     - Log result with TOOL_EXECUTED or TOOL_ERROR prefix
     - **Critical Note:** TOOL_EXECUTED only confirms no Python exception; does NOT verify UI success
     - Update objective state if report_progress received
     - Add ActionRecord to memory
  8. TURN_DELAY (1.5 seconds)
- Returns completion status string

`main()`:
- Initializes DPI (if not TEXT_ONLY_MODE)
- Prompts for mission and document/screenshot input
- Invokes Strategist for initial doctrine
- Creates AgentState with memory and context builder
- Formats Tactician prompt with mission + doctrine
- Calls run_agent()
- Prints debrief with turn count, phase, archive size

---

## DATA FLOW

### Initialization Sequence
1. User provides mission text
2. System captures initial screenshot (visual) or loads document (text)
3. Strategist generates doctrine (OPORD format)
4. AgentState initialized with mission, doctrine, empty memory
5. Tactician prompt formatted with mission + doctrine

### Turn Execution Flow
```
┌─ Turn Start ─┐
│ Increment turn │
│ Detect loop    │
│ Capture screen │
│ Loop recovery? │
└────────────────┘
        ↓
┌──────────────────┐
│ Tactician Check  │ (turn 1, every 5, loop, needs_tactician, BLOCKED)
│ - spawn_executor │
│ - update_tools   │
└──────────────────┘
        ↓
┌──────────────────┐
│ Executor Call    │
│ - ONE tool       │
│ - SITREP         │
└──────────────────┘
        ↓
┌──────────────────┐
│ Tool Execution   │
│ - Hardware op    │
│ - Result capture │
└──────────────────┘
        ↓
┌──────────────────┐
│ Memory Update    │
│ - ActionRecord   │
│ - Loop detect    │
│ - Progress track │
└──────────────────┘
        ↓
    TURN_DELAY
```

### State Persistence
- **No LLM-side memory:** Each post_json() call is stateless
- **Application-layer memory:** AgentMemory maintains rolling window + optional archive
- **Context injection:** ContextBuilder generates compressed history prompt every turn
- **Objective continuity:** objective_id/objective_dod/objective_status stored in AgentState, passed to Tactician and Executor prompts

### Objective State Machine
```
UNSPECIFIED → IN_PROGRESS (Tactician spawn)
             ↓
IN_PROGRESS → DONE (Executor report_progress)
             ↓         ↘
             BLOCKED    DONE → (triggers Tactician)
                ↓
          Strategist Review → Updated Doctrine → Tactician Respawn
```

---

## CRITICAL DESIGN DECISIONS

### 1. Stateless LLM Architecture
- LM Studio /chat/completions has no conversation memory
- Every request must include full context via system + user messages
- History compression to fit token limits (1024 max tokens for Executor)
- Recent actions limited to 8 items in context

### 2. Prompt Design for Qwen3-VL 4B Limitations
- **Linguistic Unambiguity:** Instructions must have equal weight to prevent misinterpretation
- **No Instruction Repetition:** Repeated phrases signal false importance to small models
- **Explicit Output Formats:** Strategist uses numbered sections, Executor uses SITREP structure
- **Tool Call Forcing:** tool_choice: "auto" with explicit "EXECUTE: ONE tool call" instruction
- **Justification Length Caps:** 30-60 words to prevent rambling

### 3. Hierarchical Tool Access Control
- Tactician has 2 tools (configuration only, no hardware access)
- Executor has phase-dependent tools (reconnaissance subset < execution full set)
- MIN_TOOLS_BY_PHASE enforces safety floor (always includes report_progress)
- report_completion ONLY in VERIFICATION phase tools

### 4. Loop Prevention Multi-Layer Strategy
- **Signature-based detection:** (tool, position, label) tuple matching in 5-action window
- **Threshold-based triggering:** 3 repetitions in window triggers loop flag
- **Temperature boost:** 1.5x multiplier when looping to increase response variance
- **Hardware recovery:** ESC key, cursor wiggle, optional Start menu click
- **Recovery cooldown:** 3 turns between recovery attempts
- **Reduced image resolution:** 512x288 when looping to reduce processing time
- **Context injection:** Loop warnings inserted in history prompt

### 5. Objective vs Phase Separation
- **Macro Phase:** RECONNAISSANCE/EXECUTION/VERIFICATION (UI state category)
- **Objective:** Granular goal within phase (e.g., "open_notepad", "type_document", "verify_saved")
- Phases can remain constant while objectives change
- Tactician can respawn Executor prompt for new objective WITHOUT phase change

### 6. Progress Reporting as Control Signal
- report_progress is non-terminal (continues execution)
- Carries objective_id, status (IN_PROGRESS/DONE/BLOCKED), evidence
- DONE status triggers needs_tactician flag (objective completion)
- BLOCKED status triggers Strategist Review (doctrine update)
- Lack of progress report for 10 turns triggers stagnation warning in context

### 7. Completion vs Progress Distinction
- report_completion is TERMINAL (ends run_agent loop)
- Only available in VERIFICATION phase tools
- Requires evidence length >= 100 chars (enforced in agent_system.py)
- Used when OVERALL MISSION INTENT is satisfied (not just current objective)

### 8. Auto-Healing Mechanisms
- **Turn 1 Fallback:** If Tactician provides no prompt, use EXECUTOR_FALLBACK + defaults
- **Tool Floor Enforcement:** apply_tool_floor() adds MIN_TOOLS_BY_PHASE to requested tools
- **Tool Auto-Fill:** If spawn_executor_prompt called without update_phase_tools, fills via ensure_tools_for_phase()
- **Empty Tool List Handling:** ensure_tools_for_phase() returns defaults if tool_names is None or []

### 9. Timing Strategy
- **Empirical Delays:** All TIMING values are Windows 11 125% scaling specific
- **UI_RENDER:** 1.5 seconds after actions to allow UI repaints
- **CURSOR_SETTLE:** 0.12 seconds before clicks to stabilize position
- **DRAG_STEP:** 0.01 seconds per interpolation step (20 steps total)
- **TURN_DELAY:** 1.5 seconds between turns to allow state changes to complete

### 10. Screenshot Resolution Strategy
- **Agent Operations:** 1536x864 (high detail for Executor decisions)
- **Loop Recovery:** 512x288 (low detail, faster processing, nudge toward different interpretation)
- **Scaling:** HALFTONE stretching mode for quality preservation

---

## DEPENDENCIES

### External Libraries
- **ctypes:** Windows API bindings (user32.dll, gdi32.dll)
- **struct:** Binary data packing for PNG encoding
- **zlib:** PNG IDAT chunk compression
- **json:** LM Studio API communication, debug dumps
- **urllib.request:** Synchronous HTTP POST (no external HTTP library)
- **base64:** Screenshot encoding for multimodal API
- **time:** Delay enforcement, operation pacing
- **os, sys:** File I/O, environment variables, process control

### No External Dependencies
- No PIL/Pillow (custom PNG encoding)
- No requests library (uses urllib.request)
- No numpy (raw ctypes buffer manipulation)
- No OpenCV (GDI32 screen capture)

---

## OPERATIONAL CONSTRAINTS

### Model Limitations (Qwen3-VL 4B)
- Small model requires unambiguous instructions
- Instruction repetition causes false importance weighting
- Temperature boost (1.5x) during loops to increase variance
- Context window limits require aggressive history compression
- Vision capabilities rely on LM Studio multimodal endpoint

### Hardware Constraints
- Windows 11 specific (Win32 API)
- Single display support (primary monitor only)
- 125% DPI scaling assumption in timing values
- Keyboard layout assumes US English (VK_MAP)

### Safety Mechanisms
- MAX_STEPS hard limit (30 turns default)
- Loop detection with hardware recovery
- Progress reporting stagnation detection
- Phase-specific stagnation warnings
- Objective regression prevention (Tactician responsibility)

### Known Limitations
1. **TOOL_EXECUTED does not confirm UI success** - only confirms Python execution without exception
2. **No OCR or element detection** - relies on LLM vision interpretation
3. **No window focus management** - assumes correct window is active
4. **No clipboard validation** - type_text/press_key success is unverified
5. **Timing values are hardware-specific** - may fail on slower systems
6. **Screenshot compression is lossy** - HALFTONE stretching + JPEG artifacts from LM Studio
7. **Coordinate precision loss** - 0-1000 scale rounds to nearest pixel

---

## DEBUG AND OBSERVABILITY

### Debug Output
- Environment variable: `AGENT_DEBUG_PROMPTS=1` (default enabled)
- Output directory: `dumps/prompt_dumps/`
- File naming: `turn_NNNN_{tag}.json` or `turn_NNNN_{tag}.txt`
- Request/response pairs: Numbered with _LM_CALL_SEQ (lmstudio_request_NNNN, lmstudio_response_NNNN)
- Spawned prompts: `spawned_executor_prompt_{phase}.txt`
- Base64 redaction: Image payloads replaced with `<base64_png len=NNNNN>`

### Screenshot Archive
- Directory: `dumps/` (CONFIG.DUMP_DIR)
- Naming: `screen_NNNN.png` (turn-indexed)
- Initial recon: `screen_0000.png`
- Full archive: Enabled via FEATURES.ENABLE_FULL_ARCHIVE

### Console Output
- Turn headers: 70-char separator, turn/phase/objective/status
- Tactician actions: "[TACTICIAN] Oversight...", tool call results
- Executor actions: "[EXECUTOR] Action...", tool name, result
- TOOL_EXECUTED vs TOOL_ERROR prefixes
- Loop detection: "Loop recovery executed"
- Stagnation warnings: Injected in context, visible in debug dumps

---

## CONFIGURATION SURFACE

### SystemConfig (windows_primitives.py)
- LMSTUDIO_ENDPOINT, LMSTUDIO_MODEL, LMSTUDIO_TIMEOUT
- LMSTUDIO_TEMPERATURE (0.5), LMSTUDIO_MAX_TOKENS (1024)
- AGENT_IMAGE_W/H (1536x864), LOOP_IMAGE_W/H (512x288)
- DUMP_DIR, DUMP_PREFIX, MAX_STEPS (30)
- TEXT_ONLY_MODE (False), TEXT_INPUT_PATH

### Timing (windows_primitives.py)
- STARTUP_DELAY (5.0), CURSOR_SETTLE (0.12), UI_RENDER (1.5)
- INPUT_CHAR (0.005), CLICK_DOUBLE (0.05), DRAG_STEP (0.01), DRAG_PREPARE (0.1)
- TURN_DELAY (1.5)

### Features (windows_primitives.py)
- ENABLE_LOOP_RECOVERY (True), ENABLE_ACTIVE_LOOP_PREVENTION (True)
- ENABLE_FULL_ARCHIVE (True)
- LOOP_RECOVERY_COOLDOWN_TURNS (3), LOOP_RECOVERY_CLICK_START (True)
- LOOP_DETECTION_THRESHOLD (3)

### MemoryConfig (memory_and_tools.py)
- max_recent_items (10), max_context_items (8)
- loop_detection_window (5), loop_detection_threshold (3)
- enable_full_archive (True), enable_loop_detection (True)

### Agent Constants (agent_system.py)
- TACTICIAN_INTERVAL (5), STRATEGIST_REVIEW_COOLDOWN (6)

---

## CONCLUSION

This system implements a hierarchical AI agent architecture for desktop automation, designed to compensate for small model limitations through prompt engineering, memory management, and multi-layer safety mechanisms. The three-tier structure (Strategist/Tactician/Executor) provides separation of concerns: strategic planning, tactical oversight, and operational execution. Critical design decisions prioritize robustness (loop prevention, stagnation detection, auto-healing) over performance, with extensive debug instrumentation for prompt analysis and behavior auditing. The dual-mode capability (visual/text) demonstrates architectural flexibility, though the system is fundamentally designed for Windows desktop automation via low-level API primitives.