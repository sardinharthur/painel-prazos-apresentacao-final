"""Sincronização opcional com o Google Sheets e o Drive dos robôs."""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

from .cruzamento import COLUNAS_SAIDA, Resultado, para_linha

RAIZ = Path(__file__).resolve().parents[1]
CONFIG_GOOGLE_PATH = RAIZ / "saida" / "CONFIG_GOOGLE.json"
PASTA_GAS = RAIZ / "google_apps_script"

DOMINIO_INSTITUCIONAL = "pge.pr.gov.br"
SCOPES_GOOGLE_ECOSSISTEMA = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

CANDIDATOS_TOKEN_SHEETS = [
    RAIZ / "saida" / "token_google_institucional.json",
    RAIZ / "saida" / "token_sheets.json",
    RAIZ / "robos" / "rpv" / "ROBO1_TESTE_FINAL" / "token.json",
    RAIZ / "robos" / "rpv" / "ROBO2" / "token.json",
    RAIZ / "robos" / "rpv" / "ROBO4" / "token_robo4.json",
    Path(r"C:\Users\Arthur\Documents\ROBO RPVS\ROBO1_TESTE_FINAL\ROBO1_TESTE_FINAL\token.json"),
    Path(r"C:\Users\Arthur\Documents\ROBO RPVS\ROBO2\token.json"),
    Path(r"C:\Users\Arthur\Documents\ROBO RPVS\ROBO4\token_robo4.json"),
    Path(r"C:\Users\Arthur\Documents\ROBO RPVS\ROBO1\token.json"),
]

CANDIDATOS_CREDENTIALS = [
    RAIZ / "dados" / "credentials.json",
    RAIZ / "saida" / "credentials.json",
    RAIZ / "credentials.json",
    RAIZ / "robos" / "rpv" / "ROBO1_TESTE_FINAL" / "credentials.json",
    RAIZ / "robos" / "rpv" / "ROBO2" / "credentials.json",
    RAIZ / "robos" / "rpv" / "ROBO4" / "credentials.json",
    Path(r"C:\Users\Arthur\Documents\ROBO RPVS\ROBO1_TESTE_FINAL\ROBO1_TESTE_FINAL\credentials.json"),
    Path(r"C:\Users\Arthur\Documents\ROBO RPVS\ROBO2\credentials.json"),
    Path(r"C:\Users\Arthur\Documents\ROBO RPVS\ROBO4\credentials.json"),
    Path(r"C:\Users\Arthur\Documents\ROBO RPVS\ROBO1\credentials.json"),
    Path(r"C:\Users\Arthur\Documents\ROBO RPVS\credentials.json"),
]

PASTA_DRIVE_PADRAO_ID = "0AKQe6iKo0eUeUk9PVA"
PASTA_DRIVE_PADRAO_URL = f"https://drive.google.com/drive/folders/{PASTA_DRIVE_PADRAO_ID}"
TITULO_PLANILHA_PADRAO = "Painel de Prazos PRS - Consolidado"


def carregar_config_google() -> dict[str, Any]:
    if CONFIG_GOOGLE_PATH.exists():
        try:
            cfg = json.loads(CONFIG_GOOGLE_PATH.read_text(encoding="utf-8"))
            return cfg
        except Exception:
            pass
    return {
        "folder_id": PASTA_DRIVE_PADRAO_ID,
        "folder_name": "Meu Drive (Institucional PGE)",
        "folder_url": PASTA_DRIVE_PADRAO_URL,
        "spreadsheet_id": "",
        "spreadsheet_title": TITULO_PLANILHA_PADRAO,
        "spreadsheet_url": "",
        "institutional_domain": DOMINIO_INSTITUCIONAL,
    }


def salvar_config_google(cfg: dict[str, Any]) -> None:
    CONFIG_GOOGLE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_GOOGLE_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def encontrar_credentials_json() -> Path | None:
    for p in CANDIDATOS_CREDENTIALS:
        if p.exists():
            return p
    return None


def propagar_credenciais_ecossistema(token_json_str: str | None = None) -> dict[str, Any]:
    """Garante que `credentials.json` e `token.json` estejam sincronizados em todos os robôs RPV."""
    pastas_robos = [
        RAIZ / "saida",
        RAIZ / "robos" / "rpv" / "ROBO1_TESTE_FINAL",
        RAIZ / "robos" / "rpv" / "ROBO2",
        RAIZ / "robos" / "rpv" / "ROBO4",
    ]
    pasta_ext = Path(r"C:\Users\Arthur\Documents\ROBO RPVS")
    if pasta_ext.exists():
        for sub in ("ROBO1_TESTE_FINAL/ROBO1_TESTE_FINAL", "ROBO2", "ROBO4"):
            alvo = pasta_ext / sub
            if alvo.exists():
                pastas_robos.append(alvo)

    cred_origem = encontrar_credentials_json()
    copiados_cred = []
    copiados_token = []

    if cred_origem:
        for pasta in pastas_robos:
            if not pasta.exists():
                continue
            dest = pasta / "credentials.json"
            if dest.resolve() != cred_origem.resolve() and not dest.exists():
                try:
                    shutil.copy2(cred_origem, dest)
                    copiados_cred.append(str(dest))
                except Exception:
                    pass

    if token_json_str:
        alvos_token = [
            RAIZ / "saida" / "token_google_institucional.json",
            RAIZ / "saida" / "token_sheets.json",
            RAIZ / "robos" / "rpv" / "ROBO1_TESTE_FINAL" / "token.json",
            RAIZ / "robos" / "rpv" / "ROBO2" / "token.json",
            RAIZ / "robos" / "rpv" / "ROBO4" / "token_robo4.json",
        ]
        for tpath in alvos_token:
            try:
                tpath.parent.mkdir(parents=True, exist_ok=True)
                tpath.write_text(token_json_str, encoding="utf-8")
                copiados_token.append(str(tpath))
            except Exception:
                pass

    return {
        "credentials_found": str(cred_origem) if cred_origem else None,
        "credentials_synced": copiados_cred,
        "tokens_synced": copiados_token,
    }


def _obter_credenciais_sheets():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    for p in CANDIDATOS_TOKEN_SHEETS:
        if not p.exists():
            continue
        try:
            creds = Credentials.from_authorized_user_file(str(p))
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
                try:
                    p.write_text(creds.to_json(), encoding="utf-8")
                except Exception:
                    pass
            if creds and creds.valid:
                propagar_credenciais_ecossistema(creds.to_json())
                return creds
        except Exception:
            continue
    return None


def autorizar_google_sheets() -> None:
    """Autoriza o Sheets e o Drive usando credentials.json de aplicativo desktop."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    caminho = encontrar_credentials_json()
    if caminho is None:
        raise FileNotFoundError("Coloque credentials.json na raiz, em dados/ ou em saida/.")
    os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")
    flow = InstalledAppFlow.from_client_secrets_file(str(caminho), SCOPES_GOOGLE_ECOSSISTEMA)
    creds = flow.run_local_server(port=0, prompt="select_account", hd=DOMINIO_INSTITUCIONAL)
    resultado = propagar_credenciais_ecossistema(creds.to_json())
    if str(RAIZ / "saida" / "token_sheets.json") not in resultado["tokens_synced"]:
        raise RuntimeError("Não foi possível salvar as credenciais para o Google Sheets.")


def _garantir_planilha(service, cfg: dict[str, Any]) -> str:
    sp_id = str(cfg.get("spreadsheet_id") or "").strip()
    if sp_id:
        try:
            meta = service.spreadsheets().get(spreadsheetId=sp_id).execute()
            abas = {s["properties"]["title"] for s in meta.get("sheets", [])}
            reqs = []
            if "Prazos Consolidados" not in abas:
                reqs.append({"addSheet": {"properties": {"title": "Prazos Consolidados"}}})
            if "ESTADO_PAINEL" not in abas:
                reqs.append({"addSheet": {"properties": {"title": "ESTADO_PAINEL"}}})
            if reqs:
                service.spreadsheets().batchUpdate(
                    spreadsheetId=sp_id, body={"requests": reqs}
                ).execute()
            return sp_id
        except Exception:
            sp_id = ""

    corpo_criacao = {
        "properties": {"title": cfg.get("spreadsheet_title") or TITULO_PLANILHA_PADRAO},
        "sheets": [
            {"properties": {"title": "Prazos Consolidados", "gridProperties": {"frozenRowCount": 1}}},
            {"properties": {"title": "ESTADO_PAINEL", "gridProperties": {"frozenRowCount": 1}}},
        ],
    }
    criada = service.spreadsheets().create(body=corpo_criacao).execute()
    sp_id = criada["spreadsheetId"]
    cfg["spreadsheet_id"] = sp_id
    cfg["spreadsheet_url"] = f"https://docs.google.com/spreadsheets/d/{sp_id}/edit"
    salvar_config_google(cfg)
    _atualizar_id_no_code_gs(sp_id)
    return sp_id


def _atualizar_id_no_code_gs(sp_id: str) -> None:
    arq_gs = PASTA_GAS / "Code.gs"
    if not arq_gs.exists() or not sp_id:
        return
    try:
        txt = arq_gs.read_text(encoding="utf-8")
        import re
        novo = re.sub(
            r'const SPREADSHEET_ID = "[^"]*";',
            f'const SPREADSHEET_ID = "{sp_id}";',
            txt,
        )
        if novo != txt:
            arq_gs.write_text(novo, encoding="utf-8")
    except Exception:
        pass


def sincronizar_google_sheets(resultados: list[Resultado], payload: dict[str, Any]) -> dict[str, Any]:
    """Cria (se necessário) e atualiza a planilha do Painel de Prazos no Google Drive."""
    cfg = carregar_config_google()
    try:
        from googleapiclient.discovery import build

        creds = _obter_credenciais_sheets()
        if creds is None:
            cfg["status"] = "Aguardando autorização do Google Sheets"
            return cfg

        service = build("sheets", "v4", credentials=creds)
        sp_id = _garantir_planilha(service, cfg)

        # 1. Monta linhas da aba "Prazos Consolidados"
        linhas_csv = [COLUNAS_SAIDA]
        for r in resultados:
            d = para_linha(r)
            linhas_csv.append([str(d.get(col, "") or "") for col in COLUNAS_SAIDA])

        # 2. Monta linhas da aba "ESTADO_PAINEL" (fatiado em células de até 40.000 chars para o Code.gs ler rápido)
        payload_sem_google = {k: v for k, v in payload.items() if k != "google"}
        json_str = json.dumps(payload_sem_google, ensure_ascii=False)
        fatias = [json_str[i : i + 40000] for i in range(0, len(json_str), 40000)] or ["{}"]
        linhas_estado = [
            ["CHAVE", "VALOR"],
            ["UPDATED_AT", str(payload.get("updatedAt", ""))],
            ["UPDATED_ISO", str(payload.get("updatedISO", ""))],
            ["REFERENCE_DATE", str(payload.get("referenceDate", ""))],
            ["RUNTIME", str(payload.get("runtime", ""))],
            ["QTD_FATIAS_JSON", str(len(fatias))],
        ]
        for idx, fatia in enumerate(fatias, start=1):
            linhas_estado.append([f"JSON_PARTE_{idx}", fatia])

        service.spreadsheets().values().clear(
            spreadsheetId=sp_id, range="'Prazos Consolidados'!A:Z"
        ).execute()
        service.spreadsheets().values().update(
            spreadsheetId=sp_id,
            range="'Prazos Consolidados'!A1",
            valueInputOption="RAW",
            body={"values": linhas_csv},
        ).execute()

        service.spreadsheets().values().clear(
            spreadsheetId=sp_id, range="'ESTADO_PAINEL'!A:Z"
        ).execute()
        service.spreadsheets().values().update(
            spreadsheetId=sp_id,
            range="'ESTADO_PAINEL'!A1",
            valueInputOption="RAW",
            body={"values": linhas_estado},
        ).execute()

        cfg["status"] = f"Sincronizado no Drive ({len(resultados)} prazos)"
        salvar_config_google(cfg)
        _atualizar_id_no_code_gs(sp_id)
        return cfg
    except Exception as e:
        cfg["status"] = f"Aviso Google Sync: {e}"
        return cfg


if __name__ == "__main__":
    autorizar_google_sheets()
    print("Credenciais do Google Sheets e Drive configuradas.")
