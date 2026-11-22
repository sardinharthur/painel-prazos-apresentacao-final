# Painel de Prazos — Apresentação acadêmica

Baixe pelo botão **Code → Download ZIP**, extraia a pasta inteira e abra
**Abrir_Painel.bat** no Windows ou **index.html** no navegador. No Linux e macOS,
abra **index.html**. Também pode clonar este repositório e abrir esse arquivo.

A apresentação funciona offline e inclui o React 18.3.1 em `painel/vendor/`.
A conta de avaliação abre automaticamente com 32 registros fictícios. É possível
testar os filtros, sistemas, datas, busca, alto contraste, tamanho de fonte,
carrossel, consoles, simulação de atualização e exportação de CSV. Ao sair, use
**Abrir demonstração**. As alterações duram até recarregar a página.

O cabeçalho identifica os dados fictícios e os robôs simulados. A importação
demonstra o fluxo da interface usando os exemplos incluídos. O código das
integrações está nas pastas do projeto.

## Execução conectada ao Neon

Use **Abrir_Painel_Neon.bat** para iniciar o servidor Python com o `.env` da
instalação. Login individual, persistência compartilhada, coletas nos portais e
envio de documentos pelos robôs exigem banco e credenciais da instituição.
A apresentação é ativada ao abrir arquivos locais (`file://`). Pelo servidor
Python, o frontend utiliza a API autenticada.

## Projeto original

Plataforma integrada da **Procuradoria de Saúde — Procuradoria-Geral do Estado do Paraná (PGE-PR)** para gestão e cruzamento de prazos processuais (**EPROC × PROJUDI × SAPIENS**), automação de peticionamento em lote (**Robô PET PROJUDI**) e processamento de **RPVs (Robôs 1, 2, 4 e 5)**.

## Login e permissões

Cada usuário entra com seu e-mail e senha. O administrador cria as contas e define o perfil no Postgres. A opção de entrar com Google usa uma conta institucional já cadastrada, quando habilitada. Usuários comuns consultam prazos. Administradores também podem atualizar a coleta, importar arquivos, agendar o SAPIENS e operar os robôs.

O painel e os robôs rodam em cada PC Windows. As coletas, os usuários e as sessões ficam no Postgres compartilhado. Cada coleta fica no histórico, e o painel exibe a mais recente.

## Principais funcionalidades

### Front-end em React 18 + Identidade Visual do Estado do Paraná
- **React 18 (`painel/Index.html`, `painel/app.js`, `painel/styles.css`)**: Interface declarativa construída em React 18 com suporte a alto contraste (**WCAG AAA**) e ampliação tipográfica dinâmica.
- **Logo do Estado do Paraná no Cabeçalho**: A logo oficial do Estado do Paraná (`painel/logo_parana.png`) fica posicionada ao lado do título **"PAINEL DE PRAZOS"** na barra superior e na tela inicial de autenticação.

### Carrossel dos Robôs RPV (Shadcn UI Base Carousel)
- Na seção **Automação RPVs**, quando aberta no modo **Carrossel**, o componente implementa a estrutura e animações suaves do **[Shadcn UI Base Carousel](https://ui.shadcn.com/docs/components/base/carousel)** (`carousel-content` com `translate3d`, `carousel-item`, `carousel-previous`, `carousel-next`, suporte a teclado/touch e indicadores).

### Robô PET PROJUDI e Robôs RPV: Console com Chat Integrado e CMD Oculto
- **Link do PROJUDI Salvo Automaticamente**: O **Robô PET PROJUDI (`robos/ROBO_PROJUDI/robo_projudi_v6.py`)** carrega automaticamente o link oficial salvo em `robos/ROBO_PROJUDI/projudi_config.json` (`https://projudi.tjpr.jus.br/projudi/`), sem pedir URL no console.
- **CMD Externo Oculto (`CREATE_NO_WINDOW`)**: Os robôs são executados em segundo plano sem abrir janelas pretas de CMD externas.
- **Chat Interativo no Console do Site**: O console de cada robô (PET PROJUDI e RPV 1, 2, 4 e 5) possui barra de **Chat no próprio site**, permitindo enviar comandos (`ENVIAR`, `PULAR`, `SAIR`, `<Enter>` ou texto livre) diretamente pelo navegador.

---

## Instalação e migração

Siga [Como usar em outro computador](COMO_USAR_EM_OUTRO_PC.md) para preparar o Neon, migrar a coleta inicial, provisionar contas e configurar cada PC.

Para validar o JavaScript e rodar os testes:

```powershell
node --check painel/app.js
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Defina `TEST_DATABASE_URL` apontando para um **Postgres de teste** para executar a suíte de integração. Os testes criam e removem um schema isolado.

Para rodar o cruzamento offline e gerar JSON e CSV, use `python gerar_consolidado.py --sem-banco`. O painel local utiliza o Postgres ao abrir.
