from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import pymupdf


@dataclass(frozen=True)
class DadosRPV:
    estado_parana: bool
    beneficiario: str | None
    natureza_original: str | None
    natureza_planilha: str | None
    valor: str | None


@dataclass(frozen=True)
class Paciente:
    nome: str | None
    cpf: str | None


def extrair_texto_pdf(caminho: str | Path) -> str:
    with pymupdf.open(str(caminho)) as documento:
        return "\n".join(pagina.get_text("text") for pagina in documento)


def _compactar(texto: str) -> str:
    return " ".join(str(texto or "").replace("\u00a0", " ").split())


def _sem_acentos(texto: str) -> str:
    normalizado = unicodedata.normalize("NFD", texto)
    return "".join(ch for ch in normalizado if unicodedata.category(ch) != "Mn")


def _capturar(texto: str, padrao: str) -> str | None:
    achado = re.search(padrao, texto, flags=re.IGNORECASE | re.DOTALL)
    if not achado:
        return None
    return _compactar(achado.group(1)).strip(" :-")


def _classificar_natureza(natureza: str | None) -> str | None:
    if not natureza:
        return None
    base = _sem_acentos(natureza).upper()
    if "ADVOCATIC" in base:
        return "Honorários Advocatícios"
    if "PERICIA" in base or "DATIVO" in base or "AJG" in base:
        return "Honorários Periciais"
    return None


def analisar_texto(texto_original: str) -> DadosRPV:
    texto = _compactar(texto_original)
    base = _sem_acentos(texto).upper()

    estado_parana = bool(
        re.search(r"\bPARA\s*:\s*ESTADO DO PARANA\b", base)
        or re.search(r"\bREQUERIDO\s*:\s*ESTADO DO PARANA\b", base)
    )

    beneficiario = _capturar(
        texto,
        r"Benefici[aá]rio\s*:\s*(.*?)\s*(?:\(\s*(?:CPF|CNPJ)\s*:|DATA-BASE\s*:|TOTAL REQUISITADO)",
    )

    natureza = _capturar(
        texto,
        r"Natureza da Obriga[cç][aã]o\s*:\s*(.*?)\s*(?:Natureza do Cr[eé]dito\s*:|Data do ajuizamento)",
    )

    valor_match = re.search(
        r"TOTAL REQUISITADO\s*\*?\s*:\s*R\$\s*([0-9.]+,[0-9]{2})",
        texto,
        flags=re.IGNORECASE,
    )
    valor = f"R$ {valor_match.group(1)}" if valor_match else None

    return DadosRPV(
        estado_parana=estado_parana,
        beneficiario=beneficiario,
        natureza_original=natureza,
        natureza_planilha=_classificar_natureza(natureza),
        valor=valor,
    )


def analisar_pdf(caminho: str | Path) -> DadosRPV:
    return analisar_texto(extrair_texto_pdf(caminho))


def _somente_digitos(texto: str) -> str:
    return re.sub(r"\D", "", str(texto or ""))


def _cpf_valido(cpf: str) -> bool:
    digitos = _somente_digitos(cpf)
    if len(digitos) != 11 or len(set(digitos)) == 1:
        return False

    numeros = [int(x) for x in digitos]

    soma = sum(numeros[i] * (10 - i) for i in range(9))
    d1 = (soma * 10) % 11
    d1 = 0 if d1 == 10 else d1
    if numeros[9] != d1:
        return False

    soma = sum(numeros[i] * (11 - i) for i in range(10))
    d2 = (soma * 10) % 11
    d2 = 0 if d2 == 10 else d2
    return numeros[10] == d2


def formatar_cpf(cpf: str) -> str | None:
    digitos = _somente_digitos(cpf)
    if not _cpf_valido(digitos):
        return None
    return f"{digitos[:3]}.{digitos[3:6]}.{digitos[6:9]}-{digitos[9:]}"


def _limpar_nome(nome: str) -> str:
    nome = _compactar(nome).strip(" ,.;:-")
    # Remove restos de cabeçalhos comuns antes do nome.
    nome = re.sub(
        r"^(?:AO|À|EXCELENT[IÍ]SSIMO|EXCELENT[IÍ]SSIMA|MERIT[IÍ]SSIMO|MERIT[IÍ]SSIMA)\b.*?\n",
        "",
        nome,
        flags=re.IGNORECASE,
    )
    return nome.strip(" ,.;:-")


def _nome_plausivel(nome: str) -> bool:
    nome = _limpar_nome(nome)
    if not (5 <= len(nome) <= 140):
        return False

    palavras = nome.split()
    if not (2 <= len(palavras) <= 14):
        return False

    bloqueados = {
        "EXCELENTISSIMO", "EXCELENTÍSSIMO", "EXCELENTISSIMA", "EXCELENTÍSSIMA",
        "MERITISSIMO", "MERITÍSSIMO", "MERITISSIMA", "MERITÍSSIMA",
        "AUTOR", "AUTORA", "REQUERENTE", "ADVOGADO", "ADVOGADA",
        "PROCURADOR", "PROCURADORA", "TRIBUNAL", "JUIZO", "JUÍZO",
        "ESTADO", "UNIÃO", "UNIAO", "MUNICIPIO", "MUNICÍPIO",
    }
    if any(p.upper().strip(".,:") in bloqueados for p in palavras):
        return False

    # Um nome deve ter letras em praticamente todas as palavras.
    if sum(any(c.isalpha() for c in p) for p in palavras) < 2:
        return False

    return True


def _nome_antes_do_cpf(bloco_antes: str) -> str | None:
    """
    Prioriza o padrão real das iniciais:
    NOME COMPLETO, brasileira/brasileiro, estado civil, profissão... CPF ...
    """
    # 1) Nome imediatamente antes da qualificação "brasileira/brasileiro".
    candidatos = re.findall(
        r"([A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÖØ-öø-ÿ'’.\- ]{4,139}?)\s*,\s*"
        r"(?:brasileir[oa]|nacionalidade\s+brasileira)\b",
        bloco_antes,
        flags=re.IGNORECASE,
    )
    for candidato in reversed(candidatos):
        nome = _limpar_nome(candidato)
        # Evita carregar uma linha inteira do endereçamento.
        if "\n" in nome:
            nome = nome.splitlines()[-1].strip()
        if _nome_plausivel(nome):
            return nome

    # 2) Padrão geral: último trecho de nome seguido de vírgula antes do CPF.
    candidatos = re.findall(
        r"([A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÖØ-öø-ÿ'’.\- ]{4,139})\s*,",
        bloco_antes,
    )
    for candidato in reversed(candidatos):
        nome = _limpar_nome(candidato)
        if _nome_plausivel(nome):
            return nome

    # 3) Linhas imediatamente anteriores.
    linhas = [linha.strip() for linha in bloco_antes.splitlines() if linha.strip()]
    for linha in reversed(linhas[-15:]):
        nome = _limpar_nome(linha)
        if _nome_plausivel(nome):
            return nome

    return None


def extrair_paciente_inicial_texto(texto_original: str) -> Paciente:
    """
    NOME + CPF sempre são obtidos do INIC1.

    A busca dá prioridade ao COMEÇO da petição, onde normalmente aparece a
    qualificação da parte, e só aceita CPF matematicamente válido.
    """
    texto = str(texto_original or "").replace("\u00a0", " ")

    # Começo do documento: grande o bastante para alcançar a qualificação,
    # inclusive se ela cair na segunda/terceira página do PDF extraído.
    trecho = texto[:45000]

    cpf_regex = re.compile(
        r"\bCPF\b"
        r"(?:\s*(?:sob|inscrit[oa]\s+no|portador(?:a)?\s+do|cadastrad[oa]\s+no))*"
        r"\s*(?:o\s*)?"
        r"(?:n[º°o.]?\s*)?"
        r"(?:sob\s+o\s*)?"
        r"(?:n[º°o.]?\s*)?"
        r"[:\-]?\s*"
        r"(\d{3}\.?\d{3}\.?\d{3}[-.]?\d{2}|\d{11})\b",
        flags=re.IGNORECASE,
    )

    # Também cobre "inscrita no CPF sob o nº ..."
    cpf_generico = re.compile(
        r"(?:inscrit[oa]\s+no\s+)?CPF"
        r".{0,45}?"
        r"(\d{3}\.?\d{3}\.?\d{3}[-.]?\d{2}|\d{11})\b",
        flags=re.IGNORECASE | re.DOTALL,
    )

    achados = list(cpf_regex.finditer(trecho))
    if not achados:
        achados = list(cpf_generico.finditer(trecho))

    for achado in achados:
        cpf = formatar_cpf(achado.group(1))
        if not cpf:
            continue

        inicio = max(0, achado.start() - 1400)
        antes = trecho[inicio:achado.start()]
        nome = _nome_antes_do_cpf(antes)

        if nome:
            # Mantém caixa do documento; se vier todo em maiúsculas, permanece assim.
            return Paciente(nome=_compactar(nome), cpf=cpf)

    return Paciente(nome=None, cpf=None)


def extrair_paciente_inicial_pdf(caminho: str | Path) -> Paciente:
    return extrair_paciente_inicial_texto(extrair_texto_pdf(caminho))
