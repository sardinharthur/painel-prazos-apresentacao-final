/**
 * Painel de Prazos PRS · Google Apps Script (Code.gs) — Ecossistema Google Institucional
 *
 * Como usar no navegador (.gs):
 *   1. Abra a planilha "Painel de Prazos PRS - Consolidado" no Google Drive Institucional (@pge.pr.gov.br)
 *   2. Vá em Extensões -> Apps Script
 *   3. Cole este conteúdo em `Code.gs` e crie o arquivo HTML `Index.html`
 *   4. Clique em "Implantar" -> "Nova implantação" -> "App da Web"
 *      (Executar como: "Usuário que acessa o aplicativo da web" ou "Eu" |
 *       Quem pode acessar: "Qualquer pessoa no domínio pge.pr.gov.br")
 */

const SPREADSHEET_ID = "1uFYKHu204EuqKu7G-E7-KRD5cpuPVLqoxhg3pGowM28";
const EMAILS_ADMIN = [
  "ter.arthursouza@pge.pr.gov.br",
  "ext.arthursouza@pge.pr.gov.br",
  "arthursardinha@pge.pr.gov.br",
  "arthur.sardinha@pge.pr.gov.br",
  "arthur@pge.pr.gov.br",
  "sardinharthur@gmail.com"
];

function _abrirPlanilha() {
  if (SPREADSHEET_ID) {
    return SpreadsheetApp.openById(SPREADSHEET_ID);
  }
  return SpreadsheetApp.getActiveSpreadsheet();
}

function obterSessaoUsuario() {
  let email = "";
  try {
    email = String(Session.getActiveUser().getEmail() || Session.getEffectiveUser().getEmail() || "").trim().toLowerCase();
  } catch (e) {}
  const localPart = email.split("@")[0] || "";
  const isAdmin = EMAILS_ADMIN.indexOf(email) !== -1 ||
    localPart === "arthursardinha" ||
    localPart === "arthur.sardinha" ||
    localPart === "sardinharthur";
  return {
    authenticated: Boolean(email),
    provider: "google_workspace_institucional",
    email: email,
    name: localPart ? localPart.replace(/\./g, " ").toUpperCase() : "Usuário Institucional",
    is_institutional: email.indexOf("@pge.pr.gov.br") !== -1,
    is_admin: isAdmin,
    institutional_domain: "pge.pr.gov.br"
  };
}

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu("⚖️ Painel de Prazos PRS")
    .addItem("🖥️ Abrir Painel em Tela Cheia (Modal)", "abrirModalPainel")
    .addToUi();
}

function abrirModalPainel() {
  const html = HtmlService.createHtmlOutputFromFile("Index")
    .setWidth(1420)
    .setHeight(860)
    .setTitle("Painel de Prazos · Procuradoria de Saúde (PGE-PR)");
  SpreadsheetApp.getUi().showModalDialog(html, "Painel de Prazos · PRS");
}

function doGet(e) {
  return HtmlService.createHtmlOutputFromFile("Index")
    .setTitle("Painel de Prazos · Procuradoria de Saúde (PGE-PR)")
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL)
    .addMetaTag("viewport", "width=device-width, initial-scale=1");
}

/**
 * Retorna o payload JSON completo do Painel lendo da aba ESTADO_PAINEL
 * junto com a sessão Google Auth do usuário logado no Google Workspace.
 */
function obterDadosPainel() {
  const ss = _abrirPlanilha();
  const sessao = obterSessaoUsuario();
  const shEstado = ss.getSheetByName("ESTADO_PAINEL");
  if (!shEstado) {
    return { data: [], days: [], updatedAt: "Aba ESTADO_PAINEL não encontrada", session: sessao };
  }

  const rows = shEstado.getDataRange().getValues();
  const mapa = {};
  for (let i = 1; i < rows.length; i++) {
    const k = String(rows[i][0] || "").trim();
    const v = String(rows[i][1] || "");
    if (k) mapa[k] = v;
  }

  const qtdFatias = parseInt(mapa["QTD_FATIAS_JSON"] || "0", 10);
  let jsonCompleto = "";
  for (let idx = 1; idx <= qtdFatias; idx++) {
    jsonCompleto += (mapa["JSON_PARTE_" + idx] || "");
  }

  if (!jsonCompleto) {
    return { data: [], days: [], updatedAt: "Sem dados sincronizados", session: sessao };
  }

  const payload = JSON.parse(jsonCompleto);
  payload.google = {
    spreadsheet_url: ss.getUrl(),
    folder_url: "https://drive.google.com/drive/folders/0AKQe6iKo0eUeUk9PVA",
    status: "Conectado ao Google Sheets (.gs)"
  };
  payload.session = sessao;
  return payload;
}
