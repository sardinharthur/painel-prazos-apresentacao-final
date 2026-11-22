/**
 * Painel de Prazos e Automações RPV / PROJUDI — Aplicação React 18
 * Procuradoria de Saúde (PRS) · Procuradoria-Geral do Estado do Paraná (PGE-PR)
 */
(function () {
  "use strict";

  const { useState, useEffect, useRef, useMemo, useCallback } = React;
  const h = React.createElement;

  const SYSTEMS = [
    { id: "todos", label: "Todos" },
    { id: "projudi", label: "PROJUDI" },
    { id: "eproc1", label: "EPROC · 1º Grau" },
    { id: "eprocRec", label: "EPROC · Recursal" },
    { id: "eprocTJ", label: "EPROC · TJPR" },
  ];

  const FONT_LEVELS = [1, 1.15, 1.3];

  const DEFAULT_RPV_ROBOTS = [
    {
      id: "robo1",
      order: 1,
      label: "ROBÔ 1 (Teste Final)",
      short_label: "ROBÔ 1",
      folder: "ROBO1_TESTE_FINAL",
      subtitle: "EPROC · Coleta RPV → Planilha",
      description:
        "Pesquisa processos pendentes no EPROC, extrai dados de REQEXT1/INIC1 (autor, natureza, valor, paciente, CPF) e preenche a planilha RPVs.",
      cwd: "robos/rpv/ROBO1_TESTE_FINAL",
      script: "launcher.py",
      alt_script: "main.py",
      status: "ready",
      progress: 0,
      current: 0,
      total: 0,
      message: "Pronto para executar",
      waiting_input: false,
      success: 0,
      errors: 0,
      log: [],
    },
    {
      id: "robo2",
      order: 2,
      label: "ROBÔ 2",
      short_label: "ROBÔ 2",
      folder: "ROBO2",
      subtitle: "E-PROTOCOLO · Criação de Protocolo",
      description:
        "Lê linhas prontas da planilha (AUTOS + NOME + CPF sem protocolo), cadastra o protocolo digital no eProtocolo e grava o número gerado.",
      cwd: "robos/rpv/ROBO2",
      script: "main.py",
      alt_script: "main.py",
      status: "ready",
      progress: 0,
      current: 0,
      total: 0,
      message: "Pronto para executar",
      waiting_input: false,
      success: 0,
      errors: 0,
      log: [],
    },
    {
      id: "robo4",
      order: 3,
      label: "ROBÔ 4",
      short_label: "ROBÔ 4",
      folder: "ROBO4",
      subtitle: "ASSINATURAS · REQEXT1 + RPV",
      description:
        "Baixa a RPV do Google Drive e o REQEXT1 do EPROC, anexa ambos na Minha Caixa do eProtocolo e solicita assinatura do procurador.",
      cwd: "robos/rpv/ROBO4",
      script: "main.py",
      alt_script: "main.py",
      status: "ready",
      progress: 0,
      current: 0,
      total: 0,
      message: "Pronto para executar",
      waiting_input: false,
      success: 0,
      errors: 0,
      log: [],
    },
    {
      id: "robo5",
      order: 4,
      label: "ROBÔ 5",
      short_label: "ROBÔ 5",
      folder: "ROBO5",
      subtitle: "ENVIO FINAL · Lote SESA / SESA-AT",
      description:
        "Varre a caixa de Pendências no eProtocolo, identifica as RPVs já assinadas, atualiza o volume e encaminha o lote para SESA / SESA-AT.",
      cwd: "robos/rpv/ROBO5",
      script: "robo5.py",
      alt_script: "robo5.py",
      status: "ready",
      progress: 0,
      current: 0,
      total: 0,
      message: "Pronto para executar",
      waiting_input: false,
      success: 0,
      errors: 0,
      log: [],
    },
  ];

  const demonstracao = window.PAINEL_DEMONSTRACAO;
  demonstracao?.prepararRobos(DEFAULT_RPV_ROBOTS);

  const RPV_STATUS_NAMES = {
    ready: "Pronto",
    running: "Executando",
    done: "Concluído",
    error: "Erro",
    stopped: "Interrompido",
  };

  function getStatusBadgeClass(status) {
    if (status === "done") return "status status-done";
    if (status === "running") return "soon";
    if (status === "error") return "today";
    if (status === "stopped") return "status status-review";
    return "status";
  }

  /**
   * Filtra mensagens internas de raspagem/coleta e logins nos sites quando o usuário
   * NÃO está autenticado na conta proprietária/administradora ("minha conta").
   */
  function sanitizeConsoleLinesForAccount(lines, isAdmin) {
    if (isAdmin) return lines || [];
    const hiddenPatterns = /puxando dados|coletando|login|senha|credencia|autentica|importando|\.xls|sapiens_atual|raspando|scraping/i;
    return (lines || []).filter((ln) => !hiddenPatterns.test(String(ln || "")));
  }

  function fileToBase64(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = reject;
      reader.readAsDataURL(file);
    });
  }

  /* =====================================================================
   * COMPONENTE 1: ÍCONE GOOGLE AUTH OFICIAL (SVG)
   * ===================================================================== */
  const IS_APPS_SCRIPT = Boolean(window.google?.script?.run);
  const SEM_SESSAO = { autenticado: false };
  /* =====================================================================
   * COMPONENTE 2: TELA INICIAL DE LOGIN (MODELO SAPIENS / PGE-PR - IMAGEM 1)
   * ===================================================================== */
  function SplashPge({ session, onSenha, onGoogle, authLoading, authMessage, checking, onRetry }) {
    const googleButton = useRef(null);
    const clientId = session.google_client_id;
    useEffect(() => {
      if (!clientId || !googleButton.current) return;
      const container = googleButton.current;
      const script = document.getElementById("google-identity");
      const renderGoogle = () => {
        const gsi = window.google?.accounts?.id;
        if (!gsi) return;
        gsi.initialize({ client_id: clientId, callback: ({ credential }) => onGoogle(credential) });
        gsi.renderButton(container, { theme: "outline", size: "large", locale: "pt-BR" });
      };
      if (window.google?.accounts?.id) renderGoogle();
      else script?.addEventListener("load", renderGoogle);
      return () => {
        script?.removeEventListener("load", renderGoogle);
        container.replaceChildren();
      };
    }, [clientId, onGoogle]);

    return h(
      "div",
      { className: "pge-splash-overlay", role: "dialog", "aria-modal": true, "aria-labelledby": "login-title" },
      h(
        "div",
        { className: "sapiens-login-card" },
        h(
          "div",
          { className: "sapiens-login-left" },
          !IS_APPS_SCRIPT && h("img", {
            src: "logo_parana.png",
            alt: "Brasão do Estado do Paraná",
            className: "sapiens-login-logo",
          }),
          h("div", { className: "sapiens-login-sys" }, "Painel de Prazos / PGE-PR"),
          h("div", { className: "sapiens-login-env" }, demonstracao ? "DEMONSTRAÇÃO" : "PRODUÇÃO")
        ),
        h(
          "div",
          { className: "sapiens-login-right" },
          h("h1", { className: "sapiens-login-heading", id: "login-title" }, "Entrar no Painel de Prazos"),
          checking
            ? h("p", { role: "status" }, "Verificando sessão…")
            : demonstracao
            ? h("button", {
                className: "alt-login-submit",
                onClick: () => onSenha("", ""),
              }, "Abrir demonstração")
            : IS_APPS_SCRIPT
            ? h("button", { className: "alt-login-submit", onClick: onRetry }, "Tentar novamente")
            : h(
                "form",
                {
                  className: "alt-login-form",
                  onSubmit: (event) => {
                    event.preventDefault();
                    const campos = new FormData(event.currentTarget);
                    onSenha(campos.get("email"), campos.get("senha"));
                  },
                },
                h("label", { htmlFor: "login-email", className: "alt-login-label" }, "E-mail"),
                h("input", {
                  id: "login-email", name: "email", type: "email", required: true,
                  autoComplete: "username", maxLength: 254, className: "alt-login-input",
                }),
                h("label", { htmlFor: "login-senha", className: "alt-login-label" }, "Senha"),
                h("input", {
                  id: "login-senha", name: "senha", type: "password", required: true,
                  autoComplete: "current-password", maxLength: 1024, className: "alt-login-input",
                }),
                h("button", { type: "submit", className: "alt-login-submit", disabled: authLoading },
                  authLoading ? "Entrando…" : "Entrar")
              ),
          clientId && h("div", { ref: googleButton, className: "google-gsi-container" }),
          authMessage && h("p", { className: "sapiens-login-msg", role: "alert" }, authMessage)
        )
      )
    );
  }

  /* =====================================================================
   * COMPONENTE 3: SHADCN UI BASE CAROUSEL
   * Referência oficial: https://ui.shadcn.com/docs/components/base/carousel
   * ===================================================================== */
  function Carousel({ children, selectedIndex, onSelectIndex, totalItems }) {
    const touchStartX = useRef(null);

    const canScrollPrev = totalItems > 1;
    const canScrollNext = totalItems > 1;

    const scrollPrev = useCallback(() => {
      if (totalItems <= 0) return;
      onSelectIndex((selectedIndex - 1 + totalItems) % totalItems);
    }, [selectedIndex, totalItems, onSelectIndex]);

    const scrollNext = useCallback(() => {
      if (totalItems <= 0) return;
      onSelectIndex((selectedIndex + 1) % totalItems);
    }, [selectedIndex, totalItems, onSelectIndex]);

    const handleKeyDown = (e) => {
      if (e.key === "ArrowLeft") {
        e.preventDefault();
        scrollPrev();
      } else if (e.key === "ArrowRight") {
        e.preventDefault();
        scrollNext();
      }
    };

    const handleTouchStart = (e) => {
      if (e.touches && e.touches.length > 0) {
        touchStartX.current = e.touches[0].clientX;
      }
    };

    const handleTouchEnd = (e) => {
      if (touchStartX.current === null || !e.changedTouches || !e.changedTouches.length) return;
      const deltaX = e.changedTouches[0].clientX - touchStartX.current;
      touchStartX.current = null;
      if (Math.abs(deltaX) > 40) {
        if (deltaX < 0) scrollNext();
        else scrollPrev();
      }
    };

    return h(
      "div",
      { className: "shadcn-carousel-wrapper" },
      h(
        "div",
        {
          className: "shadcn-carousel",
          role: "region",
          "aria-roledescription": "carousel",
          "aria-label": "Carrossel de Robôs RPV",
          tabIndex: 0,
          onKeyDown: handleKeyDown,
          onTouchStart: handleTouchStart,
          onTouchEnd: handleTouchEnd,
        },
        h(CarouselPrevious, { onClick: scrollPrev, disabled: !canScrollPrev }),
        h(CarouselContent, { selectedIndex }, children),
        h(CarouselNext, { onClick: scrollNext, disabled: !canScrollNext })
      ),
      h(
        "div",
        { className: "shadcn-carousel-footer" },
        h(
          "div",
          { className: "shadcn-carousel-dots" },
          Array.from({ length: totalItems }).map((_, idx) =>
            h("button", {
              key: idx,
              type: "button",
              className: "shadcn-carousel-dot" + (idx === selectedIndex ? " active" : ""),
              "aria-label": `Ir para slide ${idx + 1}`,
              onClick: () => onSelectIndex(idx),
            })
          )
        ),
        h("span", null, `Robô ${selectedIndex + 1} de ${totalItems}`)
      )
    );
  }

  function CarouselContent({ selectedIndex, children }) {
    return h(
      "div",
      { className: "shadcn-carousel-viewport", "data-slot": "carousel-content" },
      h(
        "div",
        {
          className: "shadcn-carousel-container",
          style: { transform: `translate3d(-${selectedIndex * 100}%, 0px, 0px)` },
        },
        children
      )
    );
  }

  function CarouselItem({ children }) {
    return h(
      "div",
      {
        role: "group",
        "aria-roledescription": "slide",
        "data-slot": "carousel-item",
        className: "shadcn-carousel-item",
      },
      children
    );
  }

  function CarouselPrevious({ onClick, disabled }) {
    return h(
      "button",
      {
        type: "button",
        "data-slot": "carousel-previous",
        className: "shadcn-carousel-btn prev",
        onClick,
        disabled,
        "aria-label": "Slide anterior",
      },
      h(
        "svg",
        {
          width: 16,
          height: 16,
          viewBox: "0 0 24 24",
          fill: "none",
          stroke: "currentColor",
          strokeWidth: 2.2,
          strokeLinecap: "round",
          strokeLinejoin: "round",
        },
        h("path", { d: "m15 18-6-6 6-6" })
      )
    );
  }

  function CarouselNext({ onClick, disabled }) {
    return h(
      "button",
      {
        type: "button",
        "data-slot": "carousel-next",
        className: "shadcn-carousel-btn next",
        onClick,
        disabled,
        "aria-label": "Próximo slide",
      },
      h(
        "svg",
        {
          width: 16,
          height: 16,
          viewBox: "0 0 24 24",
          fill: "none",
          stroke: "currentColor",
          strokeWidth: 2.2,
          strokeLinecap: "round",
          strokeLinejoin: "round",
        },
        h("path", { d: "m9 18 6-6-6-6" })
      )
    );
  }

  /* =====================================================================
   * COMPONENTE 4: CONSOLE DO SITE COM CHAT INTERATIVO EMBUTIDO
   * ===================================================================== */
  function ConsoleWithChat({
    title,
    badgeText,
    badgeClass,
    lines,
    emptyText,
    waitingInput,
    onSendInput,
    onClear,
    quickChips,
    extraHeaderActions,
  }) {
    const [chatText, setChatText] = useState("");
    const logBodyRef = useRef(null);

    useEffect(() => {
      const el = logBodyRef.current;
      if (el) {
        el.scrollTop = el.scrollHeight;
      }
    }, [lines]);

    const handleSubmit = (e) => {
      e.preventDefault();
      onSendInput(chatText);
      setChatText("");
    };

    return h(
      "div",
      { className: "rpv-log-shell" },
      h(
        "div",
        { className: "rpv-log-head" },
        h(
          "div",
          { style: { display: "flex", alignItems: "center", gap: "10px", flexWrap: "wrap" } },
          h("span", null, "CONSOLE DO SITE:"),
          h("strong", { style: { color: "#fff" } }, title),
          badgeText ? h("span", { className: "badge " + (badgeClass || "status") }, badgeText) : null,
          waitingInput
            ? h(
                "span",
                { className: "badge soon", style: { fontSize: "9px", padding: "2px 8px" } },
                "💬 Aguardando resposta no Chat"
              )
            : null
        ),
        h(
          "div",
          { style: { display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" } },
          extraHeaderActions,
          h(
            "button",
            {
              type: "button",
              onClick: onClear,
              style: {
                border: "1px solid #30363d",
                background: "#21262d",
                color: "#c9d1d9",
                borderRadius: "6px",
                padding: "3px 8px",
                fontSize: "10px",
                cursor: "pointer",
              },
            },
            "Limpar Console"
          )
        )
      ),
      h(
        "div",
        { className: "rpv-log-body", ref: logBodyRef },
        lines && lines.length ? lines.join("\n") : emptyText
      ),
      h(
        "div",
        { className: "console-chat-bar" },
        quickChips && quickChips.length
          ? h(
              "div",
              { className: "console-quick-chips" },
              h(
                "span",
                { style: { fontSize: "10px", color: "#8b949e", fontWeight: 600 } },
                "Atalhos do Console:"
              ),
              quickChips.map((chip, idx) =>
                h(
                  "button",
                  {
                    key: idx,
                    type: "button",
                    className: "console-chip" + (chip.highlight ? " highlight" : ""),
                    onClick: () => onSendInput(chip.value),
                  },
                  chip.label
                )
              )
            )
          : null,
        h(
          "form",
          { className: "console-chat-form", onSubmit: handleSubmit },
          h("input", {
            type: "text",
            className: "console-chat-input",
            placeholder:
              "Chat do Console: digite um comando/resposta (ex: ENVIAR) ou deixe vazio e clique em Enviar (ENTER)...",
            value: chatText,
            onChange: (e) => setChatText(e.target.value),
          }),
          h(
            "button",
            { type: "submit", className: "console-chat-send" },
            "Enviar ao Console ↵"
          )
        )
      )
    );
  }

  /* =====================================================================
   * COMPONENTE 5: MODAL DE CONTA CONECTADA (TOPBAR)
   * ===================================================================== */
  function AccountModal({ onClose, session, onLogout, authLoading, authMessage }) {
    return h(
      "div",
      { className: "google-modal-overlay", onClick: onClose },
      h(
        "div",
        {
          className: "google-modal-card", role: "dialog", "aria-modal": true, "aria-label": "Conta",
          onClick: (event) => event.stopPropagation(),
          onKeyDown: (event) => { if (event.key === "Escape") onClose(); },
        },
        h(
          "div",
          { style: { display: "flex", alignItems: "center", justifyContent: "space-between" } },
          h("strong", null, session.nome),
          h("button", { type: "button", className: "close-menu", onClick: onClose, autoFocus: true,
                        "aria-label": "Fechar" }, "×")
        ),
        h("div", null, session.email),
        h("div", null, session.perfil === "admin" ? "Administrador" : "Usuário"),
        !IS_APPS_SCRIPT && h("button", { type: "button", className: "update-btn", disabled: authLoading,
                                       onClick: onLogout }, "Sair"),
        authMessage && h("p", { role: "alert" }, authMessage)
      )
    );
  }

  /* =====================================================================
   * COMPONENTE PRINCIPAL REACT: PAINEL APP
   * ===================================================================== */
  function PainelApp() {
    const [checking, setChecking] = useState(true);
    const [menuOpen, setMenuOpen] = useState(false);
    const [section, setSection] = useState("prazos");
    const [fontIndex, setFontIndex] = useState(0);
    const [highContrast, setHighContrast] = useState(false);

    const [session, setSession] = useState(SEM_SESSAO);
    const [authModalOpen, setAuthModalOpen] = useState(false);
    const [authLoading, setAuthLoading] = useState(false);
    const [authMessage, setAuthMessage] = useState("");
    const requests = useRef(new AbortController());

    // Estado dos Prazos
    const [data, setData] = useState([]);
    const [daysList, setDaysList] = useState([]);
    const [lastSync, setLastSync] = useState("Sincronizado");
    const [runtime, setRuntime] = useState("Última consolidação: --");
    const [currentSystem, setCurrentSystem] = useState("eproc1");
    const [selectedDayNum, setSelectedDayNum] = useState("");
    const [search, setSearch] = useState("");
    const [prosecutorFilter, setProsecutorFilter] = useState("");
    const [statusFilter, setStatusFilter] = useState("abertos");
    const [dateFilter, setDateFilter] = useState("");
    const [sourceStatus, setSourceStatus] = useState("Fonte disponível");

    // Controles exclusivos da conta Admin ("minha conta")
    const [openDropdown, setOpenDropdown] = useState("");
    const [chkProjudi, setChkProjudi] = useState(true);
    const [chkEproc, setChkEproc] = useState(true);
    const [chkSapiens, setChkSapiens] = useState(false);
    const [selPortalEproc, setSelPortalEproc] = useState("todos");
    const [updatingPrazos, setUpdatingPrazos] = useState(false);
    const [uploadingEproc, setUploadingEproc] = useState(false);
    const [dragOverlay, setDragOverlay] = useState(false);
    const fileInputRef = useRef(null);

    // Estado dos 4 Robôs RPV
    const [rpvRobots, setRpvRobots] = useState(DEFAULT_RPV_ROBOTS);
    const [rpvGlobalLog, setRpvGlobalLog] = useState([]);
    const [rpvSpreadsheetUrl, setRpvSpreadsheetUrl] = useState(
      "https://docs.google.com/spreadsheets/d/1MaraQb5yraO5nwwrrW5qs7RGlMKJhSLpQhN9VnHiwsY/edit"
    );
    const [rpvDisplayMode, setRpvDisplayMode] = useState("cards");
    const [selectedRpvIndex, setSelectedRpvIndex] = useState(0);
    const [showGlobalRpvLog, setShowGlobalRpvLog] = useState(false);
    const [robo1LaunchMode, setRobo1LaunchMode] = useState("padrao");

    // Estado do Robô PROJUDI (Peticionamento)
    const [projudiStatus, setProjudiStatus] = useState("ready");
    const [projudiMessage, setProjudiMessage] = useState("Pronto para executar");
    const [projudiWaitingInput, setProjudiWaitingInput] = useState(false);
    const [projudiLog, setProjudiLog] = useState([]);
    const [projudiMode, setProjudiMode] = useState("v6");

    const ultimaVersaoRef = useRef(null);
    const isAdmin = session.perfil === "admin" && !IS_APPS_SCRIPT;

    const encerrarSessao = useCallback((mensagem = "") => {
      requests.current.abort();
      requests.current = new AbortController();
      ultimaVersaoRef.current = null;
      setSession((atual) => ({ ...SEM_SESSAO, google_client_id: atual.google_client_id }));
      setData([]);
      setDaysList([]);
      setSelectedDayNum("");
      setSearch("");
      setProsecutorFilter("");
      setStatusFilter("abertos");
      setDateFilter("");
      setLastSync("Sincronizado");
      setRuntime("Última consolidação: --");
      setRpvRobots(DEFAULT_RPV_ROBOTS);
      setRpvGlobalLog([]);
      setProjudiLog([]);
      setAuthModalOpen(false);
      setMenuOpen(false);
      setSection("prazos");
      setAuthMessage(mensagem);
    }, []);

    const api = useCallback(async (url, opts) => {
      const signal = requests.current.signal;
      const transporte = demonstracao ? demonstracao.requisitar : fetch;
      const resp = await transporte(url, { ...opts, signal });
      if (resp.status === 401 && !["/api/auth/login", "/api/auth/google"].includes(url)) {
        encerrarSessao("Entre para acessar o painel.");
      }
      return resp;
    }, [encerrarSessao]);

    // Aplica Payload de Prazos
    const applyPayload = useCallback((payload) => {
      if (!payload) return;
      const newData = payload.data || [];
      setData(newData);
      setDaysList(payload.days || []);
      if (payload.updatedAt) setLastSync(payload.updatedAt);
      if (payload.runtime) setRuntime(payload.runtime);

      setCurrentSystem((prev) => {
        if (prev !== "todos" && !newData.some((x) => x.system === prev)) {
          const firstWithData = SYSTEMS.find(
            (s) => s.id !== "todos" && newData.some((x) => x.system === s.id)
          );
          return firstWithData ? firstWithData.id : prev;
        }
        return prev;
      });
    }, []);

    const refreshRpvStatus = useCallback(async () => {
      try {
        const resp = await api("/api/rpv/status");
        if (!resp.ok) return;
        const payload = await resp.json();
        if (Array.isArray(payload.robots) && payload.robots.length) {
          setRpvRobots(payload.robots);
        }
        if (Array.isArray(payload.global_log)) {
          setRpvGlobalLog(payload.global_log);
        }
        if (payload.spreadsheet_url) {
          setRpvSpreadsheetUrl(payload.spreadsheet_url);
        }
      } catch (_) {}
    }, [api]);

    const refreshProjudiStatus = useCallback(async () => {
      try {
        const resp = await api("/api/projudi-robo/status");
        if (!resp.ok) return;
        const payload = await resp.json();
        setProjudiStatus(payload.status || "ready");
        setProjudiMessage(payload.message || "Pronto para executar");
        setProjudiWaitingInput(Boolean(payload.waiting_input));
        setProjudiLog(payload.log || []);
      } catch (_) {}
    }, [api]);

    const carregarPrazos = useCallback(async () => {
      const resp = await api("/api/prazos");
      if (!resp.ok) return false;
      const payload = await resp.json();
      applyPayload(payload);
      setSession(payload.session);
      return true;
    }, [api, applyPayload]);

    const inicializar = useCallback(async () => {
      setChecking(true);
      setAuthMessage("");
      if (IS_APPS_SCRIPT) {
        window.google.script.run
          .withSuccessHandler((payload) => {
            const conta = payload.session;
            if (conta?.authenticated && conta?.is_institutional) {
              applyPayload(payload);
              setSession({ autenticado: true, nome: conta.name, email: conta.email, perfil: "usuario" });
            } else {
              setAuthMessage("Entre com sua conta institucional para acessar o painel.");
            }
            setChecking(false);
          })
          .withFailureHandler(() => {
            setAuthMessage("Não foi possível carregar os prazos da planilha.");
            setChecking(false);
          })
          .obterDadosPainel();
        return;
      }
      try {
        const resp = await api("/api/auth/status");
        if (!resp.ok) throw new Error();
        const conta = await resp.json();
        setSession(conta);
        if (conta.autenticado) await carregarPrazos();
      } catch (_) {
        setAuthMessage("Não foi possível carregar a sessão.");
      } finally {
        setChecking(false);
      }
    }, [api, applyPayload, carregarPrazos]);

    useEffect(() => { inicializar(); }, [inicializar]);

    useEffect(() => {
      if (!session.autenticado || IS_APPS_SCRIPT) return;
      let emAndamento = false;
      let ativo = true;
      const consultar = async () => {
        if (emAndamento) return;
        emAndamento = true;
        try {
          const r = await api("/api/status-coleta");
          if (!r.ok || !ativo) return;
          const st = await r.json();
          if (!ativo) return;
          if (st.session) setSession(st.session);
          if (st.session?.perfil !== "admin" && section !== "prazos") setSection("prazos");
          if (isAdmin && (st.em_andamento || st.sapiens_em_andamento) && st.etapa) {
            setSourceStatus(st.etapa);
          }
          if (st.versao_dados !== ultimaVersaoRef.current && await carregarPrazos()) {
            ultimaVersaoRef.current = st.versao_dados;
            setSourceStatus("Painel sincronizado");
          }
          if (isAdmin && section === "rpv") await refreshRpvStatus();
          if (isAdmin && section === "projudi") await refreshProjudiStatus();
        } catch (_) {
        } finally {
          emAndamento = false;
        }
      };
      consultar();
      const interval = setInterval(consultar, 1200);
      return () => { ativo = false; clearInterval(interval); };
    }, [session.autenticado, section, isAdmin, api, carregarPrazos, refreshRpvStatus, refreshProjudiStatus]);

    // Drag & Drop de planilhas .xls (Habilitado SOMENTE para Minha Conta / Admin)
    useEffect(() => {
      if (!isAdmin) {
        setDragOverlay(false);
        return;
      }
      let counter = 0;
      const onDragEnter = (e) => {
        e.preventDefault();
        counter++;
        setDragOverlay(true);
      };
      const onDragOver = (e) => e.preventDefault();
      const onDragLeave = (e) => {
        e.preventDefault();
        counter = Math.max(0, counter - 1);
        if (counter === 0) setDragOverlay(false);
      };
      const onDrop = (e) => {
        e.preventDefault();
        counter = 0;
        setDragOverlay(false);
        if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length) {
          handleEprocFiles(e.dataTransfer.files);
        }
      };
      window.addEventListener("dragenter", onDragEnter);
      window.addEventListener("dragover", onDragOver);
      window.addEventListener("dragleave", onDragLeave);
      window.addEventListener("drop", onDrop);
      return () => {
        window.removeEventListener("dragenter", onDragEnter);
        window.removeEventListener("dragover", onDragOver);
        window.removeEventListener("dragleave", onDragLeave);
        window.removeEventListener("drop", onDrop);
      };
    }, [isAdmin]);

    // Fecha dropdowns ao clicar fora
    useEffect(() => {
      const onClick = () => setOpenDropdown("");
      window.addEventListener("click", onClick);
      return () => window.removeEventListener("click", onClick);
    }, []);

    // Acessibilidade WCAG
    const cycleFontSize = () => {
      const next = (fontIndex + 1) % FONT_LEVELS.length;
      setFontIndex(next);
      document.documentElement.style.setProperty("--font-zoom", String(FONT_LEVELS[next]));
    };

    const toggleHighContrast = () => {
      const next = !highContrast;
      setHighContrast(next);
      document.body.classList.toggle("high-contrast", next);
    };

    const entrar = useCallback(async (rota, body) => {
      setAuthLoading(true);
      setAuthMessage("");
      try {
        const resp = await api(rota, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        const resultado = await resp.json();
        if (!resp.ok) {
          setAuthMessage(resultado.bloqueado
            ? "Muitas tentativas. Tente novamente em 15 minutos."
            : resultado.erro);
          return;
        }
        setSession(resultado.session);
        await carregarPrazos();
      } catch (_) {
        setAuthMessage("Não foi possível entrar. Tente novamente.");
      } finally {
        setAuthLoading(false);
      }
    }, [api, carregarPrazos]);

    const loginGoogle = useCallback(
      (credential) => entrar("/api/auth/google", { credential }), [entrar]
    );

    const handleLogout = async () => {
      setAuthLoading(true);
      setAuthMessage("");
      try {
        const resp = await api("/api/auth/logout", { method: "POST" });
        if (resp.ok) encerrarSessao();
        else if (resp.status !== 401) setAuthMessage("Não foi possível sair. Tente novamente.");
      } catch (_) {
        setAuthMessage("Não foi possível sair. Tente novamente.");
      } finally {
        setAuthLoading(false);
      }
    };

    // Upload e Atualização de Prazos (Somente Admin)
    const handleEprocFiles = async (fileList) => {
      if (!isAdmin) return;
      const files = [...(fileList || [])].filter((f) => f.name.toLowerCase().endsWith(".xls"));
      if (!files.length) return;
      setUploadingEproc(true);
      setSourceStatus(`Importando ${files.length} planilha(s) .xls do EPROC...`);
      try {
        const arquivos = [];
        for (const f of files) {
          arquivos.push({ nome: f.name, conteudo_b64: await fileToBase64(f) });
        }
        const resp = await api("/api/upload-eproc", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ arquivos }),
        });
        if (resp.ok) {
          const payload = await resp.json();
          applyPayload(payload);
          const c = payload.counts || {};
          setSourceStatus(`Importado · ${c.abertos || 0} abertos · ${c.cumpridos || 0} cumpridos`);
        }
      } catch (_) {
      } finally {
        setUploadingEproc(false);
        if (fileInputRef.current) fileInputRef.current.value = "";
      }
    };

    const triggerUpdate = async () => {
      if (!isAdmin) return;
      setOpenDropdown("");
      setUpdatingPrazos(true);
      try {
        const s = chkSapiens ? "1" : "0";
        const p = chkProjudi ? "1" : "0";
        const ep = chkEproc ? "1" : "0";
        const resp = await api(
          `/api/atualizar?sapiens=${s}&projudi=${p}&eproc=${ep}&portal_eproc=${encodeURIComponent(
            selPortalEproc
          )}`,
          { method: "POST" }
        );
        if (resp.ok) {
          const payload = await resp.json();
          applyPayload(payload);
          const c = payload.counts || {};
          setSourceStatus(`Atualizado: ${c.abertos || 0} abertos · ${c.cumpridos || 0} cumpridos`);
        }
      } catch (_) {
      } finally {
        setUpdatingPrazos(false);
      }
    };

    // Ações dos Robôs RPV
    const runRpvRobot = async (id, ev) => {
      if (ev) ev.stopPropagation();
      const idx = rpvRobots.findIndex((r) => r.id === id);
      if (idx >= 0) setSelectedRpvIndex(idx);
      const modo = id === "robo1" ? robo1LaunchMode : "padrao";
      try {
        await api(
          `/api/rpv/run?id=${encodeURIComponent(id)}&modo=${encodeURIComponent(modo)}`,
          { method: "POST" }
        );
        await refreshRpvStatus();
      } catch (_) {}
    };

    const stopRpvRobot = async (id, ev) => {
      if (ev) ev.stopPropagation();
      try {
        await api(`/api/rpv/stop?id=${encodeURIComponent(id)}`, { method: "POST" });
        await refreshRpvStatus();
      } catch (_) {}
    };

    const sendRpvConsoleInput = async (text) => {
      const active = rpvRobots[selectedRpvIndex] || rpvRobots[0];
      if (!active) return;
      try {
        await api("/api/rpv/input", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ id: active.id, text }),
        });
        await refreshRpvStatus();
      } catch (_) {}
    };

    const clearRpvLog = async () => {
      const active = rpvRobots[selectedRpvIndex];
      const targetId = showGlobalRpvLog ? "all" : active ? active.id : "all";
      try {
        await api(`/api/rpv/clear-log?id=${encodeURIComponent(targetId)}`, { method: "POST" });
        await refreshRpvStatus();
      } catch (_) {}
    };

    const openRpvFolder = async (id, ev) => {
      if (ev) ev.stopPropagation();
      try {
        await api(`/api/rpv/open-folder?id=${encodeURIComponent(id)}`, { method: "POST" });
      } catch (_) {}
    };

    // Ações do Robô PROJUDI
    const runProjudiRobot = async () => {
      try {
        await api(`/api/projudi-robo/run?modo=${encodeURIComponent(projudiMode)}`, {
          method: "POST",
        });
        await refreshProjudiStatus();
      } catch (_) {}
    };

    const stopProjudiRobot = async () => {
      try {
        await api("/api/projudi-robo/stop", { method: "POST" });
        await refreshProjudiStatus();
      } catch (_) {}
    };

    const sendProjudiConsoleInput = async (text) => {
      try {
        await api("/api/projudi-robo/input", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text }),
        });
        await refreshProjudiStatus();
      } catch (_) {}
    };

    const clearProjudiLog = async () => {
      setProjudiLog([]);
      try {
        await api("/api/projudi-robo/clear-log", { method: "POST" });
      } catch (_) {}
    };

    const openProjudiFolder = async () => {
      try {
        await api("/api/projudi-robo/open-folder", { method: "POST" });
      } catch (_) {}
    };

    // Filtros e Métricas de Prazos
    const subset = useMemo(
      () => (currentSystem === "todos" ? data : data.filter((x) => x.system === currentSystem)),
      [data, currentSystem]
    );

    const prosecutors = useMemo(
      () => [...new Set(subset.map((x) => x.prosecutor).filter(Boolean))].sort(),
      [subset]
    );

    const rows = useMemo(() => {
      const q = search.toLowerCase().trim();
      const valid5Days = new Set(daysList.map((x) => x.dateNum));
      const normalize = (v) =>
        String(v || "")
          .toLowerCase()
          .replace(/[.\-\/\s]/g, "");

      return subset
        .filter((x) => {
          if (prosecutorFilter && x.prosecutor !== prosecutorFilter) return false;
          if (statusFilter === "abertos" && x.status === "Cumprido") return false;
          if (statusFilter === "multiplo" && (!x.prazoMultiplo || x.status === "Cumprido"))
            return false;
          if (
            statusFilter &&
            statusFilter !== "abertos" &&
            statusFilter !== "multiplo" &&
            x.status !== statusFilter
          )
            return false;
          if (selectedDayNum && x.dateNum !== selectedDayNum) return false;
          if (dateFilter === "5dias" && !valid5Days.has(x.dateNum)) return false;
          if ((dateFilter === "Hoje" || dateFilter === "Amanhã") && x.date !== dateFilter)
            return false;
          if (q) {
            const pMatch = normalize(x.process).includes(normalize(q));
            const tMatch = `${x.prosecutor} ${x.event} ${x.teor || ""} ${x.modality} ${
              x.orgao || ""
            } ${x.observacao || ""} ${x.prazoMultiplo || ""}`
              .toLowerCase()
              .includes(q);
            if (!pMatch && !tMatch) return false;
          }
          return true;
        })
        .sort((a, b) => (a.dateISO || "9999").localeCompare(b.dateISO || "9999"));
    }, [subset, prosecutorFilter, statusFilter, selectedDayNum, dateFilter, search, daysList]);

    const abertos = useMemo(() => subset.filter((x) => x.status !== "Cumprido"), [subset]);
    const cumpridos = useMemo(() => subset.filter((x) => x.status === "Cumprido"), [subset]);

    const topTitle =
      section === "prazos"
        ? "Painel de Prazos"
        : section === "rpv"
        ? "Automação de RPVs"
        : "Robô PROJUDI";
    const topSub =
      section === "prazos"
        ? "Procuradoria de Saúde · PGE-PR · visão consolidada"
        : section === "rpv"
        ? "Procuradoria de Saúde · execução e acompanhamento no Console"
        : "Automação de Peticionamento · Link PROJUDI salvo · Console Integrado";

    const activeRpvRobot = rpvRobots[selectedRpvIndex] || rpvRobots[0];
    const rpvConsoleLines = sanitizeConsoleLinesForAccount(
      showGlobalRpvLog ? rpvGlobalLog : activeRpvRobot?.log || [],
      isAdmin
    );
    const projudiConsoleLines = sanitizeConsoleLinesForAccount(projudiLog, isAdmin);

    const renderRpvCardContent = (r, idx, isCarouselSlide) => {
      const isSelected = idx === selectedRpvIndex;
      const stLabel = RPV_STATUS_NAMES[r.status] || r.status;
      const badgeCls = getStatusBadgeClass(r.status);
      const progress = Number(r.progress) || 0;
      const countTxt = r.total ? `${r.current}/${r.total} (${progress}%)` : `${progress}%`;

      return h(
        "article",
        {
          key: r.id,
          className:
            (isCarouselSlide ? "shadcn-carousel-card " : "rpv-card ") +
            `${r.status} ${isSelected ? "selected" : ""}`,
          onClick: () => setSelectedRpvIndex(idx),
        },
        h(
          "div",
          null,
          h(
            "div",
            { className: "rpv-card-top" },
            h(
              "button",
              {
                type: "button",
                className: "rpv-select",
                "aria-pressed": isSelected,
                onClick: (e) => {
                  e.stopPropagation();
                  setSelectedRpvIndex(idx);
                },
              },
              r.short_label
            ),
            h("span", { className: `badge ${badgeCls}` }, `${stLabel} · ${progress}%`)
          ),
          h("div", { className: "rpv-subtitle" }, r.subtitle)
        ),
        h("div", { className: "rpv-desc" }, r.description),
        r.id === "robo1"
          ? h(
              "div",
              { onClick: (e) => e.stopPropagation() },
              h(
                "select",
                {
                  "aria-label": "Modo de execução do Robô 1",
                  className: "control",
                  value: robo1LaunchMode,
                  onChange: (e) => setRobo1LaunchMode(e.target.value),
                  style: { height: "30px", width: "100%", fontSize: "11px", padding: "0 8px" },
                },
                h("option", { value: "padrao" }, "Menu completo"),
                h("option", { value: "direto" }, "Execução direta")
              )
            )
          : null,
        h(
          "div",
          null,
          r.status !== "ready"
            ? h(
                "div",
                { className: "rpv-meta-line", title: r.message },
                `${r.message || stLabel} · ${countTxt}`
              )
            : null,
          h(
            "div",
            { className: "rpv-actions" },
            r.status === "running"
              ? h(
                  "button",
                  {
                    type: "button",
                    className: "rpv-btn-stop",
                    onClick: (e) => stopRpvRobot(r.id, e),
                  },
                  "⏹ Parar"
                )
              : h(
                  "button",
                  {
                    type: "button",
                    className: "rpv-btn-run",
                    onClick: (e) => runRpvRobot(r.id, e),
                  },
                  "▶ Executar"
                ),
            h(
              "button",
              {
                type: "button",
                className: "rpv-btn-folder",
                onClick: (e) => openRpvFolder(r.id, e),
                title: `Abrir pasta ${r.cwd}`,
              },
              "📁 Pasta"
            )
          )
        ),
        h(
          "div",
          { className: "rpv-track" },
          h("div", { className: "rpv-track-fill", style: { width: `${progress}%` } })
        )
      );
    };

    if (checking || !session.autenticado) {
      return h(SplashPge, {
        session, checking, authLoading, authMessage, onRetry: inicializar,
        onSenha: (email, senha) => entrar("/api/auth/login", { email, senha }),
        onGoogle: loginGoogle,
      });
    }

    return h(
      React.Fragment,
      null,
      authModalOpen && h(AccountModal, {
        onClose: () => { setAuthModalOpen(false); setAuthMessage(""); },
        session, onLogout: handleLogout, authLoading, authMessage,
      }),

      // 3. Overlay de Drag-and-Drop (Visível SOMENTE para Minha Conta / Admin)
      isAdmin && dragOverlay
        ? h(
            "div",
            {
              style: {
                position: "fixed",
                inset: 0,
                zIndex: 9999,
                background: "rgba(15,23,42,0.78)",
                backdropFilter: "blur(4px)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                pointerEvents: "none",
              },
            },
            h(
              "div",
              {
                style: {
                  background: "#fff",
                  padding: "32px 48px",
                  borderRadius: "20px",
                  border: "3px dashed #2563eb",
                  textAlign: "center",
                },
              },
              h("div", { style: { fontSize: "36px", marginBottom: "8px" } }, "📂"),
              h(
                "div",
                { style: { fontSize: "18px", fontWeight: 700, color: "#0f172a" } },
                "Solte as planilhas .xls do EPROC aqui"
              )
            )
          )
        : null,

      isAdmin
        ? h("input", {
            ref: fileInputRef,
            type: "file",
            accept: ".xls",
            multiple: true,
            style: { display: "none" },
            onChange: (e) => handleEprocFiles(e.target.files),
          })
        : null,

      // 4. Menu Lateral com Logo do Estado e Rodapé Somente Texto (Imagem 3)
      h("div", {
        className: "menu-overlay" + (menuOpen ? " open" : ""),
        onClick: () => setMenuOpen(false),
      }),
      h(
        "aside",
        { className: "side-menu" + (menuOpen ? " open" : ""), id: "sideMenu" },
        h(
          "div",
          null,
          h(
            "div",
            { className: "side-menu-head" },
            h(
              "div",
              { className: "side-brand" },
              h("img", {
                src: "logo_parana.png",
                alt: "Brasão do Estado do Paraná",
                className: "side-logo",
              }),
              h(
                "div",
                null,
                h("div", { className: "side-title" }, "PGE · Procuradoria de Saúde"),
                h("div", { className: "side-sub" }, "Estado do Paraná · Menu")
              )
            ),
            h(
              "button",
              {
                className: "close-menu",
                onClick: () => setMenuOpen(false),
                "aria-label": "Fechar menu",
              },
              "×"
            )
          ),
          h(
            "nav",
            { className: "side-nav" },
            h(
              "button",
              {
                className: "side-item" + (section === "prazos" ? " active" : ""),
                onClick: () => {
                  setSection("prazos");
                  setMenuOpen(false);
                },
              },
              h("span", null, "Prazos Consolidados")
            ),
            isAdmin && h(
              "button",
              {
                className: "side-item" + (section === "rpv" ? " active" : ""),
                onClick: () => {
                  setSection("rpv");
                  setMenuOpen(false);
                },
              },
              h("span", null, "Automação RPVs"),
              h("span", { className: "badge status" }, "4 robôs")
            ),
            isAdmin && h(
              "button",
              {
                className: "side-item" + (section === "projudi" ? " active" : ""),
                onClick: () => {
                  setSection("projudi");
                  setMenuOpen(false);
                },
              },
              h("span", null, "Robô Pet PROJUDI"),
              h("span", { className: "badge status" }, "Console")
            )
          )
        ),
        h(
          "div",
          {
            className: "side-footer-text",
            style: { borderTop: "1px solid var(--line)", paddingTop: "14px" },
          },
          h("div", { className: "side-footer-title" }, "PGE PARANÁ"),
          h("div", { className: "side-footer-bar" }),
          h("div", { className: "side-footer-sub1" }, "PROCURADORIA-GERAL DO ESTADO"),
          h("div", { className: "side-footer-sub2" }, "PROCURADORIA DE SAÚDE (PRS)")
        )
      ),

      // 5. Container Principal
      h(
        "div",
        { className: "app" },
        // CABEÇALHO PRINCIPAL: LOGO DO ESTADO AO LADO DE "PAINEL DE PRAZOS"
        h(
          "header",
          { className: "topbar" },
          h(
            "div",
            { className: "brand" },
            h(
              "button",
              {
                className: "menu-btn",
                onClick: () => setMenuOpen(true),
                "aria-label": "Abrir menu",
              },
              h("span"),
              h("span"),
              h("span")
            ),
            h("img", {
              src: "logo_parana.png",
              alt: "Brasão do Estado do Paraná",
              className: "top-state-logo",
            }),
            h(
              "div",
              null,
              h(
                "div",
                { className: "brand-title-row" },
                h("div", { className: "brand-title", id: "topBrandTitle" }, topTitle),
                h("span", { className: "pge-pill" }, "PGE-PR")
              ),
              h("div", { className: "brand-sub", id: "topBrandSub" },
                demonstracao ? "Demonstração acadêmica · Dados fictícios · Robôs simulados" : topSub)
            )
          ),

          // Controles Superiores e Botão Google Auth Institucional (no canto superior direito)
          h(
            "div",
            { className: "sync" },
            h("span", { id: "lastSync" }, lastSync),
            h(
              "button",
              {
                type: "button",
                className: "update-btn a11y-top-btn" + (fontIndex > 0 ? " active" : ""),
                onClick: cycleFontSize,
              },
              fontIndex === 0
                ? "A+ Fonte"
                : `A+ (${Math.round(FONT_LEVELS[fontIndex] * 100)}%)`
            ),
            h(
              "button",
              {
                type: "button",
                className: "update-btn a11y-top-btn" + (highContrast ? " active" : ""),
                onClick: toggleHighContrast,
                "aria-pressed": String(highContrast),
              },
              "◐ Contraste"
            ),

            // Controles de puxar dados / logins nos sites: VISÍVEIS SOMENTE PARA MINHA CONTA (isAdmin)
            section === "prazos" && isAdmin
              ? h(
                  "span",
                  { style: { display: "flex", alignItems: "center", gap: "8px" } },
                  h(
                    "button",
                    {
                      type: "button",
                      className: "update-btn a11y-top-btn",
                      onClick: () => fileInputRef.current && fileInputRef.current.click(),
                    },
                    uploadingEproc ? "📂 Importando..." : "📂 Importar .xls EPROC"
                  ),
                  h(
                    "div",
                    { className: "split-btn-wrap" },
                    h(
                      "div",
                      { className: "split-btn-group" },
                      h(
                        "button",
                        {
                          type: "button",
                          className:
                            "update-btn split-main" + (updatingPrazos ? " loading" : ""),
                          onClick: triggerUpdate,
                        },
                        h("span", { className: "refresh" }, "↻"),
                        updatingPrazos ? " Atualizando..." : " Atualizar"
                      ),
                      h(
                        "button",
                        {
                          type: "button",
                          className:
                            "update-btn split-arrow" +
                            (openDropdown === "prazos" ? " open" : ""),
                          onClick: (e) => {
                            e.stopPropagation();
                            setOpenDropdown(openDropdown === "prazos" ? "" : "prazos");
                          },
                          "aria-label": "Opções de coleta",
                        },
                        h("span", { className: "chevron-icon" }, "▼")
                      )
                    ),
                    h(
                      "div",
                      {
                        className:
                          "top-dropdown-box" + (openDropdown === "prazos" ? " open" : ""),
                        onClick: (e) => e.stopPropagation(),
                      },
                      h(
                        "div",
                        { style: { fontWeight: 700, color: "var(--text)" } },
                        "Opções da Minha Conta (Admin):"
                      ),
                      h(
                        "label",
                        { style: { display: "flex", alignItems: "center", gap: "8px" } },
                        h("input", {
                          type: "checkbox",
                          checked: chkProjudi,
                          onChange: (e) => setChkProjudi(e.target.checked),
                        }),
                        "Coletar Robô PROJUDI"
                      ),
                      h(
                        "label",
                        { style: { display: "flex", alignItems: "center", gap: "8px" } },
                        h("input", {
                          type: "checkbox",
                          checked: chkEproc,
                          onChange: (e) => setChkEproc(e.target.checked),
                        }),
                        "Coletar Robô EPROC"
                      ),
                      h(
                        "select",
                        {
                          className: "control",
                          value: selPortalEproc,
                          onChange: (e) => setSelPortalEproc(e.target.value),
                          style: { height: "30px", fontSize: "11px", padding: "0 8px" },
                        },
                        h("option", { value: "todos" }, "EPROC: Todos os 3 portais"),
                        h("option", { value: "jfpr" }, "Apenas EPROC JFPR"),
                        h("option", { value: "tjpr" }, "Apenas EPROC TJPR"),
                        h("option", { value: "jfpr_recursal" }, "Apenas EPROC JFPR Recursal")
                      ),
                      h(
                        "label",
                        { style: { display: "flex", alignItems: "center", gap: "8px" } },
                        h("input", {
                          type: "checkbox",
                          checked: chkSapiens,
                          onChange: (e) => setChkSapiens(e.target.checked),
                        }),
                        "Sincronizar SAPIENS junto"
                      )
                    )
                  )
                )
              : null,

            isAdmin && section === "rpv"
              ? h(
                  "span",
                  { style: { display: "flex", alignItems: "center", gap: "8px" } },
                  h(
                    "button",
                    {
                      type: "button",
                      className: "update-btn a11y-top-btn",
                      onClick: () => demonstracao ? demonstracao.exportarPlanilha() : window.open(rpvSpreadsheetUrl, "_blank"),
                    },
                    "📊 Planilha RPVs"
                  ),
                  h(
                    "button",
                    {
                      type: "button",
                      className: "update-btn",
                      onClick: (e) => openRpvFolder("raiz", e),
                    },
                    "📁 Pasta dos Robôs"
                  )
                )
              : null,

            isAdmin && section === "projudi"
              ? h(
                  "span",
                  { style: { display: "flex", alignItems: "center", gap: "8px" } },
                  h(
                    "button",
                    {
                      type: "button",
                      className: "update-btn a11y-top-btn",
                      onClick: openProjudiFolder,
                    },
                    "📁 Pasta do Robô"
                  ),
                  h(
                    "button",
                    {
                      type: "button",
                      className: "update-btn",
                      onClick: runProjudiRobot,
                      disabled: projudiStatus === "running",
                    },
                    projudiStatus === "running" ? "↻ Rodando..." : "▶ Rodar"
                  )
                )
              : null,

            h(
              "button",
              {
                type: "button",
                className: "google-auth-btn" + (isAdmin ? " is-admin" : ""),
                onClick: () => setAuthModalOpen(true),
                title: session.email,
              },
              session.nome || session.email
            )
          )
        ),

        // ==================== VISÃO 1: PRAZOS ====================
        section === "prazos"
          ? h(
              React.Fragment,
              null,
              h(
                "section",
                { className: "summary", id: "sectionPrazosSummary" },
                h(
                  "div",
                  { className: "hero" },
                  h("div", { className: "eyebrow" }, "PRÓXIMOS 5 DIAS ÚTEIS"),
                  h(
                    "div",
                    { className: "days", id: "days" },
                    daysList.map((d, i) => {
                      const count = abertos.filter((x) => x.dateNum === d.dateNum).length;
                      const isActive = selectedDayNum
                        ? selectedDayNum === d.dateNum
                        : i === 0;
                      return h(
                        "div",
                        {
                          key: d.dateNum,
                          className: "day" + (isActive ? " active" : ""),
                          onClick: () => {
                            const next = selectedDayNum === d.dateNum ? "" : d.dateNum;
                            setSelectedDayNum(next);
                            if (next) setDateFilter("");
                          },
                        },
                        h("div", { className: "day-date" }, d.dateStr),
                        h("div", { className: "day-count" }, count),
                        h("div", { className: "day-label" }, d.label)
                      );
                    })
                  )
                ),
                h(
                  "div",
                  { className: "metric" },
                  h("div", { className: "metric-label" }, "Pendentes"),
                  h(
                    "div",
                    null,
                    h("div", { className: "metric-value" }, abertos.length),
                    h(
                      "div",
                      { className: "metric-foot" },
                      cumpridos.length
                        ? `em aberto · ${cumpridos.length} cumprido(s)`
                        : "na visão atual"
                    )
                  )
                ),
                h(
                  "div",
                  { className: "metric" },
                  h("div", { className: "metric-label" }, "Novos"),
                  h(
                    "div",
                    null,
                    h(
                      "div",
                      { className: "metric-value" },
                      abertos.filter((x) => x.isNew).length
                    ),
                    h("div", { className: "metric-foot" }, "desde a última atualização")
                  )
                ),
                h(
                  "div",
                  { className: "metric" },
                  h("div", { className: "metric-label" }, "Revisar"),
                  h(
                    "div",
                    null,
                    h(
                      "div",
                      { className: "metric-value" },
                      abertos.filter((x) => x.review).length
                    ),
                    h("div", { className: "metric-foot" }, "atenção prioritária")
                  )
                )
              ),
              h(
                "main",
                { className: "workspace", id: "sectionPrazosWorkspace" },
                h(
                  "div",
                  { className: "workspace-head" },
                  h(
                    "div",
                    { className: "system-switcher", id: "systemSwitcher" },
                    SYSTEMS.map((s) => {
                      const cnt =
                        s.id === "todos"
                          ? data.filter((x) => x.status !== "Cumprido").length
                          : data.filter((x) => x.system === s.id && x.status !== "Cumprido")
                              .length;
                      return h(
                        "button",
                        {
                          key: s.id,
                          type: "button",
                          className:
                            "system-btn" + (s.id === currentSystem ? " active" : ""),
                          onClick: () => setCurrentSystem(s.id),
                        },
                        `${s.label} (${cnt})`
                      );
                    })
                  ),
                  h(
                    "div",
                    { className: "statusline" },
                    h("span", { className: "dot" }),
                    h(
                      "span",
                      { id: "sourceStatus" },
                      isAdmin ? sourceStatus : "Painel sincronizado"
                    )
                  )
                ),
                h(
                  "div",
                  { className: "filters" },
                  h("input", {
                    className: "control",
                    placeholder: "Buscar processo, teor ou procurador...",
                    value: search,
                    onChange: (e) => setSearch(e.target.value),
                  }),
                  h(
                    "select",
                    {
                      className: "control",
                      value: prosecutorFilter,
                      onChange: (e) => setProsecutorFilter(e.target.value),
                    },
                    h("option", { value: "" }, "Todos os procuradores"),
                    prosecutors.map((p) => h("option", { key: p, value: p }, p))
                  ),
                  h(
                    "select",
                    {
                      className: "control",
                      value: statusFilter,
                      onChange: (e) => setStatusFilter(e.target.value),
                    },
                    h("option", { value: "abertos" }, "Em aberto (Pendentes + Revisar)"),
                    h("option", { value: "multiplo" }, "⚠️ Prazo Duplo / Mais de um prazo"),
                    h("option", { value: "" }, "Todos os status (inclui Cumpridos)"),
                    h("option", { value: "Pendente" }, "Apenas Pendentes"),
                    h("option", { value: "Revisar" }, "Apenas Revisar"),
                    h("option", { value: "Cumprido" }, "Apenas Cumpridos")
                  ),
                  h(
                    "select",
                    {
                      className: "control",
                      value: dateFilter,
                      onChange: (e) => {
                        setSelectedDayNum("");
                        setDateFilter(e.target.value);
                      },
                    },
                    h("option", { value: "" }, "Todas as datas"),
                    h("option", { value: "5dias" }, "Próximos 5 dias úteis"),
                    h("option", { value: "Hoje" }, "Hoje"),
                    h("option", { value: "Amanhã" }, "Amanhã")
                  )
                ),
                h(
                  "div",
                  { className: "list-shell" },
                  h(
                    "div",
                    { className: "table-head" },
                    h("div", null, "Processo"),
                    h("div", null, "Prazo"),
                    h("div", null, "Procurador"),
                    h("div", { className: "hide-md" }, "Modalidade"),
                    h("div", { className: "hide-md" }, "Teor / Evento"),
                    h("div", null, "Status")
                  ),
                  h(
                    "div",
                    { className: "deadline-scroll" },
                    !rows.length
                      ? h(
                          "div",
                          { className: "empty" },
                          "Nenhum prazo encontrado com os filtros selecionados."
                        )
                      : rows.map((x, idx) => {
                          const sysLabel = (
                            SYSTEMS.find((s) => s.id === x.system) || {
                              label: x.sistema_origem || x.system,
                            }
                          ).label;
                          const subProc = x.orgao ? `${sysLabel} · ${x.orgao}` : sysLabel;
                          const stClass =
                            x.status === "Cumprido"
                              ? "status-done"
                              : x.status === "Revisar"
                              ? "status-review"
                              : "";
                          const rowClass =
                            x.status === "Cumprido" ? "deadline-row is-done" : "deadline-row";

                          return h(
                            "div",
                            { key: `${x.process}-${idx}`, className: rowClass },
                            h(
                              "div",
                              null,
                              h("div", { className: "process" }, x.process),
                              h("div", { className: "secondary" }, subProc),
                              x.prazoMultiplo
                                ? h(
                                    "div",
                                    { className: "badge-multiplo" },
                                    `⚠️ ${x.prazoMultiplo}`
                                  )
                                : null
                            ),
                            h(
                              "div",
                              null,
                              h("span", { className: `badge ${x.flag}` }, x.date),
                              h("div", { className: "secondary" }, x.dateNum)
                            ),
                            h(
                              "div",
                              null,
                              h("div", null, x.prosecutor),
                              x.caixa ? h("div", { className: "secondary" }, x.caixa) : null
                            ),
                            h("div", { className: "hide-md" }, x.modality),
                            h(
                              "div",
                              { className: "hide-md" },
                              h("div", null, x.event),
                              x.observacao
                                ? h(
                                    "div",
                                    { className: "secondary", title: x.teor || "" },
                                    x.observacao
                                  )
                                : null
                            ),
                            h(
                              "div",
                              null,
                              h("span", { className: `badge status ${stClass}` }, x.status)
                            )
                          );
                        })
                  )
                ),
                h(
                  "div",
                  { className: "footer" },
                  h(
                    "span",
                    null,
                    `${rows.length} prazo${rows.length === 1 ? "" : "s"} exibido${
                      rows.length === 1 ? "" : "s"
                    }`
                  ),
                  h("span", null, isAdmin ? runtime : "Procuradoria de Saúde · PGE-PR")
                )
              )
            )
          : null,

        // ==================== VISÃO 2: ROBÔS RPV (COM SHADCN CAROUSEL) ====================
        isAdmin && section === "rpv"
          ? h(
              "main",
              { className: "workspace", id: "sectionRpvWorkspace" },
              h(
                "div",
                { className: "workspace-head" },
                h(
                  "div",
                  { className: "system-switcher" },
                  h(
                    "button",
                    {
                      type: "button",
                      className:
                        "system-btn" + (rpvDisplayMode === "cards" ? " active" : ""),
                      onClick: () => setRpvDisplayMode("cards"),
                    },
                    "Todos os robôs"
                  ),
                  h(
                    "button",
                    {
                      type: "button",
                      className:
                        "system-btn" + (rpvDisplayMode === "carousel" ? " active" : ""),
                      onClick: () => setRpvDisplayMode("carousel"),
                    },
                    "Carrossel (Um por vez)"
                  )
                ),
                h(
                  "div",
                  { className: "statusline" },
                  h("span", { className: "dot" }),
                  h(
                    "span",
                    null,
                    "Execução integrada ao Console do Site (sem janela CMD externa)"
                  )
                )
              ),

              rpvDisplayMode === "cards"
                ? h(
                    "div",
                    { className: "rpv-cards-grid" },
                    rpvRobots.map((r, idx) => renderRpvCardContent(r, idx, false))
                  )
                : h(
                    Carousel,
                    {
                      selectedIndex: selectedRpvIndex,
                      onSelectIndex: setSelectedRpvIndex,
                      totalItems: rpvRobots.length,
                    },
                    rpvRobots.map((r, idx) =>
                      h(CarouselItem, { key: r.id }, renderRpvCardContent(r, idx, true))
                    )
                  ),

              h(ConsoleWithChat, {
                title: showGlobalRpvLog
                  ? "TODOS OS 4 ROBÔS (LOG GERAL)"
                  : activeRpvRobot?.label || "ROBÔ 1",
                badgeText: activeRpvRobot
                  ? RPV_STATUS_NAMES[activeRpvRobot.status] || "Pronto"
                  : "Pronto",
                badgeClass: activeRpvRobot ? getStatusBadgeClass(activeRpvRobot.status) : "status",
                lines: rpvConsoleLines,
                emptyText:
                  'Selecione um dos 4 robôs acima e clique em "▶ Executar" para acompanhar e interagir diretamente por este Console.',
                waitingInput: Boolean(activeRpvRobot?.waiting_input),
                onSendInput: sendRpvConsoleInput,
                onClear: clearRpvLog,
                quickChips: [
                  { label: "Confirmar (ENTER)", value: "", highlight: true },
                  { label: "Opção 2 (Testar 1)", value: "2" },
                  { label: "Opção 4 (Executar Todos)", value: "4" },
                  { label: "Confirmar EXECUTAR", value: "EXECUTAR" },
                ],
                extraHeaderActions: h(
                  "button",
                  {
                    type: "button",
                    onClick: () => setShowGlobalRpvLog(!showGlobalRpvLog),
                    style: {
                      border: "1px solid #30363d",
                      background: "#21262d",
                      color: "#c9d1d9",
                      borderRadius: "6px",
                      padding: "3px 8px",
                      fontSize: "10px",
                      cursor: "pointer",
                    },
                  },
                  showGlobalRpvLog ? "Ver Console do Robô Atual" : "Ver Log Geral (Todos)"
                ),
              })
            )
          : null,

        // ==================== VISÃO 3: ROBÔ PET PROJUDI (CONSOLE CHAT + CMD OCULTO + LINK SALVO) ====================
        isAdmin && section === "projudi"
          ? h(
              "main",
              { className: "workspace", id: "sectionProjudiWorkspace" },
              h(
                "div",
                { className: "workspace-head" },
                h(
                  "div",
                  { style: { display: "flex", alignItems: "center", gap: "12px" } },
                  h("span", { className: "rpv-folder-tag" }, "ROBO_PROJUDI"),
                  h(
                    "div",
                    null,
                    h(
                      "div",
                      { style: { fontSize: "15px", fontWeight: 700 } },
                      "Robô Pet PROJUDI (Envio Automático de Petições .p7s)"
                    ),
                    h(
                      "div",
                      { style: { fontSize: "11px", color: "var(--muted)", marginTop: "2px" } },
                      "Link do PROJUDI salvo automaticamente (https://projudi.tjpr.jus.br/projudi/) · CMD oculto · Interação via Chat no Console"
                    )
                  )
                ),
                h(
                  "div",
                  { className: "statusline" },
                  h("span", { className: "dot" }),
                  h("span", null, projudiMessage)
                )
              ),
              h(
                "div",
                {
                  style: {
                    background: "var(--surface-soft)",
                    border: "1px solid var(--line)",
                    borderRadius: "16px",
                    padding: "14px 18px",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    gap: "16px",
                    flexWrap: "wrap",
                    marginBottom: "12px",
                  },
                },
                h(
                  "div",
                  { style: { display: "flex", alignItems: "center", gap: "12px", flexWrap: "wrap" } },
                  h(
                    "select",
                    {
                      className: "control",
                      value: projudiMode,
                      onChange: (e) => setProjudiMode(e.target.value),
                      style: { height: "38px", fontWeight: 600, minWidth: "260px" },
                    },
                    h("option", { value: "v6" }, "Executar no Console do Site (robo_projudi_v6.py)"),
                    h("option", { value: "gui" }, "Abrir Interface Gráfica (robo_projudi_gui.py)")
                  ),
                  h(
                    "button",
                    {
                      type: "button",
                      className: "update-btn",
                      onClick: runProjudiRobot,
                      disabled: projudiStatus === "running",
                    },
                    projudiStatus === "running" ? "↻ Em execução..." : "▶ Rodar Robô PROJUDI"
                  ),
                  projudiStatus === "running"
                    ? h(
                        "button",
                        {
                          type: "button",
                          className: "update-btn",
                          style: { background: "var(--danger)" },
                          onClick: stopProjudiRobot,
                        },
                        "⏹ Parar"
                      )
                    : null
                ),
                h(
                  "span",
                  { className: "badge status-done" },
                  "🔗 Link Salvo: https://projudi.tjpr.jus.br/projudi/"
                )
              ),
              h(ConsoleWithChat, {
                title: "ROBÔ PET PROJUDI (CMD OCULTO · CHAT INTEGRADO)",
                badgeText:
                  projudiStatus === "running"
                    ? "Executando"
                    : projudiStatus === "done"
                    ? "Concluído"
                    : projudiStatus === "error"
                    ? "Erro"
                    : "Pronto",
                badgeClass: getStatusBadgeClass(projudiStatus),
                lines: projudiConsoleLines,
                emptyText:
                  'Pronto para executar. O link do PROJUDI já está salvo automaticamente. Clique em "▶ Rodar Robô PROJUDI" e utilize o Chat abaixo para responder confirmações (como "ENVIAR" ou ENTER) diretamente no site, sem janela CMD.',
                waitingInput: projudiWaitingInput,
                onSendInput: sendProjudiConsoleInput,
                onClear: clearProjudiLog,
                quickChips: [
                  { label: 'Autorizar Envio ("ENVIAR")', value: "ENVIAR", highlight: true },
                  { label: "Confirmar Login no PROJUDI (ENTER)", value: "", highlight: true },
                  { label: "Finalizar / Fechar Navegador (ENTER)", value: "" },
                ],
              })
            )
          : null
      )
    );
  }

  const rootEl = document.getElementById("root");
  if (rootEl) {
    const root = ReactDOM.createRoot(rootEl);
    root.render(h(PainelApp));
  }
})();
