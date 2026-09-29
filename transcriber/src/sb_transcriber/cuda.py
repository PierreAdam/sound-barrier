"""The NVIDIA libraries (cuBLAS, cuDNN) come from pip (the `cuda` extra), not from a
system-wide CUDA install: they must be made findable before CTranslate2 (faster-whisper's
engine) loads.

- Windows: their DLL folders are added to the DLL search path.
- Linux: `transcriber.sh` puts their folders in LD_LIBRARY_PATH (read by the loader when the
  process starts, so setting it from Python is too late); when started otherwise, they are
  preloaded here, which makes CTranslate2's own loading find them.
"""

import contextlib
import ctypes
import os
import sys
from pathlib import Path


def _nvidia_folders(pattern: str) -> list[Path]:
    """`site-packages/nvidia/<package>/<pattern>` folders."""
    try:
        import nvidia  # pyright: ignore[reportMissingImports]  # namespace package
    except ImportError:
        return []
    return sorted(
        folder for root in getattr(nvidia, "__path__", []) for folder in Path(root).glob(pattern)
    )


def _windows() -> list[Path]:
    found = [folder for folder in _nvidia_folders("*/bin") if any(folder.glob("*.dll"))]
    for folder in found:
        os.add_dll_directory(str(folder))
    if found:  # some loaders only look at PATH
        os.environ["PATH"] = os.pathsep.join([*map(str, found), os.environ.get("PATH", "")])
    return found


def _linux() -> list[Path]:
    folders = _nvidia_folders("*/lib")
    known = set(os.environ.get("LD_LIBRARY_PATH", "").split(":"))
    if all(str(folder) in known for folder in folders):
        return folders  # transcriber.sh did it
    # cuBLAS Lt before cuBLAS (which needs it), cuDNN's parts after cuDNN itself.
    order = ("libcublasLt.so", "libcublas.so", "libcudnn.so")
    libraries = [lib for folder in folders for lib in folder.glob("lib*.so.*")]
    libraries.sort(
        key=lambda lib: next((i for i, n in enumerate(order) if lib.name.startswith(n)), 9)
    )
    for library in libraries:
        # A part needing a library this PC lacks: CTranslate2 reports it if it is used.
        with contextlib.suppress(OSError):
            ctypes.CDLL(str(library), mode=ctypes.RTLD_GLOBAL)
    return folders


def add_nvidia_libraries() -> list[Path]:
    """Makes the pip NVIDIA libraries findable; returns their folders. Call before
    importing faster_whisper."""
    if sys.platform == "win32":
        return _windows()
    if sys.platform.startswith("linux"):
        return _linux()
    return []


def device_count() -> int:
    add_nvidia_libraries()
    import ctranslate2

    return ctranslate2.get_cuda_device_count()
