"""Starts Tierlist IA: applies a downloaded update, runs the server and restarts it when it asks (exit code 3).

If the server dies within 20 seconds right after an update, the previous version comes back on its own.
Arguments are passed through to servidor/servidor.py (e.g. --porta 4363).
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "servidor"))

RESTART = 3


def main() -> int:
    import atualizador

    just_updated = False
    while True:
        try:
            if atualizador.apply_pending(ROOT):
                just_updated = True
        except atualizador.UpdateError as e:
            print(f"[atualização] {e}", flush=True)
        started = time.monotonic()
        code = subprocess.call([sys.executable, str(ROOT / "servidor" / "servidor.py"), *sys.argv[1:]], cwd=ROOT)
        if code == RESTART:
            continue
        if code != 0 and just_updated and time.monotonic() - started < 20:
            print("[atualização] a versão nova não abriu; voltando para a anterior.", flush=True)
            if atualizador.revert(ROOT):
                just_updated = False
                continue
        return code


if __name__ == "__main__":
    sys.exit(main())
