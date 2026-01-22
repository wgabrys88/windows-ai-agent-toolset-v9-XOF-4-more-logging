"""
File: agent_system.py
Three-body hierarchy agent system with dual-mode operation.
Supports visual automation and text-only analysis.
"""

import base64
import json
import os
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from windows_primitives import (
    CONFIG, TIMING, FEATURES, VK_MAP, Coordinate, TextDocument,
    init_dpi, get_screen_size, capture_png, move_mouse, click, double_click,
    right_click, drag, scroll_action, type_text, press_key, load_text_document
)

# -----------------------------------------------------------------------------
# Debug logging (prompts/tool calls)
# Enable by setting environment variable AGENT_DEBUG_PROMPTS=1
# -----------------------------------------------------------------------------
DEBUG_PROMPTS = os.getenv("AGENT_DEBUG_PROMPTS", "1").strip().lower() in ("1", "true", "yes", "on")
PROMPT_DUMP_DIR = os.path.join(CONFIG.DUMP_DIR, "prompt_dumps")

class _TurnHolder:
    value: int = 0
_POST_JSON_TURN = _TurnHolder()
_LM_CALL_SEQ = 0  # increments for every LM Studio request/response dump

def _redact_lmstudio_payload(obj: Any) -> Any:
    """Redact base64 image payloads to keep logs readable."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k == "url" and isinstance(v, str) and v.startswith("data:image/png;base64,"):
                b64 = v.split(",", 1)[1]
                out[k] = f"<base64_png len={len(b64)}>"
            else:
                out[k] = _redact_lmstudio_payload(v)
        return out
    if isinstance(obj, list):
        return [_redact_lmstudio_payload(x) for x in obj]
    return obj

def dump_debug_json(turn: int, tag: str, payload: Dict[str, Any]) -> None:
    if not DEBUG_PROMPTS:
        return
    os.makedirs(PROMPT_DUMP_DIR, exist_ok=True)
    safe = _redact_lmstudio_payload(payload)
    fname = f"turn_{turn:04d}_{tag}.json"
    fpath = os.path.join(PROMPT_DUMP_DIR, fname)
    try:
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(safe, f, ensure_ascii=False, indent=2)
        print(f"[DEBUG] dumped {tag} to {fpath}")
    except Exception as e:
        print(f"[DEBUG] dump failed ({tag}): {e}")

def dump_debug_text(turn: int, tag: str, text: str) -> None:
    if not DEBUG_PROMPTS:
        return
    os.makedirs(PROMPT_DUMP_DIR, exist_ok=True)
    fname = f"turn_{turn:04d}_{tag}.txt"
    fpath = os.path.join(PROMPT_DUMP_DIR, fname)
    try:
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(text or "")
        print(f"[DEBUG] dumped {tag} to {fpath}")
    except Exception as e:
        print(f"[DEBUG] dump failed ({tag}): {e}")

from memory_and_tools import (
    ToolCall, ClickArgs, DragArgs, TypeTextArgs, PressKeyArgs, ScrollArgs,
    ReportCompletionArgs, ReportProgressArgs, SpawnExecutorArgs, UpdatePhaseToolsArgs, TextAnalysisArgs,
    TACTICIAN_TOOLS, VISUAL_TOOLS, TEXT_TOOLS, VISUAL_TOOL_REGISTRY, TEXT_TOOL_REGISTRY,
    AgentMemory, MemoryConfig, ActionRecord, ContextBuilder,
    normalize_phase, apply_tool_floor, ensure_tools_for_phase
)

TACTICIAN_INTERVAL = 5
STRATEGIST_REVIEW_COOLDOWN = 6

STRATEGIST_VISUAL = """You are Command Staff for a desktop-automation unit.

INPUT: User mission + initial screenshot.

OUTPUT FORMAT (strict):
(Think: OPORD-style doctrine: objectives + DoD + verification + contingencies.)
1) MISSION (1-2 lines)
2) INTENT (what “done” means globally)
3) OBJECTIVES (numbered list, each must include: ID, DOD, VERIFY, LIKELY_BLOCKERS)
4) RULES OF ENGAGEMENT (constraints, safety, pacing)
5) FAILURE CONTINGENCIES (if blocked / if repeated loops)
6) HANDOFF TO FIELD COMMANDER (how to pick current objective)

Keep it concise. Use plain text. No JSON."""

STRATEGIST_TEXT = """You are Command Staff for a document-analysis unit.

INPUT: User mission + document content.

OUTPUT FORMAT (strict):
1) MISSION (1-2 lines)
2) INTENT (what “done” means globally)
3) OBJECTIVES (numbered list, each must include: ID, DOD, VERIFY, LIKELY_BLOCKERS)
4) RULES OF ENGAGEMENT (constraints, pacing)
5) FAILURE CONTINGENCIES (if blocked / if repeated loops)
6) HANDOFF TO FIELD COMMANDER (how to pick current objective)

Keep it concise. Use plain text. No JSON."""

STRATEGIST_REVIEW = """You are Command Staff reviewing an ongoing operation.

INPUT: Mission + current doctrine + field SITREP log + current objective.

TASK:
- Identify stall causes or objective regression causes.
- Issue updated doctrine: priorities, objective sequence, definition-of-done, verification rubrics, and contingencies.
- Keep it concise. Plain text.

OUTPUT FORMAT (strict):
1) UPDATED INTENT
2) CURRENT OBJECTIVE + NEXT OBJECTIVE (IDs)
3) UPDATED OBJECTIVES (only changes, each: ID, DOD, VERIFY, BLOCKERS)
4) UPDATED RULES OF ENGAGEMENT
5) UPDATED CONTINGENCIES
6) DIRECTIVES TO FIELD COMMANDER"""

TACTICIAN_TEMPLATE = """You are Field Commander. You supervise an Operator (Executor).

MISSION:
{mission}

STRATEGIC DOCTRINE:
{doctrine}

ROLE:
- Maintain an explicit CURRENT OBJECTIVE (objective_id, definition-of-done, status).
- Macro phase is only one of: RECONNAISSANCE / EXECUTION / VERIFICATION.
- Select the current objective and produce a tight Operator Order (Executor prompt) that includes:
  * objective_id
  * objective_dod (definition-of-done and any verification rubric)
  * objective_status (IN_PROGRESS/DONE/BLOCKED)
  * constraints and required progress reporting
- Re-spawn the executor prompt whenever objective, constraints, or approach changes (macro phase may stay the same).

TOOLS:
1) spawn_executor_prompt - Create/update Executor system prompt.
2) update_phase_tools - Define tool subset.

CRITICAL:
- When you change Executor configuration, always output BOTH tools in the same response.
- You MAY respawn Executor prompt even if macro phase did not change.
- Prevent regression: do not re-run completed objectives unless explicitly required by doctrine.
- Enforce progress reporting: Operator must call report_progress at milestones and when DOD is met or blocked.
"""

EXECUTOR_BASE = """You are an Operator executing one action at a time.

RULES:
- ONE tool call per turn.
- Do not repeat the same click target more than 2 times. If blocked, change approach or escalate with report_progress(status=BLOCKED).
- After each milestone (opened app / created file / saved file / reached website / dialog opened / etc), call report_progress with evidence.
- When DOD satisfied, call report_progress(status=DONE) immediately. Do not keep “improving” unless ordered.
- Justification for UI actions: 30-60 words. (report_progress evidence can be shorter but must be concrete.)

SITREP (MUST be in assistant text content EVERY TURN, alongside the tool call):
OBJ: <objective_id or 'UNSPECIFIED'>
DOD: <definition-of-done or 'UNSPECIFIED'>
OBS: <what you see changed / key UI state>
NEXT: <why the chosen tool advances OBJ>

COORDINATES (visual mode):
- [x,y] in 0-1000 scale
- (0,0) top-left, (1000,1000) bottom-right
"""

EXECUTOR_FALLBACK = """Execute ONE action per turn based on phase goals.

CRITICAL:
- Single action only
- Only interact with visible elements
- Do not repeat same action more than 2 times
- Use report_progress to mark milestones, DONE, or BLOCKED
"""

@dataclass
class AgentState:
    task: str
    screenshot: Optional[bytes] = None
    document: Optional[TextDocument] = None
    screen_dims: Tuple[int, int] = (1920, 1080)
    turn: int = 0
    
    memory: AgentMemory = field(default_factory=lambda: AgentMemory(MemoryConfig(
        max_recent_items=10, max_context_items=8, loop_detection_window=5,
        loop_detection_threshold=FEATURES.LOOP_DETECTION_THRESHOLD,
        enable_full_archive=FEATURES.ENABLE_FULL_ARCHIVE,
        enable_loop_detection=FEATURES.ENABLE_ACTIVE_LOOP_PREVENTION
    )))
    context_builder: Optional[ContextBuilder] = None
    
    strategist_doctrine: str = ""
    tactician_prompt: str = ""
    current_executor_prompt: Optional[str] = None
    current_phase: str = "INIT"
    current_tool_names: List[str] = field(default_factory=list)

    # Objective control (separate from macro phase)
    objective_id: str = ""
    objective_dod: str = ""
    objective_status: str = "IN_PROGRESS"   # IN_PROGRESS | DONE | BLOCKED
    needs_tactician: bool = False
    last_strategist_review_turn: int = -10000
    
    def __post_init__(self):
        self.context_builder = ContextBuilder(self.memory)
    
    def increment_turn(self):
        self.turn += 1
    
    def update_screenshot(self, png: bytes):
        if not CONFIG.TEXT_ONLY_MODE:
            self.screenshot = png
    
    def apply_executor_updates(self, prompt: Optional[str] = None, phase: Optional[str] = None, tool_names: Optional[List[str]] = None):
        if prompt is not None:
            self.current_executor_prompt = prompt
        if phase is not None:
            self.current_phase = normalize_phase(phase)
        if tool_names is not None:
            self.current_tool_names = apply_tool_floor(self.current_phase, tool_names, CONFIG.TEXT_ONLY_MODE)

    def apply_objective_update(self, objective_id: Optional[str] = None, objective_dod: Optional[str] = None, objective_status: Optional[str] = None):
        changed = False
        if objective_id is not None and objective_id.strip() and objective_id.strip() != self.objective_id.strip():
            self.objective_id = objective_id.strip()
            changed = True
        if objective_dod is not None and objective_dod.strip() and objective_dod.strip() != self.objective_dod.strip():
            self.objective_dod = objective_dod.strip()
            changed = True
        if objective_status is not None and objective_status.strip():
            new_status = objective_status.strip().upper()
            if new_status != self.objective_status.strip().upper():
                self.objective_status = new_status
                changed = True
        if changed:
            self.needs_tactician = True
    
    def get_executor_tools(self) -> List[Dict]:
        if not self.current_tool_names:
            return []
        registry = TEXT_TOOL_REGISTRY if CONFIG.TEXT_ONLY_MODE else VISUAL_TOOL_REGISTRY
        return [registry[name] for name in self.current_tool_names if name in registry]
    
    def get_history_context(self) -> str:
        return self.context_builder.build_history_context(
            self.task, self.strategist_doctrine, self.current_phase, self.turn,
            objective_id=self.objective_id, objective_dod=self.objective_dod, objective_status=self.objective_status
        )

def save_screenshot(png: bytes, turn: int) -> str:
    os.makedirs(CONFIG.DUMP_DIR, exist_ok=True)
    path = os.path.join(CONFIG.DUMP_DIR, f"{CONFIG.DUMP_PREFIX}{turn:04d}.png")
    with open(path, "wb") as f:
        f.write(png)
    return path

def post_json(payload: Dict[str, Any]) -> Dict[str, Any]:
    # Debug dump of request/response (redacted). Verifies actual prompts + tool schemas.
    global _LM_CALL_SEQ
    _LM_CALL_SEQ += 1
    seq = _LM_CALL_SEQ

    if DEBUG_PROMPTS:
        dump_debug_json(_POST_JSON_TURN.value, f"lmstudio_request_{seq:04d}", payload)

    data = json.dumps(payload, ensure_ascii=True).encode("utf-8")
    req = urllib.request.Request(CONFIG.LMSTUDIO_ENDPOINT, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=CONFIG.LMSTUDIO_TIMEOUT) as resp:
        parsed = json.loads(resp.read().decode("utf-8"))

    if DEBUG_PROMPTS:
        dump_debug_json(_POST_JSON_TURN.value, f"lmstudio_response_{seq:04d}", parsed)

    return parsed

def loop_recovery_action(state: AgentState) -> None:
    if not FEATURES.ENABLE_LOOP_RECOVERY or CONFIG.TEXT_ONLY_MODE:
        return
    if not state.memory.should_recover(state.turn, FEATURES.LOOP_RECOVERY_COOLDOWN_TURNS):
        return
    sw, sh = get_screen_size()
    try:
        press_key("esc")
        time.sleep(0.15)
        cx, cy = sw // 2, sh // 2
        move_mouse(cx, cy)
        time.sleep(0.05)
        move_mouse(min(cx + 12, sw - 1), cy)
        time.sleep(0.05)
        move_mouse(cx, cy)
        time.sleep(0.10)
        if FEATURES.LOOP_RECOVERY_CLICK_START:
            move_mouse(20, max(sh - 20, 0))
            time.sleep(0.05)
            click()
            time.sleep(0.15)
        press_key("ctrl+esc")
        time.sleep(TIMING.UI_RENDER)
        state.memory.mark_recovery(state.turn, "terminal_loop_detected")
        print("Loop recovery executed")
    except Exception as e:
        print(f"Loop recovery failed: {e}")

def execute_visual_tool(tool_call: ToolCall, sw: int, sh: int) -> str:
    args = tool_call.arguments
    
    if tool_call.name in ("click_element", "double_click_element", "right_click_element"):
        if not isinstance(args, ClickArgs) or not args.label:
            return "Error: label required"
        px, py = args.position.to_pixels(sw, sh)
        move_mouse(px, py)
        time.sleep(TIMING.CURSOR_SETTLE)
        if tool_call.name == "click_element":
            click()
            action_name = "Unconfirmed click performed"
        elif tool_call.name == "double_click_element":
            double_click()
            action_name = "Unconfirmed double-click performed"
        else:
            right_click()
            action_name = "Unconfirmed right-click performed"
        time.sleep(TIMING.UI_RENDER)
        return f"{action_name}: {args.label}"
    
    elif tool_call.name == "drag_element":
        if not isinstance(args, DragArgs) or not args.label:
            return "Error: label required"
        sx, sy = args.start.to_pixels(sw, sh)
        ex, ey = args.end.to_pixels(sw, sh)
        drag(sx, sy, ex, ey)
        time.sleep(TIMING.UI_RENDER)
        return f"Dragged {args.label}"
    
    elif tool_call.name == "type_text":
        if not isinstance(args, TypeTextArgs) or not args.text:
            return "Error: text required"
        type_text(args.text)
        time.sleep(TIMING.UI_RENDER)
        return f"Typed: {args.text[:50]}"
    
    elif tool_call.name == "press_key":
        if not isinstance(args, PressKeyArgs) or not args.key:
            return "Error: key required"
        key = args.key.strip().lower()
        parts = [p.strip() for p in key.split("+")]
        for part in parts:
            if part not in VK_MAP:
                return f"Error: Unknown key '{part}'"
        press_key(key)
        time.sleep(TIMING.UI_RENDER)
        return f"Pressed: {key}"
    
    elif tool_call.name in ("scroll_down", "scroll_up"):
        move_mouse(sw // 2, sh // 2)
        time.sleep(TIMING.CURSOR_SETTLE)
        scroll_action(-1 if tool_call.name == "scroll_down" else 1)
        time.sleep(TIMING.UI_RENDER)
        return "Scrolled down" if tool_call.name == "scroll_down" else "Scrolled up"

    elif tool_call.name == "report_progress":
        args = tool_call.arguments
        if not isinstance(args, ReportProgressArgs) or not args.objective_id or not args.status or not args.evidence:
            return "Error: objective_id/status/evidence required"
        return f"Progress: {args.objective_id} -> {args.status}"
    
    return f"Error: unknown tool '{tool_call.name}'"

def execute_text_tool(tool_call: ToolCall) -> str:
    if tool_call.name == "analyze_text":
        args = tool_call.arguments
        if not isinstance(args, TextAnalysisArgs) or not args.focus_area:
            return "Error: focus_area required"
        return f"Analyzed section '{args.focus_area}'"
    elif tool_call.name == "report_progress":
        args = tool_call.arguments
        if not isinstance(args, ReportProgressArgs) or not args.objective_id or not args.status or not args.evidence:
            return "Error: objective_id/status/evidence required"
        return f"Progress: {args.objective_id} -> {args.status}"
    return f"Error: unknown text tool '{tool_call.name}'"

def invoke_strategist(task: str, screenshot: Optional[bytes] = None, document: Optional[TextDocument] = None) -> str:
    _POST_JSON_TURN.value = 0
    if CONFIG.TEXT_ONLY_MODE:
        if not document:
            return "Error: No document provided"
        payload = {
            "model": CONFIG.LMSTUDIO_MODEL,
            "messages": [
                {"role": "system", "content": STRATEGIST_TEXT},
                {"role": "user", "content": f"Mission: {task}\n\n{document.to_context_string()}"}
            ],
            "temperature": 0.3,
            "max_tokens": 1200
        }
        dump_debug_json(_POST_JSON_TURN.value, "strategist_payload", payload)
        resp = post_json(payload)
        return resp["choices"][0]["message"].get("content", "").strip()
    else:
        if not screenshot:
            return "Error: No screenshot provided"
        b64 = base64.b64encode(screenshot).decode("ascii")
        resp = post_json({
            "model": CONFIG.LMSTUDIO_MODEL,
            "messages": [
                {"role": "system", "content": STRATEGIST_VISUAL},
                {"role": "user", "content": [
                    {"type": "text", "text": f"Mission: {task}"},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
                ]}
            ],
            "temperature": 0.3,
            "max_tokens": 1200
        })
        return resp["choices"][0]["message"].get("content", "").strip()

def invoke_strategist_review(state: AgentState) -> Optional[str]:
    _POST_JSON_TURN.value = getattr(state, 'turn', 0)
    if (state.turn - state.last_strategist_review_turn) < STRATEGIST_REVIEW_COOLDOWN:
        return None
    history = state.get_history_context()
    prompt = f"{history}\n\nREQUEST: Resolve stall/regression. Provide updated objectives with DOD+VERIFY rubrics."
    payload = {
        "model": CONFIG.LMSTUDIO_MODEL,
        "messages": [
            {"role": "system", "content": STRATEGIST_REVIEW},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.3,
        "max_tokens": 900
    }
    dump_debug_json(_POST_JSON_TURN.value, "strategist_review_payload", payload)
    resp = post_json(payload)
    updated = resp["choices"][0]["message"].get("content", "").strip()
    if updated:
        state.last_strategist_review_turn = state.turn
    return updated

def invoke_tactician(state: AgentState) -> Tuple[Optional[str], Optional[str], Optional[List[str]]]:
    _POST_JSON_TURN.value = getattr(state, 'turn', 0)
    history_text = state.get_history_context()
    
    if CONFIG.TEXT_ONLY_MODE:
        doc_context = state.document.to_context_string() if state.document else ""
        prompt = (
            f"{history_text}\n\nCURRENT DOCUMENT STATE:\n{doc_context}\n\n"
            "TASK:\n"
            "1) Identify macro phase.\n"
            "2) Set CURRENT OBJECTIVE (ID + DOD + status).\n"
            "3) If update needed: output spawn_executor_prompt + update_phase_tools.\n"
            "4) Ensure Operator Order enforces report_progress at milestones and when DONE/BLOCKED.\n"
        )
        payload = {
            "model": CONFIG.LMSTUDIO_MODEL,
            "messages": [
                {"role": "system", "content": state.tactician_prompt},
                {"role": "user", "content": prompt}
            ],
            "tools": TACTICIAN_TOOLS,
            "tool_choice": "auto",
            "temperature": 0.4,
            "max_tokens": 800
        }
        dump_debug_json(_POST_JSON_TURN.value, "tactician_payload", payload)
        resp = post_json(payload)
    else:
        b64 = base64.b64encode(state.screenshot).decode("ascii")
        prompt = (
            f"{history_text}\n\nCURRENT SCREENSHOT: [below]\n\n"
            "TASK:\n"
            "1) Identify macro phase.\n"
            "2) Set CURRENT OBJECTIVE (ID + DOD + status).\n"
            "3) If update needed: output spawn_executor_prompt + update_phase_tools.\n"
            "4) Ensure Operator Order enforces report_progress at milestones and when DONE/BLOCKED.\n"
        )
        resp = post_json({
            "model": CONFIG.LMSTUDIO_MODEL,
            "messages": [
                {"role": "system", "content": state.tactician_prompt},
                {"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
                ]}
            ],
            "tools": TACTICIAN_TOOLS,
            "tool_choice": "auto",
            "temperature": 0.4,
            "max_tokens": 800
        })
    
    msg = resp["choices"][0]["message"]
    tool_calls = msg.get("tool_calls")
    
    if not tool_calls:
        print(f"Tactician: {msg.get('content', 'No updates')[:150]}")
        return (None, None, None)
    
    executor_prompt = None
    phase_name = None
    tool_names = None
    saw_spawn = False
    saw_tools = False
    
    for tc_dict in tool_calls:
        try:
            tc = ToolCall.from_api_response(tc_dict)
        except Exception as e:
            print(f"Tool parse error: {e}")
            continue
        
        if tc.name == "spawn_executor_prompt":
            spawn_args = tc.arguments
            executor_prompt = spawn_args.prompt
            phase_name = spawn_args.phase
            dump_debug_text(state.turn, f"spawned_executor_prompt_{phase_name or 'UNKNOWN'}", executor_prompt)

            saw_spawn = True
            state.apply_objective_update(
                objective_id=getattr(spawn_args, "objective_id", "") or "",
                objective_dod=getattr(spawn_args, "objective_dod", "") or "",
                objective_status=getattr(spawn_args, "objective_status", "") or ""
            )
            print(f"Executor spawned for phase: {phase_name}")
        elif tc.name == "update_phase_tools":
            tools_args = tc.arguments
            tool_names = tools_args.tool_names
            saw_tools = True
            print(f"Tools updated: {tool_names}")
    
    if saw_spawn and not saw_tools:
        healed_phase = normalize_phase(phase_name or state.current_phase)
        tool_names = ensure_tools_for_phase(healed_phase, None, CONFIG.TEXT_ONLY_MODE)
        print(f"Auto-heal: filling tools for {healed_phase}: {tool_names}")
    
    return (executor_prompt, phase_name, tool_names)

def invoke_executor(state: AgentState) -> Tuple[Optional[ToolCall], str]:
    _POST_JSON_TURN.value = getattr(state, 'turn', 0)
    if not state.current_executor_prompt:
        print("No executor prompt - waiting for tactician")
        return (None, "")
    
    executor_tools = state.get_executor_tools()
    if not executor_tools:
        print("No tools - using fallback")
        executor_tools = TEXT_TOOLS if CONFIG.TEXT_ONLY_MODE else VISUAL_TOOLS
    
    history_text = state.get_history_context()
    
    if CONFIG.TEXT_ONLY_MODE:
        doc_context = state.document.to_context_string() if state.document else ""
        prompt = f"{history_text}\n\nCURRENT DOCUMENT:\n{doc_context}\n\nEXECUTE: ONE tool call + SITREP."
        is_looping = state.memory.detect_loop()
        temperature = CONFIG.LMSTUDIO_TEMPERATURE * 1.5 if is_looping else CONFIG.LMSTUDIO_TEMPERATURE
        payload = {
            "model": CONFIG.LMSTUDIO_MODEL,
            "messages": [
                {"role": "system", "content": EXECUTOR_BASE + "\n\n" + state.current_executor_prompt},
                {"role": "user", "content": prompt}
            ],
            "tools": executor_tools,
            "tool_choice": "auto",
            "temperature": temperature,
            "max_tokens": CONFIG.LMSTUDIO_MAX_TOKENS
        }
        dump_debug_json(_POST_JSON_TURN.value, "executor_payload", payload)
        resp = post_json(payload)
    else:
        b64 = base64.b64encode(state.screenshot).decode("ascii")
        prompt = f"{history_text}\n\nCURRENT SCREENSHOT: [below]\n\nEXECUTE: ONE tool call + SITREP."
        is_looping = state.memory.detect_loop()
        temperature = CONFIG.LMSTUDIO_TEMPERATURE * 1.5 if is_looping else CONFIG.LMSTUDIO_TEMPERATURE
        resp = post_json({
            "model": CONFIG.LMSTUDIO_MODEL,
            "messages": [
                {"role": "system", "content": EXECUTOR_BASE + "\n\n" + state.current_executor_prompt},
                {"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
                ]}
            ],
            "tools": executor_tools,
            "tool_choice": "auto",
            "temperature": temperature,
            "max_tokens": CONFIG.LMSTUDIO_MAX_TOKENS
        })
    
    msg = resp["choices"][0]["message"]
    sitrep = (msg.get("content") or "").strip()
    tool_calls = msg.get("tool_calls")
    
    if not tool_calls:
        print(f"No tool calls: {sitrep[:100]}")
        return (None, sitrep)
    
    try:
        return (ToolCall.from_api_response(tool_calls[0]), sitrep)
    except Exception as e:
        print(f"Tool parse error: {e}")
        return (None, sitrep)

def run_agent(state: AgentState) -> str:
    for iteration in range(CONFIG.MAX_STEPS):
        state.increment_turn()
        
        loop_detected = state.memory.detect_loop()
        if loop_detected:
            loop_recovery_action(state)
        
        screenshot_path = ""
        sw, sh = state.screen_dims
        
        if not CONFIG.TEXT_ONLY_MODE:
            cap_w, cap_h = (CONFIG.LOOP_IMAGE_W, CONFIG.LOOP_IMAGE_H) if loop_detected else (CONFIG.AGENT_IMAGE_W, CONFIG.AGENT_IMAGE_H)
            png, sw, sh = capture_png(cap_w, cap_h)
            screenshot_path = save_screenshot(png, state.turn)
            state.update_screenshot(png)
        
        print(f"\n{'='*70}\nTURN {state.turn} | Phase: {state.current_phase} | OBJ: {state.objective_id or 'UNSPEC'} | STATUS: {state.objective_status}\n{'='*70}")
        
        if loop_detected and state.memory.last_recovery_turn == state.turn:
            state.memory.add_action(ActionRecord(
                turn=state.turn,
                tool="system_loop_recovery",
                args={"reason": state.memory.last_recovery_reason},
                justification="Automated recovery",
                result="Recovery executed",
                screenshot=screenshot_path
            ))
        
        if state.objective_status.upper() == "BLOCKED":
            updated = invoke_strategist_review(state)
            if updated:
                print("[STRATEGIST] Doctrine update applied")
                state.strategist_doctrine = updated
                state.tactician_prompt = TACTICIAN_TEMPLATE.format(mission=state.task, doctrine=state.strategist_doctrine)
                state.needs_tactician = True
        
        if state.turn == 1 or state.turn % TACTICIAN_INTERVAL == 0 or loop_detected or state.needs_tactician:
            print("[TACTICIAN] Oversight...")
            state.needs_tactician = False
            
            executor_prompt, phase_name, tool_names = invoke_tactician(state)
            
            if executor_prompt is not None:
                state.apply_executor_updates(prompt=executor_prompt)
            if phase_name is not None:
                state.apply_executor_updates(phase=phase_name)
            if tool_names is not None:
                state.apply_executor_updates(tool_names=tool_names)
            
            if state.current_executor_prompt and not state.current_tool_names:
                state.apply_executor_updates(tool_names=ensure_tools_for_phase(state.current_phase, None, CONFIG.TEXT_ONLY_MODE))
            
            if state.turn == 1 and not state.current_executor_prompt:
                print("Tactician no prompt - using fallback")
                state.apply_executor_updates(
                    prompt=EXECUTOR_FALLBACK,
                    phase="RECONNAISSANCE",
                    tool_names=ensure_tools_for_phase("RECONNAISSANCE", None, CONFIG.TEXT_ONLY_MODE)
                )
            
            time.sleep(TIMING.TURN_DELAY)
        
        if state.current_executor_prompt:
            print("[EXECUTOR] Action...")
            
            tool_call, sitrep = invoke_executor(state)
            
            if not tool_call:
                print("No action taken")
                time.sleep(TIMING.TURN_DELAY)
                continue
            
            if tool_call.name == "report_completion":
                completion_args = tool_call.arguments
                if len(completion_args.evidence.strip()) < 100:
                    print("Insufficient evidence")
                    time.sleep(TIMING.TURN_DELAY)
                    continue
                
                print(f"\n{'='*70}\nMISSION COMPLETE\n{'='*70}\nEvidence: {completion_args.evidence}\n{'='*70}\n")
                return f"Completed in {state.turn} turns"
            
            print(f"Action: {tool_call.name}")
            
            if CONFIG.TEXT_ONLY_MODE:
                result = execute_text_tool(tool_call)
            else:
                result = execute_visual_tool(tool_call, sw, sh)
            
            tool_ok = not result.startswith("Error:")
            print(f"{'TOOL_EXECUTED' if tool_ok else 'TOOL_ERROR'}: {result}")
            # NOTE: TOOL_EXECUTED only means the tool executed without raising an error.
            # It does NOT confirm the intended UI/mission outcome.

            
            justification = ""
            if hasattr(tool_call.arguments, 'justification'):
                justification = tool_call.arguments.justification
            
            if tool_call.name == "report_progress" and isinstance(tool_call.arguments, ReportProgressArgs):
                state.apply_objective_update(
                    objective_id=tool_call.arguments.objective_id,
                    objective_status=tool_call.arguments.status
                )
                st = tool_call.arguments.status.strip().upper()
                if st in ("DONE", "COMPLETED", "COMPLETE"):
                    state.objective_status = "DONE"
                    state.needs_tactician = True
                elif st == "BLOCKED":
                    state.objective_status = "BLOCKED"
                    state.needs_tactician = True
            
            state.memory.add_action(ActionRecord(
                turn=state.turn,
                tool=tool_call.name,
                args=tool_call.arguments,
                justification=justification,
                result=result,
                screenshot=screenshot_path,
                sitrep=sitrep
            ))
        else:
            print("Waiting for tactician...")
        
        time.sleep(TIMING.TURN_DELAY)
    
    return f"Max iterations reached ({CONFIG.MAX_STEPS} turns)"

def main() -> None:
    if not CONFIG.TEXT_ONLY_MODE:
        init_dpi()
    
    mode = "TEXT-ONLY" if CONFIG.TEXT_ONLY_MODE else "VISUAL"
    print(f"\n{'='*70}\nTHREE-BODY HIERARCHY AGENT - {mode} MODE\n{'='*70}")
    print(f"Max Steps: {CONFIG.MAX_STEPS}")
    print(f"Tactician Interval: {TACTICIAN_INTERVAL}\n{'='*70}\n")
    
    task = input("Mission: ").strip()
    if not task:
        sys.exit("Error: Mission required")
    
    if CONFIG.TEXT_ONLY_MODE:
        doc_path = input(f"Document path [{CONFIG.TEXT_INPUT_PATH}]: ").strip() or CONFIG.TEXT_INPUT_PATH
        document = load_text_document(doc_path)
        print(f"Loaded: {document.path}\n")
        
        print(f"{'='*70}\nPHASE 0: STRATEGIC COMMAND\n{'='*70}\n")
        doctrine = invoke_strategist(task, document=document)
        print(f"Doctrine:\n{doctrine}\n")
        
        state = AgentState(task=task, document=document)
    else:
        time.sleep(TIMING.STARTUP_DELAY)
        png, sw, sh = capture_png(CONFIG.AGENT_IMAGE_W, CONFIG.AGENT_IMAGE_H)
        path = save_screenshot(png, 0)
        print(f"Initial recon: {path}\n")
        
        print(f"{'='*70}\nPHASE 0: STRATEGIC COMMAND\n{'='*70}\n")
        doctrine = invoke_strategist(task, screenshot=png)
        print(f"Doctrine:\n{doctrine}\n")
        
        state = AgentState(task=task, screenshot=png, screen_dims=(sw, sh))
    
    state.strategist_doctrine = doctrine
    state.tactician_prompt = TACTICIAN_TEMPLATE.format(mission=task, doctrine=doctrine)
    
    print(f"{'='*70}\nPHASE 1: FIELD OPERATIONS\n{'='*70}\n")
    result = run_agent(state)
    print(f"\n{'='*70}\nMISSION DEBRIEF\n{'='*70}\nStatus: {result}\nTurns: {state.turn}\nPhase: {state.current_phase}")
    if state.memory.archive:
        print(f"Archive: {len(state.memory.archive)} actions")
    print(f"{'='*70}\n")

if __name__ == "__main__":
    main()
