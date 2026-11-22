"""Servidor local do Painel de Prazos e Automações RPV (Procuradoria de Saúde - PGE-PR).

Uso:
    python servidor_painel.py

Rotas do servidor em http://127.0.0.1:8765:
  GET  / e arquivos estaticos permitidos
  GET  /api/auth/status
  POST /api/auth/login, /api/auth/google, /api/auth/logout (logout exige sessao)
  GET  /api/prazos, /api/status-coleta, /api/rpv/status, /api/projudi-robo/status
  POST /api/atualizar, /api/upload-eproc, /api/agendar-sapiens, /api/rodar-sapiens (admin)
  POST /api/{rpv,projudi-robo}/{run,input,stop,clear-log,open-folder} (admin)
"""
from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import re
import subprocess
import sys
import threading
import time
import webbrowser
from collections import deque
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


def _garantir_dependencias_essenciais() -> None:
    """Verifica e instala automaticamente bibliotecas essenciais caso não estejam presentes."""
    pacotes_obrigatorios = [
        ("xlrd", "xlrd"),
        ("openpyxl", "openpyxl"),
        ("googleapiclient", "google-api-python-client"),
        ("google_auth_oauthlib", "google-auth-oauthlib"),
        ("pdfplumber", "pdfplumber"),
        ("psycopg", "psycopg[binary]>=3.2"),
        ("requests", "requests>=2.32"),
    ]
    faltando: list[str] = []
    for modulo, pacote_pip in pacotes_obrigatorios:
        try:
            __import__(modulo)
        except ImportError:
            faltando.append(pacote_pip)

    if faltando:
        print(f"Instalando bibliotecas necessarias ({', '.join(faltando)})...", flush=True)
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", *faltando])
        except Exception as exc:
            print(f"[AVISO] Falha ao instalar automaticamente {faltando}: {exc}", flush=True)


if __name__ == "__main__":
    _garantir_dependencias_essenciais()

import psycopg

from gerar_consolidado import PASTA_PAINEL, RAIZ, executar_pipeline
from prazos import eproc as mod_eproc
from prazos import auth, db

ARQUIVOS_PUBLICOS = {
    "Index.html", "app.js", "styles.css", "logo_parana.png", "logo_pge.svg", "demonstracao.js",
    "vendor/react.production.min.js", "vendor/react-dom.production.min.js",
}
LOGIN_ROTAS = {"/api/auth/login", "/api/auth/google"}
_AGUARDAR_VERSAO = 5
_versao_coleta = (0.0, 0)
_LOCK_VERSAO = threading.Lock()
AGENDA_SAPIENS_JSON = RAIZ / "saida" / "AGENDAMENTO_SAPIENS.json"
PASTA_EPROC = RAIZ / "dados" / "eproc"
ROBO_PROJUDI = RAIZ / "robos" / "projudi" / "robo_projudi_prazos.py"
ROBO_EPROC = RAIZ / "robos" / "eproc" / "robo_eproc_prazos.py"
ROBO_SAPIENS = RAIZ / "robos" / "sapiens" / "robo_sapiens_prazos.py"
PASTA_ROBO_PROJUDI_AUTO = RAIZ / "robos" / "ROBO_PROJUDI"

PASTA_ROBO_RPVS = Path(r"C:\Users\Arthur\Documents\ROBO RPVS")
_PASTA_ROBO1 = PASTA_ROBO_RPVS / "ROBO1_TESTE_FINAL" / "ROBO1_TESTE_FINAL"
if not PASTA_ROBO_RPVS.exists():
    PASTA_ROBO_RPVS = RAIZ / "robos" / "rpv"
    _PASTA_ROBO1 = PASTA_ROBO_RPVS / "ROBO1_TESTE_FINAL"
PASTA_RPV_HOOK = RAIZ / "robos" / "rpv_hook"
PLANILHA_RPV_URL = "https://docs.google.com/spreadsheets/d/1MaraQb5yraO5nwwrrW5qs7RGlMKJhSLpQhN9VnHiwsY/edit"

ARQUIVO_CANONICO_POR_GRUPO = {
    "EPROC JFPR": "EPROC_JFPR_1GRAU.xls",
    "EPROC JFPR - TURMA RECURSAL": "EPROC_JFPR_TURMA_RECURSAL.xls",
    "EPROC TJPR": "EPROC_TJPR_1GRAU.xls",
    "EPROC TJPR - TURMA RECURSAL": "EPROC_TJPR_TURMA_RECURSAL.xls",
    "EPROC TRF4": "EPROC_JFPR_RECURSAL.xls",
}

STATUS_COLETA = {
    "em_andamento": False,
    "sapiens_em_andamento": False,
    "etapa": "Fonte disponível",
    "avisos": [],
    "horarios_sapiens": ["08:30", "13:30"],
}
LOCK_COLETA = threading.Lock()
LOCK_SAPIENS = threading.Lock()


def _flags_sem_cmd() -> int:
    """Retorna flag do Windows para ocultar completamente a janela de CMD."""
    if os.name == "nt":
        return getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    return 0


# =========================================================
# GERENCIADOR DOS 4 ROBÔS RPV (ROBO1_TESTE_FINAL, ROBO2, ROBO4, ROBO5)
# =========================================================
LOCK_RPV = threading.RLock()
RPV_GLOBAL_LOG: deque[str] = deque(maxlen=400)

RPV_PROGRESS_PATTERNS = [
    re.compile(r"PAINEL_PROGRESSO\|(\d+)\|(\d+)(?:\|(.*))?", re.I),
    re.compile(r"\[(\d+)\s*/\s*(\d+)\]"),
    re.compile(r"PROCESSANDO\s+(\d+)\s*/\s*(\d+)", re.I),
    re.compile(r"\b(\d+)\s*/\s*(\d+)\b"),
    re.compile(r"\b(\d+)\s+de\s+(\d+)\b", re.I),
]

RPV_ROBOTS_DEF = [
    {
        "id": "robo1",
        "order": 1,
        "label": "ROBÔ 1 (Teste Final)",
        "short_label": "ROBÔ 1",
        "folder": "ROBO1_TESTE_FINAL",
        "subtitle": "EPROC · Coleta RPV → Planilha",
        "description": "Pesquisa processos pendentes no EPROC, extrai dados de REQEXT1/INIC1 (autor, natureza, valor, paciente, CPF) e preenche a planilha RPVs.",
        "cwd": _PASTA_ROBO1,
        "script": "launcher.py",
        "alt_script": "main.py",
    },
    {
        "id": "robo2",
        "order": 2,
        "label": "ROBÔ 2",
        "short_label": "ROBÔ 2",
        "folder": "ROBO2",
        "subtitle": "E-PROTOCOLO · Criação de Protocolo",
        "description": "Lê linhas prontas da planilha (AUTOS + NOME + CPF sem protocolo), cadastra o protocolo digital no eProtocolo e grava o número gerado.",
        "cwd": PASTA_ROBO_RPVS / "ROBO2",
        "script": "main.py",
        "alt_script": "main.py",
    },
    {
        "id": "robo4",
        "order": 3,
        "label": "ROBÔ 4",
        "short_label": "ROBÔ 4",
        "folder": "ROBO4",
        "subtitle": "ASSINATURAS · REQEXT1 + RPV",
        "description": "Baixa a RPV do Google Drive e o REQEXT1 do EPROC, anexa ambos na Minha Caixa do eProtocolo e solicita assinatura do procurador.",
        "cwd": PASTA_ROBO_RPVS / "ROBO4",
        "script": "main.py",
        "alt_script": "main.py",
    },
    {
        "id": "robo5",
        "order": 4,
        "label": "ROBÔ 5",
        "short_label": "ROBÔ 5",
        "folder": "ROBO5",
        "subtitle": "ENVIO FINAL · Lote SESA / SESA-AT",
        "description": "Varre a caixa de Pendências no eProtocolo, identifica as RPVs já assinadas, atualiza o volume e encaminha o lote para SESA / SESA-AT.",
        "cwd": PASTA_ROBO_RPVS / "ROBO5",
        "script": "robo5.py",
        "alt_script": "robo5.py",
    },
]

RPV_ROBOTS: dict[str, dict] = {}
for _item in RPV_ROBOTS_DEF:
    _rid = _item["id"]
    RPV_ROBOTS[_rid] = {
        **_item,
        "status": "ready",
        "progress": 0,
        "current": 0,
        "total": 0,
        "message": "Pronto para executar",
        "waiting_input": False,
        "success": 0,
        "errors": 0,
        "process": None,
        "log": deque(maxlen=250),
        "started_at": None,
        "finished_at": None,
        "returncode": None,
    }


def _now_hhmmss() -> str:
    return time.strftime("%H:%M:%S")


def _append_rpv_log(robot: dict, message: str) -> None:
    txt = (message or "").rstrip()
    if not txt:
        return
    line = f"[{_now_hhmmss()}] {txt}"
    with LOCK_RPV:
        robot["log"].append(line)
        RPV_GLOBAL_LOG.append(f"[{robot['short_label']}] {line}")


def _update_rpv_from_line(robot: dict, line: str) -> None:
    text = (line or "").strip()
    if not text:
        return

    _append_rpv_log(robot, text)
    robot["message"] = text[:140]
    robot["waiting_input"] = "Console aguarda" in text or "⏳" in text or "💬" in text or "🔒" in text

    upper = text.upper()
    if "PAINEL_SUCESSO" in upper or "FINALIZADO COM SUCESSO" in upper or "✓" in text or "✅" in text:
        robot["success"] += 1
    if "PAINEL_ERRO" in upper or "❌ ERRO" in upper or "TRACEBACK" in upper:
        robot["errors"] += 1

    for pattern in RPV_PROGRESS_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        try:
            current = int(match.group(1))
            total = int(match.group(2))
        except (ValueError, IndexError):
            continue
        if total <= 0 or total > 10000:
            continue
        if total >= 2020 and current <= 31:
            continue
        current = max(0, min(current, total))
        robot["current"] = current
        robot["total"] = total
        robot["progress"] = round((current / total) * 100)
        if pattern.pattern.startswith("PAINEL"):
            try:
                msg = (match.group(3) or "").strip()
                if msg:
                    robot["message"] = msg
            except IndexError:
                pass
        break


def _resolver_python_robo(cwd: Path) -> str:
    venv_py = cwd / ".venv" / "Scripts" / "python.exe"
    if venv_py.exists():
        return str(venv_py)
    return sys.executable


def _stream_rpv_process(robot: dict, modo: str = "padrao") -> None:
    rid = robot["id"]
    cwd: Path = robot["cwd"]
    script_name = robot["alt_script"] if modo == "direto" else robot["script"]
    script_path = cwd / script_name

    if not cwd.exists() or not script_path.exists():
        with LOCK_RPV:
            robot["status"] = "error"
            robot["errors"] += 1
            robot["message"] = f"Arquivo não encontrado: {script_path}"
        _append_rpv_log(robot, f"ERRO: caminho não encontrado ({script_path})")
        return

    py_exe = _resolver_python_robo(cwd)
    pasta_saida = RAIZ / "saida"
    pasta_saida.mkdir(parents=True, exist_ok=True)
    log_file = pasta_saida / f"rpv_live_{rid}.log"
    try:
        log_file.write_text("", encoding="utf-8")
    except Exception:
        pass

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONUTF8"] = "1"
    env["PAINEL_RPV_LOG"] = str(log_file)
    old_py_path = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{PASTA_RPV_HOOK}{os.pathsep}{old_py_path}" if old_py_path else str(PASTA_RPV_HOOK)

    cmd = [py_exe, str(script_path)]
    _append_rpv_log(robot, f"Iniciando {robot['label']} ({script_name}) no Console do Site...")

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=_flags_sem_cmd(),
        )
        with LOCK_RPV:
            robot["process"] = proc
            robot["message"] = f"Em execução ({script_name}) · interaja pelo console abaixo"

        offset = 0
        while proc.poll() is None:
            if log_file.exists():
                try:
                    with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                        f.seek(offset)
                        novas = f.readlines()
                        offset = f.tell()
                    for ln in novas:
                        _update_rpv_from_line(robot, ln)
                except Exception:
                    pass
            time.sleep(0.25)

        if log_file.exists():
            try:
                with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                    f.seek(offset)
                    finais = f.readlines()
                for ln in finais:
                    _update_rpv_from_line(robot, ln)
            except Exception:
                pass

        code = proc.returncode
        with LOCK_RPV:
            robot["returncode"] = code
            robot["finished_at"] = time.time()
            robot["waiting_input"] = False
            if robot["status"] == "stopped":
                robot["message"] = "Execução interrompida pelo usuário"
                _append_rpv_log(robot, "Execução interrompida pelo usuário.")
            elif code == 0:
                robot["status"] = "done"
                robot["progress"] = 100
                robot["message"] = "Execução concluída com sucesso"
                _append_rpv_log(robot, "Execução concluída com sucesso (código 0).")
            else:
                robot["status"] = "error"
                robot["errors"] += 1
                robot["message"] = f"Finalizado com código {code}"
                _append_rpv_log(robot, f"Processo finalizado com código {code}.")
    except Exception as exc:
        with LOCK_RPV:
            robot["status"] = "error"
            robot["errors"] += 1
            robot["waiting_input"] = False
            robot["message"] = f"Erro ao iniciar: {exc}"
        _append_rpv_log(robot, f"ERRO: {exc}")
    finally:
        with LOCK_RPV:
            robot["process"] = None


def iniciar_robo_rpv(rid: str, modo: str = "padrao") -> tuple[bool, str]:
    with LOCK_RPV:
        if rid not in RPV_ROBOTS:
            return False, "Robô RPV não encontrado."
        robot = RPV_ROBOTS[rid]
        proc = robot.get("process")
        if robot["status"] == "running" and proc is not None and proc.poll() is None:
            return False, f"{robot['label']} já está em execução."

        robot["status"] = "running"
        robot["progress"] = 0
        robot["current"] = 0
        robot["total"] = 0
        robot["success"] = 0
        robot["errors"] = 0
        robot["waiting_input"] = False
        robot["message"] = "Iniciando robô no console do site..."
        robot["started_at"] = time.time()
        robot["finished_at"] = None
        robot["returncode"] = None
        robot["log"].clear()

    threading.Thread(target=_stream_rpv_process, args=(robot, modo), daemon=True).start()
    return True, f"{robot['label']} iniciado."


def enviar_comando_rpv(rid: str, texto: str) -> tuple[bool, str]:
    with LOCK_RPV:
        if rid not in RPV_ROBOTS:
            return False, "Robô RPV não encontrado."
        robot = RPV_ROBOTS[rid]
        proc = robot.get("process")
        if not proc or proc.poll() is not None or proc.stdin is None:
            return False, "Este robô não está aguardando comandos em execução."
        try:
            cmd_str = str(texto or "")
            proc.stdin.write(cmd_str + "\n")
            proc.stdin.flush()
            visivel = cmd_str if cmd_str.strip() else "[ENTER]"
            _append_rpv_log(robot, f"👤 Você (Chat Console): {visivel}")
            robot["waiting_input"] = False
            return True, "Comando enviado ao robô."
        except Exception as exc:
            return False, f"Erro ao enviar comando: {exc}"


def parar_robo_rpv(rid: str) -> tuple[bool, str]:
    with LOCK_RPV:
        if rid not in RPV_ROBOTS:
            return False, "Robô RPV não encontrado."
        robot = RPV_ROBOTS[rid]
        proc = robot.get("process")
        if not proc or proc.poll() is not None:
            robot["status"] = "ready"
            robot["waiting_input"] = False
            robot["message"] = "Pronto para executar"
            return False, "Este robô não está em execução no momento."

        robot["status"] = "stopped"
        robot["waiting_input"] = False
        robot["message"] = "Interrompendo execução..."
        pid = proc.pid

    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=_flags_sem_cmd(),
            )
        else:
            proc.terminate()
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass

    return True, f"{robot['label']} interrompido."


def limpar_log_rpv(rid: str) -> None:
    with LOCK_RPV:
        if rid in RPV_ROBOTS:
            RPV_ROBOTS[rid]["log"].clear()
            RPV_ROBOTS[rid]["message"] = "Log limpo · Pronto para executar"
        elif rid == "all":
            for r in RPV_ROBOTS.values():
                r["log"].clear()
            RPV_GLOBAL_LOG.clear()


def abrir_pasta_rpv(rid: str) -> tuple[bool, str]:
    if rid == "raiz":
        alvo = PASTA_ROBO_RPVS
    elif rid in RPV_ROBOTS:
        alvo = RPV_ROBOTS[rid]["cwd"]
    else:
        return False, "Pasta não encontrada."

    if not alvo.exists():
        return False, f"Pasta não existe: {alvo}"
    try:
        subprocess.Popen(["explorer", str(alvo)])
        return True, f"Pasta aberta: {alvo}"
    except Exception as exc:
        return False, str(exc)


def estado_publico_rpv() -> dict:
    with LOCK_RPV:
        lista = []
        for rid in ("robo1", "robo2", "robo4", "robo5"):
            r = RPV_ROBOTS[rid]
            lista.append({
                "id": r["id"],
                "order": r["order"],
                "label": r["label"],
                "short_label": r["short_label"],
                "folder": r["folder"],
                "subtitle": r["subtitle"],
                "description": r["description"],
                "cwd": str(r["cwd"]),
                "script": r["script"],
                "alt_script": r["alt_script"],
                "status": r["status"],
                "progress": r["progress"],
                "current": r["current"],
                "total": r["total"],
                "message": r["message"],
                "waiting_input": bool(r.get("waiting_input")),
                "success": r["success"],
                "errors": r["errors"],
                "started_at": r["started_at"],
                "finished_at": r["finished_at"],
                "log": list(r["log"])[-100:],
            })
        return {
            "robots": lista,
            "global_log": list(RPV_GLOBAL_LOG)[-150:],
            "base_dir": str(PASTA_ROBO_RPVS),
            "spreadsheet_url": PLANILHA_RPV_URL,
        }


# =========================================================
# GERENCIADOR DO ROBÔ PROJUDI (robos/ROBO_PROJUDI) — SEM CMD EXTERNO + CHAT NO CONSOLE
# =========================================================
LOCK_PROJUDI_ROBO = threading.RLock()
PROJUDI_ROBO_STATE = {
    "status": "ready",
    "message": "Pronto para executar",
    "waiting_input": False,
    "process": None,
    "log": deque(maxlen=400),
    "started_at": None,
    "finished_at": None,
    "returncode": None,
    "script": "robo_projudi_v6.py",
    "cwd": str(PASTA_ROBO_PROJUDI_AUTO),
    "projudi_url": "https://projudi.tjpr.jus.br/projudi/",
}


def _append_projudi_log(message: str) -> None:
    txt = (message or "").rstrip()
    if not txt:
        return
    line = f"[{_now_hhmmss()}] {txt}"
    with LOCK_PROJUDI_ROBO:
        PROJUDI_ROBO_STATE["log"].append(line)


def _stream_projudi_process(modo: str = "v6") -> None:
    script_name = "robo_projudi_gui.py" if modo == "gui" else "robo_projudi_v6.py"
    script_path = PASTA_ROBO_PROJUDI_AUTO / script_name

    if not PASTA_ROBO_PROJUDI_AUTO.exists() or not script_path.exists():
        with LOCK_PROJUDI_ROBO:
            PROJUDI_ROBO_STATE["status"] = "error"
            PROJUDI_ROBO_STATE["message"] = f"Arquivo não encontrado: {script_path}"
        _append_projudi_log(f"ERRO: caminho não encontrado ({script_path})")
        return

    py_exe = _resolver_python_robo(PASTA_ROBO_PROJUDI_AUTO)
    pasta_saida = RAIZ / "saida"
    pasta_saida.mkdir(parents=True, exist_ok=True)
    log_file = pasta_saida / "projudi_live.log"
    try:
        log_file.write_text("", encoding="utf-8")
    except Exception:
        pass

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONUTF8"] = "1"
    env["PAINEL_RPV_LOG"] = str(log_file)
    old_py_path = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{PASTA_RPV_HOOK}{os.pathsep}{old_py_path}" if old_py_path else str(PASTA_RPV_HOOK)

    cmd = [py_exe, str(script_path)]
    _append_projudi_log(f"Iniciando Robô PROJUDI ({script_name}) diretamente no Console do Site (CMD oculto)...")
    _append_projudi_log("Link salvo do PROJUDI: https://projudi.tjpr.jus.br/projudi/")
    _append_projudi_log("Use o campo de Chat abaixo para responder confirmações (ex: ENVIAR ou ENTER).")

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(PASTA_ROBO_PROJUDI_AUTO),
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=_flags_sem_cmd(),
        )
        with LOCK_PROJUDI_ROBO:
            PROJUDI_ROBO_STATE["process"] = proc
            PROJUDI_ROBO_STATE["message"] = f"Em execução ({script_name}) · Console interativo ativo"

        offset = 0
        while proc.poll() is None:
            if log_file.exists():
                try:
                    with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                        f.seek(offset)
                        novas = f.readlines()
                        offset = f.tell()
                    for ln in novas:
                        txt = ln.strip()
                        if txt:
                            _append_projudi_log(txt)
                            with LOCK_PROJUDI_ROBO:
                                PROJUDI_ROBO_STATE["message"] = txt[:140]
                                PROJUDI_ROBO_STATE["waiting_input"] = (
                                    "Console aguarda" in txt or "💬" in txt or "🔒" in txt
                                )
                except Exception:
                    pass
            time.sleep(0.25)

        if log_file.exists():
            try:
                with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                    f.seek(offset)
                    finais = f.readlines()
                for ln in finais:
                    txt = ln.strip()
                    if txt:
                        _append_projudi_log(txt)
            except Exception:
                pass

        code = proc.returncode
        with LOCK_PROJUDI_ROBO:
            PROJUDI_ROBO_STATE["returncode"] = code
            PROJUDI_ROBO_STATE["finished_at"] = time.time()
            PROJUDI_ROBO_STATE["waiting_input"] = False
            if PROJUDI_ROBO_STATE["status"] == "stopped":
                PROJUDI_ROBO_STATE["message"] = "Execução interrompida pelo usuário"
                _append_projudi_log("Execução interrompida pelo usuário.")
            elif code == 0:
                PROJUDI_ROBO_STATE["status"] = "done"
                PROJUDI_ROBO_STATE["message"] = "Execução concluída com sucesso"
                _append_projudi_log("Execução concluída com sucesso (código 0).")
            else:
                PROJUDI_ROBO_STATE["status"] = "error"
                PROJUDI_ROBO_STATE["message"] = f"Finalizado com código {code}"
                _append_projudi_log(f"Processo finalizado com código {code}.")
    except Exception as exc:
        with LOCK_PROJUDI_ROBO:
            PROJUDI_ROBO_STATE["status"] = "error"
            PROJUDI_ROBO_STATE["waiting_input"] = False
            PROJUDI_ROBO_STATE["message"] = f"Erro ao iniciar: {exc}"
        _append_projudi_log(f"ERRO: {exc}")
    finally:
        with LOCK_PROJUDI_ROBO:
            PROJUDI_ROBO_STATE["process"] = None


def iniciar_robo_projudi(modo: str = "v6") -> tuple[bool, str]:
    with LOCK_PROJUDI_ROBO:
        proc = PROJUDI_ROBO_STATE.get("process")
        if PROJUDI_ROBO_STATE["status"] == "running" and proc is not None and proc.poll() is None:
            return False, "Robô PROJUDI já está em execução."

        PROJUDI_ROBO_STATE["status"] = "running"
        PROJUDI_ROBO_STATE["waiting_input"] = False
        PROJUDI_ROBO_STATE["script"] = "robo_projudi_gui.py" if modo == "gui" else "robo_projudi_v6.py"
        PROJUDI_ROBO_STATE["message"] = "Iniciando Robô PROJUDI no Console do Site..."
        PROJUDI_ROBO_STATE["started_at"] = time.time()
        PROJUDI_ROBO_STATE["finished_at"] = None
        PROJUDI_ROBO_STATE["returncode"] = None
        PROJUDI_ROBO_STATE["log"].clear()

    threading.Thread(target=_stream_projudi_process, args=(modo,), daemon=True).start()
    return True, "Robô PROJUDI iniciado no Console do Site."


def enviar_comando_projudi(texto: str) -> tuple[bool, str]:
    with LOCK_PROJUDI_ROBO:
        proc = PROJUDI_ROBO_STATE.get("process")
        visivel = str(texto or "").strip() or "[ENTER]"
        _append_projudi_log(f"👤 Você (Chat Console): {visivel}")
        if not proc or proc.poll() is not None or proc.stdin is None:
            return True, "Mensagem registrada no console (inicie o robô para interagir com o processo)."
        try:
            proc.stdin.write(str(texto or "") + "\n")
            proc.stdin.flush()
            PROJUDI_ROBO_STATE["waiting_input"] = False
            PROJUDI_ROBO_STATE["message"] = f"Resposta enviada: {visivel}"
            return True, f"Comando '{visivel}' enviado ao Robô PROJUDI."
        except Exception as exc:
            return False, f"Erro ao enviar comando: {exc}"


def parar_robo_projudi() -> tuple[bool, str]:
    with LOCK_PROJUDI_ROBO:
        proc = PROJUDI_ROBO_STATE.get("process")
        if not proc or proc.poll() is not None:
            PROJUDI_ROBO_STATE["status"] = "ready"
            PROJUDI_ROBO_STATE["waiting_input"] = False
            PROJUDI_ROBO_STATE["message"] = "Pronto para executar"
            return False, "O Robô PROJUDI não está em execução no momento."

        PROJUDI_ROBO_STATE["status"] = "stopped"
        PROJUDI_ROBO_STATE["waiting_input"] = False
        PROJUDI_ROBO_STATE["message"] = "Interrompendo execução..."
        pid = proc.pid

    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=_flags_sem_cmd(),
            )
        else:
            proc.terminate()
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass

    return True, "Robô PROJUDI interrompido."


def limpar_log_projudi() -> None:
    with LOCK_PROJUDI_ROBO:
        PROJUDI_ROBO_STATE["log"].clear()
        PROJUDI_ROBO_STATE["message"] = "Console limpo · Pronto para executar"


def abrir_pasta_projudi() -> tuple[bool, str]:
    alvo = PASTA_ROBO_PROJUDI_AUTO
    if not alvo.exists():
        return False, f"Pasta não existe: {alvo}"
    try:
        subprocess.Popen(["explorer", str(alvo)])
        return True, f"Pasta aberta: {alvo}"
    except Exception as exc:
        return False, str(exc)


def estado_publico_projudi() -> dict:
    with LOCK_PROJUDI_ROBO:
        return {
            "status": PROJUDI_ROBO_STATE["status"],
            "message": PROJUDI_ROBO_STATE["message"],
            "waiting_input": bool(PROJUDI_ROBO_STATE.get("waiting_input")),
            "script": PROJUDI_ROBO_STATE["script"],
            "cwd": str(PASTA_ROBO_PROJUDI_AUTO),
            "projudi_url": PROJUDI_ROBO_STATE["projudi_url"],
            "log": list(PROJUDI_ROBO_STATE["log"])[-200:],
            "started_at": PROJUDI_ROBO_STATE["started_at"],
            "finished_at": PROJUDI_ROBO_STATE["finished_at"],
            "returncode": PROJUDI_ROBO_STATE["returncode"],
        }


def carregar_agendamento_sapiens() -> list[str]:
    if AGENDA_SAPIENS_JSON.exists():
        try:
            dados = json.loads(AGENDA_SAPIENS_JSON.read_text(encoding="utf-8"))
            horarios = [h.strip() for h in dados.get("horarios", []) if re.match(r"^\d{2}:\d{2}$", str(h).strip())]
            if horarios:
                STATUS_COLETA["horarios_sapiens"] = horarios
                return horarios
        except Exception:
            pass
    return STATUS_COLETA["horarios_sapiens"]


def salvar_agendamento_sapiens(horarios_txt: str) -> list[str]:
    horarios = [
        h.strip()
        for h in re.split(r"[,;\s]+", horarios_txt or "")
        if re.match(r"^\d{2}:\d{2}$", h.strip())
    ]
    AGENDA_SAPIENS_JSON.parent.mkdir(parents=True, exist_ok=True)
    AGENDA_SAPIENS_JSON.write_text(
        json.dumps({"horarios": horarios}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    STATUS_COLETA["horarios_sapiens"] = horarios

    for idx in range(1, 6):
        subprocess.run(
            ["schtasks", "/Delete", "/TN", f"PRS_Coleta_SAPIENS_{idx}", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=_flags_sem_cmd(),
        )
    cmd_tarefa = f'"{sys.executable}" "{ROBO_SAPIENS}" --sem-pausa'
    for idx, h in enumerate(horarios[:5], start=1):
        subprocess.run(
            [
                "schtasks", "/Create", "/F",
                "/SC", "DAILY",
                "/TN", f"PRS_Coleta_SAPIENS_{idx}",
                "/TR", cmd_tarefa,
                "/ST", h,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=_flags_sem_cmd(),
        )
    return horarios


def _loop_agendador_sapiens() -> None:
    ultimo_disparo = ""
    while True:
        try:
            agora = time.strftime("%Y-%m-%d %H:%M")
            hhmm = agora.split(" ")[1]
            horarios = STATUS_COLETA.get("horarios_sapiens") or []
            if hhmm in horarios and agora != ultimo_disparo:
                ultimo_disparo = agora
                if not STATUS_COLETA.get("sapiens_em_andamento"):
                    sys.stdout.write(f"[Agendador SAPIENS] Disparando coleta automática das {hhmm}...\n")
                    threading.Thread(target=_rodar_sapiens_background, daemon=True).start()
        except Exception:
            pass
        time.sleep(20)


def _executar_robo(cmd: list[str], cwd: Path, nome: str, *, env=None) -> tuple[bool, str]:
    STATUS_COLETA["etapa"] = f"Executando {nome}..."
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=_flags_sem_cmd(),
    )
    ultimas: list[str] = []
    assert proc.stdout is not None
    for linha in proc.stdout:
        txt = linha.strip()
        if txt:
            ultimas.append(txt)
            STATUS_COLETA["etapa"] = f"{nome}: {txt[:80]}"
            sys.stdout.write(f"[{nome}] {txt}\n")
    codigo = proc.wait()
    resumo = ultimas[-1] if ultimas else ""
    return (codigo == 0, resumo)


def _salvar_planilhas_eproc(arquivos: list[dict]) -> tuple[list[str], list[str]]:
    """Salva arquivos .xls enviados pelo painel em dados/eproc/ e retorna (resumos, erros)."""
    PASTA_EPROC.mkdir(parents=True, exist_ok=True)
    resumos: list[str] = []
    erros: list[str] = []

    for idx, item in enumerate(arquivos):
        nome_orig = str(item.get("nome") or f"eproc_{idx + 1}.xls")
        b64 = str(item.get("conteudo_b64") or "")
        if not b64:
            continue
        if "," in b64:
            b64 = b64.split(",", 1)[1]
        try:
            raw = base64.b64decode(b64)
        except Exception as e:
            erros.append(f"{nome_orig}: base64 inválido ({e})")
            continue

        nome_limpo = re.sub(r"[^A-Za-z0-9_.\-]", "_", Path(nome_orig).name)
        if not nome_limpo.lower().endswith(".xls"):
            nome_limpo += ".xls"
        caminho_temp = PASTA_EPROC / f"upload_{int(time.time() * 1000)}_{idx}_{nome_limpo}"
        caminho_temp.write_bytes(raw)

        try:
            regs = mod_eproc.ler_arquivo(caminho_temp)
            if not regs:
                if caminho_temp.exists():
                    caminho_temp.unlink()
                resumos.append(f"{nome_orig} (0 prazos em aberto)")
                continue
            grupo = mod_eproc.grupo_relatorio_eproc(regs, caminho_temp)
            canonico = ARQUIVO_CANONICO_POR_GRUPO.get(grupo)
            if canonico:
                destino = PASTA_EPROC / canonico
                destino.write_bytes(raw)
                if caminho_temp != destino and caminho_temp.exists():
                    caminho_temp.unlink()
                resumos.append(f"{grupo} ({len(regs)} prazos)")
            else:
                resumos.append(f"{nome_orig} ({len(regs)} prazos)")
        except Exception as e:
            if caminho_temp.exists():
                caminho_temp.unlink()
            erros.append(f"{nome_orig}: não é um .xls válido do EPROC ({e})")

    return resumos, erros


def _rodar_sapiens_background(usuario_id=None) -> None:
    if not LOCK_SAPIENS.acquire(blocking=False):
        return
    STATUS_COLETA["sapiens_em_andamento"] = True
    try:
        ok, det = _executar_robo(
            [sys.executable, str(ROBO_SAPIENS), "--sem-pausa"],
            cwd=ROBO_SAPIENS.parent,
            nome="Robô SAPIENS",
            env={**os.environ, "PAINEL_SAPIENS_SEM_CONSOLIDAR": "1"},
        )
        STATUS_COLETA["etapa"] = "Robô SAPIENS concluído · Recruzando prazos..."
        executar_pipeline(usuario_id=usuario_id)
        _invalidar_versao_coleta()
        STATUS_COLETA["etapa"] = (
            "SAPIENS atualizado e cruzado com sucesso!"
            if ok
            else f"SAPIENS manteve base anterior ({det or 'coleta interrompida'})"
        )
    finally:
        STATUS_COLETA["sapiens_em_andamento"] = False
        LOCK_SAPIENS.release()


def _versao_atual():
    global _versao_coleta
    with _LOCK_VERSAO:
        agora = time.monotonic()
        if agora >= _versao_coleta[0]:
            _versao_coleta = (agora + _AGUARDAR_VERSAO, db.ultima_coleta_id() or 0)
        return _versao_coleta[1]


def _invalidar_versao_coleta():
    global _versao_coleta
    with _LOCK_VERSAO:
        _versao_coleta = (0.0, 0)


class PainelHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stdout.write(f"[Painel] {fmt % args}\n")

    def _responder_json(self, status: int, obj: dict, *, cookie=None) -> None:
        corpo = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(corpo)))
        if cookie is not None:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(corpo)

    def _ler_json_body(self) -> dict:
        try:
            tamanho = int(self.headers.get("Content-Length") or 0)
            limite = 64 * 1024 * 1024 if self.path.split("?", 1)[0] == "/api/upload-eproc" else 16 * 1024
            if not 0 < tamanho <= limite:
                return {}
            corpo = json.loads(self.rfile.read(tamanho).decode("utf-8"))
            return corpo if isinstance(corpo, dict) else {}
        except (ValueError, UnicodeError):
            return {}

    def _token(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except CookieError:
            return ""
        return cookie["sessao"].value if "sessao" in cookie else ""

    def _enderecos_validos(self, post):
        porta = self.server.server_port
        hosts = {f"127.0.0.1:{porta}", f"localhost:{porta}"}
        host = self.headers.get_all("Host", [])
        origin = self.headers.get_all("Origin", [])
        return len(host) == 1 and host[0].lower() in hosts and (
            not post or not origin or origin == [f"http://{host[0].lower()}"]
        )

    def _despachar(self, *, post):
        if not self._enderecos_validos(post):
            return self._responder_json(403, {"erro": "origem_invalida"})
        try:
            parsed = urlparse(self.path)
        except ValueError:
            return self.send_error(400)
        rota = parsed.path
        try:
            if post and rota in LOGIN_ROTAS:
                return self._login(rota)
            if not rota.startswith("/api/"):
                return self.send_error(404) if post else self._arquivo_publico(rota)
            usuario = auth.usuario_da_sessao(self._token(), usar_cache=not post)
            if not post and rota == "/api/auth/status":
                return self._responder_json(200, auth.status(usuario))
            if not usuario:
                return self._responder_json(401, {"erro": "nao_autenticado"})
            if not post:
                return self._get_api(rota, usuario)
            if rota == "/api/auth/logout":
                auth.sair(self._token())
                return self._responder_json(200, {"ok": True, "session": auth.status(None)},
                                            cookie="sessao=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0")
            if usuario["perfil"] != "admin":
                return self._responder_json(403, {"erro": "sem_permissao"})
            return self._post_admin(parsed, usuario["id"])
        except psycopg.Error:
            self.log_error("Falha ao acessar o banco de dados.")
            return self._responder_json(503, {"erro": "Banco de dados indispon\u00edvel."})

    def do_GET(self):
        return self._despachar(post=False)

    def do_POST(self):
        return self._despachar(post=True)

    def _login(self, rota):
        body = self._ler_json_body()
        try:
            if rota == "/api/auth/login":
                token, conta = auth.entrar_com_senha(str(body.get("email") or ""),
                                                      str(body.get("senha") or ""), self._token())
            else:
                token, conta = auth.entrar_com_google(str(body.get("credential") or ""), self._token())
        except auth.LoginNegado as exc:
            status = 429 if exc.bloqueado else 401
            return self._responder_json(status, {"erro": str(exc), "bloqueado": exc.bloqueado})
        cookie = f"sessao={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={auth.sessao_horas() * 3600}"
        return self._responder_json(200, {"ok": True, "session": auth.status(conta)}, cookie=cookie)

    def _get_api(self, rota, usuario):
        admin = usuario["perfil"] == "admin"
        if rota == "/api/status-coleta":
            estado = {"versao_dados": _versao_atual(), "session": auth.status(usuario)}
            if admin:
                estado = {**STATUS_COLETA, **estado}
            return self._responder_json(200, estado)

        if rota == "/api/rpv/status":
            estado = estado_publico_rpv()
            if not admin:
                estado = {"robots": [{"id": robo["id"], "status": robo["status"]} for robo in estado["robots"]]}
            return self._responder_json(200, estado)

        if rota == "/api/projudi-robo/status":
            estado = estado_publico_projudi()
            return self._responder_json(200, estado if admin else {"status": estado["status"]})

        if rota == "/api/prazos":
            payload = db.carregar_estado() or {"data": [], "days": [], "counts": {}, "updatedAt": "Sem coletas"}
            return self._responder_json(200, {**payload, "session": auth.status(usuario)})
        return self.send_error(404)

    def _arquivo_publico(self, rota):
        nome = rota[1:] if rota.startswith("/") else ""
        if nome in ("", "index.html"):
            nome = "Index.html"
        if nome not in ARQUIVOS_PUBLICOS:
            return self.send_error(404)
        arq = PASTA_PAINEL / nome
        if not arq.is_file() or not arq.resolve().is_relative_to(PASTA_PAINEL.resolve()):
            return self.send_error(404)

        tipo = "text/javascript" if nome.endswith(".js") else mimetypes.guess_type(str(arq))[0]
        conteudo = arq.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", tipo or "application/octet-stream")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer-when-downgrade")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(conteudo)))
        self.end_headers()
        self.wfile.write(conteudo)

    def _post_admin(self, parsed, usuario_id):
        qs = parse_qs(parsed.query)
        if parsed.path == "/api/rpv/run":
            rid = (qs.get("id") or [""])[0]
            modo = (qs.get("modo") or ["padrao"])[0]
            ok, msg = iniciar_robo_rpv(rid, modo=modo)
            return self._responder_json(200 if ok else 409, {"ok": ok, "message": msg})

        if parsed.path == "/api/rpv/input":
            body = self._ler_json_body()
            rid = str(body.get("id") or (qs.get("id") or ["robo1"])[0])
            texto = str(body.get("text") or "")
            ok, msg = enviar_comando_rpv(rid, texto)
            return self._responder_json(200 if ok else 409, {"ok": ok, "message": msg})

        if parsed.path == "/api/rpv/stop":
            rid = (qs.get("id") or [""])[0]
            ok, msg = parar_robo_rpv(rid)
            return self._responder_json(200 if ok else 409, {"ok": ok, "message": msg})

        if parsed.path == "/api/rpv/clear-log":
            rid = (qs.get("id") or ["all"])[0]
            limpar_log_rpv(rid)
            return self._responder_json(200, {"ok": True})

        if parsed.path == "/api/rpv/open-folder":
            rid = (qs.get("id") or ["raiz"])[0]
            ok, msg = abrir_pasta_rpv(rid)
            return self._responder_json(200 if ok else 404, {"ok": ok, "message": msg})

        if parsed.path == "/api/projudi-robo/run":
            modo = (qs.get("modo") or ["v6"])[0]
            ok, msg = iniciar_robo_projudi(modo=modo)
            return self._responder_json(200 if ok else 409, {"ok": ok, "message": msg})

        if parsed.path == "/api/projudi-robo/input":
            body = self._ler_json_body()
            texto = str(body.get("text") or "")
            ok, msg = enviar_comando_projudi(texto)
            return self._responder_json(200 if ok else 409, {"ok": ok, "message": msg})

        if parsed.path == "/api/projudi-robo/stop":
            ok, msg = parar_robo_projudi()
            return self._responder_json(200 if ok else 409, {"ok": ok, "message": msg})

        if parsed.path == "/api/projudi-robo/clear-log":
            limpar_log_projudi()
            return self._responder_json(200, {"ok": True})

        if parsed.path == "/api/projudi-robo/open-folder":
            ok, msg = abrir_pasta_projudi()
            return self._responder_json(200 if ok else 404, {"ok": ok, "message": msg})

        if parsed.path == "/api/agendar-sapiens":
            body = self._ler_json_body()
            horarios = salvar_agendamento_sapiens(str(body.get("horarios") or ""))
            return self._responder_json(200, {"ok": True, "horarios": horarios})

        if parsed.path == "/api/rodar-sapiens":
            if not STATUS_COLETA.get("sapiens_em_andamento"):
                threading.Thread(target=_rodar_sapiens_background, args=(usuario_id,), daemon=True).start()
            return self._responder_json(200, {"ok": True, "etapa": "Robô SAPIENS iniciado em 2º plano"})

        if parsed.path == "/api/upload-eproc":
            body = self._ler_json_body()
            arquivos = body.get("arquivos") or []
            with LOCK_COLETA:
                STATUS_COLETA["em_andamento"] = True
                try:
                    STATUS_COLETA["etapa"] = "Importando planilhas .xls do EPROC..."
                    resumos, erros = _salvar_planilhas_eproc(arquivos)
                    STATUS_COLETA["etapa"] = "Consolidando e cruzando prazos..."
                    info = executar_pipeline(usuario_id=usuario_id)
                    _invalidar_versao_coleta()
                    payload = info["payload"]
                    payload["importados_eproc"] = resumos
                    payload["avisos_coleta"] = erros
                    STATUS_COLETA["etapa"] = "Concluído"
                finally:
                    STATUS_COLETA["em_andamento"] = False
            return self._responder_json(200, payload)

        if parsed.path != "/api/atualizar":
            self.send_error(404)
            return

        rodar_projudi = qs.get("projudi", ["1"])[0] == "1"
        rodar_sapiens = qs.get("sapiens", ["1"])[0] == "1"
        rodar_eproc = qs.get("eproc", ["1"])[0] == "1"
        portal_eproc = qs.get("portal_eproc", ["todos"])[0]

        with LOCK_COLETA:
            STATUS_COLETA["em_andamento"] = True
            STATUS_COLETA["avisos"] = []
            avisos: list[str] = []
            try:
                if rodar_sapiens and ROBO_SAPIENS.exists() and not STATUS_COLETA.get("sapiens_em_andamento"):
                    threading.Thread(target=_rodar_sapiens_background, args=(usuario_id,), daemon=True).start()

                resultados_robos: dict[str, tuple[bool, str]] = {}

                def _worker_eproc():
                    resultados_robos["eproc"] = _executar_robo(
                        [sys.executable, str(ROBO_EPROC), "--portal", portal_eproc, "--sem-pausa"],
                        cwd=ROBO_EPROC.parent,
                        nome="Robô EPROC",
                    )

                def _worker_projudi():
                    resultados_robos["projudi"] = _executar_robo(
                        [sys.executable, str(ROBO_PROJUDI), "--sem-pausa"],
                        cwd=ROBO_PROJUDI.parent,
                        nome="Robô PROJUDI",
                    )

                threads: list[threading.Thread] = []
                if rodar_eproc and ROBO_EPROC.exists():
                    t_ep = threading.Thread(target=_worker_eproc, daemon=True)
                    t_ep.start()
                    threads.append(t_ep)

                if rodar_projudi and ROBO_PROJUDI.exists():
                    t_pj = threading.Thread(target=_worker_projudi, daemon=True)
                    t_pj.start()
                    threads.append(t_pj)

                for t in threads:
                    t.join()

                if "eproc" in resultados_robos and not resultados_robos["eproc"][0]:
                    det = resultados_robos["eproc"][1]
                    avisos.append(f"EPROC usou planilhas anteriores ({det or 'falha na coleta'})")

                if "projudi" in resultados_robos and not resultados_robos["projudi"][0]:
                    det = resultados_robos["projudi"][1]
                    avisos.append(f"PROJUDI usou base anterior ({det or 'falha na coleta'})")

                STATUS_COLETA["etapa"] = "Consolidando e cruzando prazos..."
                info = executar_pipeline(usuario_id=usuario_id)
                _invalidar_versao_coleta()
                payload = info["payload"]
                if STATUS_COLETA.get("sapiens_em_andamento"):
                    avisos.append("Robô SAPIENS segue coletando as 16 caixas em 2º plano (o painel atualizará sozinho ao terminar)")
                payload["avisos_coleta"] = avisos
                STATUS_COLETA["avisos"] = avisos
                STATUS_COLETA["etapa"] = "Concluído"
            finally:
                STATUS_COLETA["em_andamento"] = False

        return self._responder_json(200, payload)


class ThreadedHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True


def main() -> None:
    ap = argparse.ArgumentParser(description="Servidor local do Painel de Prazos")
    ap.add_argument("--porta", type=int, default=8765)
    ap.add_argument("--sem-navegador", action="store_true")
    a = ap.parse_args()

    try:
        auth.sessao_horas()
        db.aplicar_schema()
        db.limpar_sessoes_expiradas()
    except (ValueError, RuntimeError) as exc:
        ap.exit(1, f"{exc}\n")
    except psycopg.Error:
        ap.exit(1, "Falha ao preparar o Postgres. Confira o DATABASE_URL, a conex\u00e3o e as permiss\u00f5es do banco.\n")

    carregar_agendamento_sapiens()
    threading.Thread(target=_loop_agendador_sapiens, daemon=True).start()

    servidor = ThreadedHTTPServer(("127.0.0.1", a.porta), PainelHandler)
    with servidor:
        host = "localhost" if auth.google_client_id() else "127.0.0.1"
        url = f"http://{host}:{servidor.server_port}"
        print(f"Painel de Prazos disponível em: {url}")
        if not a.sem_navegador:
            webbrowser.open(url)
        try:
            servidor.serve_forever()
        except KeyboardInterrupt:
            print("\nServidor encerrado.")


if __name__ == "__main__":
    main()
