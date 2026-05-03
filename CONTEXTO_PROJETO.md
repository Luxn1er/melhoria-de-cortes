# Contexto do Projeto MRX Otimizador

## Visao geral

O MRX Otimizador e uma aplicacao desktop em Python para otimizar cortes de bobinas jumbo em bobinas menores. O sistema resolve um problema de corte unidimensional, respeitando regras industriais de refile, limite de facas e tratamento de sobras.

O usuario informa:

- largura do jumbo, em mm;
- medida inicial da regua traseira da maquina, em mm;
- bobinas desejadas, com largura e quantidade;
- opcionalmente, uma lista colada em lote via Importar Puxadas.

Depois disso, o sistema gera um plano de producao com puxadas, repeticoes, refiles, sobras, visualizacao grafica, tabela de facas e exportacao para Excel.

## Tecnologias

- Python 3.10+
- customtkinter para interface desktop
- tkinter Canvas para visualizacao
- SQLite para persistencia local
- openpyxl para exportacao Excel
- PyInstaller para gerar executavel Windows

## Entrada principal

Arquivo:

```text
mrx_otimizador.py
```

Esse arquivo ajusta o `sys.path` para permitir imports de `src` e chama:

```python
from src.app import main
```

## Estrutura principal

```text
src/
  app.py                 Interface principal, estado do app, processamento e exportacao
  optimizer.py           Motor de otimizacao das puxadas
  helpers.py             Funcoes auxiliares, layout, residuais e calculo de facas
  knapsack.py            Mochila para melhor combinacao de sobras
  policy.py              Politica de refiles F1/F2
  models.py              Dataclasses Bobina, Jumbo, Puxada e SlotNaRegua
  database.py            Persistencia SQLite
  ui/
    report.py            Relatorio textual no app
    canvas_viz.py        Visualizacao grafica da puxada
    sobras_window.py     Janela manual para tratamento de sobras
```

## Fluxo do usuario

1. Abre o app.
2. Define o Jumbo, por padrao `1565`.
3. Define a Med. inicial, por padrao `795`.
4. Adiciona bobinas manualmente ou por importacao em lote.
5. Clica em Gerar Plano de Producao.
6. O sistema otimiza as puxadas automaticamente.
7. Se sobra nao couber automaticamente, abre a janela de sobras.
8. O app mostra relatorio, visualizacao da puxada e tabela de facas.
9. O usuario pode exportar para Excel.

## Importar Puxadas

Foi adicionada uma janela chamada Importar Puxadas para o usuario colar varias bobinas de uma vez, copiadas de planilha ou texto.

Formatos aceitos:

```text
1200 3
1200;3
1200x3
3x1200
900
```

Regras:

- uma linha com apenas uma medida vira quantidade 1;
- pares largura/quantidade sao agregados;
- importacao em lote entra no mesmo estoque do botao Adicionar;
- o botao Desfazer remove o lote importado inteiro.

## Medida inicial e facas

Foi adicionada a Med. inicial para calcular onde posicionar as facas na parte traseira da maquina.

Formula:

```text
primeira posicao = medida inicial - refile esquerdo
proximas posicoes = posicao anterior - largura da bobina anterior
```

Exemplo validado:

```text
Jumbo: 1565
Med. inicial: 795
Refile esquerdo: 10
Bobinas: 400, 400, 298, 120, 120, 107, 100
```

Resultado:

```text
785, 385, -15, -313, -433, -553, -660
Refile direito: -760
Total de corte: 1545
```

A tabela de facas aparece:

- no relatorio dentro do app;
- em uma aba nova chamada `Facas` na exportacao Excel.

## Algoritmo de otimizacao

O motor fica em:

```text
src/optimizer.py
```

Ele continua tentando otimizar o plano com:

- menor numero pratico de puxadas;
- maximo possivel de repeticoes por padrao;
- prioridade para refile da faixa primaria;
- fallback para refile da faixa secundaria;
- tratamento inteligente de residuais.

O criterio principal em `_melhor_candidato` e o numero de repeticoes:

```python
score = (reps, -nd, -nb, -re_esq, -re_dir)
```

Prioridades:

1. mais repeticoes;
2. menos larguras distintas;
3. menos bobinas no padrao;
4. menor refile esquerdo;
5. menor refile direito.

## Regras de refile

Arquivo:

```text
src/policy.py
```

Faixa primaria:

```text
10 a 15 mm por lado
20 a 30 mm no total
```

Faixa secundaria:

```text
15 a 25 mm por lado
30 a 50 mm no total
```

O sistema tenta primeiro a faixa primaria. Se nao encontrar padrao, tenta a secundaria.

## Limite de facas

Arquivos:

```text
src/helpers.py
src/knapsack.py
```

O limite atual e:

```python
FACAS_MAX = 23
```

Cada puxada pode ter no maximo 23 bobinas/facas.

## Persistencia

Arquivo:

```text
src/database.py
```

O app cria e usa um SQLite local em:

```text
ProducaoAlt/mrx_otimizador.sqlite3
```

Tabelas:

- `estoque`
- `puxada_execucao`
- `puxada_linha`

O estoque e salvo automaticamente conforme o usuario adiciona, importa, desfaz, limpa ou gera puxadas.

## Exportacao Excel

Arquivo:

```text
src/app.py
```

O app exporta planilhas para:

```text
ProducaoAlt/Puxadas_MRX_YYYYMMDD_HHMMSS.xlsx
```

Abas:

- `Puxadas`: padroes gerados, cada puxada em uma coluna;
- `Facas`: tabela de posicionamento das facas por puxada.

## Visualizacao

Arquivo:

```text
src/ui/canvas_viz.py
```

Mostra graficamente:

- largura do jumbo;
- refile esquerdo e direito;
- bobinas no eixo superior/inferior;
- cor da faixa de refile.

## Janela de sobras

Arquivo:

```text
src/ui/sobras_window.py
```

Quando o otimizador nao consegue fechar automaticamente os residuais, o app abre a janela de sobras para o usuario completar manualmente uma puxada.

Ela permite:

- usar a base automatica sugerida;
- adicionar extras;
- validar se o refile final esta dentro das regras F1/F2;
- salvar a puxada manual no plano;
- reprocessar o estoque restante.

## Como executar

Instalar dependencias:

```bash
pip install customtkinter openpyxl
```

Rodar:

```bash
python mrx_otimizador.py
```

## Como gerar executavel

O projeto possui arquivo PyInstaller:

```text
MRX_Otimizador.spec
```

Comando:

```bash
pyinstaller MRX_Otimizador.spec
```

## Validacao feita

Comando de validacao usado durante as alteracoes:

```bash
python -m compileall src mrx_otimizador.py
```

Esse comando compilou os arquivos Python sem erro.

## Pontos de atencao

- O projeto possui artefatos de build (`build`, `dist`, `.exe`) na pasta.
- Nao existem testes automatizados ainda.
- O texto com acentos pode aparecer quebrado dependendo do encoding do terminal.
- O algoritmo principal nao foi alterado pelas funcoes de importacao e facas; essas mudancas afetam entrada, exibicao e exportacao.

