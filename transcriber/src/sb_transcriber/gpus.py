"""`--gpu 0`, `--gpu 0,1`, `--gpu all`: one worker process per GPU.

Each worker sees only its GPU (CUDA_VISIBLE_DEVICES), claims its own files (the server
never gives the same one to two workers: the faster GPU simply takes more), and prints
full lines, which this parent shows prefixed with the GPU ("[GPU 1] …"). Ctrl+C reaches
every worker (same console): each gives its file back.
"""

import os
import shutil
import subprocess
import sys
import threading

CHILD_FLAG = "--child"


def count() -> int:
    """The NVIDIA GPUs of this PC."""
    if shutil.which("nvidia-smi"):
        listed = subprocess.run(["nvidia-smi", "-L"], capture_output=True, text=True, check=False)
        found = [line for line in listed.stdout.splitlines() if line.startswith("GPU ")]
        if found:
            return len(found)
    from sb_transcriber.cuda import device_count

    return device_count()


def parse(value: str) -> list[int]:
    """'0' -> [0]; '0,1' -> [0, 1]; 'all' -> every GPU."""
    if value.strip().lower() == "all":
        found = count()
        if not found:
            raise SystemExit("No NVIDIA GPU found (see `transcriber devices`)")
        return list(range(found))
    try:
        gpus = sorted({int(part) for part in value.split(",") if part.strip()})
    except ValueError:
        raise SystemExit(f"--gpu: a number, a list (0,1) or all, not {value!r}") from None
    if not gpus:
        raise SystemExit("--gpu: which GPU?")
    return gpus


def use(gpu: int) -> None:
    """This process works on `gpu` only (call before CUDA is loaded): it is then device 0."""
    os.environ["CUDA_VISIBLE_DEVICES"] = str(gpu)


def _with_gpu(argv: list[str], gpu: int) -> list[str]:
    """The command line with `--gpu <gpu>` in place of the given one."""
    out: list[str] = []
    skip = False
    for arg in argv:
        if skip:
            skip = False
            continue
        if arg == "--gpu":
            skip = True
            continue
        if arg.startswith("--gpu="):
            continue
        out.append(arg)
    return [*out, "--gpu", str(gpu), CHILD_FLAG]


def run_workers(argv: list[str], gpus: list[int]) -> int:
    """Runs the command once per GPU and waits; returns the worst exit code."""
    workers: list[tuple[int, subprocess.Popen[str]]] = []
    lock = threading.Lock()
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONUTF8": "1"}
    for gpu in gpus:
        process = subprocess.Popen(
            [sys.executable, "-m", "sb_transcriber", *_with_gpu(argv, gpu)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        workers.append((gpu, process))

    def relay(gpu: int, process: subprocess.Popen[str]) -> None:
        assert process.stdout is not None
        for line in process.stdout:
            with lock:
                print(f"[GPU {gpu}] {line.rstrip()}", flush=True)

    threads = [threading.Thread(target=relay, args=w, daemon=True) for w in workers]
    for thread in threads:
        thread.start()
    try:
        codes = [process.wait() for _, process in workers]
    except KeyboardInterrupt:
        # The workers got Ctrl+C too: they give their files back, then stop.
        codes = [process.wait() for _, process in workers]
        raise
    finally:
        for thread in threads:
            thread.join(timeout=2)
    return max(codes, default=0)
