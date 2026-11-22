# Robô 2 — pontos para configurar no Playwright

## O que já está pronto

O Robô 2 foi separado para fazer **somente**:

1. Ler a aba `RPVs`.
2. Localizar linhas com:
   - `AUTOS` preenchido;
   - `NOME PACIENTE` preenchido;
   - `CPF PACIENTE` preenchido;
   - `PROTOCOLO` vazio.
3. Entrar no eProtocolo.
4. Acessar **Protocolo Geral → Incluir Protocolo**.
5. Preencher o cadastro.
6. Clicar em **Próximo**.
7. Capturar o número no padrão `25.xxx.xxx-x`.
8. Gravar o número na coluna `PROTOCOLO` **da mesma linha**.

Ele para aí. O envio da RPV e a solicitação de assinatura serão do **Robô 4**.

## Dados fixos já colocados no `config.json`

- Tipo do Processo: Digital
- Órgão de Cadastro: PGE - PROCURADORIA GERAL DO ESTADO
- Local de Cadastro: PGE/PRS - PROCURADORIA DE SAÚDE
- Espécie do Documento: REQUISIÇÃO
- Restrição: Restrito
- Assunto: AREA JURIDICA
- Palavra-Chave 1: PAGAMENTO
- País: BRASIL
- Estado: PR
- Cidade: CURITIBA
- Prioridade legal: Não
- Interessado: Não Autoridade
- Tipo: PESSOA FÍSICA
- Identificação: CPF

A descrição é montada assim:

`Requisição de Pequeno Valor oriunda dos Autos num. [AUTOS]`

## O que falta mapear quando você for configurar o Playwright

Abra `eprotocolo.py`.

Os pontos principais são:

- `_login()`
- `_abrir_incluir_protocolo()`
- `_selecionar_combo()`
- `_preencher_interessado()`

O número do protocolo já é buscado pelo padrão:

`25.xxx.xxx-x`

inclusive no texto `Analisar Protocolo 25.xxx.xxx-x`.

## Segurança antes do primeiro teste

O arquivo vem com:

- `"modo_teste": true`
- `"limite_por_execucao": 1`

Assim, no primeiro teste ele pega no máximo uma linha e **não clica em Próximo**.

Depois que os seletores estiverem conferidos, altere no `config.json`:

```json
"modo_teste": false
```

Para processar todas as linhas pendentes:

```json
"limite_por_execucao": 0
```
