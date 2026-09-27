"""Joined in-process heartbeat for blocking foreground work; no detached jobs."""
from contextlib import contextmanager
from threading import Event, Thread


@contextmanager
def progress(label, interval=30):
    stopped = Event()
    def heartbeat():
        while not stopped.wait(interval):
            print(f"{label}: still working…", flush=True)
    print(f"{label}…", flush=True)
    thread = Thread(target=heartbeat)
    thread.start()
    try:
        yield
    finally:
        stopped.set()
        thread.join()


if __name__ == "__main__":
    import subprocess
    import sys
    # Run pip using this exact venv, inheriting its visible progress output.
    with progress("Installing Python packages"):
        result = subprocess.run([sys.executable, "-m", "pip", "install", *sys.argv[1:]])
    raise SystemExit(result.returncode)
