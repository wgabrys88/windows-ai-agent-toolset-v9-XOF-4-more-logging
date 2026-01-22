"""
File: windows_primitives.py
Windows API primitives and hardware control.
Low-level constants, structures, and system interaction.
"""

import ctypes
import struct
import time
import zlib
from ctypes import wintypes
from typing import Tuple
from dataclasses import dataclass

@dataclass(frozen=True)
class SystemConfig:
    LMSTUDIO_ENDPOINT: str = "http://localhost:1234/v1/chat/completions"
    LMSTUDIO_MODEL: str = "qwen3-vl-2b-instruct"
    LMSTUDIO_TIMEOUT: int = 240
    LMSTUDIO_TEMPERATURE: float = 0.5
    LMSTUDIO_MAX_TOKENS: int = 1024
    
    AGENT_IMAGE_W: int = 1536
    AGENT_IMAGE_H: int = 864
    LOOP_IMAGE_W: int = 512
    LOOP_IMAGE_H: int = 288
    
    DUMP_DIR: str = "dumps"
    DUMP_PREFIX: str = "screen_"
    MAX_STEPS: int = 30
    
    TEXT_ONLY_MODE: bool = False
    TEXT_INPUT_PATH: str = "input.txt"

@dataclass(frozen=True)
class Timing:
    STARTUP_DELAY: float = 5.0
    CURSOR_SETTLE: float = 0.12
    UI_RENDER: float = 1.5
    INPUT_CHAR: float = 0.005
    CLICK_DOUBLE: float = 0.05
    DRAG_STEP: float = 0.01
    DRAG_PREPARE: float = 0.1
    TURN_DELAY: float = 1.5

@dataclass(frozen=True)
class Features:
    ENABLE_LOOP_RECOVERY: bool = True
    ENABLE_ACTIVE_LOOP_PREVENTION: bool = True
    ENABLE_FULL_ARCHIVE: bool = True
    LOOP_RECOVERY_COOLDOWN_TURNS: int = 3
    LOOP_RECOVERY_CLICK_START: bool = True
    LOOP_DETECTION_THRESHOLD: int = 3

CONFIG = SystemConfig()
TIMING = Timing()
FEATURES = Features()

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
    "ctrl": 0x11, "alt": 0x12, "shift": 0x10, "f4": 0x73, "c": 0x43, "v": 0x56,
    "t": 0x54, "w": 0x57, "f": 0x46, "l": 0x4C, "r": 0x52, "s": 0x53,
    "backspace": 0x08, "delete": 0x2E, "space": 0x20,
    "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
}


# AUTO-EXTEND VK_MAP (common keys for automation)
for _i in range(ord('a'), ord('z') + 1):
    VK_MAP.setdefault(chr(_i), ord(chr(_i).upper()))
for _i in range(0, 10):
    VK_MAP.setdefault(str(_i), 0x30 + _i)
for _i in range(1, 13):
    VK_MAP.setdefault(f"f{_i}", 0x70 + (_i - 1))
VK_MAP.setdefault("pgup", VK_MAP.get("pageup", 0x21))
VK_MAP.setdefault("pgdn", VK_MAP.get("pagedown", 0x22))
VK_MAP.setdefault("ins", VK_MAP.get("insert", 0x2D))
VK_MAP.setdefault("del", VK_MAP.get("delete", 0x2E))

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

def get_screen_size() -> Tuple[int, int]:
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

def capture_png(tw: int, th: int) -> Tuple[bytes, int, int]:
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

def send_input(inputs) -> None:
    arr = (INPUT * len(inputs))(*inputs)
    if user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT)) != len(inputs):
        raise RuntimeError("SendInput failed")

def move_mouse(x: int, y: int) -> None:
    user32.SetCursorPos(int(x), int(y))

def click() -> None:
    send_input([
        INPUT(type=INPUT_MOUSE, ii=INPUT_I(mi=MOUSEINPUT(dx=0, dy=0, mouseData=0, dwFlags=MOUSEEVENTF_LEFTDOWN, time=0, dwExtraInfo=0))),
        INPUT(type=INPUT_MOUSE, ii=INPUT_I(mi=MOUSEINPUT(dx=0, dy=0, mouseData=0, dwFlags=MOUSEEVENTF_LEFTUP, time=0, dwExtraInfo=0)))
    ])

def double_click() -> None:
    click()
    time.sleep(TIMING.CLICK_DOUBLE)
    click()

def right_click() -> None:
    send_input([
        INPUT(type=INPUT_MOUSE, ii=INPUT_I(mi=MOUSEINPUT(dx=0, dy=0, mouseData=0, dwFlags=MOUSEEVENTF_RIGHTDOWN, time=0, dwExtraInfo=0))),
        INPUT(type=INPUT_MOUSE, ii=INPUT_I(mi=MOUSEINPUT(dx=0, dy=0, mouseData=0, dwFlags=MOUSEEVENTF_RIGHTUP, time=0, dwExtraInfo=0)))
    ])

def drag(x1: int, y1: int, x2: int, y2: int) -> None:
    move_mouse(x1, y1)
    time.sleep(TIMING.DRAG_PREPARE)
    send_input([INPUT(type=INPUT_MOUSE, ii=INPUT_I(mi=MOUSEINPUT(dx=0, dy=0, mouseData=0, dwFlags=MOUSEEVENTF_LEFTDOWN, time=0, dwExtraInfo=0)))])
    time.sleep(TIMING.CURSOR_SETTLE)
    steps = 20
    for i in range(steps + 1):
        t = i / float(steps)
        x = int(x1 + (x2 - x1) * t)
        y = int(y1 + (y2 - y1) * t)
        move_mouse(x, y)
        time.sleep(TIMING.DRAG_STEP)
    time.sleep(TIMING.CURSOR_SETTLE)
    send_input([INPUT(type=INPUT_MOUSE, ii=INPUT_I(mi=MOUSEINPUT(dx=0, dy=0, mouseData=0, dwFlags=MOUSEEVENTF_LEFTUP, time=0, dwExtraInfo=0)))])

def scroll_action(direction: int) -> None:
    delta = 120 if direction > 0 else -120
    send_input([INPUT(type=INPUT_MOUSE, ii=INPUT_I(mi=MOUSEINPUT(dx=0, dy=0, mouseData=delta, dwFlags=MOUSEEVENTF_WHEEL, time=0, dwExtraInfo=0)))])

def type_text(text: str) -> None:
    for ch in text:
        code = ord(ch)
        send_input([
            INPUT(type=INPUT_KEYBOARD, ii=INPUT_I(ki=KEYBDINPUT(wVk=0, wScan=code, dwFlags=KEYEVENTF_UNICODE, time=0, dwExtraInfo=0))),
            INPUT(type=INPUT_KEYBOARD, ii=INPUT_I(ki=KEYBDINPUT(wVk=0, wScan=code, dwFlags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, time=0, dwExtraInfo=0)))
        ])
        time.sleep(TIMING.INPUT_CHAR)

def press_key(key: str) -> None:
    parts = [p.strip() for p in key.strip().lower().split("+") if p.strip()]
    vks = [VK_MAP[p] for p in parts]
    send_input([INPUT(type=INPUT_KEYBOARD, ii=INPUT_I(ki=KEYBDINPUT(wVk=vk, wScan=0, dwFlags=0, time=0, dwExtraInfo=0))) for vk in vks] +
               [INPUT(type=INPUT_KEYBOARD, ii=INPUT_I(ki=KEYBDINPUT(wVk=vk, wScan=0, dwFlags=KEYEVENTF_KEYUP, time=0, dwExtraInfo=0))) for vk in reversed(vks)])

@dataclass(frozen=True)
class Coordinate:
    x: float
    y: float
    
    def to_pixels(self, screen_width: int, screen_height: int) -> Tuple[int, int]:
        xn = max(0.0, min(1000.0, self.x))
        yn = max(0.0, min(1000.0, self.y))
        px = min(int(round((xn / 1000.0) * screen_width)), screen_width - 1)
        py = min(int(round((yn / 1000.0) * screen_height)), screen_height - 1)
        return (px, py)
    
    def signature(self) -> Tuple[float, float]:
        return (round(self.x, 1), round(self.y, 1))

@dataclass
class TextDocument:
    content: str
    path: str
    
    def get_excerpt(self, max_chars: int = 2000) -> str:
        if len(self.content) <= max_chars:
            return self.content
        return self.content[:max_chars] + f"\n\n[... {len(self.content) - max_chars} more chars ...]"
    
    def to_context_string(self) -> str:
        return f"DOCUMENT: {self.path}\n\nCONTENT:\n{self.get_excerpt()}"

def load_text_document(path: str) -> TextDocument:
    import os
    if not os.path.exists(path):
        raise FileNotFoundError(f"Text document not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    return TextDocument(content=content, path=path)