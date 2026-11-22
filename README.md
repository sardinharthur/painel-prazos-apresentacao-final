# Painel de Prazos da Procuradoria de Saúde

## Acesso da banca

Este repositório inclui a coleta real de **18/11/2026 às 19h47**, com **264
registros**, exportada do banco do projeto. Os processos, as datas, os estados e
os procuradores são os da coleta. A data exibida pelo painel corresponde a essa
fotografia dos dados.

1. Instale o **Python 3.11 ou mais recente** caso ele ainda esteja ausente no PC.
2. Baixe o repositório por **Code → Download ZIP** e extraia a pasta inteira,
   ou faça um clone.
3. No Windows, abra **Abrir_Painel.bat** e mantenha a janela do servidor aberta.
4. Entre no painel com **login@fesppr** e senha **@integrador2026**.

No macOS, Windows ou Linux, na pasta extraída, execute:

```sh
python3 servidor_avaliacao.py
```

O navegador abre no endereço local informado pelo servidor. O servidor de avaliação
usa apenas a biblioteca padrão do Python. O arquivo `.env`, o Neon e a instalação
de pacotes adicionais ficam dispensados nesse acesso.

## O que pode ser avaliado

- Consulta dos 264 registros reais da coleta incluída.
- Abas EPROC e PROJUDI, busca por processo ou texto e filtros por procurador,
  situação e data.
- Indicadores, prazos cumpridos, registros novos e registros para revisão,
  conforme a coleta.
- Alto contraste, tamanho da fonte e navegação responsiva.
- Painéis dos robôs RPV e PET PROJUDI, suas descrições e carrossel.
- Login, sessão por navegador e logout.
- Botão **Atualizar** visível no painel de prazos.

A conta da banca tem **acesso de leitura**. Operações de atualização, importação,
execução e parada dos robôs, acesso a pastas e comandos de console ficam bloqueadas
no servidor. O botão **Atualizar** permanece visível para avaliação da interface.
Na instalação institucional, ele aciona a coleta pelos robôs. Na versão da banca,
clicar nele exibe uma explicação sobre as credenciais dos portais necessárias para
essa operação. A coleta será demonstrada pelo responsável pelo projeto na
apresentação. Os controles de importação e operação direta dos robôs ficam ocultos,
e os consoles informam a restrição de acesso.

O painel de avaliação consulta a fotografia real incluída em
`avaliacao/estado.json`. Novas coletas feitas na instalação institucional exigem
uma nova exportação desse arquivo para aparecerem nesta versão.

## Arquivos para a revisão do código

- `painel/Index.html` carrega a interface.
- `painel/styles.css` define o layout e os recursos visuais.
- `painel/app.js` contém os componentes React, os filtros, as tabelas e a
  comunicação com a API.
- `servidor_avaliacao.py` fornece a API local de leitura e a conta da banca.
- `servidor_painel.py`, `prazos/`, `scripts/` e `robos/` contêm a aplicação
  institucional, a persistência no Postgres, a consolidação e as automações.

O React 18.3.1 e o React DOM estão incluídos em `painel/vendor/`, com as respectivas
licenças. O acesso da banca funciona localmente com os arquivos extraídos.

## Instalação institucional

O arquivo **Abrir_Painel_Neon.bat** inicia a aplicação institucional. Essa modalidade
usa as dependências de `requirements.txt`, uma conexão configurada no `.env`,
usuários cadastrados no banco e as credenciais dos portais para executar as
automações. As credenciais de banco e tribunais pertencem à configuração de cada PC.

## Testes

```sh
python -m unittest tests.test_avaliacao
node --check painel/app.js
```

Os testes da aplicação institucional podem ser executados depois de instalar
`requirements.txt`. Os testes do Postgres usam um banco separado configurado em
`TEST_DATABASE_URL`.
