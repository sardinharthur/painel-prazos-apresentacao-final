from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def _normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFD", str(texto or ""))
    texto = "".join(ch for ch in texto if unicodedata.category(ch) != "Mn")
    return " ".join(texto.upper().strip().split())


def _coluna_a1(indice_zero_based: int) -> str:
    numero = indice_zero_based + 1
    letras = ""
    while numero:
        numero, resto = divmod(numero - 1, 26)
        letras = chr(65 + resto) + letras
    return letras


@dataclass(frozen=True)
class LinhaPendente:
    numero_linha: int
    autos: str
    autor: str
    natureza: str
    valor: str
    evento: str
    nome_paciente: str
    cpf_paciente: str


class PlanilhaRPV:
    def __init__(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        header_row: int = 1,
        nome_paciente_header: str = "NOME PACIENTE",
        cpf_paciente_header: str = "CPF PACIENTE",
        status_header: str = "STATUS AUTOMAÇÃO",
    ):
        self.spreadsheet_id = spreadsheet_id
        self.sheet_name = sheet_name
        self.header_row = header_row
        self.nome_paciente_header = _normalizar(nome_paciente_header)
        self.cpf_paciente_header = _normalizar(cpf_paciente_header)
        self.status_header = _normalizar(status_header)
        self.service = self._autorizar()
        self.headers: list[str] = []
        self.header_index: dict[str, int] = {}

    @staticmethod
    def _autorizar():
        raiz_proj = Path(__file__).resolve().parents[3]
        candidatos_cred = [
            Path("credentials.json"),
            raiz_proj / "saida" / "credentials.json",
            raiz_proj / "robos" / "rpv" / "ROBO2" / "credentials.json",
        ]
        cred_path = next((p for p in candidatos_cred if p.exists()), None)

        candidatos_token = [
            Path("token.json"),
            raiz_proj / "saida" / "token_google_institucional.json",
            raiz_proj / "saida" / "token_sheets.json",
        ]
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
                if not cred_path:
                    raise FileNotFoundError(
                        "Arquivo credentials.json não encontrado. Configure o login Google OAuth no Painel ou copie credentials.json para esta pasta."
                    )
                flow = InstalledAppFlow.from_client_secrets_file(str(cred_path), SCOPES)
                creds = flow.run_local_server(port=0, hd="pge.pr.gov.br", prompt="select_account")
            Path("token.json").write_text(creds.to_json(), encoding="utf-8")
            try:
                (raiz_proj / "saida").mkdir(parents=True, exist_ok=True)
                (raiz_proj / "saida" / "token_google_institucional.json").write_text(creds.to_json(), encoding="utf-8")
            except Exception:
                pass

        return build("sheets", "v4", credentials=creds)

    def _ler_tudo(self) -> list[list[Any]]:
        try:
            resultado = (
                self.service.spreadsheets()
                .values()
                .get(
                    spreadsheetId=self.spreadsheet_id,
                    range=f"'{self.sheet_name}'!A:ZZ",
                    valueRenderOption="FORMATTED_VALUE",
                )
                .execute()
            )
            return resultado.get("values", [])
        except HttpError as exc:
            raise RuntimeError(f"Erro ao ler a planilha: {exc}") from exc

    def _montar_cabecalhos(self, linhas: list[list[Any]]) -> None:
        if self.header_row < 1 or self.header_row > len(linhas):
            raise ValueError("header_row está fora do intervalo da planilha.")

        self.headers = [str(v).strip() for v in linhas[self.header_row - 1]]
        self.header_index = {
            _normalizar(nome): indice for indice, nome in enumerate(self.headers)
        }

        obrigatorios = [
            "AUTOS",
            "AUTOR",
            "NATUREZA",
            "VALOR",
            self.nome_paciente_header,
            self.cpf_paciente_header,
        ]
        faltantes = [h for h in obrigatorios if h not in self.header_index]
        if faltantes:
            raise ValueError(
                "Cabeçalhos obrigatórios não encontrados: " + ", ".join(faltantes)
            )

    @staticmethod
    def _valor(linha: list[Any], indice: int | None) -> str:
        if indice is None or indice >= len(linha):
            return ""
        return str(linha[indice]).strip()

    def listar_pendentes(self) -> list[LinhaPendente]:
        linhas = self._ler_tudo()
        self._montar_cabecalhos(linhas)

        i_autos = self.header_index["AUTOS"]
        i_autor = self.header_index["AUTOR"]
        i_natureza = self.header_index["NATUREZA"]
        i_valor = self.header_index["VALOR"]
        i_evento = self.header_index.get("EVENTO")
        i_nome = self.header_index[self.nome_paciente_header]
        i_cpf = self.header_index[self.cpf_paciente_header]

        pendentes: list[LinhaPendente] = []
        for numero_linha, linha in enumerate(
            linhas[self.header_row :], start=self.header_row + 1
        ):
            autos = self._valor(linha, i_autos)
            if not autos:
                continue

            autor = self._valor(linha, i_autor)
            natureza = self._valor(linha, i_natureza)
            valor = self._valor(linha, i_valor)
            evento = self._valor(linha, i_evento)
            nome_paciente = self._valor(linha, i_nome)
            cpf_paciente = self._valor(linha, i_cpf)

            if autor and natureza and valor and nome_paciente and cpf_paciente:
                continue

            pendentes.append(
                LinhaPendente(
                    numero_linha=numero_linha,
                    autos=autos,
                    autor=autor,
                    natureza=natureza,
                    valor=valor,
                    evento=evento,
                    nome_paciente=nome_paciente,
                    cpf_paciente=cpf_paciente,
                )
            )

        return pendentes

    def _garantir_headers(self) -> None:
        if not self.header_index:
            linhas = self._ler_tudo()
            self._montar_cabecalhos(linhas)

    def atualizar_campos(self, numero_linha: int, campos: dict[str, str | None]) -> None:
        self._garantir_headers()
        dados = []

        for cabecalho, valor in campos.items():
            if valor is None:
                continue
            chave = _normalizar(cabecalho)
            indice = self.header_index.get(chave)
            if indice is None:
                continue
            coluna = _coluna_a1(indice)
            dados.append(
                {
                    "range": f"'{self.sheet_name}'!{coluna}{numero_linha}",
                    "values": [[str(valor)]],
                }
            )

        if not dados:
            return

        try:
            (
                self.service.spreadsheets()
                .values()
                .batchUpdate(
                    spreadsheetId=self.spreadsheet_id,
                    body={"valueInputOption": "USER_ENTERED", "data": dados},
                )
                .execute()
            )
        except HttpError as exc:
            raise RuntimeError(f"Erro ao atualizar a planilha: {exc}") from exc

    def atualizar_status(self, numero_linha: int, status: str) -> None:
        self.atualizar_campos(numero_linha, {self.status_header: status})
