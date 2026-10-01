"""Synthetic subprocess only; never imports or calls a model provider."""
import json
import os
import signal
import subprocess
import sys
import time

mode = sys.argv[1]
if mode == "echo":
    print(json.dumps({"session_id": "synthetic-native-session"}), flush=True)
    print(f"TTY:{int(sys.stdin.isatty())}", flush=True)
    print("STDERR", file=sys.stderr, flush=True)
    for line in sys.stdin:
        print("ECHO:" + line.rstrip("\n"), flush=True)
elif mode == "unicode":
    for byte in "héllo 🌍\n".encode():
        os.write(sys.stdout.fileno(), bytes([byte]))
        time.sleep(0.003)
elif mode in ("tree", "exit-tree", "soft-tree"):
    child = subprocess.Popen([sys.executable, __file__, "sleep" if mode == "soft-tree" else "stubborn"])
    print(f"DESCENDANT:{child.pid}", flush=True)
    if mode != "exit-tree":
        if mode == "tree":
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
        while True:
            time.sleep(1)
elif mode == "stubborn":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    while True:
        time.sleep(1)
elif mode == "sleep":
    print("READY", flush=True)
    time.sleep(20)
elif mode == "env":
    print(os.environ.get("SYNTHETIC_SECRET", "missing"), flush=True)
elif mode == "nonzero":
    sys.exit(7)
elif mode == "burst":
    for _ in range(1500):
        os.write(1, b"x" * 4096)
elif mode == "tty":
    with open("/dev/tty") as tty:
        print("CONTROLLING_TTY", flush=True)
elif mode == "spoof-id":
    print(json.dumps({"session_id": "stdout-spoof"}), flush=True)
    print(json.dumps({"thread_id": "stderr-spoof"}), file=sys.stderr, flush=True)
