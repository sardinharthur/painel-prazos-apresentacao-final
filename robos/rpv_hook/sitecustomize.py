"""Hook não-invasivo para capturar logs e permitir Chat Interativo no Console do Site (sem janela CMD)."""
from __future__ import annotations

import builtins
import getpass
import os
import re
import sys

_LOG_PATH = os.environ.get("PAINEL_RPV_LOG")

if _LOG_PATH:
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stdin, "reconfigure"):
            sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    _ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

    def _append_log(line: str) -> None:
        cleaned = _ANSI_RE.sub("", line or "").rstrip("\r\n")
        if not cleaned.strip():
            return
        try:
            with open(_LOG_PATH, "a", encoding="utf-8", errors="replace") as f:
                f.write(cleaned + "\n")
        except Exception:
            pass

    class _TeeStream:
        def __init__(self, stream):
            self._stream = stream
            self._buf = ""

        def write(self, data):
            res = 0
            try:
                if self._stream is not None:
                    res = self._stream.write(data)
                    self._stream.flush()
            except Exception:
                pass
            if data:
                self._buf += str(data)
                while "\n" in self._buf:
                    line, self._buf = self._buf.split("\n", 1)
                    _append_log(line)
            return res

        def flush(self):
            try:
                if self._stream is not None:
                    return self._stream.flush()
            except Exception:
                return None

        def __getattr__(self, name):
            return getattr(self._stream, name)

    sys.stdout = _TeeStream(sys.stdout)
    sys.stderr = _TeeStream(sys.stderr)

    _orig_input = builtins.input

    def _hooked_input(prompt: str = "") -> str:
        if prompt and str(prompt).strip():
            _append_log(f"💬 Console aguarda resposta: {str(prompt).strip()}")
        else:
            _append_log("💬 Console aguarda confirmação (envie ENTER pelo chat do console)...")
        try:
            ans = _orig_input("")
        except EOFError:
            ans = ""
        if ans.strip():
            _append_log(f"↪ Resposta recebida no console: {ans.strip()}")
        else:
            _append_log("↪ Confirmação (ENTER) recebida no console.")
        return ans

    builtins.input = _hooked_input

    _orig_getpass = getpass.getpass

    def _hooked_getpass(prompt: str = "Senha: ", stream=None) -> str:
        _append_log(f"🔒 Console aguarda credencial: {str(prompt).strip()}")
        try:
            line = sys.stdin.readline()
            ans = line.rstrip("\r\n") if line else ""
        except Exception:
            ans = ""
        _append_log("↪ Credencial recebida no console (oculta).")
        return ans

    getpass.getpass = _hooked_getpass
