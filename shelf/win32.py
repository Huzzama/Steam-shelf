"""
The Windows calls Steam Shelf needs, through ctypes (no pywin32 to package):
optical drives, whether a disc is in one, uptime, a single-instance mutex,
and a hidden window that receives WM_DEVICECHANGE / WM_POWERBROADCAST.
shelf.linux offers the same functions on Linux; shelf.host picks one.

Imported only on Windows.
"""
from __future__ import annotations

import ctypes
import string
from ctypes import wintypes
from typing import Callable, Optional

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_POWERBROADCAST = 0x0218
WM_DEVICECHANGE = 0x0219
DBT_DEVICEARRIVAL = 0x8000
DBT_DEVICEREMOVECOMPLETE = 0x8004
DBT_DEVTYP_VOLUME = 0x00000002
DBTF_MEDIA = 0x0001
PBT_APMSUSPEND = 0x0004
PBT_APMRESUMESUSPEND = 0x0007
PBT_APMRESUMEAUTOMATIC = 0x0012
DRIVE_CDROM = 5
ERROR_ALREADY_EXISTS = 183
SEM_FAILCRITICALERRORS = 0x0001
SEM_NOOPENFILEERRORBOX = 0x8000

AGENT_CLASS = "SteamShelfAgentWindow"
AGENT_MUTEX = "Local\\SteamShelfAgent"
BURNER_MUTEX = "Local\\SteamShelfBurner"      # held while the app window is open
SYNCHRONIZE = 0x00100000


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]


class DEV_BROADCAST_HDR(ctypes.Structure):
    _fields_ = [("dbch_size", wintypes.DWORD), ("dbch_devicetype", wintypes.DWORD), ("dbch_reserved", wintypes.DWORD)]


class DEV_BROADCAST_VOLUME(ctypes.Structure):
    _fields_ = [("dbcv_size", wintypes.DWORD), ("dbcv_devicetype", wintypes.DWORD), ("dbcv_reserved", wintypes.DWORD),
                ("dbcv_unitmask", wintypes.DWORD), ("dbcv_flags", wintypes.WORD)]


user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
user32.RegisterClassW.restype = wintypes.ATOM
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU,
                                   wintypes.HINSTANCE, wintypes.LPVOID]
user32.CreateWindowExW.restype = wintypes.HWND
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.GetMessageW.restype = wintypes.BOOL
user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.restype = LRESULT
user32.PostQuitMessage.argtypes = [ctypes.c_int]
user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowW.restype = wintypes.HWND
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostMessageW.restype = wintypes.BOOL
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
kernel32.GetLogicalDrives.restype = wintypes.DWORD
kernel32.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
kernel32.GetDriveTypeW.restype = wintypes.UINT
kernel32.GetVolumeInformationW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD,
                                           ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD),
                                           ctypes.POINTER(wintypes.DWORD), wintypes.LPWSTR, wintypes.DWORD]
kernel32.GetVolumeInformationW.restype = wintypes.BOOL
kernel32.GetTickCount64.restype = ctypes.c_ulonglong
kernel32.SetErrorMode.argtypes = [wintypes.UINT]
kernel32.SetErrorMode.restype = wintypes.UINT
kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.CreateMutexW.restype = wintypes.HANDLE
kernel32.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.OpenMutexW.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL


def quiet_errors() -> None:
    """No 'insert a disk' system dialogs when we probe an empty drive."""
    kernel32.SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOOPENFILEERRORBOX)


def uptime() -> float:
    return kernel32.GetTickCount64() / 1000.0


def optical_drives() -> list[str]:
    """['D:', 'E:'] — real drives and mounted ISOs (both report DRIVE_CDROM)."""
    mask = kernel32.GetLogicalDrives()
    out = []
    for i, letter in enumerate(string.ascii_uppercase):
        if mask & (1 << i) and kernel32.GetDriveTypeW(f"{letter}:\\") == DRIVE_CDROM:
            out.append(f"{letter}:")
    return out


def volume_info(drive: str) -> Optional[tuple[str, int]]:
    """(label, serial) if a readable disc is in the drive, else None."""
    name = ctypes.create_unicode_buffer(261)
    fs = ctypes.create_unicode_buffer(261)
    serial = wintypes.DWORD()
    ok = kernel32.GetVolumeInformationW(f"{drive}\\", name, 261, ctypes.byref(serial), None, None, fs, 261)
    return (name.value, serial.value) if ok else None


def drives_with_media() -> set[str]:
    return {d for d in optical_drives() if volume_info(d) is not None}


def drive_name(drive: str) -> str:
    return drive


def drive_label(drive: str) -> str:
    return drive


def access_problem() -> bool:
    return False                       # any user may read a CD/DVD drive on Windows


def single_instance(name: str = AGENT_MUTEX) -> Optional[int]:
    """A handle if we are the only one, None if another agent already runs. Keep the handle alive."""
    h = kernel32.CreateMutexW(None, False, name)
    if not h or ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        return None
    return h


def hold_burner_mode() -> Optional[int]:
    """The app window calls this once and keeps the handle: burner mode until the process ends."""
    return kernel32.CreateMutexW(None, False, BURNER_MUTEX) or None


def burner_mode_on() -> bool:
    h = kernel32.OpenMutexW(SYNCHRONIZE, False, BURNER_MUTEX)
    if not h:
        return False
    kernel32.CloseHandle(h)
    return True


def agent_window() -> int:
    return user32.FindWindowW(AGENT_CLASS, None) or 0


def agent_running() -> bool:
    return bool(agent_window())


def stop_agent() -> bool:
    hwnd = agent_window()
    return bool(hwnd) and bool(user32.PostMessageW(hwnd, WM_CLOSE, 0, 0))


def _letters(mask: int) -> list[str]:
    return [f"{c}:" for i, c in enumerate(string.ascii_uppercase) if mask & (1 << i)]


class DeviceWindow:
    """
    Hidden top-level window (volume broadcasts never reach message-only windows).
    Calls on_volume(kind, drives, is_media) with kind "arrival"/"removal", and
    on_power(event) with "suspend"/"resume". Runs the message loop in run().
    """

    def __init__(self, on_volume: Callable[[str, list[str], bool], None], on_power: Callable[[str], None]):
        self._on_volume, self._on_power = on_volume, on_power
        self._proc = WNDPROC(self._wndproc)           # keep a reference: ctypes callbacks die with it
        hinst = kernel32.GetModuleHandleW(None)
        wc = WNDCLASSW()
        wc.lpfnWndProc = self._proc
        wc.hInstance = hinst
        wc.lpszClassName = AGENT_CLASS
        if not user32.RegisterClassW(ctypes.byref(wc)):
            raise ctypes.WinError(ctypes.get_last_error())
        self.hwnd = user32.CreateWindowExW(0, AGENT_CLASS, "Steam Shelf Agent", 0, 0, 0, 0, 0, None, None, hinst, None)
        if not self.hwnd:
            raise ctypes.WinError(ctypes.get_last_error())

    def _wndproc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == WM_DEVICECHANGE and wparam in (DBT_DEVICEARRIVAL, DBT_DEVICEREMOVECOMPLETE) and lparam:
                hdr = ctypes.cast(lparam, ctypes.POINTER(DEV_BROADCAST_HDR)).contents
                if hdr.dbch_devicetype == DBT_DEVTYP_VOLUME:
                    vol = ctypes.cast(lparam, ctypes.POINTER(DEV_BROADCAST_VOLUME)).contents
                    kind = "arrival" if wparam == DBT_DEVICEARRIVAL else "removal"
                    self._on_volume(kind, _letters(vol.dbcv_unitmask), bool(vol.dbcv_flags & DBTF_MEDIA))
                return 1
            if msg == WM_POWERBROADCAST:
                if wparam == PBT_APMSUSPEND:
                    self._on_power("suspend")
                elif wparam in (PBT_APMRESUMEAUTOMATIC, PBT_APMRESUMESUSPEND):
                    self._on_power("resume")
                return 1
            if msg == WM_CLOSE:
                user32.DestroyWindow(hwnd)
                return 0
            if msg == WM_DESTROY:
                user32.PostQuitMessage(0)
                return 0
        except Exception:          # never let an exception cross the C boundary
            import logging
            logging.getLogger("shelf.agent").exception("window procedure")
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def run(self) -> None:
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))


def watch(on_volume: Callable[[str, list[str], bool], None], on_power: Callable[[str], None]) -> None:
    """The agent's main loop on Windows: blocks until the window is closed (stop_agent)."""
    DeviceWindow(on_volume, on_power).run()
