# MRX — Otimizador de Corte Industrial v2.0

Sistema desktop para otimização de corte de bobinas jumbo em bobinas menores, resolvento o problema clássico de *One-Dimensional Cutting Stock Problem* com regras de refile industrial.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![customtkinter](https://img.shields.io/badge/GUI-customtkinter-green)

## Funcionalidades

- **Otimização automática** com busca exaustiva de padrões repetíveis
- **Duas faixas de refile**: Primária (10–15mm/lado) e Secundária (15–25mm/lado)
- **Janela de Sobras** interativa para tratamento manual de residuais
- **Persistência SQLite** — histórico de puxadas salvas automaticamente
- **Exportação para Excel** (.xlsx) — cada puxada em uma coluna com bobinas empilhadas
- **Visualização gráfica** da puxada com canvas (eixos, refiles e posições)
- **Botão Desfazer** — remove a última bobina adicionada antes de gerar o plano

## Estrutura do Projeto

```
projeto_mrx/
├── mrx_otimizador.py          # Ponto de entrada
├── .gitignore
└── src/
    ├── __init__.py
    ├── models.py              # Bobina, Jumbo, Puxada, SlotNaRegua
    ├── policy.py              # RefilePolicy (F1/F2)
    ├── helpers.py             # Funções auxiliares (layouts, formatação)
    ├── knapsack.py            # Resolver de mochila para residuais
    ├── optimizer.py           # Motor de otimização
    ├── database.py            # Persistência SQLite
    ├── app.py                 # AppMRX — interface principal
    └── ui/
        ├── __init__.py
        ├── report.py          # Renderizador do relatório em texto
        ├── canvas_viz.py      # Desenho da puxada na Canvas
        └── sobras_window.py   # Janela de Sobras
```

## Instalação

```bash
pip install customtkinter openpyxl
```

## Uso

```bash
python mrx_otimizador.py
```

1. Defina a largura do **Jumbo** (padrão: 1565mm)
2. Adicione bobinas com **largura** e **quantidade**
3. Clique em **GERAR PLANO DE PRODUÇÃO**
4. Trate as sobras na janela interativa (se necessário)
5. Exporte para Excel com **Exportar Planilha**

## Requisitos

- Python 3.10+
- `customtkinter`
- `openpyxl`
- `tkinter` (vem com Python)

## Fluxo de Otimização

1. **Fase 1** — Busca exaustiva por padrões repetíveis: esgota Faixa Primária → depois Secundária
2. **Fase 2** — Residuais: mochila para máxima ocupação; sobra ≤ 50mm gera puxada automática, > 50mm abre janela manual

## Licença

Proprietário — Todos os direitos reservados.
