# MiniC v2 — Analisador léxico, sintático e semântico

Trabalho da Etapa 3 de Aspectos Teóricos da Computação (UNIFOR).

Analisador da mini-linguagem MiniC v2 feito com PLY (`ply.lex` + `ply.yacc`, LALR(1)),
o equivalente em Python a JFlex + JCup. Ele constrói a árvore sintática, preenche a
tabela de símbolos e reporta erros léxicos, sintáticos e semânticos com linha e coluna.

## Como executar

Requer Python 3.8 ou superior.

```
pip install ply
python minic.py programa.mc              # árvore sintática, tabela de símbolos e erros
python minic.py --testes                 # roda os 11 programas de teste (4 válidos, 7 inválidos)
python minic.py --testes v04_expressoes  # mostra a saída completa de um caso de teste
```

A gramática, as regras semânticas e os exemplos de execução estão no relatório entregue no AVA.
