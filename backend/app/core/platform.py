"""Platform adapter: feature code asks here, never `sys.platform` / `os.name` directly."""
import os
import sys

IS_WINDOWS = sys.platform == 'win32'
IS_LINUX = sys.platform.startswith('linux')
IS_MAC = sys.platform == 'darwin'


def exclusive_udp_bind_supported() -> bool:
    """Windows can bind UDP exclusively (SO_EXCLUSIVEADDRUSE) so two receivers cannot share the port."""
    return os.name == 'nt'


def cpu_count() -> int:
    return os.cpu_count() or 1


def total_memory_bytes() -> int | None:
    """Best effort, stdlib only; None when unknown."""
    try:
        if IS_LINUX:
            with open('/proc/meminfo', encoding='utf-8') as f:
                for line in f:
                    if line.startswith('MemTotal:'):
                        return int(line.split()[1]) * 1024
        if IS_WINDOWS:
            import ctypes

            class Status(ctypes.Structure):
                _fields_ = [('l', ctypes.c_ulong), ('m', ctypes.c_ulong), ('total', ctypes.c_ulonglong),
                            ('a', ctypes.c_ulonglong), ('tp', ctypes.c_ulonglong), ('ap', ctypes.c_ulonglong),
                            ('tv', ctypes.c_ulonglong), ('av', ctypes.c_ulonglong), ('ax', ctypes.c_ulonglong)]

            status = Status()
            status.l = ctypes.sizeof(Status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):  # type: ignore[attr-defined]
                return int(status.total)
    except Exception:
        return None
    return None


def resolve_performance_profile(setting: str, cpus: int | None = None, memory: int | None = None) -> str:
    """AUTO picks LOW_POWER on <=4 CPUs or <=4 GB RAM. LOW_POWER never changes recording rate/accuracy."""
    if setting in ('DESKTOP', 'LOW_POWER'):
        return setting
    cpus = cpu_count() if cpus is None else cpus
    memory = total_memory_bytes() if memory is None else memory
    if cpus <= 4 or (memory is not None and memory <= 4 * 1024 ** 3):
        return 'LOW_POWER'
    return 'DESKTOP'
