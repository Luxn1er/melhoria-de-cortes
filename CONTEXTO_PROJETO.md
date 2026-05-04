# Contexto do Projeto MRX Otimizador

## Visao geral

O MRX Otimizador e uma aplicacao desktop em Python para otimizar cortes de bobinas jumbo em bobinas menores. O sistema resolve um problema de corte unidimensional, respeitando regras industriais de refile, limite de facas, status de producao e tratamento de sobras.

O usuario informa:

- largura do jumbo, em mm;
- medida inicial da regua traseira da maquina, em mm;
- bobinas desejadas, com largura e quantidade;
- opcionalmente, uma lista colada em lote via Importar Puxadas/Planilhas.

Depois disso, o sistema gera um plano de producao com puxadas, repeticoes, refiles, status, sobras, visualizacao grafica, tabela de facas e exportacao para Excel.

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
  app.py                 Interface principal, estado do app, processamento, status e exportacao
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
tests/
  test_refile_balance.py       Regressao do refile centralizado e facas
  test_puxada_status_reuso.py  Regressao de reutilizacao por status
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
9. O usuario pode selecionar uma puxada e alterar o status.
10. O usuario pode exportar para Excel.

## Importar Puxadas / Planilhas

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

## Status das puxadas

Cada puxada possui um status:

```text
planejado
em_producao
finalizado
```

Labels exibidas na interface:

- `Planejado`: puxada ainda nao iniciada; pode ser reutilizada em uma nova geracao.
- `Em producao`: puxada ja iniciou na maquina; fica travada.
- `Finalizado`: puxada concluida; fica travada.

Regra de reprocessamento:

- ao gerar novamente, o sistema preserva as puxadas `em_producao` e `finalizado`;
- puxadas `planejado` voltam para o estoque de geracao;
- materiais novos adicionados entram junto com esse estoque livre;
- o otimizador recalcula apenas o que ainda pode mudar.

O status aparece:

- no seletor de puxada;
- no relatorio textual;
- na visualizacao grafica;
- na exportacao Excel;
- no historico SQLite (`puxada_linha.status`).

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
Med. inicial: 778
Refile esquerdo: 22
Bobinas: 331, 331, 331, 331, 197
```

Resultado:

```text
756, 425, 94, -237, -568
Refile direito: -765
Total de corte: 1521
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

O sistema testa padroes por alvo de corte. O limite de seguranca e:

```python
COMPOSICOES_MAX_POR_ALVO = 50_000
```

Como os refiles geram varios alvos:

- F1: refile total de 20 a 30mm, ate 11 alvos;
- F2: refile total de 31 a 50mm, ate 20 alvos.

Teto teorico por ciclo de busca:

```text
F1: 11 x 50.000 = 550.000 tentativas
F2: 20 x 50.000 = 1.000.000 tentativas
Total: ate 1.550.000 tentativas por ciclo
```

Na pratica costuma testar menos, porque o DFS corta combinacoes impossiveis por largura, resto minimo e limite de facas.

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

O refile agora e repartido de forma mais centralizada. Exemplo:

```text
Sobra total: 44mm
Antes: 19mm + 25mm
Agora: 22mm + 22mm
```

Esse ajuste alinha as posicoes das facas com a planilha antiga usada na operacao.

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

Quando rodando pelo executavel, a pasta `ProducaoAlt` fica ao lado do `.exe`.

Tabelas:

- `estoque`
- `puxada_execucao`
- `puxada_linha`

Campo importante adicionado:

```text
puxada_linha.status
```

O estoque e salvo automaticamente conforme o usuario adiciona, importa, desfaz, limpa ou gera puxadas. O banco local e ignorado pelo Git para nao subir dados de uso.

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

O cabecalho exportado inclui repeticao e status da puxada.

## Visualizacao

Arquivo:

```text
src/ui/canvas_viz.py
```

Mostra graficamente:

- largura do jumbo;
- refile esquerdo e direito;
- bobinas no eixo superior/inferior;
- cor da faixa de refile;
- status da puxada selecionada.

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
pip install customtkinter openpyxl pyinstaller
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

Tambem foi gerado:

```text
dist/MRX_Otimizador.exe
dist/MRX_Otimizador_Portatil.zip
```

O executavel foi commitado no GitHub no commit:

```text
42f1e82 - Adicionar controle de status e executavel
```

## Validacao feita

Comandos de validacao usados:

```bash
python -m unittest discover tests
python -m compileall src mrx_otimizador.py
```

Testes automatizados existentes:

- `tests/test_refile_balance.py`
- `tests/test_puxada_status_reuso.py`

## Teste de estresse

Foi feito teste de estresse diretamente no motor de otimizacao, sem abrir a interface.

Resultado pratico observado:

- ate 20 medidas diferentes / 1000 bobinas: cerca de 1s;
- 40 medidas diferentes / 2000 bobinas: cerca de 8,5s;
- 50 medidas diferentes / 2500 bobinas: cerca de 22s;
- 80 a 100 medidas diferentes: pode passar de 12 a 15s;
- 150 medidas diferentes x1: passou de 20s.

Quantidade alta de bobinas iguais:

- se a medida fecha padrao repetivel, aguenta quantidade enorme;
- exemplo testado: `309mm x 1.000.000` rodou praticamente instantaneo;
- se a medida nao fecha padrao e vira sobra, o tempo cresce com a quantidade;
- exemplo testado: `331mm x 50.000` levou cerca de 5,7s.

Conclusao:

- o gargalo principal nao e a quantidade total de bobinas;
- o que pesa e a quantidade de larguras diferentes tentando combinar no jumbo;
- uso recomendado: ate 40 medidas diferentes com milhares de bobinas roda bem;
- 50 medidas diferentes ainda funciona, mas pode demorar;
- acima de 80 medidas diferentes depende bastante das medidas.

## GitHub

Repositorio remoto:

```text
https://github.com/Luxn1er/melhoria-de-cortes
```

Branch usada:

```text
master
```

Ultimo push relevante:

```text
42f1e82 - Adicionar controle de status e executavel
```

## Pontos de atencao

- O projeto possui artefatos de build (`build`, `dist`, `.exe`) na pasta.
- `build/`, bancos SQLite locais e planilhas exportadas sao ignorados pelo Git.
- `dist/MRX_Otimizador.exe` e `dist/MRX_Otimizador_Portatil.zip` foram adicionados ao Git por pedido do usuario.
- O texto com acentos pode aparecer quebrado dependendo do encoding do terminal.
- O limite de facas e 23 e foi respeitado nos testes de estresse.
