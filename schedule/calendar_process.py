"""Own the calendar worker and its descendants for the whole job lifetime."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time


class CalendarJobCancelled(RuntimeError):
    pass


class _WindowsJob:
    """A kill-on-close Job Object also contains Git/credential-helper children."""
    def __init__(self):
        import ctypes
        from ctypes import wintypes

        class Limits(ctypes.Structure):
            _fields_ = [("process_time", ctypes.c_longlong), ("job_time", ctypes.c_longlong),
                        ("flags", wintypes.DWORD), ("min_ws", ctypes.c_size_t),
                        ("max_ws", ctypes.c_size_t), ("processes", wintypes.DWORD),
                        ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD),
                        ("scheduling", wintypes.DWORD)]

        class IO(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in
                        ("reads", "writes", "others", "read_bytes", "write_bytes", "other_bytes")]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [("basic", Limits), ("io", IO),
                        ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
                        ("peak_process", ctypes.c_size_t), ("peak_job", ctypes.c_size_t)]

        self.api = ctypes.WinDLL('kernel32', use_last_error=True)
        self.api.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.api.CreateJobObjectW.restype = wintypes.HANDLE
        self.api.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        self.api.SetInformationJobObject.restype = wintypes.BOOL
        self.api.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.api.AssignProcessToJobObject.restype = wintypes.BOOL
        self.api.CloseHandle.argtypes = [wintypes.HANDLE]
        self.api.CloseHandle.restype = wintypes.BOOL
        self.handle = self.api.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.api.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            error = ctypes.WinError(ctypes.get_last_error())
            self.close()
            raise error

    def assign(self, process):
        import ctypes
        if not self.api.AssignProcessToJobObject(self.handle, int(process._handle)):
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        if self.handle:
            self.api.CloseHandle(self.handle)
            self.handle = None


def run_child(command, *, env, cancel, timeout=300):
    """Return an exit code; cancellation/timeout always stop the process tree.

    Start suspended on Windows so it cannot spawn outside the Job Object before
    assignment. POSIX children start in their own session/process group.
    """
    if cancel.is_set():
        raise CalendarJobCancelled("日历任务已取消；若发布已经开始，请先修复发布状态")
    windows = sys.platform == 'win32'
    job = _WindowsJob() if windows else None
    process = None
    try:
        process = subprocess.Popen(
            command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env=env, start_new_session=not windows,
            creationflags=(subprocess.CREATE_NO_WINDOW | 0x4) if windows else 0,
        )
        if job is not None:
            import psutil
            job.assign(process)
            psutil.Process(process.pid).resume()
        deadline = time.monotonic() + timeout
        while process.poll() is None:
            if cancel.wait(0.05):
                raise CalendarJobCancelled("日历任务已取消；若发布已经开始，请先修复发布状态")
            if time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(command, timeout)
        return process.returncode
    finally:
        if job is not None:
            job.close()
        elif process is not None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if process is not None:
            # Also covers failure to assign a still-suspended Windows process.
            if process.poll() is None:
                process.kill()
            process.wait()
