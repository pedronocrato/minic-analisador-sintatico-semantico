"""Analisador léxico, sintático e semântico da MiniC v2 — Etapa 3.

Aspectos Teóricos da Computação — UNIFOR — Pedro Roberto Nocrato Meira (2410358)

Requer Python 3.8+ e o gerador PLY (equivalente a JFlex + JCup):  pip install ply

Uso:
    python minic.py programa.mc              árvore sintática, tabela de símbolos e erros
    python minic.py --testes                 roda os programas de teste válidos e inválidos
    python minic.py --testes v04_expressoes  mostra a saída completa de um caso de teste

Códigos de erro reportados (sempre com linha:coluna):
    L01 caractere inválido     L02 string não terminada     L03 comentário não terminado
    S01 token inesperado       S02 fim de arquivo inesperado
    E01 não declarado          E02 redeclaração no escopo   E03 atribuição incompatível
    E04 operandos inválidos    E05 condição não booleana    E06 indexação inválida
    E07 nº de argumentos       E08 tipo de argumento        E09 retorno incompatível
    E10 função usada como variável (ou o contrário)

Organização do arquivo:
    1. Especificação léxica  (ply.lex  — papel do arquivo .flex)
    2. Especificação sintática e nós da AST  (ply.yacc, LALR(1) — papel do arquivo .cup)
    3. Tabela de símbolos e análise semântica
    4. Programa principal
    5. Testes
"""
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import ply.lex as lex
import ply.yacc as yacc


# #########################################################################
# 1. ESPECIFICAÇÃO LÉXICA (ply.lex)
# #########################################################################
@dataclass
class Diagnostico:
    """Erro léxico, sintático ou semântico, com a posição no código-fonte."""
    fase: str       # "léxico", "sintático" ou "semântico"
    codigo: str
    linha: int
    coluna: int
    mensagem: str

    def __str__(self):
        return f"{self.linha:>3}:{self.coluna:<3} erro {self.fase} [{self.codigo}] {self.mensagem}"


reservadas = {
    "int": "INT", "float": "FLOAT", "bool": "BOOL", "void": "VOID",
    "if": "IF", "else": "ELSE", "while": "WHILE", "for": "FOR",
    "return": "RETURN", "func": "FUNC", "print": "PRINT",
    "true": "TRUE", "false": "FALSE",
}

tokens = [
    "ID", "NUM_INT", "NUM_REAL", "STRING",
    "MAIS", "MENOS", "VEZES", "DIVIDE", "MOD",
    "ATRIB", "IGUAL", "DIFERENTE", "MENOR", "MENOR_IGUAL", "MAIOR", "MAIOR_IGUAL",
    "E", "OU", "NAO",
    "ABRE_PAR", "FECHA_PAR", "ABRE_COL", "FECHA_COL", "ABRE_CHAVE", "FECHA_CHAVE",
    "PONTO_VIRGULA", "VIRGULA", "DOIS_PONTOS",
] + sorted(set(reservadas.values()))

# Operadores de dois caracteres: o ply.lex ordena as regras-string pelo
# tamanho da expressão (decrescente), então "<=" é testado antes de "<".
t_IGUAL = r"=="
t_DIFERENTE = r"!="
t_MENOR_IGUAL = r"<="
t_MAIOR_IGUAL = r">="
t_E = r"&&"
t_OU = r"\|\|"
t_MAIS = r"\+"
t_MENOS = r"-"
t_VEZES = r"\*"
t_DIVIDE = r"/"
t_MOD = r"%"
t_ATRIB = r"="
t_MENOR = r"<"
t_MAIOR = r">"
t_NAO = r"!"
t_ABRE_PAR = r"\("
t_FECHA_PAR = r"\)"
t_ABRE_COL = r"\["
t_FECHA_COL = r"\]"
t_ABRE_CHAVE = r"\{"
t_FECHA_CHAVE = r"\}"
t_PONTO_VIRGULA = r";"
t_VIRGULA = r","
t_DOIS_PONTOS = r":"

t_ignore = " \t\r"


def coluna(texto, pos):
    inicio = texto.rfind("\n", 0, pos) + 1
    return pos - inicio + 1


# Regras-função são testadas na ordem em que aparecem no arquivo.
def t_COMENTARIO_BLOCO(t):
    r"/\*(.|\n)*?\*/"
    t.lexer.lineno += t.value.count("\n")


def t_COMENTARIO_BLOCO_ABERTO(t):
    r"/\*(.|\n)*"
    t.lexer.diagnosticos.append(Diagnostico(
        "léxico", "L03", t.lineno, coluna(t.lexer.lexdata, t.lexpos),
        "comentário de bloco aberto e nunca fechado"))
    t.lexer.lineno += t.value.count("\n")


def t_COMENTARIO_LINHA(t):
    r"//[^\n]*"


def t_NUM_REAL(t):
    r"\d+\.\d+"
    t.value = float(t.value)
    return t


def t_NUM_INT(t):
    r"\d+"
    t.value = int(t.value)
    return t


def t_ID(t):
    r"[A-Za-z_][A-Za-z_0-9]*"
    t.type = reservadas.get(t.value, "ID")
    return t


def t_STRING(t):
    r'"([^"\\\n]|\\.)*"'
    t.value = t.value[1:-1]
    return t


def t_STRING_ABERTA(t):
    r'"([^"\\\n]|\\.)*'
    t.lexer.diagnosticos.append(Diagnostico(
        "léxico", "L02", t.lineno, coluna(t.lexer.lexdata, t.lexpos),
        "string sem aspas de fechamento antes do fim da linha"))


def t_nova_linha(t):
    r"\n+"
    t.lexer.lineno += len(t.value)


def t_error(t):
    c = t.value[0]
    t.lexer.diagnosticos.append(Diagnostico(
        "léxico", "L01", t.lineno, coluna(t.lexer.lexdata, t.lexpos),
        f"caractere inválido {c!r}"))
    t.lexer.skip(1)


def criar_lexer():
    lexer = lex.lex(optimize=False, module=sys.modules[__name__])
    lexer.diagnosticos = []
    return lexer


# #########################################################################
# 2. ESPECIFICAÇÃO SINTÁTICA (ply.yacc, LALR(1)) E NÓS DA AST
# #########################################################################
# Cada função p_* traz na docstring as produções da gramática e, no corpo,
# a ação que monta o nó correspondente da árvore sintática.

# =========================================================== nós da AST
# Cada nó guarda linha e coluna; rotulo() e filhos() servem para imprimir a árvore.
@dataclass
class No:
    linha: int
    coluna: int

    def rotulo(self):
        return type(self).__name__

    def filhos(self):
        return []


# ---------------------------------------------------------------- declarações
@dataclass
class Programa(No):
    decls: List[No] = field(default_factory=list)

    def filhos(self):
        return self.decls


@dataclass
class ItemVar(No):
    nome: str = ""
    dims: List[int] = field(default_factory=list)
    init: Optional[No] = None

    def rotulo(self):
        return f"Var {self.nome}" + "".join(f"[{d}]" for d in self.dims)

    def filhos(self):
        return [self.init] if self.init else []


@dataclass
class DeclVar(No):
    tipo: str = ""
    itens: List[ItemVar] = field(default_factory=list)

    def rotulo(self):
        return f"DeclVar {self.tipo}"

    def filhos(self):
        return self.itens


@dataclass
class Param(No):
    tipo: str = ""
    nome: str = ""
    dims: List[int] = field(default_factory=list)

    def rotulo(self):
        return f"Param {self.tipo} {self.nome}" + "".join(f"[{d}]" for d in self.dims)


@dataclass
class DeclFunc(No):
    nome: str = ""
    params: List[Param] = field(default_factory=list)
    tipo_ret: str = "void"
    corpo: "Bloco" = None

    def rotulo(self):
        return f"Func {self.nome} : {self.tipo_ret}"

    def filhos(self):
        return list(self.params) + [self.corpo]


# ------------------------------------------------------------------ comandos
@dataclass
class Bloco(No):
    cmds: List[No] = field(default_factory=list)

    def filhos(self):
        return self.cmds


@dataclass
class Atrib(No):
    alvo: No = None
    expr: No = None

    def rotulo(self):
        return "Atrib ="

    def filhos(self):
        return [self.alvo, self.expr]


@dataclass
class Se(No):
    cond: No = None
    entao: No = None
    senao: Optional[No] = None

    def rotulo(self):
        return "If"

    def filhos(self):
        return [self.cond, self.entao] + ([self.senao] if self.senao else [])


@dataclass
class Enquanto(No):
    cond: No = None
    corpo: No = None

    def rotulo(self):
        return "While"

    def filhos(self):
        return [self.cond, self.corpo]


@dataclass
class Para(No):
    init: Optional[No] = None
    cond: No = None
    passo: Optional[No] = None
    corpo: No = None

    def rotulo(self):
        return "For"

    def filhos(self):
        return [x for x in (self.init, self.cond, self.passo, self.corpo) if x]


@dataclass
class Retorno(No):
    expr: Optional[No] = None

    def rotulo(self):
        return "Return"

    def filhos(self):
        return [self.expr] if self.expr else []


@dataclass
class Imprime(No):
    args: List[No] = field(default_factory=list)

    def rotulo(self):
        return "Print"

    def filhos(self):
        return self.args


@dataclass
class ErroSintatico(No):
    """Marca o trecho descartado pela recuperação de erro do parser."""

    def rotulo(self):
        return "<erro sintático>"


# --------------------------------------------------------------- expressões
@dataclass
class Literal(No):
    tipo: str = ""
    valor: object = None

    def rotulo(self):
        if self.tipo == "string":
            return f'Lit string "{self.valor}"'
        if self.tipo == "bool":
            return f"Lit bool {'true' if self.valor else 'false'}"
        return f"Lit {self.tipo} {self.valor}"


@dataclass
class Var(No):
    nome: str = ""

    def rotulo(self):
        return f"Id {self.nome}"


@dataclass
class Indice(No):
    base: No = None
    indice: No = None

    def rotulo(self):
        return "Index []"

    def filhos(self):
        return [self.base, self.indice]


@dataclass
class Chamada(No):
    nome: str = ""
    args: List[No] = field(default_factory=list)

    def rotulo(self):
        return f"Call {self.nome}()"

    def filhos(self):
        return self.args


@dataclass
class Binaria(No):
    op: str = ""
    esq: No = None
    dir: No = None

    def rotulo(self):
        return f"BinOp {self.op}"

    def filhos(self):
        return [self.esq, self.dir]


@dataclass
class Unaria(No):
    op: str = ""
    expr: No = None

    def rotulo(self):
        return f"UnOp {self.op}"

    def filhos(self):
        return [self.expr]


def arvore_texto(no):
    linhas = [f"{no.rotulo()}  ({no.linha}:{no.coluna})"]

    def rec(n, prefixo):
        fs = n.filhos()
        for i, f in enumerate(fs):
            ultimo = i == len(fs) - 1
            linhas.append(f"{prefixo}{'└── ' if ultimo else '├── '}{f.rotulo()}  ({f.linha}:{f.coluna})")
            rec(f, prefixo + ("    " if ultimo else "│   "))

    rec(no, "")
    return "\n".join(linhas)


# ============================================================== gramática
# Produções em BNF nas docstrings das funções p_* (formato exigido pelo yacc).

# Único uso de precedência: resolver o "else pendurado" (dangling else).
# A regra do if sem else recebe a precedência SEM_ELSE, menor que a de ELSE;
# no conflito shift/reduce o yacc escolhe o shift, ligando o else ao if mais
# interno. As demais precedências estão codificadas na própria gramática.
precedence = (
    ("nonassoc", "SEM_ELSE"),
    ("nonassoc", "ELSE"),
)

start = "programa"


def pos(p, i):
    return p.lineno(i), coluna(p.lexer.lexdata, p.lexpos(i))


# ------------------------------------------------------------------ programa
def p_programa(p):
    "programa : lista_decl"
    p[0] = Programa(1, 1, p[1])


def p_lista_decl(p):
    """lista_decl : lista_decl decl
                  | decl"""
    p[0] = p[1] + [p[2]] if len(p) == 3 else [p[1]]


def p_decl(p):
    """decl : decl_var
            | decl_func"""
    p[0] = p[1]


def p_decl_erro(p):
    "decl : error PONTO_VIRGULA"
    p[0] = ErroSintatico(*pos(p, 2))


# --------------------------------------------------------- declaração de var
def p_tipo(p):
    """tipo : INT
            | FLOAT
            | BOOL"""
    p[0] = (p[1], *pos(p, 1))


def p_decl_var(p):
    "decl_var : tipo lista_itens PONTO_VIRGULA"
    nome, l, c = p[1]
    p[0] = DeclVar(l, c, nome, p[2])


def p_lista_itens(p):
    """lista_itens : lista_itens VIRGULA item
                   | item"""
    p[0] = p[1] + [p[3]] if len(p) == 4 else [p[1]]


def p_item(p):
    """item : ID dims
            | ID dims ATRIB expr"""
    l, c = pos(p, 1)
    p[0] = ItemVar(l, c, p[1], p[2], p[4] if len(p) == 5 else None)


def p_dims(p):
    """dims : dims ABRE_COL NUM_INT FECHA_COL
            | vazio"""
    p[0] = p[1] + [p[3]] if len(p) == 5 else []


def p_vazio(p):
    "vazio :"
    p[0] = None


# ------------------------------------------------------- declaração de func
def p_decl_func(p):
    "decl_func : FUNC ID ABRE_PAR params FECHA_PAR retorno bloco"
    l, c = pos(p, 2)
    p[0] = DeclFunc(l, c, p[2], p[4], p[6], p[7])


def p_retorno(p):
    """retorno : DOIS_PONTOS tipo
               | DOIS_PONTOS VOID
               | vazio"""
    if len(p) == 2:
        p[0] = "void"
    else:
        p[0] = p[2][0] if isinstance(p[2], tuple) else "void"


def p_params(p):
    """params : lista_params
              | vazio"""
    p[0] = p[1] or []


def p_lista_params(p):
    """lista_params : lista_params VIRGULA param
                    | param"""
    p[0] = p[1] + [p[3]] if len(p) == 4 else [p[1]]


def p_param(p):
    "param : tipo ID dims"
    nome_tipo, l, c = p[1]
    p[0] = Param(*pos(p, 2), nome_tipo, p[2], p[3])


# ----------------------------------------------------------------- comandos
def p_bloco(p):
    "bloco : ABRE_CHAVE lista_cmd FECHA_CHAVE"
    p[0] = Bloco(*pos(p, 1), p[2])


def p_lista_cmd(p):
    """lista_cmd : lista_cmd cmd
                 | vazio"""
    p[0] = p[1] + [p[2]] if len(p) == 3 else []


def p_cmd_simples(p):
    """cmd : decl_var
           | bloco
           | cmd_if
           | cmd_while
           | cmd_for
           | cmd_return
           | cmd_print"""
    p[0] = p[1]


def p_cmd_atrib(p):
    """cmd : atrib PONTO_VIRGULA
           | chamada PONTO_VIRGULA"""
    p[0] = p[1]


def p_cmd_erro(p):
    "cmd : error PONTO_VIRGULA"
    p[0] = ErroSintatico(*pos(p, 2))


def p_atrib(p):
    "atrib : lval ATRIB expr"
    p[0] = Atrib(p[1].linha, p[1].coluna, p[1], p[3])


def p_lval_id(p):
    "lval : ID"
    p[0] = Var(*pos(p, 1), p[1])


def p_lval_indice(p):
    "lval : lval ABRE_COL expr FECHA_COL"
    p[0] = Indice(p[1].linha, p[1].coluna, p[1], p[3])


def p_if(p):
    "cmd_if : IF ABRE_PAR expr FECHA_PAR cmd %prec SEM_ELSE"
    p[0] = Se(*pos(p, 1), p[3], p[5])


def p_if_else(p):
    "cmd_if : IF ABRE_PAR expr FECHA_PAR cmd ELSE cmd"
    p[0] = Se(*pos(p, 1), p[3], p[5], p[7])


def p_while(p):
    "cmd_while : WHILE ABRE_PAR expr FECHA_PAR cmd"
    p[0] = Enquanto(*pos(p, 1), p[3], p[5])


def p_for(p):
    "cmd_for : FOR ABRE_PAR for_init PONTO_VIRGULA expr PONTO_VIRGULA for_passo FECHA_PAR cmd"
    p[0] = Para(*pos(p, 1), p[3], p[5], p[7], p[9])


def p_for_init_decl(p):
    "for_init : tipo ID ATRIB expr"
    nome_tipo, l, c = p[1]
    p[0] = DeclVar(l, c, nome_tipo, [ItemVar(*pos(p, 2), p[2], [], p[4])])


def p_for_init(p):
    """for_init : atrib
                | vazio"""
    p[0] = p[1]


def p_for_passo(p):
    """for_passo : atrib
                 | vazio"""
    p[0] = p[1]


def p_return(p):
    """cmd_return : RETURN expr PONTO_VIRGULA
                  | RETURN PONTO_VIRGULA"""
    p[0] = Retorno(*pos(p, 1), p[2] if len(p) == 4 else None)


def p_print(p):
    "cmd_print : PRINT ABRE_PAR args FECHA_PAR PONTO_VIRGULA"
    p[0] = Imprime(*pos(p, 1), p[3])


def p_chamada(p):
    "chamada : ID ABRE_PAR args FECHA_PAR"
    p[0] = Chamada(*pos(p, 1), p[1], p[3])


def p_args(p):
    """args : lista_args
            | vazio"""
    p[0] = p[1] or []


def p_lista_args(p):
    """lista_args : lista_args VIRGULA expr
                  | expr"""
    p[0] = p[1] + [p[3]] if len(p) == 4 else [p[1]]


# --------------------------------------------------------------- expressões
# Um nível da gramática por nível de precedência (do menor para o maior):
# ||  <  &&  <  == !=  <  < <= > >=  <  + -  <  * / %  <  unários ! -
def _binaria(p):
    """Monta o nó do operador binário; com um só símbolo, apenas repassa o filho."""
    return Binaria(*pos(p, 2), p[2], p[1], p[3]) if len(p) == 4 else p[1]


def p_expr(p):
    """expr : expr OU e_and
            | e_and"""
    p[0] = _binaria(p)


def p_e_and(p):
    """e_and : e_and E e_ig
             | e_ig"""
    p[0] = _binaria(p)


def p_e_ig(p):
    """e_ig : e_ig IGUAL e_rel
            | e_ig DIFERENTE e_rel
            | e_rel"""
    p[0] = _binaria(p)


def p_e_rel(p):
    """e_rel : e_ad MENOR e_ad
             | e_ad MENOR_IGUAL e_ad
             | e_ad MAIOR e_ad
             | e_ad MAIOR_IGUAL e_ad
             | e_ad"""
    p[0] = _binaria(p)


def p_e_ad(p):
    """e_ad : e_ad MAIS e_mul
            | e_ad MENOS e_mul
            | e_mul"""
    p[0] = _binaria(p)


def p_e_mul(p):
    """e_mul : e_mul VEZES e_un
             | e_mul DIVIDE e_un
             | e_mul MOD e_un
             | e_un"""
    p[0] = _binaria(p)


def p_e_un(p):
    """e_un : NAO e_un
            | MENOS e_un
            | prim"""
    if len(p) == 3:
        p[0] = Unaria(*pos(p, 1), p[1], p[2])
    else:
        p[0] = p[1]


def p_prim_int(p):
    "prim : NUM_INT"
    p[0] = Literal(*pos(p, 1), "int", p[1])


def p_prim_real(p):
    "prim : NUM_REAL"
    p[0] = Literal(*pos(p, 1), "float", p[1])


def p_prim_string(p):
    "prim : STRING"
    p[0] = Literal(*pos(p, 1), "string", p[1])


def p_prim_bool(p):
    """prim : TRUE
            | FALSE"""
    p[0] = Literal(*pos(p, 1), "bool", p[1] == "true")


def p_prim(p):
    """prim : lval
            | chamada"""
    p[0] = p[1]


def p_prim_par(p):
    "prim : ABRE_PAR expr FECHA_PAR"
    p[0] = p[2]


# ----------------------------------------------------------- erro sintático
def p_error(t):
    diags = _estado["diagnosticos"]
    if t is None:
        linhas = _estado["texto"].split("\n")
        diags.append(Diagnostico("sintático", "S02", len(linhas), len(linhas[-1]) + 1,
                                 "fim de arquivo inesperado (falta fechar algum bloco ou comando?)"))
    else:
        diags.append(Diagnostico("sintático", "S01", t.lineno, coluna(t.lexer.lexdata, t.lexpos),
                                 f"token inesperado '{t.value}'"))


_estado = {}


def construir_parser():
    return yacc.yacc(debug=False, write_tables=False, errorlog=yacc.NullLogger(),
                     module=sys.modules[__name__])


def analisar(texto):
    """Executa léxico + sintático. Retorna (AST ou None, diagnósticos léxicos, diagnósticos sintáticos)."""
    lexer = criar_lexer()
    parser = construir_parser()
    sint = []
    _estado.update(diagnosticos=sint, texto=texto)
    arvore = parser.parse(texto, lexer=lexer, tracking=True)
    return arvore, lexer.diagnosticos, sint


# #########################################################################
# 3. TABELA DE SÍMBOLOS E ANÁLISE SEMÂNTICA
# #########################################################################
# A análise semântica percorre a AST em duas passadas: (1) registra a
# assinatura de todas as funções, o que permite chamar uma função antes da
# sua definição; (2) percorre declarações e comandos na ordem do texto,
# abrindo e fechando escopos e verificando declarações, tipos e chamadas.
# Tipos são pares (base, dims): ("int", ()) é inteiro, ("float", (3, 3)) é
# uma matriz 3x3. O tipo "erro" evita erros em cascata.

# ===================================================== tabela de símbolos
# Pilha de escopos: cada escopo é um dicionário nome -> Simbolo com ponteiro
# para o pai. A busca sobe do escopo atual até o global. Ao fechar, o escopo
# sai da pilha mas fica no histórico, para a tabela completa ser exibida.
@dataclass
class Simbolo:
    nome: str
    categoria: str              # "variável", "parâmetro" ou "função"
    tipo: str                   # int, float, bool (para função: tipo de retorno)
    dims: List[int]
    escopo: str
    nivel: int
    linha: int
    coluna: int
    params: Optional[list] = None   # só para funções: lista de (tipo, dims)

    def tipo_completo(self):
        if self.categoria == "função":
            ps = ", ".join(t + "".join(f"[{d}]" for d in ds) for t, ds in self.params)
            return f"({ps}) -> {self.tipo}"
        return self.tipo + "".join(f"[{d}]" for d in self.dims)


@dataclass
class Escopo:
    nome: str
    nivel: int
    pai: Optional["Escopo"]
    simbolos: Dict[str, Simbolo] = field(default_factory=dict)


class TabelaSimbolos:
    def __init__(self):
        self.global_ = Escopo("global", 0, None)
        self.atual = self.global_
        self.historico = [self.global_]

    def abrir(self, nome):
        self.atual = Escopo(nome, self.atual.nivel + 1, self.atual)
        self.historico.append(self.atual)

    def fechar(self):
        self.atual = self.atual.pai

    def declarar(self, simbolo):
        """Insere no escopo atual. Retorna o símbolo já existente em caso de conflito."""
        existente = self.atual.simbolos.get(simbolo.nome)
        if existente:
            return existente
        simbolo.escopo, simbolo.nivel = self.atual.nome, self.atual.nivel
        self.atual.simbolos[simbolo.nome] = simbolo
        return None

    def buscar(self, nome):
        e = self.atual
        while e:
            if nome in e.simbolos:
                return e.simbolos[nome]
            e = e.pai
        return None

    def todos(self):
        for e in self.historico:
            yield from e.simbolos.values()

    def formatar(self):
        cab = ["Escopo", "Nív", "Nome", "Categoria", "Tipo", "Decl."]
        linhas = [[s.escopo, str(s.nivel), s.nome, s.categoria, s.tipo_completo(),
                   f"{s.linha}:{s.coluna}"] for s in self.todos()]
        if not linhas:
            return "(tabela vazia)"
        larg = [max(len(x) for x in col) for col in zip(cab, *linhas)]
        sep = "+" + "+".join("-" * (w + 2) for w in larg) + "+"

        def fmt(r):
            return "| " + " | ".join(x.ljust(w) for x, w in zip(r, larg)) + " |"

        return "\n".join([sep, fmt(cab), sep] + [fmt(r) for r in linhas] + [sep])


# ===================================================== análise semântica
ERRO = ("erro", ())
NUMERICOS = ("int", "float")


def nome_tipo(t):
    base, dims = t
    return base + "".join(f"[{d}]" for d in dims)


def compativel(destino, origem):
    """Regra de atribuição: tipos iguais, ou int alargado para float."""
    if destino[0] == "erro" or origem[0] == "erro":
        return True
    if destino == origem:
        return True
    return destino == ("float", ()) and origem == ("int", ())


class AnalisadorSemantico:
    def __init__(self):
        self.tabela = TabelaSimbolos()
        self.diagnosticos = []
        self.funcao = None              # símbolo da função sendo analisada
        self.nao_declarados = set()     # (função, nome) já reportados como E01

    # ------------------------------------------------------------ utilidades
    def erro(self, no, codigo, msg):
        self.diagnosticos.append(Diagnostico("semântico", codigo, no.linha, no.coluna, msg))

    def analisar(self, programa):
        for d in programa.decls:
            if isinstance(d, DeclFunc):
                self.registrar_funcao(d)
        for d in programa.decls:
            self.visitar(d)
        self.diagnosticos.sort(key=lambda d: (d.linha, d.coluna))
        return self.diagnosticos

    def visitar(self, no):
        if no is None:
            return None
        return getattr(self, "v_" + type(no).__name__)(no)

    # ---------------------------------------------------------- declarações
    def registrar_funcao(self, f):
        params = [(p.tipo, tuple(p.dims)) for p in f.params]
        s = Simbolo(f.nome, "função", f.tipo_ret, [], "", 0, f.linha, f.coluna, params)
        existente = self.tabela.declarar(s)
        if existente:
            self.erro(f, "E02", f"função '{f.nome}' já declarada em {existente.linha}:{existente.coluna}")
            f.duplicada = True

    def declarar(self, no, nome, categoria, tipo, dims):
        s = Simbolo(nome, categoria, tipo, list(dims), "", 0, no.linha, no.coluna)
        existente = self.tabela.declarar(s)
        if existente:
            self.erro(no, "E02", f"'{nome}' já declarado neste escopo como {existente.categoria} "
                                 f"em {existente.linha}:{existente.coluna}")
        return s

    def v_Programa(self, no):
        for d in no.decls:
            self.visitar(d)

    def v_ErroSintatico(self, no):
        pass

    def v_DeclVar(self, no):
        for item in no.itens:
            for d in item.dims:
                if d == 0:
                    self.erro(item, "E06", f"array '{item.nome}' com dimensão 0")
            if item.init is not None:
                t = self.visitar(item.init)          # avaliada antes de declarar: 'int x = x;' é erro
                if item.dims:
                    self.erro(item, "E03", f"array '{item.nome}' não pode ser inicializado na declaração")
                elif not compativel((no.tipo, ()), t):
                    self.erro(item.init, "E03", f"não é possível inicializar '{item.nome}' ({no.tipo}) "
                                                f"com valor do tipo {nome_tipo(t)}")
            self.declarar(item, item.nome, "variável", no.tipo, item.dims)

    def v_DeclFunc(self, no):
        if getattr(no, "duplicada", False):
            simbolo = Simbolo(no.nome, "função", no.tipo_ret, [], "", 0, no.linha, no.coluna, [])
        else:
            simbolo = self.tabela.global_.simbolos[no.nome]
        self.funcao = simbolo
        self.tabela.abrir(f"func {no.nome}")
        for p in no.params:
            self.declarar(p, p.nome, "parâmetro", p.tipo, p.dims)
        for c in no.corpo.cmds:      # o corpo compartilha o escopo dos parâmetros
            self.visitar(c)
        self.tabela.fechar()
        self.funcao = None

    # ------------------------------------------------------------- comandos
    def v_Bloco(self, no):
        self.tabela.abrir(f"bloco {no.linha}:{no.coluna}")
        for c in no.cmds:
            self.visitar(c)
        self.tabela.fechar()

    def condicao(self, expr, comando):
        t = self.visitar(expr)
        if t[0] != "erro" and t != ("bool", ()):
            self.erro(expr, "E05", f"condição do {comando} deve ser bool, mas é {nome_tipo(t)}")

    def v_Se(self, no):
        self.condicao(no.cond, "if")
        self.visitar(no.entao)
        self.visitar(no.senao)

    def v_Enquanto(self, no):
        self.condicao(no.cond, "while")
        self.visitar(no.corpo)

    def v_Para(self, no):
        self.tabela.abrir(f"for {no.linha}:{no.coluna}")
        self.visitar(no.init)
        self.condicao(no.cond, "for")
        self.visitar(no.passo)
        self.visitar(no.corpo)
        self.tabela.fechar()

    def v_Atrib(self, no):
        destino = self.visitar(no.alvo)
        origem = self.visitar(no.expr)
        if destino[1] and destino[0] != "erro":
            self.erro(no, "E03", f"não é possível atribuir a um array inteiro ({nome_tipo(destino)})")
        elif not compativel(destino, origem):
            self.erro(no.expr, "E03", f"não é possível atribuir {nome_tipo(origem)} a "
                                      f"variável do tipo {nome_tipo(destino)}")

    def v_Retorno(self, no):
        esperado = self.funcao.tipo
        if no.expr is None:
            if esperado != "void":
                self.erro(no, "E09", f"'{self.funcao.nome}' deve retornar {esperado}")
            return
        t = self.visitar(no.expr)
        if esperado == "void":
            self.erro(no.expr, "E09", f"função void '{self.funcao.nome}' não pode retornar valor")
        elif not compativel((esperado, ()), t):
            self.erro(no.expr, "E09", f"'{self.funcao.nome}' retorna {esperado}, "
                                      f"mas a expressão é {nome_tipo(t)}")

    def v_Imprime(self, no):
        for a in no.args:
            t = self.visitar(a)
            if t[0] != "erro" and (t[1] or t[0] == "void"):
                self.erro(a, "E08", f"print não aceita valor do tipo {nome_tipo(t)}")

    # ----------------------------------------------------------- expressões
    def v_Literal(self, no):
        return (no.tipo, ())

    def v_Var(self, no):
        s = self.tabela.buscar(no.nome)
        if s is None:
            chave = (self.funcao.nome if self.funcao else "", no.nome)
            if chave not in self.nao_declarados:
                self.nao_declarados.add(chave)
                self.erro(no, "E01", f"'{no.nome}' não foi declarado")
            return ERRO
        if s.categoria == "função":
            self.erro(no, "E10", f"'{no.nome}' é uma função e foi usada como variável")
            return ERRO
        return (s.tipo, tuple(s.dims))

    def v_Indice(self, no):
        base = self.visitar(no.base)
        idx = self.visitar(no.indice)
        if idx[0] != "erro" and idx != ("int", ()):
            self.erro(no.indice, "E06", f"índice de array deve ser int, mas é {nome_tipo(idx)}")
        if base[0] == "erro":
            return ERRO
        if not base[1]:
            self.erro(no, "E06", f"valor do tipo {nome_tipo(base)} não é array e não pode ser indexado")
            return ERRO
        return (base[0], base[1][1:])

    def v_Chamada(self, no):
        s = self.tabela.buscar(no.nome)
        tipos = [self.visitar(a) for a in no.args]
        if s is None:
            self.erro(no, "E01", f"função '{no.nome}' não foi declarada")
            return ERRO
        if s.categoria != "função":
            self.erro(no, "E10", f"'{no.nome}' é {s.categoria}, não função, e não pode ser chamado")
            return ERRO
        if len(tipos) != len(s.params):
            self.erro(no, "E07", f"'{no.nome}' espera {len(s.params)} argumento(s), recebeu {len(tipos)}")
        else:
            for i, (arg, t, p) in enumerate(zip(no.args, tipos, s.params), 1):
                if not compativel(p, t):
                    self.erro(arg, "E08", f"argumento {i} de '{no.nome}' deve ser {nome_tipo(p)}, "
                                          f"mas é {nome_tipo(t)}")
        return (s.tipo, ())

    def v_Unaria(self, no):
        t = self.visitar(no.expr)
        if t[0] == "erro":
            return ERRO
        if no.op == "-" and t[0] in NUMERICOS and not t[1]:
            return t
        if no.op == "!" and t == ("bool", ()):
            return t
        self.erro(no, "E04", f"operador unário '{no.op}' não se aplica a {nome_tipo(t)}")
        return ERRO

    def v_Binaria(self, no):
        e = self.visitar(no.esq)
        d = self.visitar(no.dir)
        if e[0] == "erro" or d[0] == "erro":
            return ERRO
        op = no.op
        num = e[0] in NUMERICOS and d[0] in NUMERICOS and not e[1] and not d[1]
        if op in ("+", "-", "*", "/") and num:
            return ("float", ()) if "float" in (e[0], d[0]) else ("int", ())
        if op == "%" and e == d == ("int", ()):
            return ("int", ())
        if op in ("<", "<=", ">", ">=") and num:
            return ("bool", ())
        if op in ("==", "!=") and (num or e == d == ("bool", ())):
            return ("bool", ())
        if op in ("&&", "||") and e == d == ("bool", ()):
            return ("bool", ())
        self.erro(no, "E04", f"operador '{op}' não se aplica a {nome_tipo(e)} e {nome_tipo(d)}")
        return ERRO


# #########################################################################
# 4. PROGRAMA PRINCIPAL
# #########################################################################
def analisar_texto(texto):
    """Executa as três fases e devolve a árvore, a tabela e os diagnósticos."""
    arvore, lex, sint = analisar(texto)
    r = {"arvore": arvore, "tabela": None, "semanticos": [], "sintaticos": sint}
    if arvore is not None and not sint:      # semântica só sobre árvore sem erro sintático
        sem = AnalisadorSemantico()
        r["semanticos"] = sem.analisar(arvore)
        r["tabela"] = sem.tabela
    r["diagnosticos"] = sorted(lex + sint + r["semanticos"], key=lambda d: (d.linha, d.coluna))
    return r


def exibir(texto):
    """Analisa o código-fonte e imprime a árvore, a tabela de símbolos e os erros."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    r = analisar_texto(texto)

    print("== Árvore sintática ==")
    if r["arvore"] is not None and not r["sintaticos"]:
        print(arvore_texto(r["arvore"]))
    else:
        print("(não construída: há erros sintáticos)")

    print("\n== Tabela de símbolos ==")
    print(r["tabela"].formatar() if r["tabela"] else "(não preenchida: há erros sintáticos)")

    print("\n== Erros ==")
    for d in r["diagnosticos"]:
        print(d)
    if not r["diagnosticos"]:
        print("  nenhum erro")
    print("\nResultado:", "ACEITO" if not r["diagnosticos"] else f"REJEITADO ({len(r['diagnosticos'])} erro(s))")
    return 0 if not r["diagnosticos"] else 1


# #########################################################################
# 5. TESTES: programas válidos e inválidos com os erros esperados
# #########################################################################
# Cada caso: (nome, erros esperados como (código, linha, coluna), fonte).
# Um programa válido espera a lista vazia.
CASOS = [
    ("v01_fatorial", [], """\
// Fatorial recursivo e iterativo
func fatorial(int n) : int {
    if (n <= 1) {
        return 1;
    } else {
        return n * fatorial(n - 1);
    }
}

func fatorial_iter(int n) : int {
    int r = 1;
    while (n > 1) {
        r = r * n;
        n = n - 1;
    }
    return r;
}

func main() {
    int x = 5;
    print("fatorial(5) =", fatorial(x), fatorial_iter(x));
}
"""),
    ("v02_matriz", [], """\
/* Soma de matrizes 3x3: arrays, for aninhado e
   conversão implícita de int para float */
func soma(float a[3][3], float b[3][3]) {
    for (int i = 0; i < 3; i = i + 1) {
        for (int j = 0; j < 3; j = j + 1) {
            a[i][j] = a[i][j] + b[i][j];
        }
    }
}

func main() {
    float m[3][3], n[3][3];
    for (int i = 0; i < 3; i = i + 1) {
        for (int j = 0; j < 3; j = j + 1) {
            m[i][j] = i * 3 + j;        // int -> float
            n[i][j] = 0.5;
        }
    }
    soma(m, n);
    print("m[2][2] =", m[2][2]);
}
"""),
    ("v03_escopos", [], """\
// Escopos aninhados, variável global, sombreamento e
// chamada de função antes da sua definição
int limite = 10;

func main() {
    int total = 0;
    bool achou = false;
    int i = 0;
    while (i < limite && !achou) {
        int quadrado = i * i;           // local ao bloco do while
        if (eh_par(quadrado)) {
            total = total + quadrado;
        }
        if (total > 50) achou = true;
        i = i + 1;
    }
    {
        float total = 2.5;              // sombreia o 'total' de main
        print("bloco interno:", total);
    }
    print("total =", total, "achou =", achou);
}

func eh_par(int v) : bool {
    return v % 2 == 0;
}
"""),
    ("v04_expressoes", [], """\
// Precedência e associatividade de operadores
func media(int a, int b, int c) : float {
    return (a + b + c) / 3.0;
}

func main() {
    int a = 2, b = 3, c = 4;
    int r = a + b * c - -a;             // 2 + (3*4) - (-2) = 16
    bool ok = a < b && b < c || !(a == c);
    float m = media(a, b, c);
    if (ok)
        if (m >= 3.0) print("media alta", m);
        else print("media baixa", m);      // else pertence ao if interno
    print(r % 5, r / 2, ok);
}
"""),
    ("i01_erros_lexicos", [('L01', 3, 15), ('S01', 3, 17), ('L02', 4, 11), ('S01', 5, 5), ('L01', 5, 15), ('L03', 7, 1)], """\
func main() {
    int x = 10;
    int y = x @ 2;
    print("texto sem fechar);
    int z = 3 # 4;
}
/* comentário que nunca fecha
"""),
    ("i02_erros_sintaticos", [('S01', 3, 5), ('S01', 4, 15), ('S01', 6, 5), ('S01', 7, 15)], """\
func main() {
    int x = 10
    x = x + 1;
    x = (x * 2;
    print("fim")
    x = 3;
    if (x > 5 {
        print("maior");
    }
}
"""),
    ("i03_bloco_nao_fechado", [('S02', 6, 1)], """\
func loop(int n) {
    while (n > 0) {
        n = n - 1;

}
"""),
    ("i04_declaracoes", [('E02', 3, 9), ('E01', 4, 5), ('E01', 6, 13), ('E01', 10, 5), ('E02', 13, 6)], """\
func main() {
    int x = 1;
    int x = 2;
    y = x + 1;
    print(y);
    int w = w + 1;
    {
        int k = 0;
    }
    k = 5;
}

func main() {
}
"""),
    ("i05_tipos", [('E03', 2, 13), ('E04', 5, 11), ('E03', 6, 9), ('E05', 7, 9), ('E05', 8, 12), ('E04', 9, 11), ('E03', 10, 9), ('E04', 11, 9)], """\
func main() {
    int i = 2.5;
    bool b = true;
    float f = 1;
    i = b + 1;
    b = i;
    if (i) print("i");
    while (f) f = f - 1.0;
    i = f % 2;
    i = "texto";
    b = !i;
}
"""),
    ("i06_arrays", [('E06', 5, 7), ('E06', 6, 5), ('E03', 7, 5), ('E06', 8, 5), ('E06', 9, 9), ('E06', 10, 11)], """\
func main() {
    int v[5];
    int x = 0;
    float r = 1.5;
    v[r] = 1;
    x[0] = 2;
    v = 3;
    v[1][2] = 4;
    int z[0];
    x = v[true];
}
"""),
    ("i07_funcoes", [('E09', 6, 12), ('E07', 14, 13), ('E08', 15, 17), ('E10', 16, 9), ('E10', 17, 9), ('E01', 18, 9), ('E08', 19, 11), ('E08', 21, 15)], """\
func soma(int a, int b) : int {
    return a + b;
}

func nada() {
    return 1;
}

func sinal(int n) : int {
    if (n > 0) return 1; else return 0;
}

func main() {
    int x = soma(1);
    x = soma(1, true);
    x = soma + 1;
    x = x(3);
    x = imprime(2);
    print(nada());
    float f = soma(1, 2);
    x = sinal(f);
}
"""),
]


def rodar_todos():
    falhas = 0
    for nome, esperado, fonte in CASOS:
        r = analisar_texto(fonte)
        obtido = [(d.codigo, d.linha, d.coluna) for d in r["diagnosticos"]]
        ok = obtido == esperado
        falhas += not ok
        tipo = "válido  " if not esperado else "inválido"
        print(f"{'OK   ' if ok else 'FALHA'} {tipo} {nome:<24} {len(obtido)} erro(s)")
        if not ok:
            print(f"      esperado: {esperado}\n      obtido:   {obtido}")
    print(f"\n{len(CASOS) - falhas} de {len(CASOS)} casos passaram")
    return 1 if falhas else 0


def mostrar(nome):
    fonte = next(f for n, _, f in CASOS if n == nome)
    print(fonte)
    return exibir(fonte)


def main(argv):
    if argv[:1] == ["--testes"]:
        return mostrar(argv[1]) if len(argv) > 1 else rodar_todos()
    if len(argv) != 1:
        print(__doc__)
        return 2
    with open(argv[0], encoding="utf-8") as f:
        return exibir(f.read())


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
