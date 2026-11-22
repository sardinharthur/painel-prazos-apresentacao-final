# Robô 1 — EPROC -> Google Sheets

Planilha configurada:
https://docs.google.com/spreadsheets/d/1MaraQb5yraO5nwwrrW5qs7RGlMKJhSLpQhN9VnHiwsY/edit

## Cabeçalhos esperados

Além dos cabeçalhos antigos, a planilha precisa possuir:

- NOME PACIENTE
- CPF PACIENTE

O código procura os cabeçalhos pelo nome, portanto as colunas podem ter sido inseridas depois da J sem quebrar os índices.

## Regra do paciente

1. O Robô abre o processo pelo número de AUTOS.
2. Localiza e baixa o REQEXT1.
3. Lê beneficiário, natureza e valor.
4. Se for Honorários Periciais, tenta obter NOME + CPF da área AUTOR do cabeçalho do EPROC.
5. Nos demais casos, ou se o cabeçalho falhar, percorre as páginas de eventos até encontrar INIC1.
6. Baixa o INIC1 e associa NOME + CPF dentro do bloco de qualificação da parte.
7. Preenche NOME PACIENTE e CPF PACIENTE na mesma linha.

## Antes do primeiro teste

Este pacote NÃO inclui credentials.json, token.json ou o perfil do navegador por segurança.
Copie da pasta antiga para esta pasta:

- credentials.json
- token.json (opcional; será recriado se faltar)
- playwright/perfil_eproc (opcional, para reaproveitar a sessão do EPROC)

## Primeiro teste recomendado

O config.json vem com:

`"dry_run": true`

Assim o robô acessa os sistemas e mostra o que preencheria, mas não altera a planilha.

Execute `RODAR_ROBO1.bat` e faça o login quando solicitado.

Se o EPROC local tiver seletores diferentes dos seletores genéricos usados neste código, o programa grava screenshot e HTML na pasta `debug`. Isso permite ajustar o seletor real sem reescrever o restante do Robô 1.

Depois que um processo real passar de ponta a ponta corretamente, altere em config.json:

`"dry_run": false`

A partir daí ele escreverá na planilha.

O primeiro pacote também vem com `"limite_processos": 1`, para testar somente uma linha por execução. Depois do teste real, use `0` para não limitar.
