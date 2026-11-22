from __future__ import annotations

import io
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload


SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]


def normalizar(texto: Any) -> str:
    texto = unicodedata.normalize("NFD", str(texto or ""))
    texto = "".join(ch for ch in texto if unicodedata.category(ch) != "Mn")
    return " ".join(texto.upper().strip().split())


@dataclass(frozen=True)
class LinhaRobo4:
    numero_linha: int
    numero_rpv: str
    protocolo: str
    autos: str
    evento: str
    procurador: str


class GoogleServices:
    def __init__(self, config_path: str | Path = "config.json"):
        self.config_path = Path(config_path)
        self.config = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.planilha_cfg = self.config["planilha"]
        self.drive_cfg = self.config["drive"]
        self.creds = self._autenticar()
        self.sheets = build("sheets", "v4", credentials=self.creds)
        self.drive = build("drive", "v3", credentials=self.creds)

    def _autenticar(self) -> Credentials:
        raiz_proj = Path(__file__).resolve().parents[3]
        token_path = Path("token_robo4.json")
        candidatos_token = [
            token_path,
            raiz_proj / "saida" / "token_google_institucional.json",
            Path("token.json"),
        ]
        candidatos_cred = [
            Path("credentials.json"),
            raiz_proj / "saida" / "credentials.json",
            raiz_proj / "robos" / "rpv" / "ROBO1_TESTE_FINAL" / "credentials.json",
            raiz_proj / "robos" / "rpv" / "ROBO2" / "credentials.json",
        ]
        credentials_path = next((p for p in candidatos_cred if p.exists()), None)
        creds = None

        for tpath in candidatos_token:
            if tpath.exists():
                try:
                    creds = Credentials.from_authorized_user_file(str(tpath), SCOPES)
                    if creds and creds.valid:
                        break
                except Exception:
                    creds = None

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception:
                    creds = None

            if not creds:
                if not credentials_path:
                    raise FileNotFoundError(
                        "credentials.json não encontrado. Configure o login Google OAuth no Painel "
                        "ou copie para esta pasta o mesmo credentials.json usado no Robô 1/Robô 2."
                    )
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(credentials_path), SCOPES
                )
                creds = flow.run_local_server(port=0, hd="pge.pr.gov.br", prompt="select_account")

            token_path.write_text(creds.to_json(), encoding="utf-8")
            try:
                (raiz_proj / "saida").mkdir(parents=True, exist_ok=True)
                (raiz_proj / "saida" / "token_google_institucional.json").write_text(creds.to_json(), encoding="utf-8")
            except Exception:
                pass

        return creds

    @staticmethod
    def _extrair_id_planilha(url_ou_id: str) -> str:
        valor = str(url_ou_id or "").strip()
        m = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", valor)
        return m.group(1) if m else valor

    @staticmethod
    def _valor(row: list[Any], idx: int) -> str:
        return str(row[idx]).strip() if idx < len(row) else ""

    def listar_linhas(
        self,
        linha_inicial: int,
        linha_final: int | None = None,
        limite: int = 0,
    ) -> list[LinhaRobo4]:
        spreadsheet_id = self._extrair_id_planilha(self.planilha_cfg["id_ou_url"])
        aba = self.planilha_cfg.get("aba", "RPVs")
        header_row = int(self.planilha_cfg.get("linha_cabecalho", 1))

        result = (
            self.sheets.spreadsheets()
            .values()
            .get(
                spreadsheetId=spreadsheet_id,
                range=f"'{aba}'!A:ZZ",
                valueRenderOption="FORMATTED_VALUE",
            )
            .execute()
        )
        valores = result.get("values", [])
        if len(valores) < header_row:
            return []

        cabecalho = valores[header_row - 1]
        mapa = {normalizar(nome): i for i, nome in enumerate(cabecalho)}

        aliases = {
            "numero": ["NÚMERO", "NUMERO"],
            "protocolo": ["PROTOCOLO"],
            "autos": ["AUTOS", "PROCESSO"],
            "evento": ["EVENTO"],
            "procurador": ["PROCURADOR"],
        }

        def indice(chave: str) -> int:
            for nome in aliases[chave]:
                n = normalizar(nome)
                if n in mapa:
                    return mapa[n]
            raise KeyError(f"Coluna obrigatória não encontrada: {chave}")

        i_numero = indice("numero")
        i_protocolo = indice("protocolo")
        i_autos = indice("autos")
        i_evento = indice("evento")
        i_procurador = indice("procurador")

        itens: list[LinhaRobo4] = []
        for n_linha, row in enumerate(
            valores[header_row:], start=header_row + 1
        ):
            if n_linha < linha_inicial:
                continue
            if linha_final is not None and n_linha > linha_final:
                break

            numero = self._valor(row, i_numero)
            protocolo = self._valor(row, i_protocolo)
            autos = self._valor(row, i_autos)
            evento = self._valor(row, i_evento)
            procurador = self._valor(row, i_procurador)

            if not any([numero, protocolo, autos, evento, procurador]):
                continue

            faltantes = [
                nome
                for nome, valor in [
                    ("NÚMERO", numero),
                    ("PROTOCOLO", protocolo),
                    ("AUTOS", autos),
                    ("EVENTO", evento),
                    ("PROCURADOR", procurador),
                ]
                if not valor
            ]
            if faltantes:
                print(
                    f"Linha {n_linha} ignorada: faltando " + ", ".join(faltantes)
                )
                continue

            # A coluna A deve ser um número inteiro. Remove eventual '.0'.
            if re.fullmatch(r"\d+[.,]0", numero):
                numero = re.split(r"[.,]", numero)[0]
            numero = re.sub(r"\s+", "", numero)

            itens.append(
                LinhaRobo4(
                    numero_linha=n_linha,
                    numero_rpv=numero,
                    protocolo=protocolo,
                    autos=autos,
                    evento=evento,
                    procurador=procurador,
                )
            )

            if limite > 0 and len(itens) >= limite:
                break

        return itens

    def baixar_rpv(self, numero_rpv: str, destino_dir: Path) -> Path:
        pasta_id = str(self.drive_cfg["pasta_rpvs_id"]).strip()
        if not pasta_id:
            raise RuntimeError("drive.pasta_rpvs_id não configurado.")

        numero = str(numero_rpv).strip()
        nomes = [f"{numero}.pdf", numero]
        encontrados: list[dict[str, str]] = []

        for nome in nomes:
            nome_esc = nome.replace("'", "\\'")
            query = (
                f"name = '{nome_esc}' and '{pasta_id}' in parents "
                "and trashed = false"
            )
            resposta = (
                self.drive.files()
                .list(
                    q=query,
                    fields="files(id,name,mimeType,modifiedTime)",
                    pageSize=20,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                )
                .execute()
            )
            encontrados.extend(resposta.get("files", []))
            if encontrados:
                break

        if not encontrados:
            raise FileNotFoundError(
                f"Não encontrei a RPV '{numero}.pdf' na pasta do Google Drive."
            )

        # Evita anexar um documento ambíguo.
        ids_unicos = {a["id"]: a for a in encontrados}
        arquivos = list(ids_unicos.values())
        if len(arquivos) > 1:
            nomes_encontrados = ", ".join(a.get("name", "") for a in arquivos)
            raise RuntimeError(
                f"Há mais de um arquivo para a RPV {numero}: {nomes_encontrados}"
            )

        arquivo = arquivos[0]
        mime = arquivo.get("mimeType", "")
        if mime != "application/pdf" and not arquivo.get("name", "").lower().endswith(".pdf"):
            raise RuntimeError(
                f"O arquivo da RPV {numero} não parece ser PDF: {arquivo.get('name')}"
            )

        destino_dir.mkdir(parents=True, exist_ok=True)
        destino = destino_dir / f"{numero}.pdf"

        request = self.drive.files().get_media(
            fileId=arquivo["id"], supportsAllDrives=True
        )
        with io.FileIO(destino, "wb") as fh:
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()

        if not destino.exists() or destino.stat().st_size == 0:
            raise RuntimeError(f"A RPV {numero} foi baixada vazia.")

        return destino
