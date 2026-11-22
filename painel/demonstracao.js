/* Apresentação local com dados fictícios. Este módulo funciona sem serviços externos. */
(() => {
  "use strict";
  if (location.protocol !== "file:") return;

  let autenticado = true;
  let versao = 1;
  let atualizado = new Date();
  const trabalhos = new Map();
  const robos = new Map();
  const projudi = {
    status: "ready", message: "Simulação pronta", waiting_input: false, log: [],
  };
  const sistemas = ["eproc1", "projudi", "eprocRec", "eprocTJ"];
  const pessoas = ["Procuradora Exemplo A", "Procurador Exemplo B", "Procuradora Exemplo C"];
  const hoje = new Date();
  hoje.setHours(12, 0, 0, 0);
  const dias = [];
  const cursor = new Date(hoje);
  while (dias.length < 5) {
    if (cursor.getDay() !== 0 && cursor.getDay() !== 6) dias.push(new Date(cursor));
    cursor.setDate(cursor.getDate() + 1);
  }

  function iso(data) {
    return [data.getFullYear(), String(data.getMonth() + 1).padStart(2, "0"),
      String(data.getDate()).padStart(2, "0")].join("-");
  }

  const itens = Array.from({ length: 32 }, (_, i) => {
    const dia = dias[i % dias.length];
    const cumprido = i % 9 === 0;
    const revisao = !cumprido && i % 5 === 0;
    return {
      key: `demonstracao-${i}`, system: sistemas[i % sistemas.length],
      process: `EXEMPLO-${String(i + 1).padStart(4, "0")}`,
      date: iso(dia) === iso(hoje) ? "Hoje"
        : (dia.getTime() - hoje.getTime() === 86400000 ? "Amanhã"
          : dia.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" })),
      dateNum: dia.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" }),
      dateISO: iso(dia), intimacao: "Intimação fictícia", qtdIntimacoes: 1,
      prosecutor: pessoas[i % pessoas.length], modality: i % 2 ? "Execução" : "Conhecimento",
      event: ["Manifestação de exemplo", "Recurso de exemplo", "Cumprimento de exemplo"][i % 3],
      teor: "Registro fictício para avaliação acadêmica da interface.",
      status: cumprido ? "Cumprido" : revisao ? "Revisar" : "Pendente",
      isNew: !cumprido && i % 4 === 0, review: revisao,
      flag: cumprido ? "done" : i % 5 === 0 ? "today" : "later",
      orgao: "Unidade fictícia", caixa: "Caixa de demonstração", urgente: i % 7 === 0,
      observacao: "Dado fictício", situacao_cruzamento: revisao ? "VERIFICAR MANUAL" : "LOCALIZADO",
      prazoMultiplo: "", avisoPrazoMultiplo: "",
    };
  });

  function sessao() {
    return autenticado
      ? { autenticado: true, nome: "Professor · Demonstração", email: "avaliacao@example.com", perfil: "admin" }
      : { autenticado: false };
  }

  function payload() {
    return {
      data: itens, referenceDate: iso(hoje), updatedISO: atualizado.toISOString(),
      updatedAt: `Demonstração atualizada às ${atualizado.toLocaleTimeString("pt-BR")}`,
      runtime: "Coleta simulada", session: sessao(),
      days: dias.map((dia) => ({
        iso: iso(dia),
        dateNum: dia.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" }),
        dateStr: dia.toLocaleDateString("pt-BR", { day: "2-digit", month: "short" }),
        label: dia.toLocaleDateString("pt-BR", { weekday: "long" }),
      })),
      counts: {
        abertos: itens.filter((it) => it.status !== "Cumprido").length,
        cumpridos: itens.filter((it) => it.status === "Cumprido").length,
        novos: itens.filter((it) => it.isNew).length,
        revisar: itens.filter((it) => it.review).length,
        multiplos: 0,
      },
    };
  }

  function registrar(robo, texto) {
    robo.log = [...robo.log, `[${new Date().toLocaleTimeString("pt-BR")}] ${texto}`].slice(-100);
  }

  function parar(chave) {
    clearInterval(trabalhos.get(chave));
    trabalhos.delete(chave);
  }

  function iniciar(chave, robo) {
    parar(chave);
    Object.assign(robo, { status: "running", progress: 0, current: 0, total: 5, success: 0, errors: 0 });
    robo.message = "Simulando processamento de exemplos";
    registrar(robo, "Simulação iniciada com dados fictícios.");
    const temporizador = setInterval(() => {
      robo.current += 1;
      robo.success = robo.current;
      robo.progress = robo.current * 20;
      registrar(robo, `Exemplo ${robo.current}/5 processado na simulação.`);
      if (robo.current >= 5) {
        parar(chave);
        robo.status = "done";
        robo.message = "Simulação concluída";
      }
    }, 750);
    trabalhos.set(chave, temporizador);
  }

  function resposta(status, dados) {
    return new Response(JSON.stringify(dados), {
      status, headers: { "Content-Type": "application/json; charset=utf-8" },
    });
  }

  async function requisitar(caminho, opcoes = {}) {
    if (opcoes.signal?.aborted) throw new DOMException("Requisição cancelada", "AbortError");
    const url = new URL(caminho, "http://demonstracao.local");
    const rota = url.pathname;
    const metodo = opcoes.method || "GET";
    if (rota === "/api/auth/status") return resposta(200, sessao());
    if (rota === "/api/auth/login" && metodo === "POST") {
      autenticado = true;
      return resposta(200, { ok: true, session: sessao() });
    }
    if (!autenticado) return resposta(401, { erro: "nao_autenticado" });
    if (rota === "/api/auth/logout") {
      autenticado = false;
      for (const chave of trabalhos.keys()) parar(chave);
      for (const robo of [...robos.values(), projudi]) {
        if (robo.status === "running") {
          robo.status = "stopped";
          robo.message = "Simulação interrompida ao sair";
        }
      }
      return resposta(200, { ok: true });
    }
    if (rota === "/api/prazos") return resposta(200, payload());
    if (rota === "/api/status-coleta") {
      return resposta(200, { versao_dados: versao, session: sessao(), etapa: "Demonstração" });
    }
    if (rota === "/api/atualizar" || rota === "/api/upload-eproc") {
      if (rota === "/api/upload-eproc") {
        alert("Demonstração de importação concluída. A tabela usa os exemplos fictícios incluídos no projeto.");
      }
      atualizado = new Date();
      versao += 1;
      itens.forEach((item, i) => { item.isNew = item.status !== "Cumprido" && (i + versao) % 4 === 0; });
      return resposta(200, payload());
    }
    if (rota === "/api/rpv/status") {
      return resposta(200, { robots: [...robos.values()], global_log: [...robos.values()].flatMap((r) => r.log) });
    }
    if (rota === "/api/projudi-robo/status") return resposta(200, projudi);

    const acao = rota.match(/^\/api\/(rpv|projudi-robo)\/(run|stop|input|clear-log|open-folder)$/);
    if (acao && metodo === "POST") {
      const corpo = opcoes.body ? JSON.parse(opcoes.body) : {};
      const id = corpo.id || url.searchParams.get("id");
      const chave = acao[1] === "rpv" ? id : "projudi";
      const robo = acao[1] === "rpv" ? robos.get(id) : projudi;
      if (acao[2] === "open-folder") {
        alert("Arquivos dos robôs disponíveis na pasta robos/ do projeto extraído.");
      } else if (acao[2] === "clear-log" && id === "all") {
        robos.forEach((r) => { r.log = []; });
      } else if (!robo) {
        return resposta(404, { erro: "Robô desconhecido" });
      } else if (acao[2] === "run") {
        iniciar(chave, robo);
      } else if (acao[2] === "stop") {
        parar(chave);
        robo.status = "stopped";
        robo.message = "Simulação interrompida";
        registrar(robo, "Simulação interrompida.");
      } else if (acao[2] === "clear-log") {
        robo.log = [];
      } else {
        registrar(robo, "Comando recebido pela simulação.");
      }
      return resposta(200, { ok: true, message: "Ação simulada" });
    }
    return resposta(404, { erro: "Ação indisponível na demonstração" });
  }

  function exportarPlanilha() {
    const linhas = [["Processo", "Sistema", "Data", "Procurador", "Status"],
      ...itens.map((i) => [i.process, i.system, i.dateNum, i.prosecutor, i.status])];
    const csv = linhas.map((linha) => linha.map((v) => `"${v.replaceAll('"', '""')}"`).join(";")).join("\r\n");
    const url = URL.createObjectURL(new Blob(["\uFEFF", csv], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = "Prazos-ficticios.csv";
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  window.PAINEL_DEMONSTRACAO = {
    requisitar, exportarPlanilha,
    prepararRobos(modelos) {
      modelos.forEach((modelo) => robos.set(modelo.id, {
        ...modelo, message: "Simulação pronta", log: ["Ambiente acadêmico com dados fictícios."],
      }));
    },
  };
})();
