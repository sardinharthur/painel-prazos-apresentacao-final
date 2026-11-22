# Fontes examinadas em 21/10/2026

Os arquivos foram tratados como dados de entrada. Textos de orientação contidos no ZIP não foram executados nem considerados novas instruções para o projeto.

## Exportações EPROC

Os cinco arquivos `ProcessosProcuradoria-2026-10-20-*.xls` fornecidos em Downloads têm assinatura OLE e dados BIFF, não HTML com extensão de Excel. Todos usam a aba de processos por órgão, com metadados na primeira linha, parte no título do bloco, cabeçalho na linha 4 e subtotal no fim.

As oito colunas úteis são Número Processo, Órgão Julgador, Classe, Qualificação da parte, Remetido ao Plantão, Prazo aberto / Data Final, Data Intimação e Remessa Externa Ativa. Quatro colunas adicionais vazias nos exemplos são preservadas nas células originais.

O título do bloco identifica a parte consultada; não fornece o nome da parte adversa. Órgão julgador é um código, sem descrição expandida. Teor e número de evento não estão presentes. A coluna de intimação pode conter várias datas; não há identificação que permita associar cada data a uma tarefa ou evento específico.

## Consolidado de referência

`Exemplo FINAL COM TODOS OS PRAZOS.xlsx` foi aberto apenas para inspeção. Tem a aba Consulta e outras abas, inclusive de audiências. Consulta reúne linhas de apresentação sem cabeçalho uniforme, com eventos e datas textuais em linhas PROJUDI e classes/datas em linhas EPROC. Não foi usado para substituir os dados brutos ou deduzir correspondências entre múltiplas intimações. Nenhuma aba foi modificada. A importação PROJUDI precisa de um adaptador próprio.

## ZIP SAPIENS

`CÓDIGO SAPIENS PRAZOS.zip` contém a pasta `ROBO PRAZOS V6.7 - SINCRONIZACAO PAGINAS`, com `ROBO PRAZOS V6.py`, compatibilidade JavaScript, testes, logs, snapshots, dependências do Playwright, CSV atual, CSV de coleta inicial e relatório de validação.

Foram inspecionados o inventário, o código de exportação e de marcação de duplicidades, o fluxo principal de gravação, o CSV atual e o relatório fornecido. Não foi executada a coleta nem modificado o robô. O código grava UTF-8 com BOM e delimitador vírgula, usando `csv.DictWriter`; só substitui o CSV atual após concluir a coleta, por arquivo temporário e `os.replace`.

O contrato exportado tem 18 colunas:

```text
fonte,caixa,nome_caixa_sapiens,procurador,pagina,linha,id_tarefa,processo,
data_distribuicao,inicio_prazo,final_prazo,situacao_prazo,especie_tarefa,
assunto_pge,teor_previa,teor,status,coletado_em
```

O CSV atual tem 978 tarefas. O relatório de validação que acompanha o ZIP informa 592 registros `TEOR_COMPLETO`, 372 `TEOR_PARCIAL` e 14 `VERIFICAR MANUAL - OCORRÊNCIA DUPLICADA`; informa também 74 teores vazios e 691 datas finais vazias, associadas a prazo fechado. Esses números descrevem a coleta fornecida, não uma nova coleta nem um resultado de cruzamento.

O código marca possíveis duplicidades por processo, início, final e teor normalizado, sem removê-las. Assim, não se deve reduzir o futuro índice SAPIENS a uma única tarefa por CNJ. `inicio_prazo` e `data_distribuicao` têm nomes e significados próprios; não presumir que sejam sempre iguais à intimação judicial.

Antes do próximo módulo, será necessário definir como registrar candidatos múltiplos e correspondências incertas. O texto `NÃO LOCALIZADO NO SAPIENS` está reservado a ocorrências judiciais efetivamente sem correspondência após o cruzamento, mantendo os prazos originais.
