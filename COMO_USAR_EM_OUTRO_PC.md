# Como usar em outro computador

Para avaliação acadêmica, extraia o ZIP e abra `Abrir_Painel.bat` ou `index.html`.
A apresentação usa dados fictícios e funciona offline pelo navegador.

Os passos abaixo configuram a instalação institucional. Para abri-la depois de
configurar o banco, use `Abrir_Painel_Neon.bat` ou `python servidor_painel.py`.

## Preparação do Neon pelo administrador

1. Antes de atualizar uma instalação antiga, copie `saida/ESTADO_PAINEL.json` para um local seguro. Use a cópia do PC que tem a coleta mais recente.
2. Com a autorização da Procuradoria para armazenar os dados em nuvem, crie o projeto `painel-prazos` no Neon com PostgreSQL 17 em AWS São Paulo (`aws-sa-east-1`). [Regiões do Neon](https://neon.com/docs/introduction/regions)
3. Use a conta proprietária do banco, como `painel_owner`, para aplicar `prazos/schema.sql` no SQL Editor. Outra opção é executar `python scripts/migrar_json_para_banco.py --somente-schema` usando a conexão do proprietário em `DATABASE_URL`.
4. Crie o papel de login `painel_app` via SQL, para que ele receba apenas as permissões concedidas abaixo. O Neon concede privilégios adicionais aos papéis criados pelo console, CLI ou API. [Gestão de papéis no Neon](https://neon.com/docs/manage/roles)

   ```sql
   CREATE ROLE painel_app LOGIN PASSWORD '<senha forte e exclusiva>';
   GRANT CONNECT ON DATABASE neondb TO painel_app;
   GRANT USAGE ON SCHEMA public TO painel_app;
   GRANT SELECT, INSERT, UPDATE, DELETE
     ON usuarios, sessoes, tentativas_login, coletas, prazos TO painel_app;
   GRANT USAGE ON SEQUENCE usuarios_id_seq, coletas_id_seq, prazos_id_seq TO painel_app;
   ```

   Use o nome do seu banco no lugar de `neondb`, se for diferente. Copie a conexão **Pooled** de `painel_app` com TLS para a configuração dos PCs. A string permite ler e alterar os dados e os perfis diretamente, por isso deve circular apenas entre responsáveis de confiança. [Pooling no Neon](https://neon.com/docs/connect/connection-pooling)

## Instalação em cada PC Windows

1. Instale o Python 3.11 ou mais recente e o Git. Em um PC novo, clone o repositório e entre na branch que contém a atualização. Em instalações existentes, atualize essa branch com `git pull` depois de guardar a cópia do estado antigo.
2. Na raiz do projeto, configure o ambiente:

   ```powershell
   py -3 -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   Copy-Item .env.example .env
   ```

3. No `.env`, preencha `DATABASE_URL` com a conexão recebida e `PAINEL_MAQUINA` com um nome para o PC. `SESSAO_HORAS` tem valor padrão de 12 horas.
4. Nos PCs que executam robôs com Playwright, instale o Chromium com `.\.venv\Scripts\playwright.exe install chromium`.
5. Depois da migração e da criação da conta, abra `Abrir_Painel_Neon.bat` ou rode `.\.venv\Scripts\python.exe servidor_painel.py`. Entre com seu e-mail e senha. O navegador usa o servidor local na porta 8765.

## Migração inicial e gestão de contas

Em um único PC, importe a cópia do JSON antes da primeira atualização. Use o caminho onde a cópia foi guardada:

```powershell
.\.venv\Scripts\python.exe scripts/migrar_json_para_banco.py --arquivo 'C:\caminho\ESTADO_PAINEL.json'
.\.venv\Scripts\python.exe -m prazos.usuarios criar --email admin@pge.pr.gov.br --nome "Nome do administrador" --admin
```

Confira a contagem exibida pelo script. Se não houver JSON anterior, comece pela criação da conta e faça a primeira coleta no painel.

A CLI solicita a senha de forma interativa, com mínimo de 10 caracteres. Para uma avaliação, use `criar --email <e-mail do avaliador> --nome "Professor (FESPPR)" --sem-google` e entregue a senha por um canal seguro. Use `desativar` ao final para revogar as sessões.

```powershell
.\.venv\Scripts\python.exe -m prazos.usuarios listar
.\.venv\Scripts\python.exe -m prazos.usuarios senha --email pessoa@example.com
.\.venv\Scripts\python.exe -m prazos.usuarios perfil --email pessoa@example.com --usuario
.\.venv\Scripts\python.exe -m prazos.usuarios desativar --email pessoa@example.com
```

## Google opcional

- Para habilitar o login institucional, configure um OAuth Client ID de **Aplicativo da Web** com as origens locais usadas pelo painel, incluindo `http://localhost` e `http://localhost:8765`. Defina `GOOGLE_CLIENT_ID` no `.env` e abra o painel pela origem autorizada. A conta `@pge.pr.gov.br` precisa estar ativa no Postgres e habilitada para Google. [Configuração do Google Identity Services](https://developers.google.com/identity/gsi/web/guides/get-google-api-clientid?hl=pt-br)
- Para autorizar o Sheets e o Drive dos robôs, coloque um `credentials.json` de **Aplicativo para computador** na raiz, em `dados/` ou em `saida/` e rode `.\.venv\Scripts\python.exe -m prazos.google_sync`. A autorização usa tokens locais. Revise o compartilhamento da planilha e do Apps Script, que seguem as permissões do Google Workspace.

Os arquivos gerados `ESTADO_PAINEL.json`, `PRAZOS_CONSOLIDADOS.csv` e `dados_iniciais.js` saíram do controle de versão. Versões antigas continuam no histórico do Git. A senha compartilhada antiga deve ser descartada.
