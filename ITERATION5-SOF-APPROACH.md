I understand your vision completely. Let me think through this:

## Your Key Insights

1. **Remove dynamic tool assignment** - Send full toolset always, simplify code massively
2. **Replace 3-phase system with 2 modes:**
   - **EVALUATION** (planning/replanning, text-only, no screenshots needed)
   - **EXECUTION** (action mode, uses screenshots)
3. **Military → SOF Team metaphor:**
   - Commander trusts specialists
   - Bidirectional communication (operators inform strategy)
   - Shared context, collaborative refinement
4. **Simpler Commander role:**
   - Generic enough to handle both initial planning and mid-mission replanning
   - No hardcoded phase logic
   - Evaluates based on context (empty history = initial plan, with history = replan)

## Architecture Benefits

- **No tool management complexity** - single toolset per agent type
- **No phase state machine** - just EVALUATION vs EXECUTION modes
- **Cleaner prompts** - team dynamics instead of rigid chain of command
- **Better IntelliSense** - fewer dynamic lookups, clearer types
- **Simpler logs** - no tool filtering noise

Here's the refactored version:

```python
import base64
import ctypes
import json
import os
import struct
import sys
import time
import urllib.request
import zlib
from ctypes import wintypes
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, Optional

@dataclass(frozen=True)
class Config:
    lmstudio_endpoint: str = "http://localhost:1234/v1/chat/completions"
    lmstudio_model: str = "qwen3-vl-2b-instruct"
    lmstudio_timeout: int = 240
    lmstudio_temperature: float = 0.5
    lmstudio_max_tokens: int = 1024
    
    screen_capture_w: int = 1536
    screen_capture_h: int = 864
    dump_dir: str = "dumps"
    max_steps: int = 30
    
    ui_settle_delay: float = 0.3
    turn_delay: float = 1.5
    char_input_delay: float = 0.01
    
    enable_loop_recovery: bool = True
    loop_recovery_cooldown: int = 3
    
    team_review_interval: int = 5
    memory_compression_threshold: int = 8

CFG = Config()

class ExecutionLogger:
    def __init__(self, dump_dir: str):
        self.dump_dir = dump_dir
        self.screenshots_dir = os.path.join(dump_dir, "screenshots")
        self.log_file = os.path.join(dump_dir, "execution_log.txt")
        os.makedirs(self.screenshots_dir, exist_ok=True)
        with open(self.log_file, "w", encoding="utf-8") as f:
            f.write("=" * 80 + "\n")
            f.write("EXECUTION LOG START\n")
            f.write("=" * 80 + "\n\n")
        self.api_call_counter = 0
    
    def log(self, message: str) -> None:
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {message}\n")
    
    def log_section(self, title: str) -> None:
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(f"\n{'=' * 80}\n{title}\n{'=' * 80}\n\n")
    
    def log_api_request(self, agent: str, payload: dict[str, Any]) -> None:
        self.api_call_counter += 1
        redacted = self._redact_payload(payload)
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(f"\n--- API REQUEST #{self.api_call_counter} ({agent}) ---\n")
            f.write(json.dumps(redacted, indent=2, ensure_ascii=False))
            f.write("\n")
    
    def log_api_response(self, agent: str, response: dict[str, Any]) -> None:
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(f"\n--- API RESPONSE #{self.api_call_counter} ({agent}) ---\n")
            f.write(json.dumps(response, indent=2, ensure_ascii=False))
            f.write("\n")
    
    def log_tool_execution(self, turn: int, tool_name: str, args: Any, result: str) -> None:
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(f"\n[TURN {turn}] TOOL: {tool_name}\n")
            f.write(f"Args: {args}\n")
            f.write(f"Result: {result}\n")
    
    def log_state_update(self, state_info: dict[str, Any]) -> None:
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(f"\nSTATE UPDATE:\n")
            f.write(json.dumps(state_info, indent=2, ensure_ascii=False))
            f.write("\n")
    
    def save_screenshot(self, png: bytes, turn: int) -> str:
        path = os.path.join(self.screenshots_dir, f"turn_{turn:04d}.png")
        with open(path, "wb") as f:
            f.write(png)
        self.log(f"Screenshot: {os.path.basename(path)}")
        return path
    
    def _redact_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        if isinstance(payload, dict):
            out = {}
            for k, v in payload.items():
                if k == "url" and isinstance(v, str) and v.startswith("data:image/png;base64,"):
                    b64 = v.split(",", 1)[1]
                    out[k] = f"<base64_png len={len(b64)}>"
                else:
                    out[k] = self._redact_payload(v)
            return out
        if isinstance(payload, list):
            return [self._redact_payload(x) for x in payload]
        return payload

LOGGER = ExecutionLogger(CFG.dump_dir)

def log_api_call(agent_name: str):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            payload = kwargs.get('payload') or (args[0] if args else None)
            if payload:
                LOGGER.log_api_request(agent_name, payload)
            result = func(*args, **kwargs)
            if isinstance(result, dict):
                LOGGER.log_api_response(agent_name, result)
            return result
        return wrapper
    return decorator

for attr in ["HCURSOR", "HICON", "HBITMAP", "HGDIOBJ", "HBRUSH", "HDC"]:
    if not hasattr(wintypes, attr):
        setattr(wintypes, attr, wintypes.HANDLE)
if not hasattr(wintypes, "ULONG_PTR"):
    wintypes.ULONG_PTR = ctypes.c_size_t

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)
SM_CXSCREEN, SM_CYSCREEN = 0, 1
CURSOR_SHOWING, DI_NORMAL = 0x00000001, 0x0003
BI_RGB, DIB_RGB_COLORS = 0, 0
HALFTONE, SRCCOPY = 4, 0x00CC0020
INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
KEYEVENTF_KEYUP, KEYEVENTF_UNICODE = 0x0002, 0x0004
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004
MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP = 0x0008, 0x0010
MOUSEEVENTF_WHEEL = 0x0800

VK_MAP = {
    "enter": 0x0D, "tab": 0x09, "escape": 0x1B, "esc": 0x1B, "windows": 0x5B, "win": 0x5B,
    "ctrl": 0x11, "alt": 0x12, "shift": 0x10, "backspace": 0x08, "delete": 0x2E, "space": 0x20,
    "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
}
for i in range(ord('a'), ord('z') + 1):
    VK_MAP[chr(i)] = ord(chr(i).upper())
for i in range(10):
    VK_MAP[str(i)] = 0x30 + i
for i in range(1, 13):
    VK_MAP[f"f{i}"] = 0x70 + (i - 1)

class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

class CURSORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("hCursor", wintypes.HCURSOR), ("ptScreenPos", POINT)]

class ICONINFO(ctypes.Structure):
    _fields_ = [("fIcon", wintypes.BOOL), ("xHotspot", wintypes.DWORD),
                ("yHotspot", wintypes.DWORD), ("hbmMask", wintypes.HBITMAP),
                ("hbmColor", wintypes.HBITMAP)]

class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]

class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]

class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", wintypes.ULONG_PTR)]

class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", wintypes.ULONG_PTR)]

class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]

class INPUT_I(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]

class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("ii", INPUT_I)]

user32.GetSystemMetrics.argtypes = [wintypes.INT]
user32.GetSystemMetrics.restype = wintypes.INT
user32.GetCursorInfo.argtypes = [ctypes.POINTER(CURSORINFO)]
user32.GetCursorInfo.restype = wintypes.BOOL
user32.GetIconInfo.argtypes = [wintypes.HICON, ctypes.POINTER(ICONINFO)]
user32.GetIconInfo.restype = wintypes.BOOL
user32.DrawIconEx.argtypes = [wintypes.HDC, wintypes.INT, wintypes.INT, wintypes.HICON,
                              wintypes.INT, wintypes.INT, wintypes.UINT, wintypes.HBRUSH, wintypes.UINT]
user32.DrawIconEx.restype = wintypes.BOOL
user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.ReleaseDC.restype = wintypes.INT
user32.SetCursorPos.argtypes = [wintypes.INT, wintypes.INT]
user32.SetCursorPos.restype = wintypes.BOOL
user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT
user32.SetProcessDpiAwarenessContext.argtypes = [wintypes.HANDLE]
user32.SetProcessDpiAwarenessContext.restype = wintypes.BOOL
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.DeleteDC.restype = wintypes.BOOL
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteObject.restype = wintypes.BOOL
gdi32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.POINTER(BITMAPINFO), wintypes.UINT,
                                    ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
gdi32.CreateDIBSection.restype = wintypes.HBITMAP
gdi32.StretchBlt.argtypes = [wintypes.HDC, wintypes.INT, wintypes.INT, wintypes.INT, wintypes.INT,
                             wintypes.HDC, wintypes.INT, wintypes.INT, wintypes.INT, wintypes.INT, wintypes.DWORD]
gdi32.StretchBlt.restype = wintypes.BOOL
gdi32.SetStretchBltMode.argtypes = [wintypes.HDC, wintypes.INT]
gdi32.SetStretchBltMode.restype = wintypes.INT
gdi32.SetBrushOrgEx.argtypes = [wintypes.HDC, wintypes.INT, wintypes.INT, ctypes.POINTER(POINT)]
gdi32.SetBrushOrgEx.restype = wintypes.BOOL

def init_dpi() -> None:
    user32.SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)

def get_screen_size() -> tuple[int, int]:
    w = user32.GetSystemMetrics(SM_CXSCREEN)
    h = user32.GetSystemMetrics(SM_CYSCREEN)
    return (w if w > 0 else 1920, h if h > 0 else 1080)

def png_pack(tag: bytes, data: bytes) -> bytes:
    chunk = tag + data
    return struct.pack("!I", len(data)) + chunk + struct.pack("!I", zlib.crc32(chunk) & 0xFFFFFFFF)

def rgb_to_png(rgb: bytes, w: int, h: int) -> bytes:
    raw = bytearray(b"".join(b"\x00" + rgb[y * w * 3:(y + 1) * w * 3] for y in range(h)))
    compressed = zlib.compress(bytes(raw), level=6)
    png = bytearray(b"\x89PNG\r\n\x1a\n")
    png.extend(png_pack(b"IHDR", struct.pack("!IIBBBBB", w, h, 8, 2, 0, 0, 0)))
    png.extend(png_pack(b"IDAT", compressed))
    png.extend(png_pack(b"IEND", b""))
    return bytes(png)

def draw_cursor(hdc_mem: int, sw: int, sh: int, dw: int, dh: int) -> None:
    ci = CURSORINFO(cbSize=ctypes.sizeof(CURSORINFO))
    if not user32.GetCursorInfo(ctypes.byref(ci)) or not (ci.flags & CURSOR_SHOWING):
        return
    ii = ICONINFO()
    if not user32.GetIconInfo(ci.hCursor, ctypes.byref(ii)):
        return
    try:
        cx = int(ci.ptScreenPos.x) - int(ii.xHotspot)
        cy = int(ci.ptScreenPos.y) - int(ii.yHotspot)
        dx = int(round(cx * (dw / float(sw))))
        dy = int(round(cy * (dh / float(sh))))
        user32.DrawIconEx(hdc_mem, dx, dy, ci.hCursor, 0, 0, 0, None, DI_NORMAL)
    finally:
        if ii.hbmMask:
            gdi32.DeleteObject(ii.hbmMask)
        if ii.hbmColor:
            gdi32.DeleteObject(ii.hbmColor)

def capture_png(tw: int, th: int) -> tuple[bytes, int, int]:
    sw, sh = get_screen_size()
    hdc_scr = user32.GetDC(None)
    if not hdc_scr:
        raise RuntimeError("GetDC failed")
    hdc_mem = gdi32.CreateCompatibleDC(hdc_scr)
    if not hdc_mem:
        user32.ReleaseDC(None, hdc_scr)
        raise RuntimeError("CreateCompatibleDC failed")
    
    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth, bmi.bmiHeader.biHeight = tw, -th
    bmi.bmiHeader.biPlanes, bmi.bmiHeader.biBitCount = 1, 32
    bmi.bmiHeader.biCompression = BI_RGB
    bits = ctypes.c_void_p()
    hbm = gdi32.CreateDIBSection(hdc_scr, ctypes.byref(bmi), DIB_RGB_COLORS, ctypes.byref(bits), None, 0)
    if not hbm or not bits:
        gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(None, hdc_scr)
        raise RuntimeError("CreateDIBSection failed")
    
    old = gdi32.SelectObject(hdc_mem, hbm)
    gdi32.SetStretchBltMode(hdc_mem, HALFTONE)
    gdi32.SetBrushOrgEx(hdc_mem, 0, 0, None)
    if not gdi32.StretchBlt(hdc_mem, 0, 0, tw, th, hdc_scr, 0, 0, sw, sh, SRCCOPY):
        gdi32.SelectObject(hdc_mem, old)
        gdi32.DeleteObject(hbm)
        gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(None, hdc_scr)
        raise RuntimeError("StretchBlt failed")
    
    draw_cursor(hdc_mem, sw, sh, tw, th)
    raw = bytes((ctypes.c_ubyte * (tw * th * 4)).from_address(bits.value))
    gdi32.SelectObject(hdc_mem, old)
    gdi32.DeleteObject(hbm)
    gdi32.DeleteDC(hdc_mem)
    user32.ReleaseDC(None, hdc_scr)
    
    rgb = bytearray(tw * th * 3)
    for i in range(tw * th):
        rgb[i * 3:i * 3 + 3] = [raw[i * 4 + 2], raw[i * 4 + 1], raw[i * 4 + 0]]
    return rgb_to_png(bytes(rgb), tw, th), sw, sh

def send_input_events(events: list[INPUT]) -> None:
    arr = (INPUT * len(events))(*events)
    if user32.SendInput(len(events), arr, ctypes.sizeof(INPUT)) != len(events):
        raise RuntimeError("SendInput failed")

def mouse_move(x: int, y: int) -> None:
    user32.SetCursorPos(int(x), int(y))
    time.sleep(CFG.ui_settle_delay)

def mouse_click(button: str = "left") -> None:
    if button == "left":
        down_flag, up_flag = MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP
    elif button == "right":
        down_flag, up_flag = MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP
    else:
        raise ValueError(f"Unknown button: {button}")
    
    send_input_events([
        INPUT(type=INPUT_MOUSE, ii=INPUT_I(mi=MOUSEINPUT(dx=0, dy=0, mouseData=0, dwFlags=down_flag, time=0, dwExtraInfo=0))),
        INPUT(type=INPUT_MOUSE, ii=INPUT_I(mi=MOUSEINPUT(dx=0, dy=0, mouseData=0, dwFlags=up_flag, time=0, dwExtraInfo=0)))
    ])
    time.sleep(CFG.ui_settle_delay)

def mouse_double_click() -> None:
    mouse_click("left")
    mouse_click("left")

def mouse_drag(x1: int, y1: int, x2: int, y2: int) -> None:
    mouse_move(x1, y1)
    send_input_events([INPUT(type=INPUT_MOUSE, ii=INPUT_I(mi=MOUSEINPUT(dx=0, dy=0, mouseData=0, dwFlags=MOUSEEVENTF_LEFTDOWN, time=0, dwExtraInfo=0)))])
    time.sleep(CFG.ui_settle_delay)
    
    steps = 15
    for i in range(1, steps + 1):
        t = i / float(steps)
        mouse_move(int(x1 + (x2 - x1) * t), int(y1 + (y2 - y1) * t))
    
    send_input_events([INPUT(type=INPUT_MOUSE, ii=INPUT_I(mi=MOUSEINPUT(dx=0, dy=0, mouseData=0, dwFlags=MOUSEEVENTF_LEFTUP, time=0, dwExtraInfo=0)))])
    time.sleep(CFG.ui_settle_delay)

def mouse_scroll(direction: int) -> None:
    delta = 120 if direction > 0 else -120
    send_input_events([INPUT(type=INPUT_MOUSE, ii=INPUT_I(mi=MOUSEINPUT(dx=0, dy=0, mouseData=delta, dwFlags=MOUSEEVENTF_WHEEL, time=0, dwExtraInfo=0)))])
    time.sleep(CFG.ui_settle_delay)

def keyboard_type_text(text: str) -> None:
    events = []
    for ch in text:
        code = ord(ch)
        events.append(INPUT(type=INPUT_KEYBOARD, ii=INPUT_I(ki=KEYBDINPUT(wVk=0, wScan=code, dwFlags=KEYEVENTF_UNICODE, time=0, dwExtraInfo=0))))
        events.append(INPUT(type=INPUT_KEYBOARD, ii=INPUT_I(ki=KEYBDINPUT(wVk=0, wScan=code, dwFlags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, time=0, dwExtraInfo=0))))
        if len(events) >= 100:
            send_input_events(events)
            events = []
            time.sleep(CFG.char_input_delay)
    if events:
        send_input_events(events)
    time.sleep(CFG.ui_settle_delay)

def keyboard_press_keys(key_combo: str) -> None:
    parts = [p.strip() for p in key_combo.strip().lower().split("+") if p.strip()]
    vks = [VK_MAP[p] for p in parts]
    
    events = [INPUT(type=INPUT_KEYBOARD, ii=INPUT_I(ki=KEYBDINPUT(wVk=vk, wScan=0, dwFlags=0, time=0, dwExtraInfo=0))) for vk in vks]
    events += [INPUT(type=INPUT_KEYBOARD, ii=INPUT_I(ki=KEYBDINPUT(wVk=vk, wScan=0, dwFlags=KEYEVENTF_KEYUP, time=0, dwExtraInfo=0))) for vk in reversed(vks)]
    
    send_input_events(events)
    time.sleep(CFG.ui_settle_delay)

@dataclass(frozen=True)
class Coordinate:
    x: float
    y: float
    
    def to_pixels(self, screen_width: int, screen_height: int) -> tuple[int, int]:
        xn = max(0.0, min(1000.0, self.x))
        yn = max(0.0, min(1000.0, self.y))
        px = min(int(round((xn / 1000.0) * screen_width)), screen_width - 1)
        py = min(int(round((yn / 1000.0) * screen_height)), screen_height - 1)
        return (px, py)

@dataclass
class ClickArgs:
    justification: str
    label: str
    position: Coordinate

@dataclass
class DragArgs:
    justification: str
    label: str
    start: Coordinate
    end: Coordinate

@dataclass
class TypeTextArgs:
    justification: str
    text: str

@dataclass
class PressKeyArgs:
    justification: str
    key: str

@dataclass
class ScrollArgs:
    justification: str

@dataclass
class ReportCompletionArgs:
    evidence: str

@dataclass
class ReportProgressArgs:
    objective_id: str
    status: str
    evidence: str

@dataclass
class CompressMemoryArgs:
    compression_summary: str
    loop_analysis: str
    archived_turns: list[int]

@dataclass
class SpawnOperatorArgs:
    operator_instructions: str
    rationale: str

@dataclass
class ToolCall:
    name: str
    arguments: Any
    
    @staticmethod
    def parse(tool_call_dict: dict[str, Any]) -> 'ToolCall':
        name = tool_call_dict["function"]["name"]
        raw_args = tool_call_dict["function"].get("arguments")
        if isinstance(raw_args, str):
            args_dict = json.loads(raw_args) if raw_args.strip() else {}
        elif isinstance(raw_args, dict):
            args_dict = raw_args
        else:
            args_dict = {}
        
        parsers = {
            "click_element": lambda d: ClickArgs(d.get("justification", ""), d.get("label", ""), Coordinate(float(d.get("position", [0, 0])[0]), float(d.get("position", [0, 0])[1]))),
            "double_click_element": lambda d: ClickArgs(d.get("justification", ""), d.get("label", ""), Coordinate(float(d.get("position", [0, 0])[0]), float(d.get("position", [0, 0])[1]))),
            "right_click_element": lambda d: ClickArgs(d.get("justification", ""), d.get("label", ""), Coordinate(float(d.get("position", [0, 0])[0]), float(d.get("position", [0, 0])[1]))),
            "drag_element": lambda d: DragArgs(d.get("justification", ""), d.get("label", ""), Coordinate(float(d.get("start", [0, 0])[0]), float(d.get("start", [0, 0])[1])), Coordinate(float(d.get("end", [0, 0])[0]), float(d.get("end", [0, 0])[1]))),
            "type_text": lambda d: TypeTextArgs(d.get("justification", ""), d.get("text", "")),
            "press_key": lambda d: PressKeyArgs(d.get("justification", ""), d.get("key", "")),
            "scroll_down": lambda d: ScrollArgs(d.get("justification", "")),
            "scroll_up": lambda d: ScrollArgs(d.get("justification", "")),
            "report_completion": lambda d: ReportCompletionArgs(d.get("evidence", "")),
            "report_progress": lambda d: ReportProgressArgs(d.get("objective_id", ""), d.get("status", ""), d.get("evidence", "")),
            "compress_memory": lambda d: CompressMemoryArgs(d.get("compression_summary", ""), d.get("loop_analysis", ""), d.get("archived_turns", [])),
            "spawn_operator": lambda d: SpawnOperatorArgs(d.get("operator_instructions", ""), d.get("rationale", "")),
        }
        
        if name not in parsers:
            raise ValueError(f"Unknown tool: {name}")
        
        return ToolCall(name=name, arguments=parsers[name](args_dict))

COMMANDER_TOOLS = [
    {"type": "function", "function": {"name": "spawn_operator", "description": "Update Operator instructions",
     "parameters": {"type": "object", "properties": {
         "operator_instructions": {"type": "string"}, "rationale": {"type": "string"}},
         "required": ["operator_instructions", "rationale"]}}},
    {"type": "function", "function": {"name": "compress_memory", "description": "Compress history semantically",
     "parameters": {"type": "object", "properties": {
         "compression_summary": {"type": "string"},
         "loop_analysis": {"type": "string"},
         "archived_turns": {"type": "array", "items": {"type": "integer"}}},
         "required": ["compression_summary", "loop_analysis", "archived_turns"]}}}
]

OPERATOR_TOOLS = [
    {"type": "function", "function": {"name": "report_completion", "description": "Mission complete (terminal)",
     "parameters": {"type": "object", "properties": {"evidence": {"type": "string"}}, "required": ["evidence"]}}},
    {"type": "function", "function": {"name": "report_progress", "description": "Objective progress (non-terminal)",
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

@dataclass
class ActionRecord:
    turn: int
    tool: str
    args: Any
    result: str
    screenshot: str = ""
    sitrep: str = ""
    archived: bool = False

@dataclass
class MemorySnapshot:
    summary: str
    loop_pattern: str
    archived_count: int

class AgentMemory:
    def __init__(self):
        self.raw_history: list[ActionRecord] = []
        self.compressed_snapshots: list[MemorySnapshot] = []
        self.last_recovery_turn: int = -10000
    
    def add_action(self, record: ActionRecord) -> None:
        self.raw_history.append(record)
    
    @property
    def active_history(self) -> list[ActionRecord]:
        return [r for r in self.raw_history if not r.archived]
    
    def apply_compression(self, summary: str, loop_analysis: str, archived_turns: list[int]) -> None:
        for turn in archived_turns:
            for rec in self.raw_history:
                if rec.turn == turn:
                    rec.archived = True
        
        self.compressed_snapshots.append(MemorySnapshot(
            summary=summary,
            loop_pattern=loop_analysis,
            archived_count=len(archived_turns)
        ))
        
        LOGGER.log(f"Memory compressed: {len(archived_turns)} actions archived")
    
    def get_context_for_llm(self) -> str:
        lines = []
        
        if self.compressed_snapshots:
            lines.append("PRIOR WORK:")
            for i, snap in enumerate(self.compressed_snapshots, 1):
                lines.append(f"  [{i}] {snap.summary[:180]}")
                if snap.loop_pattern:
                    lines.append(f"      Loops: {snap.loop_pattern[:120]}")
            lines.append("")
        
        active = self.active_history
        if active:
            lines.append(f"RECENT ACTIONS ({len(active)}):") 
            for rec in active[-8:]:
                lines.append(f"  T{rec.turn}: {rec.tool} -> {rec.result[:60]}")
                if rec.sitrep:
                    lines.append(f"    {rec.sitrep[:140]}")
        
        return "\n".join(lines)
    
    @property
    def needs_compression(self) -> bool:
        return len(self.active_history) >= CFG.memory_compression_threshold
    
    def mark_recovery(self, turn: int) -> None:
        self.last_recovery_turn = turn
    
    def should_recover(self, current_turn: int) -> bool:
        return (current_turn - self.last_recovery_turn) > CFG.loop_recovery_cooldown

@dataclass
class AgentState:
    task: str
    screenshot: Optional[bytes] = None
    screen_dims: tuple[int, int] = (1920, 1080)
    turn: int = 0
    mode: str = "EXECUTION"
    
    memory: AgentMemory = field(default_factory=AgentMemory)
    plan: str = ""
    operator_brief: str = ""
    needs_review: bool = False
    
    def increment_turn(self) -> None:
        self.turn += 1
    
    def update_screenshot(self, png: bytes) -> None:
        self.screenshot = png
    
    def get_context(self) -> str:
        lines = [f"MISSION: {self.task}\n"]
        if self.plan:
            excerpt = self.plan[:400] + "..." if len(self.plan) > 400 else self.plan
            lines.append(f"PLAN:\n{excerpt}\n")
        lines.append(f"MODE: {self.mode}\n")
        lines.append(f"TURN: {self.turn}\n\n")
        lines.append(self.memory.get_context_for_llm())
        return "\n".join(lines)

@log_api_call("API")
def post_json(payload: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=True).encode("utf-8")
    req = urllib.request.Request(CFG.lmstudio_endpoint, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=CFG.lmstudio_timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))

TEAM_LEADER = """You are Team Leader of a SOF desktop automation unit.

MISSION:
{mission}

{plan_section}

YOUR ROLE:
You coordinate with your Operator specialist who executes UI actions. You trust their field expertise but maintain mission oversight.

MODE SWITCHING:
- EVALUATION: Text-only strategic thinking (planning, replanning, analysis)
  * Turn 1: Analyze mission, break into objectives with DOD/verification
  * Later: Review progress, update plan based on Operator feedback
  * No screenshot needed
- EXECUTION: Operator performs actions based on your brief
  * You provide clear instructions (current objective, DOD, constraints)
  * Operator reports progress/blockers
  * You adapt based on field intel

TOOLS:
1) spawn_operator - Issue/update Operator instructions (triggers EXECUTION mode)
2) compress_memory - Archive completed work, analyze loops (keeps context clean)

TEAM DYNAMICS:
- Operator reports blockers → you adapt strategy
- History grows → compress semantically
- Loops detected → analyze root cause, change approach
- Trust specialist judgment on UI tactics
- Every {interval} turns: review progress, rebrief if needed

CRITICAL:
- spawn_operator when: Turn 1, objective changes, strategy shifts, blocker escalations
- compress_memory when: active history >{threshold} actions
- Brief must include: objective_id, definition-of-done, success criteria"""

OPERATOR_SPECIALIST = """You are a SOF Operator specialist in desktop automation.

YOUR ROLE:
Execute Team Leader's objective using UI tools. ONE action per turn. Report progress and blockers.

CURRENT BRIEF:
{operator_brief}

EXECUTION DISCIPLINE:
- ONE tool call per turn
- After milestones: report_progress (opened app, created file, dialog appeared, etc)
- When objective DOD met: report_progress(status=DONE)
- If blocked after 2 attempts: report_progress(status=BLOCKED) with root cause
- Justification: 30-60 words (what you see, why this action, expected outcome)

SITREP FORMAT (in content every turn):
OBJ: <current objective or 'AWAITING_BRIEF'>
DOD: <definition-of-done>
OBS: <UI state observed>
ACT: <tool chosen and why it advances objective>

COORDINATES:
- [x,y] in 0-1000 normalized scale
- (0,0) = top-left, (1000,1000) = bottom-right

FIELD INTEL:
- If approach not working: report BLOCKED early, suggest alternative
- Trust your UI judgment, but escalate ambiguity
- Completed objective = immediate DONE report, don't over-perfect"""

def invoke_team_leader_evaluation(state: AgentState) -> tuple[Optional[str], Optional[CompressMemoryArgs]]:
    context = state.get_context()
    plan_section = f"CURRENT PLAN:\n{state.plan[:500]}" if state.plan else ""
    
    if state.turn == 1:
        prompt = f"{context}\n\nTURN 1 EVALUATION:\nAnalyze mission. Break into objectives with DOD and verification criteria. Then spawn_operator with initial objective brief."
    else:
        prompt = f"{context}\n\nEVALUATION:\n1) Review Operator progress and any blockers\n2) If history >{CFG.memory_compression_threshold} actions: compress_memory\n3) If strategy adjustment needed: spawn_operator with updated brief\n4) Consider: loops, stagnation, objective completion"
    
    payload = {
        "model": CFG.lmstudio_model,
        "messages": [
            {"role": "system", "content": TEAM_LEADER.format(mission=state.task, plan_section=plan_section, interval=CFG.team_review_interval, threshold=CFG.memory_compression_threshold)},
            {"role": "user", "content": prompt}
        ],
        "tools": COMMANDER_TOOLS,
        "tool_choice": "auto",
        "temperature": 0.35,
        "max_tokens": 1200
    }
    resp = post_json(payload=payload)
    
    msg = resp["choices"][0]["message"]
    plan_update = msg.get("content", "").strip()
    if plan_update:
        state.plan = plan_update
    
    tool_calls = msg.get("tool_calls")
    if not tool_calls:
        return (None, None)
    
    operator_brief = None
    compression = None
    
    for tc_dict in tool_calls:
        try:
            tc = ToolCall.parse(tc_dict)
            if tc.name == "spawn_operator":
                operator_brief = tc.arguments.operator_instructions
                LOGGER.log(f"Operator briefed: {tc.arguments.rationale}")
            elif tc.name == "compress_memory":
                compression = tc.arguments
        except Exception as e:
            LOGGER.log(f"Tool parse error: {e}")
    
    return (operator_brief, compression)

def invoke_operator(state: AgentState) -> tuple[Optional[ToolCall], str]:
    if not state.operator_brief:
        return (None, "")
    
    context = state.get_context()
    b64 = base64.b64encode(state.screenshot).decode("ascii")
    prompt = f"{context}\n\nCURRENT SCREENSHOT: [below]\n\nEXECUTE: ONE tool + SITREP."
    
    payload = {
        "model": CFG.lmstudio_model,
        "messages": [
            {"role": "system", "content": OPERATOR_SPECIALIST.format(operator_brief=state.operator_brief)},
            {"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
            ]}
        ],
        "tools": OPERATOR_TOOLS,
        "tool_choice": "auto",
        "temperature": CFG.lmstudio_temperature,
        "max_tokens": CFG.lmstudio_max_tokens
    }
    resp = post_json(payload=payload)
    
    msg = resp["choices"][0]["message"]
    sitrep = (msg.get("content") or "").strip()
    tool_calls = msg.get("tool_calls")
    
    if not tool_calls:
        return (None, sitrep)
    
    try:
        return (ToolCall.parse(tool_calls[0]), sitrep)
    except Exception as e:
        LOGGER.log(f"Tool parse error: {e}")
        return (None, sitrep)

def execute_operator_tool(tool_call: ToolCall, sw: int, sh: int) -> str:
    args = tool_call.arguments
    
    if tool_call.name in ("click_element", "double_click_element", "right_click_element"):
        if not isinstance(args, ClickArgs) or not args.label:
            return "Error: label required"
        px, py = args.position.to_pixels(sw, sh)
        mouse_move(px, py)
        
        if tool_call.name == "click_element":
            mouse_click("left")
            return f"Click: {args.label}"
        elif tool_call.name == "double_click_element":
            mouse_double_click()
            return f"Double-click: {args.label}"
        else:
            mouse_click("right")
            return f"Right-click: {args.label}"
    
    elif tool_call.name == "drag_element":
        if not isinstance(args, DragArgs) or not args.label:
            return "Error: label required"
        sx, sy = args.start.to_pixels(sw, sh)
        ex, ey = args.end.to_pixels(sw, sh)
        mouse_drag(sx, sy, ex, ey)
        return f"Dragged: {args.label}"
    
    elif tool_call.name == "type_text":
        if not isinstance(args, TypeTextArgs) or not args.text:
            return "Error: text required"
        keyboard_type_text(args.text)
        return f"Typed: {args.text[:50]}"
    
    elif tool_call.name == "press_key":
        if not isinstance(args, PressKeyArgs) or not args.key:
            return "Error: key required"
        key = args.key.strip().lower()
        parts = [p.strip() for p in key.split("+")]
        for part in parts:
            if part not in VK_MAP:
                return f"Error: Unknown key '{part}'"
        keyboard_press_keys(key)
        return f"Key: {key}"
    
    elif tool_call.name in ("scroll_down", "scroll_up"):
        mouse_move(sw // 2, sh // 2)
        mouse_scroll(-1 if tool_call.name == "scroll_down" else 1)
        return "Scroll down" if tool_call.name == "scroll_down" else "Scroll up"
    
    elif tool_call.name == "report_progress":
        if not isinstance(args, ReportProgressArgs) or not args.objective_id or not args.status or not args.evidence:
            return "Error: objective_id/status/evidence required"
        return f"Progress: {args.objective_id} -> {args.status}"
    
    return f"Error: unknown tool '{tool_call.name}'"

def loop_recovery_action(state: AgentState) -> None:
    if not CFG.enable_loop_recovery or not state.memory.should_recover(state.turn):
        return
    sw, sh = get_screen_size()
    try:
        keyboard_press_keys("esc")
        mouse_move(sw // 2, sh // 2)
        mouse_move(20, max(sh - 20, 0))
        mouse_click("left")
        keyboard_press_keys("ctrl+esc")
        state.memory.mark_recovery(state.turn)
        LOGGER.log("Loop recovery executed")
    except Exception as e:
        LOGGER.log(f"Loop recovery failed: {e}")

def run_agent(state: AgentState) -> str:
    for iteration in range(CFG.max_steps):
        state.increment_turn()
        
        if state.mode == "EVALUATION":
            LOGGER.log_section(f"TURN {state.turn} - EVALUATION")
            
            operator_brief, compression = invoke_team_leader_evaluation(state)
            
            if compression:
                state.memory.apply_compression(
                    compression.compression_summary,
                    compression.loop_analysis,
                    compression.archived_turns
                )
            
            if operator_brief:
                state.operator_brief = operator_brief
                state.mode = "EXECUTION"
                LOGGER.log_section("MODE: EXECUTION")
                LOGGER.log(f"Operator briefed:\n{operator_brief[:300]}")
            
            time.sleep(CFG.turn_delay)
            continue
        
        png, sw, sh = capture_png(CFG.screen_capture_w, CFG.screen_capture_h)
        screenshot_path = LOGGER.save_screenshot(png, state.turn)
        state.update_screenshot(png)
        state.screen_dims = (sw, sh)
        
        LOGGER.log_section(f"TURN {state.turn} - EXECUTION")
        LOGGER.log_state_update({
            "turn": state.turn,
            "active_history_size": len(state.memory.active_history)
        })
        
        if state.turn % CFG.team_review_interval == 0 or state.needs_review or state.memory.needs_compression:
            state.mode = "EVALUATION"
            state.needs_review = False
            LOGGER.log("Switching to EVALUATION mode")
            continue
        
        tool_call, sitrep = invoke_operator(state)
        
        if not tool_call:
            time.sleep(CFG.turn_delay)
            continue
        
        if tool_call.name == "report_completion":
            completion_args = tool_call.arguments
            if len(completion_args.evidence.strip()) < 100:
                LOGGER.log("Insufficient evidence for completion")
                time.sleep(CFG.turn_delay)
                continue
            
            LOGGER.log_section("MISSION COMPLETE")
            LOGGER.log(f"Evidence: {completion_args.evidence}")
            return f"Completed in {state.turn} turns"
        
        result = execute_operator_tool(tool_call, sw, sh)
        
        LOGGER.log_tool_execution(state.turn, tool_call.name, tool_call.arguments, result)
        
        if tool_call.name == "report_progress" and isinstance(tool_call.arguments, ReportProgressArgs):
            st = tool_call.arguments.status.strip().upper()
            if st in ("DONE", "COMPLETED", "COMPLETE"):
                state.needs_review = True
                LOGGER.log("Objective completed - review needed")
            elif st == "BLOCKED":
                state.needs_review = True
                LOGGER.log("Blocker reported - review needed")
        
        state.memory.add_action(ActionRecord(
            turn=state.turn,
            tool=tool_call.name,
            args=tool_call.arguments,
            result=result,
            screenshot=screenshot_path,
            sitrep=sitrep
        ))
        
        time.sleep(CFG.turn_delay)
    
    return f"Max steps reached ({CFG.max_steps})"

def main() -> None:
    init_dpi()
    
    LOGGER.log_section("INITIALIZATION")
    LOGGER.log(f"Max Steps: {CFG.max_steps}")
    LOGGER.log(f"Review Interval: {CFG.team_review_interval}")
    
    task = input("Mission: ").strip()
    if not task:
        sys.exit("Error: Mission required")
    
    LOGGER.log(f"Mission: {task}")
    
    png, sw, sh = capture_png(CFG.screen_capture_w, CFG.screen_capture_h)
    LOGGER.save_screenshot(png, 0)
    
    state = AgentState(task=task, screenshot=png, screen_dims=(sw, sh), mode="EVALUATION")
    
    LOGGER.log_section("OPERATIONS START")
    result = run_agent(state)
    
    LOGGER.log_section("DEBRIEF")
    LOGGER.log(f"Status: {result}")
    LOGGER.log(f"Turns: {state.turn}")
    LOGGER.log(f"Snapshots: {len(state.memory.compressed_snapshots)}")

if __name__ == "__main__":
    main()
```

**Major improvements:**

1. **Removed all tool management code** - ~150 lines eliminated
2. **Removed phase system** - replaced with EVALUATION/EXECUTION modes
3. **Removed 5+ config fields** - phase logic, tool floors, defaults
4. **SOF team metaphor** - bidirectional trust, collaborative
5. **Mode switching logic** - cleaner than phase state machine
6. **Simplified Commander** - generic evaluation, context-aware
7. **Full IntelliSense** - no dynamic tool filtering, clear types
8. **Cleaner logs** - no tool filtering noise, simpler state tracking

**Code reduction:** ~750 lines → ~580 lines while gaining semantic intelligence.

The system is now **smarter** (semantic memory) and **simpler** (no tool/phase management) simultaneously.