"""
Verificação dos notebooks.

Não é teste de fumaça: além de conferir que tudo executa, ele refaz as contas do
zero e confronta cada número afirmado no texto com o valor recalculado. É o que
pega o erro que mais aparece num projeto de análise, que é a prosa envelhecer
enquanto o código muda.

    python tests/teste_notebooks.py              # rápido
    python tests/teste_notebooks.py --executar   # inclui rodar os 6 do zero

Cobre cinco frentes: integridade dos arquivos, igualdade da base preparada entre
os notebooks, conferência de cada número afirmado, presença desses números no
texto, e o app, que repete a mesma pipeline.

O modo rápido leva cerca de um minuto. O modo completo leva alguns minutos a
mais, porque o notebook 04 faz busca em grade sobre oito famílias de modelo.
"""

import ast
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
NOTEBOOKS = sorted((RAIZ / "notebooks").glob("0*.ipynb"))
CSV = RAIZ / "data" / "raw" / "habitos_e_desempenho_estudantil.csv"

falhas = []
verificacoes = 0


def checar(condicao, rotulo, detalhe=""):
    """Registra uma verificação e devolve se ela passou."""
    global verificacoes
    verificacoes += 1
    if condicao:
        return True
    falhas.append(f"{rotulo}{(': ' + detalhe) if detalhe else ''}")
    return False


def titulo(texto):
    print(f"\n{texto}")
    print("-" * len(texto))


# ═══════════════════════ 1. Integridade dos arquivos ══════════════════════

def parte_1_integridade():
    titulo("1. Integridade dos notebooks")

    checar(len(NOTEBOOKS) == 6, "quantidade de notebooks", f"achei {len(NOTEBOOKS)}")

    for caminho in NOTEBOOKS:
        nome = caminho.stem
        nb = json.loads(caminho.read_text(encoding="utf-8"))
        codigo = [c for c in nb["cells"] if c["cell_type"] == "code"]
        bruto = json.dumps(nb, ensure_ascii=False)

        erros = [o for c in codigo for o in c.get("outputs", [])
                 if o.get("output_type") == "error"]
        checar(not erros, f"{nome}: saída de erro gravada",
               erros[0].get("ename", "") if erros else "")

        # Célula sem saída significa que o notebook foi salvo sem executar, ou
        # que a execução parou no meio. A exceção é a célula de paleta, que só
        # define constantes e não imprime nada.
        sem_saida = [i for i, c in enumerate(codigo) if not c.get("outputs")]
        checar(len(sem_saida) <= 1, f"{nome}: células sem saída",
               f"{len(sem_saida)} células")

        # Contador fora de ordem indica execução parcial ou fora de sequência,
        # que é como um notebook passa a mostrar resultado de outro estado.
        contadores = [c["execution_count"] for c in codigo]
        checar(contadores == list(range(1, len(codigo) + 1)),
               f"{nome}: contadores de execução em sequência")

        checar("—" not in bruto, f"{nome}: sem travessão")

        # Imagem e link quebrados só aparecem quando alguém abre no GitHub.
        for ref in set(__import__("re").findall(r"\]\(\.\./([\w/.-]+)\)", bruto)):
            checar((RAIZ / ref).exists(), f"{nome}: referência {ref}")
        for ref in set(__import__("re").findall(r"\]\((0\d_[\w]+\.ipynb)\)", bruto)):
            checar((RAIZ / "notebooks" / ref).exists(), f"{nome}: link {ref}")

        print(f"  {nome:28s} {len(codigo):3d} células de código")


# ═════════════════ 2. A base preparada é a mesma em todos ═════════════════

# Constantes de que preparar_dados() depende. No notebook 02 elas estão espalhadas
# por células diferentes da função; nos demais ficam na mesma célula.
DEPENDENCIAS = {"INTEIRAS", "DECIMAIS", "ORDINAIS", "FAIXAS"}


def extrair_preparar_dados(caminho):
    """
    Roda a função preparar_dados() definida dentro de um notebook.

    Extrai por AST em vez de recortar texto: pega só a definição da função e as
    constantes de que ela depende, de qualquer célula. Executar o notebook
    inteiro até ali funcionaria, mas rodaria gráfico e impressão à toa.
    """
    nb = json.loads(caminho.read_text(encoding="utf-8"))
    pedacos = []

    for c in nb["cells"]:
        if c["cell_type"] != "code":
            continue
        fonte = "".join(c["source"])
        try:
            arvore = ast.parse(fonte)
        except SyntaxError:
            continue
        for no in arvore.body:
            if isinstance(no, ast.FunctionDef) and no.name == "preparar_dados":
                pedacos.append(ast.get_source_segment(fonte, no))
            elif isinstance(no, ast.Assign):
                nomes = {a.id for a in no.targets if isinstance(a, ast.Name)}
                if nomes & DEPENDENCIAS:
                    pedacos.append(ast.get_source_segment(fonte, no))

    if not any("def preparar_dados" in p for p in pedacos):
        return None

    ns = {"pd": pd, "np": np, "CSV": CSV}
    exec(compile("\n\n".join(pedacos), str(caminho), "exec"), ns)
    return ns["preparar_dados"](CSV)


def parte_2_base():
    titulo("2. A base preparada é idêntica em todos os notebooks")

    bases = {}
    for caminho in NOTEBOOKS:
        base = extrair_preparar_dados(caminho)
        if base is not None:
            bases[caminho.stem] = base

    checar(len(bases) == 5, "notebooks com preparar_dados()", f"achei {len(bases)}")

    nomes = list(bases)
    referencia = bases[nomes[0]]
    for outro in nomes[1:]:
        igual = referencia.equals(bases[outro])
        checar(igual, f"{outro} devolve a mesma base que {nomes[0]}")
        print(f"  {outro:28s} {'idêntica' if igual else 'DIVERGE'}")

    return referencia


# ═══════════════════ 3. Os números afirmados no texto ═════════════════════

def carregar_cru():
    return pd.read_csv(CSV, dtype=str, na_filter=False)


def parte_3_numeros(base):
    titulo("3. Cada número afirmado bate com o recalculado")

    from sklearn.linear_model import LinearRegression
    from sklearn.metrics import mean_absolute_error
    from sklearn.model_selection import KFold, train_test_split

    cru = carregar_cru()
    y = base["exam_score"]
    dp = y.std()
    MODELO = ["study_hours_per_day", "mental_health_rating", "tempo_tela_total",
              "exercise_frequency", "sleep_hours", "attendance_percentage"]

    X_tr, X_te, y_tr, y_te = train_test_split(base[MODELO], y, test_size=0.2,
                                              random_state=42)
    modelo = LinearRegression().fit(X_tr, y_tr)
    previsto = modelo.predict(X_te)
    desvio = float(np.std(y_te - previsto))

    kf = KFold(n_splits=5, shuffle=True, random_state=42)
    oof = np.empty(len(y))
    for treino, teste in kf.split(base[MODELO]):
        oof[teste] = (LinearRegression()
                      .fit(base[MODELO].iloc[treino], y.iloc[treino])
                      .predict(base[MODELO].iloc[teste]))
    real, prev = (y < 60).to_numpy(), oof < 60

    def parcial(coluna):
        """Correlação entre coluna e nota, descontado o efeito das horas de estudo."""
        x = base["study_hours_per_day"]
        residuo = lambda s: s - np.polyval(np.polyfit(x, s, 1), x)
        return residuo(base[coluna]).corr(residuo(y))

    faixa = pd.cut(base["study_hours_per_day"], [0, 2, 3, 4, np.inf], right=False)
    por_faixa = y.groupby(faixa, observed=True)

    # (rótulo, valor recalculado, valor que o texto afirma, casas de comparação)
    FATOS = [
        ("linhas da base",                     len(base),                        1000, 0),
        ("colunas do CSV cru",                 cru.shape[1],                       16, 0),
        ("células vazias no arquivo",          int((cru == "").sum().sum()),        0, 0),
        ("'None' em parental_education_level", int(cru["parental_education_level"].eq("None").sum()), 91, 0),
        ("notas exatamente 100",               int((y == 100).sum()),              48, 0),
        ("frequências exatamente 100",         int((base["attendance_percentage"] == 100).sum()), 66, 0),
        ("linhas duplicadas",                  int(base.duplicated().sum()),        0, 0),
        ("alunos com gender Other",            int((base["gender"] == "Other").sum()), 42, 0),
        ("alunos abaixo de 60",                int((y < 60).sum()),               280, 0),
        ("r de study_hours_per_day",           base["study_hours_per_day"].corr(y), 0.825, 3),
        ("r de tempo_tela_total",              base["tempo_tela_total"].corr(y),  -0.238, 3),
        ("r de social_media_hours",            base["social_media_hours"].corr(y), -0.167, 3),
        ("r de netflix_hours",                 base["netflix_hours"].corr(y),     -0.172, 3),
        ("parcial de mental_health_rating",    parcial("mental_health_rating"),    0.575, 3),
        ("parcial de tempo_tela_total",        parcial("tempo_tela_total"),       -0.412, 3),
        ("R² em teste",                        modelo.score(X_te, y_te),           0.900, 3),
        ("erro médio em teste",                mean_absolute_error(y_te, previsto), 4.12, 2),
        ("desvio do resíduo",                  desvio,                              5.07, 2),
        ("acurácia do veredito",               (real == prev).mean(),              0.921, 3),
        ("baseline (todos passam)",            1 - real.mean(),                    0.720, 3),
        ("acerto perto do corte",              (real == prev)[np.abs(oof - 60) < desvio].mean(), 0.675, 3),
        ("alunos na zona de incerteza",        int((np.abs(oof - 60) < desvio).sum()), 203, 0),
        ("previsões acima de 100",             int((oof > 100).sum()),              37, 0),
        ("destes com nota real 100",           int((y[oof > 100] == 100).sum()),    32, 0),
        ("previsão média de quem tirou 100",   oof[(y == 100).to_numpy()].mean(),  103.1, 1),
        ("alunos abaixo de 2h de estudo",      int(por_faixa.size().iloc[0]),      133, 0),
        ("destes abaixo de 60",                100 * por_faixa.apply(lambda s: (s < 60).mean()).iloc[0], 93.98, 2),
        ("alunos abaixo de 3h de estudo",      int(por_faixa.size().iloc[:2].sum()), 334, 0),
        ("mediana de tempo de tela",           base["tempo_tela_total"].median(),    4.4, 1),
        ("amplitude por gênero",               _amplitude(base, y, "gender"),       1.28, 2),
        ("amplitude por dieta",                _amplitude(base, y, "diet_quality"), 2.30, 2),
        ("amplitude por saúde mental",         _amplitude(base, y, "mental_health_rating"), 15.6, 1),
        ("amplitude saúde mental em desvios",  _amplitude(base, y, "mental_health_rating") / dp, 0.92, 2),
    ]

    for rotulo, obtido, esperado, casas in FATOS:
        ok = round(float(obtido), casas) == round(float(esperado), casas)
        checar(ok, f"número: {rotulo}",
               f"recalculado {obtido:.{casas}f}, texto afirma {esperado}")
        marca = "ok " if ok else "XX "
        print(f"  {marca}{rotulo:38s} {obtido:>10.{casas}f}")


def _amplitude(base, y, coluna):
    """Distância entre a maior e a menor média de grupo de uma variável."""
    medias = y.groupby(base[coluna], observed=True).mean()
    return medias.max() - medias.min()


# ══════════ 4. O texto cita os números que o código calcula ═══════════════

def parte_4_afirmacoes():
    titulo("4. O texto cita os números que o código calcula")

    # (notebook, trecho que precisa aparecer no markdown). Se um número mudar, a
    # parte 3 acusa o valor novo e esta acusa o texto que ficou para trás.
    AFIRMACOES = [
        ("01_exploracao_inicial",   "91 linhas (9,1%)"),
        ("01_exploracao_inicial",   "48 alunos (4,8%)"),
        ("02_engenharia_de_dados",  "-0,238"),
        ("03_analise_estatistica",  "0,825"),
        ("03_analise_estatistica",  "0,575"),
        ("03_analise_estatistica",  "90,1%"),
        ("03_analise_estatistica",  "68,1%"),
        ("03_analise_estatistica",  "0,072"),
        ("04_aplicacao_pratica",    "0,921"),
        ("04_aplicacao_pratica",    "67,5%"),
        ("04_aplicacao_pratica",    "103,1"),
        ("04_aplicacao_pratica",    "53 configurações"),
        ("05_visualizacao",         "9,6 pontos"),
        ("06_sintese_de_insights",  "94% deles reprovam"),
        ("06_sintese_de_insights",  "4,4 horas"),
        ("06_sintese_de_insights",  "15,6 pontos"),
        ("06_sintese_de_insights",  "0,92 desvio"),
    ]

    textos = {}
    for caminho in NOTEBOOKS:
        nb = json.loads(caminho.read_text(encoding="utf-8"))
        textos[caminho.stem] = " ".join(
            "".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "markdown"
        )

    for nome, trecho in AFIRMACOES:
        presente = trecho in textos.get(nome, "")
        checar(presente, f"texto: {nome} cita {trecho!r}")
        print(f"  {'ok ' if presente else 'XX '}{nome:28s} {trecho!r}")


# ═══════════════════ 5. Execução do zero (opcional) ═══════════════════════

def parte_5_execucao():
    titulo("5. Execução do zero")

    import nbformat
    from nbclient import NotebookClient

    for caminho in NOTEBOOKS:
        nb = nbformat.read(caminho, as_version=4)
        cliente = NotebookClient(nb, timeout=900, kernel_name="python3",
                                 resources={"metadata": {"path": str(caminho.parent)}})
        try:
            cliente.execute()
            print(f"  ok  {caminho.stem}")
            checar(True, f"execução de {caminho.stem}")
        except Exception as erro:
            print(f"  XX  {caminho.stem}")
            checar(False, f"execução de {caminho.stem}", str(erro).splitlines()[-1])


# ═════════════════════ 6. O app consome a mesma base ══════════════════════

def parte_6_app():
    """
    O app repete a pipeline dos notebooks e precisa chegar no mesmo lugar.

    Verifica conteúdo, e não só ausência de exceção: um bug de desempacotamento
    já derrubou uma aba inteira sem que nenhum teste de gráfico isolado
    percebesse, porque renderizar a figura funcionava e o app não.
    """
    titulo("6. O app")

    from streamlit.testing.v1 import AppTest

    app = str(RAIZ / "app.py")

    def abrir(preparar=None):
        at = AppTest.from_file(app, default_timeout=180).run()
        if preparar:
            preparar(at)
        return at

    at = abrir()
    checar(not at.exception, "app: carga inicial",
           str(at.exception[0].value) if at.exception else "")

    # O veredito e as métricas precisam aparecer de fato na página.
    pagina = " ".join(m.value for m in at.markdown)
    checar("Nota prevista" in pagina, "app: cartão de veredito renderizado")
    checar("Triagem de risco acadêmico" in pagina, "app: título renderizado")
    checar("Klubi" not in pagina, "app: sem o nome do cliente na interface")

    # As três abas e todos os seletores, que é onde o desempacotamento quebrou.
    habitos = list(at.selectbox[1].options)
    recortes = list(at.selectbox[2].options)
    checar(len(habitos) == 6, "app: seis hábitos no Panorama", f"achei {len(habitos)}")
    checar(len(recortes) == 6, "app: seis recortes no Insights", f"achei {len(recortes)}")

    for h in habitos:
        a = abrir(lambda at, x=h: at.selectbox[1].set_value(x).run())
        checar(not a.exception, f"app: hábito {h!r}",
               str(a.exception[0].value) if a.exception else "")
    for r in recortes:
        a = abrir(lambda at, x=r: at.selectbox[2].set_value(x).run())
        checar(not a.exception, f"app: recorte {r!r}",
               str(a.exception[0].value) if a.exception else "")

    a = abrir(lambda at: at.radio[0].set_value("Cadastrar novo").run())
    checar(not a.exception, "app: aba de cadastro novo",
           str(a.exception[0].value) if a.exception else "")

    # O modelo do app tem que reproduzir a métrica que a barra lateral anuncia.
    lateral = " ".join(m.value for m in at.sidebar.markdown)
    checar("0,900" in lateral, "app: R² anunciado bate com o dos notebooks")

    print(f"  ok  três abas, {len(habitos)} hábitos e {len(recortes)} recortes")


# ══════════════════════════════════ main ══════════════════════════════════

if __name__ == "__main__":
    completo = "--executar" in sys.argv

    parte_1_integridade()
    base = parte_2_base()
    parte_3_numeros(base)
    parte_4_afirmacoes()
    parte_6_app()
    if completo:
        parte_5_execucao()
    else:
        print("\n(execução dos notebooks do zero pulada; use --executar para incluí-la)")

    print(f"\n{'=' * 60}")
    if falhas:
        print(f"{len(falhas)} de {verificacoes} verificações FALHARAM:\n")
        for f in falhas:
            print(f"  · {f}")
        sys.exit(1)
    print(f"As {verificacoes} verificações passaram.")
