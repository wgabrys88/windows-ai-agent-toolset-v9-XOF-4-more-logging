"""
File: memory_and_tools.py
Memory subsystem, tool definitions, and context generation.
Centralized state management and type-safe tool handling.
"""

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union

from windows_primitives import Coordinate, FEATURES

@dataclass
class ClickArgs:
    justification: str
    label: str
    position: Coordinate
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ClickArgs':
        pos = data.get("position", [0, 0])
        return cls(
            justification=data.get("justification", ""),
            label=data.get("label", ""),
            position=Coordinate(float(pos[0]), float(pos[1]))
        )

@dataclass
class DragArgs:
    justification: str
    label: str
    start: Coordinate
    end: Coordinate
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DragArgs':
        start = data.get("start", [0, 0])
        end = data.get("end", [0, 0])
        return cls(
            justification=data.get("justification", ""),
            label=data.get("label", ""),
            start=Coordinate(float(start[0]), float(start[1])),
            end=Coordinate(float(end[0]), float(end[1]))
        )

@dataclass
class TypeTextArgs:
    justification: str
    text: str
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TypeTextArgs':
        return cls(justification=data.get("justification", ""), text=data.get("text", ""))

@dataclass
class PressKeyArgs:
    justification: str
    key: str
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PressKeyArgs':
        return cls(justification=data.get("justification", ""), key=data.get("key", ""))

@dataclass
class ScrollArgs:
    justification: str
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ScrollArgs':
        return cls(justification=data.get("justification", ""))

@dataclass
class ReportCompletionArgs:
    evidence: str
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ReportCompletionArgs':
        return cls(evidence=data.get("evidence", ""))

@dataclass
class ReportProgressArgs:
    objective_id: str
    status: str
    evidence: str
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ReportProgressArgs':
        return cls(
            objective_id=data.get("objective_id", ""),
            status=data.get("status", ""),
            evidence=data.get("evidence", "")
        )

@dataclass
class SpawnExecutorArgs:
    prompt: str
    phase: str
    rationale: str
    objective_id: str = ""
    objective_dod: str = ""
    objective_status: str = ""
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SpawnExecutorArgs':
        return cls(
            prompt=data.get("prompt", ""),
            phase=data.get("phase", ""),
            rationale=data.get("rationale", ""),
            objective_id=data.get("objective_id", "") or "",
            objective_dod=data.get("objective_dod", "") or "",
            objective_status=data.get("objective_status", "") or ""
        )

@dataclass
class UpdatePhaseToolsArgs:
    tool_names: List[str]
    rationale: str
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'UpdatePhaseToolsArgs':
        return cls(tool_names=data.get("tool_names", []), rationale=data.get("rationale", ""))

@dataclass
class TextAnalysisArgs:
    justification: str
    focus_area: str
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TextAnalysisArgs':
        return cls(justification=data.get("justification", ""), focus_area=data.get("focus_area", ""))

@dataclass
class ToolCall:
    name: str
    arguments: Any
    
    @classmethod
    def from_api_response(cls, tool_call_dict: Dict[str, Any]) -> 'ToolCall':
        name = tool_call_dict["function"]["name"]
        raw_args = tool_call_dict["function"].get("arguments")
        if isinstance(raw_args, str):
            args_dict = json.loads(raw_args) if raw_args.strip() else {}
        elif isinstance(raw_args, dict):
            args_dict = raw_args
        else:
            args_dict = {}
        
        arg_map = {
            "click_element": ClickArgs, "double_click_element": ClickArgs, "right_click_element": ClickArgs,
            "drag_element": DragArgs, "type_text": TypeTextArgs, "press_key": PressKeyArgs,
            "scroll_down": ScrollArgs, "scroll_up": ScrollArgs, "report_completion": ReportCompletionArgs,
            "report_progress": ReportProgressArgs,
            "spawn_executor_prompt": SpawnExecutorArgs, "update_phase_tools": UpdatePhaseToolsArgs,
            "analyze_text": TextAnalysisArgs,
        }
        
        arg_class = arg_map.get(name)
        if not arg_class:
            raise ValueError(f"Unknown tool: {name}")
        
        return cls(name=name, arguments=arg_class.from_dict(args_dict))

JUSTIFICATION_DESC = "Brief reasoning (30-60 words): what you see, why this action, expected outcome"

TACTICIAN_TOOLS = [
    {"type": "function", "function": {"name": "spawn_executor_prompt", "description": "Create/update Executor system prompt",
     "parameters": {"type": "object", "properties": {
         "prompt": {"type": "string"}, "phase": {"type": "string"}, "rationale": {"type": "string"},
         "objective_id": {"type": "string"}, "objective_dod": {"type": "string"}, "objective_status": {"type": "string"}},
         "required": ["prompt", "phase", "rationale"]}}},

    {"type": "function", "function": {"name": "update_phase_tools", "description": "Define tool subset for Executor",
     "parameters": {"type": "object", "properties": {
         "tool_names": {"type": "array", "items": {"type": "string"}}, "rationale": {"type": "string"}},
         "required": ["tool_names", "rationale"]}}}
]

VISUAL_TOOLS = [
    {"type": "function", "function": {"name": "report_completion", "description": "Report task completion (terminal)",
     "parameters": {"type": "object", "properties": {"evidence": {"type": "string"}}, "required": ["evidence"]}}},

    {"type": "function", "function": {"name": "report_progress", "description": "Report objective progress/state (non-terminal)",
     "parameters": {"type": "object", "properties": {
         "objective_id": {"type": "string"}, "status": {"type": "string"}, "evidence": {"type": "string"}}, 
         "required": ["objective_id", "status", "evidence"]}}},

    {"type": "function", "function": {"name": "click_element", "description": "Click UI element",
     "parameters": {"type": "object", "properties": {
         "justification": {"type": "string"}, "label": {"type": "string"},
         "position": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2}},
         "required": ["justification", "label", "position"]}}},

    {"type": "function", "function": {"name": "double_click_element", "description": "Double-click element",
     "parameters": {"type": "object", "properties": {
         "justification": {"type": "string"}, "label": {"type": "string"},
         "position": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2}},
         "required": ["justification", "label", "position"]}}},

    {"type": "function", "function": {"name": "right_click_element", "description": "Right-click element",
     "parameters": {"type": "object", "properties": {
         "justification": {"type": "string"}, "label": {"type": "string"},
         "position": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2}},
         "required": ["justification", "label", "position"]}}},

    {"type": "function", "function": {"name": "drag_element", "description": "Drag from start to end",
     "parameters": {"type": "object", "properties": {
         "justification": {"type": "string"}, "label": {"type": "string"},
         "start": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2},
         "end": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2}},
         "required": ["justification", "label", "start", "end"]}}},

    {"type": "function", "function": {"name": "type_text", "description": "Type text",
     "parameters": {"type": "object", "properties": {
         "justification": {"type": "string"}, "text": {"type": "string"}},
         "required": ["justification", "text"]}}},

    {"type": "function", "function": {"name": "press_key", "description": "Press key or combo",
     "parameters": {"type": "object", "properties": {
         "justification": {"type": "string"}, "key": {"type": "string"}},
         "required": ["justification", "key"]}}},

    {"type": "function", "function": {"name": "scroll_down", "description": "Scroll downward",
     "parameters": {"type": "object", "properties": {"justification": {"type": "string"}}, "required": ["justification"]}}},

    {"type": "function", "function": {"name": "scroll_up", "description": "Scroll upward",
     "parameters": {"type": "object", "properties": {"justification": {"type": "string"}}, "required": ["justification"]}}}
]

TEXT_TOOLS = [
    {"type": "function", "function": {"name": "report_completion", "description": "Report analysis completion (terminal)",
     "parameters": {"type": "object", "properties": {"evidence": {"type": "string"}}, "required": ["evidence"]}}},

    {"type": "function", "function": {"name": "report_progress", "description": "Report objective progress/state (non-terminal)",
     "parameters": {"type": "object", "properties": {
         "objective_id": {"type": "string"}, "status": {"type": "string"}, "evidence": {"type": "string"}}, 
         "required": ["objective_id", "status", "evidence"]}}},

    {"type": "function", "function": {"name": "analyze_text", "description": "Analyze document section",
     "parameters": {"type": "object", "properties": {
         "justification": {"type": "string"}, "focus_area": {"type": "string"}},
         "required": ["justification", "focus_area"]}}}
]

VISUAL_TOOL_REGISTRY = {tool["function"]["name"]: tool for tool in VISUAL_TOOLS}
TEXT_TOOL_REGISTRY = {tool["function"]["name"]: tool for tool in TEXT_TOOLS}

DEFAULT_TOOLS_BY_PHASE_VISUAL = {
    "RECONNAISSANCE": ["report_progress", "click_element", "double_click_element", "press_key", "type_text", "scroll_down", "scroll_up"],
    "EXECUTION": ["report_progress", "click_element", "double_click_element", "right_click_element", "drag_element", "press_key", "type_text", "scroll_down", "scroll_up"],
    "VERIFICATION": ["report_progress", "click_element", "double_click_element", "right_click_element", "drag_element", "press_key", "type_text", "scroll_down", "scroll_up", "report_completion"],
}

MIN_TOOLS_BY_PHASE_VISUAL = {
    "RECONNAISSANCE": ["report_progress", "click_element", "double_click_element", "press_key", "type_text"],
    "EXECUTION": ["report_progress", "click_element", "double_click_element", "press_key", "type_text", "drag_element"],
    "VERIFICATION": ["report_progress", "click_element", "double_click_element", "press_key", "type_text", "drag_element", "report_completion"],
}

DEFAULT_TOOLS_BY_PHASE_TEXT = {
    "RECONNAISSANCE": ["report_progress", "analyze_text"],
    "EXECUTION": ["report_progress", "analyze_text"],
    "VERIFICATION": ["report_progress", "analyze_text", "report_completion"],
}

MIN_TOOLS_BY_PHASE_TEXT = {
    "RECONNAISSANCE": ["report_progress", "analyze_text"],
    "EXECUTION": ["report_progress", "analyze_text"],
    "VERIFICATION": ["report_progress", "analyze_text", "report_completion"],
}

def normalize_phase(phase: Optional[str]) -> str:
    p = (phase or "").strip().upper()
    if p.startswith("EXECUTION"):
        return "EXECUTION"
    if p.startswith("RECON"):
        return "RECONNAISSANCE"
    if p.startswith("VERIFY") or p.startswith("VERIFICATION"):
        return "VERIFICATION"
    return p or "EXECUTION"

def apply_tool_floor(phase: str, tool_names: List[str], is_text_mode: bool) -> List[str]:
    phase = normalize_phase(phase)
    floor_map = MIN_TOOLS_BY_PHASE_TEXT if is_text_mode else MIN_TOOLS_BY_PHASE_VISUAL
    floor = floor_map.get(phase, floor_map["EXECUTION"])
    return sorted(set(tool_names) | set(floor))

def ensure_tools_for_phase(phase: str, tool_names: Optional[List[str]], is_text_mode: bool) -> List[str]:
    phase = normalize_phase(phase)
    defaults_map = DEFAULT_TOOLS_BY_PHASE_TEXT if is_text_mode else DEFAULT_TOOLS_BY_PHASE_VISUAL
    if tool_names is None or len(tool_names) == 0:
        return defaults_map.get(phase, defaults_map["EXECUTION"])
    return tool_names

@dataclass
class ActionRecord:
    turn: int
    tool: str
    args: Any
    justification: str
    result: str
    screenshot: str = ""
    sitrep: str = ""
    
    def get_target_label(self) -> str:
        if isinstance(self.args, (ClickArgs, DragArgs)):
            return self.args.label[:30]
        elif isinstance(self.args, TypeTextArgs):
            return self.args.text[:30]
        elif isinstance(self.args, PressKeyArgs):
            return self.args.key[:30]
        elif isinstance(self.args, TextAnalysisArgs):
            return self.args.focus_area[:30]
        elif isinstance(self.args, ReportProgressArgs):
            return f"{self.args.objective_id}:{self.args.status}"[:30]
        return ""
    
    def get_position_signature(self) -> Optional[Tuple[float, float]]:
        if isinstance(self.args, ClickArgs):
            return self.args.position.signature()
        return None
    
    def get_action_signature(self) -> Tuple[str, Optional[Tuple[float, float]], str]:
        return (self.tool, self.get_position_signature(), self.get_target_label())

@dataclass
class MemoryConfig:
    max_recent_items: int = 10
    max_context_items: int = 8
    loop_detection_window: int = 5
    loop_detection_threshold: int = 3
    enable_full_archive: bool = True
    enable_loop_detection: bool = True

class AgentMemory:
    def __init__(self, config: MemoryConfig):
        self.config = config
        self.recent: List[ActionRecord] = []
        self.archive: Optional[List[ActionRecord]] = [] if config.enable_full_archive else None
        self.last_recovery_turn: int = -10000
        self.last_recovery_reason: str = ""
    
    def add_action(self, record: ActionRecord) -> None:
        self.recent.append(record)
        if self.archive is not None:
            self.archive.append(record)
        if len(self.recent) > self.config.max_recent_items:
            self.recent = self.recent[-self.config.max_recent_items:]
    
    def get_recent_actions(self, count: Optional[int] = None) -> List[ActionRecord]:
        if count is None:
            count = self.config.max_context_items
        return self.recent[-count:]
    
    def detect_loop(self) -> bool:
        if not self.config.enable_loop_detection or len(self.recent) < self.config.loop_detection_threshold:
            return False
        window = self.recent[-self.config.loop_detection_window:]
        if len(window) < self.config.loop_detection_threshold:
            return False
        last = window[-1]
        last_sig = last.get_action_signature()
        matches = sum(1 for action in window if action.get_action_signature() == last_sig)
        return matches >= self.config.loop_detection_threshold
    
    def get_loop_details(self) -> Optional[Dict[str, Any]]:
        if not self.detect_loop():
            return None
        window = self.recent[-self.config.loop_detection_window:]
        last = window[-1]
        last_sig = last.get_action_signature()
        matches = sum(1 for action in window if action.get_action_signature() == last_sig)
        return {"tool": last.tool, "label": last.get_target_label(), "position": last.get_position_signature(), "repetitions": matches}
    
    def mark_recovery(self, turn: int, reason: str) -> None:
        self.last_recovery_turn = turn
        self.last_recovery_reason = reason
    
    def should_recover(self, current_turn: int, cooldown_turns: int) -> bool:
        return (current_turn - self.last_recovery_turn) > cooldown_turns
    
    def get_last_progress_for_objective(self, objective_id: str) -> Optional[ActionRecord]:
        if not objective_id:
            return None
        for rec in reversed(self.recent):
            if rec.tool == "report_progress" and isinstance(rec.args, ReportProgressArgs):
                if rec.args.objective_id.strip() == objective_id.strip():
                    return rec
        return None

class ContextBuilder:
    def __init__(self, memory: AgentMemory):
        self.memory = memory
    
    def build_history_context(self, task: str, doctrine: str, current_phase: str, current_turn: int,
                              objective_id: str = "", objective_dod: str = "", objective_status: str = "") -> str:
        lines = [f"MISSION: {task}\n"]
        if doctrine:
            excerpt = doctrine[:400] + "..." if len(doctrine) > 400 else doctrine
            lines.append(f"DOCTRINE:\n{excerpt}\n")
        lines.append(f"CURRENT PHASE: {current_phase}\n")
        lines.append(f"TURN: {current_turn}\n")
        
        if objective_id:
            lines.append(f"CURRENT OBJECTIVE: {objective_id}\n")
            if objective_status:
                lines.append(f"OBJECTIVE STATUS: {objective_status}\n")
            if objective_dod:
                dod = objective_dod.strip().replace("\n", " ")
                lines.append(f"DEFINITION OF DONE: {dod[:220]}\n")
        
        stagnation = self._get_stagnation_warning(current_phase, current_turn, objective_id)
        if stagnation:
            lines.append(stagnation)
        
        history = self.memory.get_recent_actions()
        if history:
            lines.append("RECENT ACTIONS:")
            for h in history:
                target = h.get_target_label()
                outcome = h.result[:60]
                lines.append(f"  T{h.turn}: {h.tool}({target}) -> {outcome}")
                if h.sitrep:
                    sit = h.sitrep.strip().replace("\n", " ")
                    lines.append(f"        SITREP: {sit[:160]}")
        
        loop_details = self.memory.get_loop_details()
        if loop_details:
            pos_str = str(loop_details["position"]) if loop_details["position"] else "N/A"
            lines.append(f"\nLOOP DETECTED: {loop_details['tool']} on '{loop_details['label']}' @ {pos_str} repeated {loop_details['repetitions']}x - CHANGE APPROACH IMMEDIATELY\n")
        
        if objective_id:
            last_prog = self.memory.get_last_progress_for_objective(objective_id)
            if last_prog is None:
                if current_turn >= 12:
                    lines.append("\nOBJECTIVE STAGNATION: No progress reports for current objective. Use report_progress or change approach.\n")
            else:
                turns_since = current_turn - last_prog.turn
                if turns_since >= 10 and (not isinstance(last_prog.args, ReportProgressArgs) or last_prog.args.status.upper() != "DONE"):
                    lines.append(f"\nOBJECTIVE STAGNATION: No progress update for objective '{objective_id}' in {turns_since} turns. Re-plan or escalate.\n")
        
        return "\n".join(lines)
    
    def _get_stagnation_warning(self, phase: str, turn: int, objective_id: str) -> Optional[str]:
        normalized = normalize_phase(phase)
        if normalized == "RECONNAISSANCE" and turn >= 15:
            return "\nSTAGNATION DETECTED: RECONNAISSANCE >15 turns. Force transition to EXECUTION.\n"
        elif normalized == "EXECUTION" and turn >= 25:
            return "\nSTAGNATION DETECTED: EXECUTION >25 turns. Force phase transition now.\n"
        elif normalized == "VERIFICATION" and turn >= 15:
            return "\nSTAGNATION DETECTED: VERIFICATION >15 turns. Use report_progress(DONE/BLOCKED) for the current objective or escalate. Only use report_completion when the overall mission intent is satisfied.\n"
        return None
