from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


@dataclass
class LinhaPendente:
    numero_linha: int
    processo: str
    cpf: str
    nome: str
    protocolo: str = ""


class GoogleSheets:
    def __init__(self, config_path: str | Path = "config.json"):
        self.config_path = Path(config_path)
        self.config = self._carregar_config()
        self.url = self.config["planilha"]["url"].strip()
        self.aba = self.config["planilha"]["aba"].strip()
        self.linha_cabecalho = int(self.config["planilha"].get("linha_cabecalho", 1))
        self.colunas = self.config["planilha"]["colunas"]

        self.url = self._garantir_url_planilha(self.url)
        self.spreadsheet_id = self._extrair_id(self.url)
        self.service = build("sheets", "v4", credentials=self._autenticar())

    def _carregar_config(self) -> dict[str, Any]:
        if not self.config_path.exists():
            raise FileNotFoundError("config.json não encontrado.")
        return json.loads(self.config_path.read_text(encoding="utf-8"))

    def _salvar_config(self) -> None:
        self.config_path.write_text(
            json.dumps(self.config, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _garantir_url_planilha(self, url: str) -> str:
        if url and "docs.google.com/spreadsheets/d/" in url:
            return url

        print("\nO link da planilha ainda não está configurado.")
        url = input("Cole o link completo do Google Sheets: ").strip()
        if "docs.google.com/spreadsheets/d/" not in url:
            raise ValueError("O link informado não parece ser um Google Sheets válido.")

        self.config["planilha"]["url"] = url
        self._salvar_config()
        print("Link salvo em config.json. Nas próximas execuções não será solicitado.")
        return url

    @staticmethod
    def _extrair_id(url: str) -> str:
        m = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", url)
        if not m:
            raise ValueError("Não foi possível extrair o ID da planilha.")
        return m.group(1)

    @staticmethod
    def _autenticar() -> Credentials:
        raiz_proj = Path(__file__).resolve().parents[3]
        token_path = Path("token.json")
        candidatos_token = [
            token_path,
            raiz_proj / "saida" / "token_google_institucional.json",
            raiz_proj / "saida" / "token_sheets.json",
            raiz_proj / "robos" / "rpv" / "ROBO1_TESTE_FINAL" / "token.json",
        ]
        candidatos_cred = [
            Path("credentials.json"),
            raiz_proj / "saida" / "credentials.json",
            raiz_proj / "robos" / "rpv" / "ROBO1_TESTE_FINAL" / "credentials.json",
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
                creds.refresh(Request())
            else:
                if not credentials_path:
                    raise FileNotFoundError(
                        "credentials.json não encontrado. "
                        "Configure o login Google OAuth no Painel ou copie credentials.json para esta pasta."
                    )
                flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
                creds = flow.run_local_server(port=0, hd="pge.pr.gov.br", prompt="select_account")

            token_path.write_text(creds.to_json(), encoding="utf-8")
            try:
                (raiz_proj / "saida").mkdir(parents=True, exist_ok=True)
                (raiz_proj / "saida" / "token_google_institucional.json").write_text(creds.to_json(), encoding="utf-8")
            except Exception:
                pass

        return creds

    @staticmethod
    def _normalizar_cabecalho(valor: Any) -> str:
        return str(valor or "").strip().upper()

    def _ler_tabela(self) -> list[list[str]]:
        intervalo = f"'{self.aba}'!A:ZZ"
        result = (
            self.service.spreadsheets()
            .values()
            .get(spreadsheetId=self.spreadsheet_id, range=intervalo)
            .execute()
        )
        return result.get("values", [])

    def listar_pendentes(self) -> list[LinhaPendente]:
        valores = self._ler_tabela()
        if len(valores) < self.linha_cabecalho:
            return []

        cabecalho = valores[self.linha_cabecalho - 1]
        mapa = {
            self._normalizar_cabecalho(nome): idx
            for idx, nome in enumerate(cabecalho)
        }

        def idx_col(chave: str) -> int:
            nome_config = self._normalizar_cabecalho(self.colunas[chave])
            if nome_config in mapa:
                return mapa[nome_config]

            aliases = {
                "processo": ["AUTOS", "PROCESSO", "NÚMERO DO PROCESSO", "NUMERO DO PROCESSO"],
                "protocolo": ["PROTOCOLO", "NÚMERO DO PROTOCOLO", "NUMERO DO PROTOCOLO"],
                "nome": ["NOME PACIENTE", "NOME DO PACIENTE", "PACIENTE"],
                "cpf": ["CPF PACIENTE", "CPF DO PACIENTE", "CPF"],
            }
            for alias in aliases.get(chave, []):
                if self._normalizar_cabecalho(alias) in mapa:
                    return mapa[self._normalizar_cabecalho(alias)]

            raise KeyError(
                f"Coluna '{self.colunas[chave]}' não encontrada na aba '{self.aba}'."
            )

        idx_processo = idx_col("processo")
        idx_protocolo = idx_col("protocolo")
        idx_nome = idx_col("nome")
        idx_cpf = idx_col("cpf")

        def valor(row: list[str], idx: int) -> str:
            return str(row[idx]).strip() if idx < len(row) else ""

        pendentes: list[LinhaPendente] = []

        for numero_linha, row in enumerate(
            valores[self.linha_cabecalho:],
            start=self.linha_cabecalho + 1,
        ):
            processo = valor(row, idx_processo)
            protocolo = valor(row, idx_protocolo)
            nome = valor(row, idx_nome)
            cpf = valor(row, idx_cpf)

            # Regra principal: se já existe PROTOCOLO, o Robô 2 não toca na linha.
            if protocolo:
                continue

            # Só cadastra linhas que o Robô 1 já deixou completas.
            if not processo or not nome or not cpf:
                continue

            pendentes.append(
                LinhaPendente(
                    numero_linha=numero_linha,
                    processo=processo,
                    cpf=cpf,
                    nome=nome,
                    protocolo="",
                )
            )

        return pendentes

    def protocolo_da_linha(self, numero_linha: int) -> str:
        valores = self._ler_tabela()
        cabecalho = valores[self.linha_cabecalho - 1]
        mapa = {
            self._normalizar_cabecalho(nome): idx
            for idx, nome in enumerate(cabecalho)
        }
        nome_col = self._normalizar_cabecalho(self.colunas["protocolo"])
        if nome_col not in mapa:
            raise KeyError(f"Coluna '{self.colunas['protocolo']}' não encontrada.")

        idx = mapa[nome_col]
        row_idx = numero_linha - 1
        if row_idx >= len(valores):
            return ""
        row = valores[row_idx]
        return str(row[idx]).strip() if idx < len(row) else ""

    def gravar_protocolo(self, numero_linha: int, protocolo: str) -> None:
        valores = self._ler_tabela()
        cabecalho = valores[self.linha_cabecalho - 1]
        mapa = {
            self._normalizar_cabecalho(nome): idx
            for idx, nome in enumerate(cabecalho)
        }

        nome_col = self._normalizar_cabecalho(self.colunas["protocolo"])
        if nome_col not in mapa:
            raise KeyError(f"Coluna '{self.colunas['protocolo']}' não encontrada.")

        idx_coluna = mapa[nome_col]
        letra = self._numero_para_coluna(idx_coluna + 1)
        range_a1 = f"'{self.aba}'!{letra}{numero_linha}"

        # Proteção contra duplicidade/conflito:
        atual = self.protocolo_da_linha(numero_linha)
        if atual:
            raise RuntimeError(
                f"A linha {numero_linha} já recebeu o protocolo '{atual}'. "
                "O valor não foi sobrescrito."
            )

        (
            self.service.spreadsheets()
            .values()
            .update(
                spreadsheetId=self.spreadsheet_id,
                range=range_a1,
                valueInputOption="RAW",
                body={"values": [[protocolo]]},
            )
            .execute()
        )

    @staticmethod
    def _numero_para_coluna(numero: int) -> str:
        letras = ""
        while numero:
            numero, resto = divmod(numero - 1, 26)
            letras = chr(65 + resto) + letras
        return letras
