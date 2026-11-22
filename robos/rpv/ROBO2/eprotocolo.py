from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urljoin

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    sync_playwright,
)


PADRAO_PROTOCOLO = re.compile(r"\b\d{2}\.\d{3}\.\d{3}-\d\b")


class EProtocolo:

    def __init__(self, config_path: str | Path = "config.json"):
        self.config_path = Path(config_path)

        self.config = json.loads(
            self.config_path.read_text(encoding="utf-8")
        )

        self.cfg = self.config["eprotocolo"]
        self.fixos = self.cfg["dados_fixos"]

        self.pw: Playwright | None = None
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None

    # ============================================================
    # INICIAR
    # ============================================================

    def iniciar(self, usuario: str, senha: str) -> None:
        url = str(self.cfg.get("url_login", "")).strip()

        if not url or url.startswith("COLE_AQUI"):
            raise RuntimeError(
                "Configure eprotocolo.url_login no config.json."
            )

        self.pw = sync_playwright().start()

        self.browser = self.pw.chromium.launch(
            headless=bool(self.cfg.get("headless", False)),
            slow_mo=int(self.cfg.get("slow_mo_ms", 0)),
        )

        self.context = self.browser.new_context()
        self.page = self.context.new_page()

        self.page.set_default_timeout(
            int(self.cfg.get("timeout_ms", 30000))
        )

        self.page.goto(
            url,
            wait_until="domcontentloaded",
        )

        self._login(usuario, senha)

    # ============================================================
    # FECHAR
    # ============================================================

    def fechar(self) -> None:
        try:
            if self.context:
                self.context.close()

            if self.browser:
                self.browser.close()

        finally:
            if self.pw:
                self.pw.stop()

    # ============================================================
    # LOGIN
    # ============================================================

    def _login(self, usuario: str, senha: str) -> None:
        assert self.page is not None
        page = self.page

        usuario_ok = self._preencher_primeiro_disponivel(
            [
                lambda: page.get_by_label(
                    re.compile(r"usu[aá]rio|login|cpf", re.I)
                ),
                lambda: page.locator('input[name*="user" i]'),
                lambda: page.locator('input[name*="login" i]'),
                lambda: page.locator('input[type="text"]').first,
            ],
            usuario,
        )

        senha_ok = self._preencher_primeiro_disponivel(
            [
                lambda: page.get_by_label(
                    re.compile(r"senha", re.I)
                ),
                lambda: page.locator('input[type="password"]').first,
            ],
            senha,
        )

        if not usuario_ok or not senha_ok:
            raise RuntimeError(
                "Não consegui localizar usuário ou senha."
            )

        botao_ok = self._clicar_primeiro_disponivel(
            [
                lambda: page.get_by_role(
                    "button",
                    name=re.compile(r"entrar|acessar|login", re.I),
                ),
                lambda: page.locator('button[type="submit"]'),
                lambda: page.locator('input[type="submit"]'),
            ]
        )

        if not botao_ok:
            raise RuntimeError(
                "Não consegui localizar o botão de login."
            )

        page.wait_for_load_state("domcontentloaded")

    # ============================================================
    # CRIAR PROTOCOLO
    # ============================================================

    def criar_protocolo(
        self,
        processo: str,
        cpf: str,
        nome: str,
    ) -> str | None:

        assert self.page is not None
        page = self.page

        print("\nAbrindo tela Incluir Protocolo...")
        self._abrir_incluir_protocolo()

        print("Preenchendo dados fixos...")
        self._preencher_dados_fixos()

        print("Preenchendo descrição...")
        self._preencher_descricao(processo)

        print("Preenchendo interessado...")
        self._preencher_interessado(cpf, nome)

        # ========================================================
        # MODO TESTE
        # ========================================================

        if bool(self.cfg.get("modo_teste", True)):
            print("\n[MODO TESTE] Formulário preenchido.")
            print("Não cliquei em Próximo.")
            print("Nenhum protocolo foi criado.")
            return None

        # ========================================================
        # MODO REAL
        # ========================================================

        print("Clicando em Próximo...")

        page.get_by_role(
            "button",
            name=re.compile(r"^Pr[oó]ximo$", re.I),
        ).click()

        page.wait_for_load_state("domcontentloaded")

        print("Capturando número do protocolo...")

        protocolo = self._capturar_numero_protocolo()

        if not protocolo:
            raise RuntimeError(
                "A tela abriu após Próximo, "
                "mas não encontrei o número do protocolo."
            )

        print(f"PROTOCOLO CAPTURADO: {protocolo}")

        return protocolo

    # ============================================================
    # ABRIR NOVO PROTOCOLO
    # ============================================================

    def _abrir_incluir_protocolo(self) -> None:
        assert self.page is not None
        page = self.page

        # Em lote, não dependemos mais do menu lateral.
        # Mantém a sessão autenticada e abre diretamente a tela oficial.
        pagina_incluir = (
            "/spiweb/"
            "incluirProcessoDigital.do"
            "?action=iniciarProcesso"
        )

        url_incluir = urljoin(
            page.url,
            pagina_incluir,
        )

        page.goto(
            url_incluir,
            wait_until="domcontentloaded",
        )

        page.wait_for_timeout(400)

    # ============================================================
    # DADOS FIXOS
    # ============================================================

    def _preencher_dados_fixos(self) -> None:
        self._selecionar_combo(
            "Órgão de Cadastro",
            self.fixos["orgao_cadastro"],
        )

        self._selecionar_combo(
            "Local de Cadastro",
            self.fixos["local_cadastro"],
        )

        self._selecionar_combo(
            "Espécie do Documento",
            self.fixos["especie_documento"],
        )

        self._clicar_texto_exato(
            self.fixos["restricao_acesso"]
        )

        self._selecionar_combo(
            "Assunto",
            self.fixos["assunto"],
        )

        self._selecionar_combo(
            "Palavra-Chave 1",
            self.fixos["palavra_chave_1"],
        )

        self._selecionar_combo(
            "País",
            self.fixos["pais"],
        )

        self._selecionar_combo(
            "Estado",
            self.fixos["estado"],
        )

        self._selecionar_combo(
            "Cidade",
            self.fixos["cidade"],
        )

    # ============================================================
    # DESCRIÇÃO
    # ============================================================

    def _preencher_descricao(
        self,
        processo: str,
    ) -> None:

        assert self.page is not None
        page = self.page

        descricao = (
            "Requisição de Pequeno Valor "
            "oriunda dos Autos num. "
            f"{processo}"
        )

        candidatos = [
            lambda: page.get_by_label(
                re.compile(
                    r"Descri[cç][aã]o do protocolo",
                    re.I,
                )
            ),
            lambda: page.locator("textarea").first,
        ]

        if not self._preencher_primeiro_disponivel(
            candidatos,
            descricao,
        ):
            raise RuntimeError(
                "Não localizei o campo Descrição do protocolo."
            )

    # ============================================================
    # INTERESSADO
    # ============================================================

    def _preencher_interessado(
        self,
        cpf: str,
        nome: str,
    ) -> None:

        assert self.page is not None
        page = self.page

        # ========================================================
        # 1 - PESSOA FISICA
        # ========================================================

        print("  1/5 - Selecionando PESSOA FISICA...")

        resultado = page.locator("#tipoInteressadoEdit").evaluate(
            """
            (select) => {
                const alvo = Array.from(select.options).find(
                    o => o.text.trim() === "PESSOA FISICA"
                );

                if (!alvo) {
                    return {
                        ok: false,
                        opcoes: Array.from(select.options).map(
                            o => o.text.trim()
                        )
                    };
                }

                select.value = alvo.value;

                select.dispatchEvent(
                    new Event("change", { bubbles: true })
                );

                return {
                    ok: true,
                    valor: alvo.value,
                    texto: alvo.text.trim()
                };
            }
            """
        )

        if not resultado.get("ok"):
            raise RuntimeError(
                "Não encontrei PESSOA FISICA no select "
                "tipoInteressadoEdit. "
                f"Opções: {resultado.get('opcoes')}"
            )

        page.wait_for_timeout(500)

        selecionado = page.locator(
            "#tipoInteressadoEdit"
        ).evaluate(
            """
            (select) => {
                const o = select.options[select.selectedIndex];
                return o ? o.text.trim() : "";
            }
            """
        )

        if selecionado != "PESSOA FISICA":
            raise RuntimeError(
                "O eProtocolo não manteve PESSOA FISICA selecionada. "
                f"Valor atual: {selecionado}"
            )

        print("      PESSOA FISICA selecionada.")

        # ========================================================
        # 2 - CPF
        # ========================================================

        print("  2/5 - Selecionando CPF...")

        page.get_by_text(
            "CPF",
            exact=True,
        ).click()

        page.wait_for_timeout(300)

        print("      CPF selecionado.")

        # ========================================================
        # 3 - CPF
        # ========================================================

        cpf_limpo = re.sub(r"\D", "", cpf)

        print(
            f"  3/5 - Preenchendo CPF: {cpf_limpo}"
        )

        campo_cpf = page.get_by_role(
            "textbox",
            name="* Número da Identificação:",
            exact=True,
        )

        campo_cpf.fill(cpf_limpo)

        # Faz o eProtocolo processar o CPF antes do nome.
        campo_cpf.press("Tab")

        page.wait_for_timeout(1000)

        # ========================================================
        # 4 - NOME
        # ========================================================

        print(
            f"  4/5 - Preenchendo nome: {nome}"
        )

        campo_nome = page.get_by_role(
            "textbox",
            name="*Nome Completo:",
            exact=True,
        )

        campo_nome.wait_for(
            state="visible",
            timeout=5000,
        )

        campo_nome.click()
        campo_nome.fill(nome.strip())

        page.wait_for_timeout(300)

        nome_digitado = campo_nome.input_value()

        if nome_digitado.strip() != nome.strip():
            raise RuntimeError(
                "O campo Nome Completo não manteve o valor. "
                f"Esperado: '{nome}'. "
                f"Encontrado: '{nome_digitado}'."
            )

        print(
            f"      Nome preenchido: {nome_digitado}"
        )

        # ========================================================
        # 5 - CONFIRMAR INTERESSADO
        # ========================================================

        print(
            "  5/5 - Confirmando interessado..."
        )

        page.get_by_role(
            "button",
            name="Confirmar Interessado",
            exact=True,
        ).click()

        # Aguarda a resposta do eProtocolo.
        page.wait_for_timeout(700)

        # ========================================================
        # POPUP: JÁ EXISTE PROTOCOLO PARA O INTERESSADO
        # ========================================================
        # REGRA TEMPORÁRIA:
        # se aparecer o aviso de protocolo já existente,
        # apenas CONFIRMA e continua criando o novo protocolo.
        # Não captura, não compara e não grava o número mostrado.
        aviso_existente = page.get_by_text(
            re.compile(
                r"Já existe para esse interessado",
                re.I,
            )
        )

        if (
            aviso_existente.count() > 0
            and aviso_existente.first.is_visible()
        ):
            print(
                "      Aviso de protocolo existente detectado."
            )
            print(
                "      Confirmando inclusão do interessado..."
            )

            confirmou_popup = False

            # Preferência: botão dentro do diálogo/modal.
            try:
                dialogo = page.get_by_role("dialog")

                if (
                    dialogo.count() > 0
                    and dialogo.last.is_visible()
                ):
                    botao_confirmar = dialogo.last.get_by_role(
                        "button",
                        name="Confirmar",
                        exact=True,
                    )

                    if botao_confirmar.count() > 0:
                        botao_confirmar.click()
                        confirmou_popup = True
            except Exception:
                pass

            # Fallback: botão Confirmar visível na página.
            if not confirmou_popup:
                botoes = page.get_by_role(
                    "button",
                    name="Confirmar",
                    exact=True,
                )

                for i in range(botoes.count() - 1, -1, -1):
                    botao = botoes.nth(i)

                    try:
                        if botao.is_visible():
                            botao.click()
                            confirmou_popup = True
                            break
                    except Exception:
                        continue

            if not confirmou_popup:
                raise RuntimeError(
                    "O aviso de protocolo existente apareceu, "
                    "mas não consegui clicar no botão Confirmar."
                )

            page.wait_for_timeout(700)

            print(
                "      Inclusão confirmada. Continuando..."
            )

        print("      Interessado confirmado.")

    # ============================================================
    # CAPTURAR PROTOCOLO
    # ============================================================

    def _capturar_numero_protocolo(
        self,
    ) -> str | None:

        assert self.page is not None
        page = self.page

        try:
            titulo = (
                page.get_by_text(
                    re.compile(
                        r"Analisar Protocolo",
                        re.I,
                    )
                )
                .first
                .inner_text()
            )

            resultado = PADRAO_PROTOCOLO.search(
                titulo
            )

            if resultado:
                return resultado.group(0)

        except Exception:
            pass

        texto = page.locator("body").inner_text()

        resultado = PADRAO_PROTOCOLO.search(
            texto
        )

        if resultado:
            return resultado.group(0)

        return None

    # ============================================================
    # PRINT DE ERRO
    # ============================================================

    def salvar_print_erro(
        self,
        nome: str,
    ) -> None:

        if not self.page:
            return

        Path("prints_erro").mkdir(
            exist_ok=True
        )

        caminho = (
            Path("prints_erro")
            / nome
        )

        self.page.screenshot(
            path=str(caminho),
            full_page=True,
        )

    # ============================================================
    # COMBOS GENÉRICOS DOS DADOS FIXOS
    # ============================================================

    def _selecionar_combo(
        self,
        rotulo: str,
        opcao: str,
    ) -> None:

        assert self.page is not None
        page = self.page

        try:
            campo = page.get_by_label(
                re.compile(
                    re.escape(rotulo),
                    re.I,
                )
            )

            if (
                campo.count()
                and campo.first.evaluate(
                    "el => el.tagName"
                )
                == "SELECT"
            ):
                campo.first.select_option(
                    label=opcao
                )
                return

        except Exception:
            pass

        try:
            rotulo_elemento = (
                page.get_by_text(
                    re.compile(
                        rf"^\*?{re.escape(rotulo)}:?$",
                        re.I,
                    )
                )
                .first
            )

            container = rotulo_elemento.locator(
                "xpath=following::*[@role='combobox'][1]"
            )

            container.click()

            page.wait_for_timeout(100)

            page.get_by_text(
                opcao,
                exact=True,
            ).last.click()

            return

        except Exception:
            pass

    # ============================================================
    # HELPERS
    # ============================================================

    def _clicar_texto_exato(
        self,
        texto: str,
    ) -> bool:

        assert self.page is not None

        try:
            locator = self.page.get_by_text(
                texto,
                exact=True,
            )

            if locator.count():
                locator.first.click()
                return True

        except Exception:
            pass

        return False

    @staticmethod
    def _preencher_primeiro_disponivel(
        candidatos,
        valor: str,
    ) -> bool:

        for fabrica in candidatos:
            try:
                locator = fabrica()

                if locator.count():
                    locator.first.fill(valor)
                    return True

            except Exception:
                continue

        return False

    @staticmethod
    def _clicar_primeiro_disponivel(
        candidatos,
    ) -> bool:

        for fabrica in candidatos:
            try:
                locator = fabrica()

                if locator.count():
                    locator.first.click()
                    return True

            except Exception:
                continue

        return False
