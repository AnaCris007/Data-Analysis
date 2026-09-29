"""
Triagem de risco acadêmico

Prevê a nota de prova de um aluno a partir dos hábitos dele e indica quem está
em rota de reprovação, com a incerteza declarada. Quem usa: coordenação
pedagógica e tutoria, para decidir quem chamar para reforço e o que recomendar.

O modelo e as decisões de desenho estão documentados em
notebooks/04_aplicacao_pratica.ipynb.

Rodar local:   streamlit run app.py
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # o Streamlit renderiza a figura, não uma janela do sistema

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import streamlit as st
from matplotlib import font_manager
from matplotlib.colors import LinearSegmentedColormap
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error
from sklearn.model_selection import train_test_split

# ───────────────────────────── Constantes ─────────────────────────────────

RAIZ = Path(__file__).parent

# Resolvido a partir do próprio arquivo: funciona rodando da raiz do repositório
# (que é como o Streamlit Cloud executa) ou de qualquer outro diretório.
CSV = RAIZ / "data" / "raw" / "habitos_e_desempenho_estudantil.csv"

# Tipografia igual à da interface. Sem isso os gráficos sairiam em DejaVu Sans
# no meio de uma página em Red Hat, e a diferença salta aos olhos.
for _arquivo in sorted((RAIZ / "assets" / "fonts").glob("*.ttf")):
    font_manager.fontManager.addfont(str(_arquivo))
FAMILIA = ("Red Hat Text"
           if "Red Hat Text" in {f.name for f in font_manager.fontManager.ttflist}
           else "sans-serif")

# Paleta única, derivada da identidade visual do cliente. Cada cor tem um papel
# fixo, e a de marca (âmbar) fica reservada ao dado que importa: usá-la em tudo
# faria ela parar de significar alguma coisa.
COR = {
    "marca":        "#ffb73f",  # âmbar da marca, preenchimento do dado principal
    "marca_forte":  "#c97d00",  # âmbar escuro, para marca fina e estado de atenção
    "marca_tinta":  "#8f5800",  # âmbar legível como texto sobre fundo claro
    "creme":        "#fff5e5",  # âmbar rebaixado, para faixa de referência
    "escuro":       "#252a2d",  # grafite da marca, para linha e ponto
    "teal":         "#05bcb4",  # polo frio, oposto ao âmbar
    "teal_forte":   "#00706b",
    "verde":        "#1dc077",  # estado bom
    "vermelho":     "#e82c2a",  # estado crítico
    "superficie":   "#ffffff",
    "superficie_2": "#f7f7f9",
    "tinta":        "#08080a",
    "tinta_2":      "#545c64",
    "suave":        "#8a9199",
    "grade":        "#e5e5e9",  # dado recuado, sem ênfase
    "eixo":         "#d4d4d9",
}

# Escala divergente da correlação: teal no negativo, cinza neutro no zero
# (precisa ler como "nenhuma relação"), âmbar no positivo.
DIVERGENTE = LinearSegmentedColormap.from_list(
    "corr",
    [COR["teal_forte"], COR["teal"], "#a8e5e2", COR["superficie_2"],
     "#ffd694", COR["marca"], COR["marca_tinta"]],
)

# Rampa ordinal âmbar, do claro ao escuro. Faixa tem ordem, então a cor também:
# escurece com a posição na escala, nunca com o valor da nota.
RAMPA = ["#ffe0ad", "#ffc96f", COR["marca"], "#d98f0e", COR["marca_tinta"]]

INTEIRAS = ["age", "exercise_frequency", "mental_health_rating"]
DECIMAIS = [
    "study_hours_per_day", "social_media_hours", "netflix_hours",
    "attendance_percentage", "sleep_hours", "exam_score",
]

# Os seis preditores que o notebook 03 mostrou ter efeito detectável sobre a nota.
MODELO = [
    "study_hours_per_day", "mental_health_rating", "tempo_tela_total",
    "exercise_frequency", "sleep_hours", "attendance_percentage",
]

# Rótulo curto e unidade separados: assim a lista de hábitos alinha o número e
# deixa a unidade recuar para o segundo plano.
ROTULOS = {
    "study_hours_per_day":   ("Estudo por dia", "h", "cada hora a mais por dia"),
    "mental_health_rating":  ("Saúde mental", "de 10", "cada ponto a mais na escala"),
    "tempo_tela_total":      ("Tela por lazer", "h", "cada hora a mais por dia"),
    "exercise_frequency":    ("Exercício", "dias/sem", "cada dia a mais na semana"),
    "sleep_hours":           ("Sono por noite", "h", "cada hora a mais por noite"),
    "attendance_percentage": ("Frequência", "%", "cada ponto percentual a mais"),
}

# Mudança realista de cada hábito, na direção que melhora a nota.
ALAVANCAS = {
    "study_hours_per_day":   (+1.0, "estudar 1h a mais por dia"),
    "mental_health_rating":  (+1.0, "subir 1 ponto na escala de saúde mental"),
    "tempo_tela_total":      (-1.0, "cortar 1h de tela por lazer"),
    "sleep_hours":           (+1.0, "dormir 1h a mais por noite"),
    "exercise_frequency":    (+1.0, "exercitar-se 1 dia a mais na semana"),
    "attendance_percentage": (+10.0, "subir 10 pontos de frequência"),
}

# Recortes categóricos que a síntese compara.
GRUPOS = {
    "gender": "Gênero",
    "part_time_job": "Trabalha meio período",
    "extracurricular_participation": "Atividade extracurricular",
    "diet_quality": "Qualidade da alimentação",
    "internet_quality": "Qualidade da internet",
    "parental_education_level": "Escolaridade dos pais",
}

# Ordem natural das ordinais. Sem isso o groupby ordenaria alfabeticamente e
# "Fair" viria antes de "Good" antes de "Poor", que não é a escala.
ORDEM_GRUPOS = {
    "diet_quality": ["Poor", "Fair", "Good"],
    "internet_quality": ["Poor", "Average", "Good"],
    "parental_education_level": ["None", "High School", "Bachelor", "Master"],
}

# Faixas de hora cheia. Leem melhor que quartil: "2h a 3h" é algo que alguém
# repete numa reunião, "1,7h a 2,5h" não.
FAIXAS = {
    "study_hours_per_day":   ([0, 2, 3, 4, 5, np.inf],
                              ["< 2h", "2h a 3h", "3h a 4h", "4h a 5h", "5h+"]),
    "tempo_tela_total":      ([0, 2, 3, 4, 5, np.inf],
                              ["< 2h", "2h a 3h", "3h a 4h", "4h a 5h", "5h+"]),
    "sleep_hours":           ([0, 6, 7, 8, np.inf],
                              ["< 6h", "6h a 7h", "7h a 8h", "8h+"]),
    "mental_health_rating":  ([1, 4, 6, 8, 11],
                              ["1 a 3", "4 a 5", "6 a 7", "8 a 10"]),
    "exercise_frequency":    ([0, 2, 4, 7], ["0 a 1", "2 a 3", "4 a 6"]),
    "attendance_percentage": ([0, 70, 80, 90, 101],
                              ["< 70%", "70 a 80%", "80 a 90%", "90%+"]),
}


def num(valor, casas=1):
    """Número no padrão brasileiro, com vírgula decimal."""
    return f"{valor:,.{casas}f}".replace(",", " ").replace(".", ",")


def rampa(n):
    """n cores da rampa ordinal, distribuídas do claro ao escuro."""
    if n == 1:
        return [COR["marca"]]
    passos = np.linspace(0, len(RAMPA) - 1, n).round().astype(int)
    return [RAMPA[i] for i in passos]


# ─────────────────────────── Dados e modelo ───────────────────────────────

@st.cache_data
def carregar_dados():
    """Lê o CSV cru e aplica o tratamento definido no notebook 02."""
    # Leitura crua: dtype=str e na_filter=False impedem que o read_csv converta a
    # string "None" de parental_education_level em NaN. Ver notebook 01, seção 2.
    base = pd.read_csv(CSV, dtype=str, na_filter=False)
    base[INTEIRAS] = base[INTEIRAS].astype(int)
    base[DECIMAIS] = base[DECIMAIS].astype(float)
    base["tempo_tela_total"] = base["social_media_hours"] + base["netflix_hours"]
    return base


@st.cache_resource
def ajustar_modelo(_base):
    """
    Ajusta a regressão e devolve o modelo com suas métricas de validação.

    Regressão linear não é escolha por omissão. O notebook 04 comparou oito
    famílias de modelo em 53 configurações (Ridge, Lasso, ElasticNet, SVR, KNN,
    Random Forest, Gradient Boosting) e nenhuma superou a linear. Ela ganhou na
    métrica e ainda é a única cujos coeficientes o simulador lê direto.
    """
    X, y = _base[MODELO], _base["exam_score"]
    X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2, random_state=42)

    modelo = LinearRegression().fit(X_tr, y_tr)

    previsto = modelo.predict(X_te)
    # O desvio-padrão do resíduo é o que define a largura da zona de incerteza:
    # é o tamanho típico do erro do modelo, e portanto a distância do corte
    # dentro da qual o veredito não é confiável.
    desvio = float(np.std(y_te - previsto))

    return modelo, {
        "r2": modelo.score(X_te, y_te),
        "mae": mean_absolute_error(y_te, previsto),
        "desvio": desvio,
    }


def prever(modelo, habitos):
    """Nota prevista para um dicionário de hábitos."""
    return float(modelo.predict(pd.DataFrame([{c: habitos[c] for c in MODELO}]))[0])


def classificar(nota_prevista, corte, desvio):
    """
    Veredito em três estados.

    O terceiro estado não é enfeite. Perto da linha de corte o modelo acerta
    cerca de 68% dos vereditos, contra 98% longe dela, e nessa faixa fica pior
    que simplesmente chutar que todos passam. Cravar "vai reprovar" ali venderia
    uma precisão que o modelo não tem.
    """
    if nota_prevista >= corte + desvio:
        return ("aprovado", COR["verde"], "Aprovação provável",
                "Sem sinal de risco pelos hábitos declarados.")
    if nota_prevista <= corte - desvio:
        return ("risco", COR["vermelho"], "Risco de reprovação",
                "Candidato a reforço antes da prova.")
    return ("incerto", COR["marca_forte"], "Zona de incerteza",
            "Previsão perto da linha de corte, onde o veredito acerta cerca de "
            "68% das vezes contra 98% fora dela. Vale olhar o caso de perto.")


# ─────────────────────────────── Gráficos ─────────────────────────────────

def estilo_base():
    """Estilo comum a todos os gráficos, na tipografia e nas cores da marca."""
    plt.rcParams.update({
        "figure.facecolor":   COR["superficie"],
        "axes.facecolor":     COR["superficie"],
        "savefig.facecolor":  COR["superficie"],
        "font.family":        FAMILIA,
        "font.size":          11,
        "text.color":         COR["tinta"],
        "axes.titlesize":     12,
        "axes.titleweight":   "normal",
        "axes.titlecolor":    COR["tinta_2"],
        "axes.titlelocation": "left",
        "axes.titlepad":      13,
        "axes.labelsize":     10.5,
        "axes.labelcolor":    COR["suave"],
        "axes.edgecolor":     COR["eixo"],
        "axes.spines.top":    False,
        "axes.spines.right":  False,
        "axes.spines.left":   False,
        "axes.grid":          False,
        "xtick.color":        COR["suave"],
        "ytick.color":        COR["suave"],
        "xtick.labelsize":    10,
        "ytick.labelsize":    10,
        "legend.frameon":     False,
    })


def grafico_posicao(base, nota_prevista, corte, desvio, cor_veredito):
    """Onde o aluno cai na distribuição de notas da turma."""
    estilo_base()
    fig, ax = plt.subplots(figsize=(7.2, 3.2))

    ax.hist(base["exam_score"], bins=34, color=COR["grade"],
            edgecolor=COR["superficie"], linewidth=0.8)

    # Faixa de incerteza em volta da previsão, para o número não parecer exato.
    ax.axvspan(nota_prevista - desvio, nota_prevista + desvio,
               color=cor_veredito, alpha=0.18, zorder=2)
    ax.axvline(nota_prevista, color=cor_veredito, linewidth=2.4, zorder=3)
    ax.axvline(corte, color=COR["escuro"], linewidth=1.1, zorder=3)

    topo = ax.get_ylim()[1]
    ax.set_ylim(0, topo * 1.2)
    ax.text(corte, topo * 1.06, "corte", color=COR["tinta_2"], fontsize=10,
            ha="center", va="bottom")

    ax.set_title("Distribuição das notas da turma")
    ax.set_yticks([])
    ax.set_xlim(0, 105)
    ax.set_xticks([0, 20, 40, 60, 80, 100])
    fig.tight_layout()
    return fig


def grafico_alavancas(ganhos):
    """Quanto cada mudança de hábito renderia, em pontos."""
    estilo_base()
    fig, ax = plt.subplots(figsize=(10, 3.6))

    g = ganhos.iloc[::-1]
    # Âmbar só na maior alavanca. As demais recuam para cinza, senão a cor de
    # marca aparece em tudo e deixa de apontar nada.
    cores = [COR["marca"] if i == len(g) - 1 else COR["grade"] for i in range(len(g))]

    ax.barh(np.arange(len(g)), g["ganho"], height=0.52, color=cores,
            edgecolor=COR["superficie"], linewidth=1)

    for i, v in enumerate(g["ganho"]):
        ax.text(v + 0.18, i, f"+{num(v)} pontos", va="center", fontsize=10.5,
                color=COR["tinta_2"])

    ax.set_yticks(np.arange(len(g)), g["acao"])
    ax.tick_params(axis="y", length=0, pad=8)
    ax.set_xticks([])
    ax.spines["bottom"].set_visible(False)
    ax.set_xlim(0, max(g["ganho"].max() * 1.35, 1))
    fig.tight_layout()
    return fig


def calcular_alavancas(modelo, habitos, limites):
    """Ganho em pontos de cada mudança de hábito, respeitando os limites da base."""
    atual = prever(modelo, habitos)

    linhas = []
    for variavel, (delta, descricao) in ALAVANCAS.items():
        minimo, maximo = limites[variavel]
        # np.clip impede sugerir o impossível, como 9h de estudo quando o máximo
        # observado na base é 8,3, ou tela negativa.
        novo_valor = float(np.clip(habitos[variavel] + delta, minimo, maximo))
        if np.isclose(novo_valor, habitos[variavel]):
            continue  # já está no limite, a alavanca não existe para este aluno

        simulado = dict(habitos)
        simulado[variavel] = novo_valor
        linhas.append({"acao": descricao, "ganho": prever(modelo, simulado) - atual})

    ganhos = pd.DataFrame(linhas)
    if ganhos.empty:
        return ganhos
    return ganhos.sort_values("ganho", ascending=False).reset_index(drop=True)


def grafico_habito(base, coluna, corte):
    """
    Dois painéis empilhados sobre o mesmo eixo de faixas: onde a nota fica e
    quanto risco há em cada faixa.

    A versão anterior punha um gráfico de dispersão ao lado das barras. Não
    funcionava por dois motivos. Em variável discreta (exercício de 0 a 6, saúde
    mental de 1 a 10) a dispersão vira um punhado de listras verticais que não
    mostram nem densidade nem relação. E os dois painéis tinham eixos x
    diferentes, um contínuo e outro em faixas, de forma que não dava para ligar
    um ao outro. Aqui os dois compartilham o eixo, e cada faixa mantém a mesma
    cor nos dois painéis.
    """
    estilo_base()
    # constrained em vez de tight_layout: é o único que posiciona o suptitle
    # sem reclamar de eixos compartilhados.
    fig, (ax_nota, ax_risco) = plt.subplots(
        2, 1, figsize=(10, 5.6), sharex=True, layout="constrained",
        height_ratios=[2.4, 1],
    )

    x, y = base[coluna], base["exam_score"]
    cortes, rotulos = FAIXAS[coluna]
    faixa = pd.cut(x, bins=cortes, labels=rotulos, right=False)

    grupos = [y[faixa == r].to_numpy() for r in rotulos]
    n_faixa = [len(g) for g in grupos]
    cores = rampa(len(rotulos))
    posicoes = np.arange(len(rotulos))

    # ── Painel de cima: a nota de cada faixa, com dispersão ──
    caixas = ax_nota.boxplot(
        grupos, positions=posicoes, patch_artist=True, widths=0.5,
        medianprops=dict(color=COR["superficie"], linewidth=2),
        whiskerprops=dict(color=COR["eixo"], linewidth=1.2),
        capprops=dict(color=COR["eixo"], linewidth=1.2),
        flierprops=dict(markeredgecolor=COR["eixo"], markersize=3.5),
    )
    for caixa, cor in zip(caixas["boxes"], cores):
        caixa.set(facecolor=cor, edgecolor="none")

    ax_nota.axhline(corte, color=COR["escuro"], linewidth=1.2, zorder=1)
    ax_nota.text(len(rotulos) - 0.45, corte + 1.5, f"corte {corte}",
                 fontsize=10, color=COR["tinta_2"], ha="right")
    ax_nota.set_ylabel("nota da prova")
    ax_nota.set_ylim(10, 106)
    ax_nota.spines["left"].set_visible(True)

    # ── Painel de baixo: quanto de cada faixa fica abaixo do corte ──
    risco = [100 * (g < corte).mean() for g in grupos]
    ax_risco.bar(posicoes, risco, width=0.5, color=cores,
                 edgecolor=COR["superficie"], linewidth=1)
    # Rótulo acima da barra: dentro dele o degrau escuro da rampa engoliria o texto.
    for i, v in enumerate(risco):
        ax_risco.text(i, v + 7, f"{v:.0f}%", ha="center", fontsize=10.5,
                      color=COR["tinta_2"])

    ax_risco.set_ylabel("abaixo do corte")
    ax_risco.set_ylim(0, 128)
    ax_risco.set_yticks([])

    # Rótulo só embaixo, valendo para os dois painéis.
    ax_risco.set_xticks(posicoes, [f"{r}\nn={n}" for r, n in zip(rotulos, n_faixa)],
                        fontsize=10.5)
    ax_risco.set_xlim(-0.6, len(rotulos) - 0.4)

    inclinacao = np.polyfit(x, y, 1)[0]
    sinal = "vale" if inclinacao > 0 else "custa"
    fig.suptitle(
        f"{ROTULOS[coluna][0]}: {ROTULOS[coluna][2]} {sinal} "
        f"{num(abs(inclinacao))} pontos na nota",
        x=0.01, ha="left", fontsize=12.5, color=COR["tinta"],
    )
    return fig


def grafico_correlacao(base):
    """Mapa de calor das variáveis que explicam a nota."""
    estilo_base()
    matriz = base[["exam_score"] + MODELO].corr()

    fig, ax = plt.subplots(figsize=(7.6, 5.6))
    # Triângulo inferior estrito, sem a primeira linha nem a última coluna: a
    # matriz é simétrica e a diagonal vale sempre 1,00.
    recorte = matriz.iloc[1:, :-1]
    visivel = recorte.mask(np.triu(np.ones(recorte.shape, dtype=bool), k=1))
    im = ax.imshow(visivel, cmap=DIVERGENTE, vmin=-1, vmax=1)

    for i in range(recorte.shape[0]):
        for j in range(i + 1):
            v = recorte.iloc[i, j]
            # Texto claro só nas células escuras das duas pontas da escala.
            escura = v > 0.62 or v < -0.45
            ax.text(j, i, f"{v:.2f}".replace("-0.00", "0.00").replace(".", ","),
                    ha="center", va="center", fontsize=10.5,
                    color=COR["superficie"] if escura else COR["tinta_2"])

    nomes = ["Nota da prova"] + [ROTULOS[c][0] for c in MODELO]
    ax.set_xticks(range(recorte.shape[1]), nomes[:-1], rotation=30, ha="right",
                  fontsize=10)
    ax.set_yticks(range(recorte.shape[0]), nomes[1:], fontsize=10)
    ax.grid(visible=False)
    for lado in ax.spines.values():
        lado.set_visible(False)

    barra = fig.colorbar(im, ax=ax, shrink=0.62, pad=0.03)
    barra.outline.set_visible(False)
    barra.ax.tick_params(labelsize=9, colors=COR["suave"])

    fig.tight_layout()
    return fig


def grafico_grupos(base, coluna):
    """Nota média por grupo, com intervalo de 95% e régua de referência."""
    estilo_base()
    y = base["exam_score"]
    media_geral, dp = y.mean(), y.std()

    categorias = ORDEM_GRUPOS.get(coluna) or sorted(base[coluna].dropna().unique())

    linhas = []
    for categoria in categorias:
        serie = y[base[coluna] == categoria]
        margem = 1.96 * serie.std() / np.sqrt(len(serie))
        linhas.append((str(categoria), len(serie), serie.mean(),
                       serie.mean() - margem, serie.mean() + margem))

    fig, ax = plt.subplots(figsize=(8.6, 0.68 * len(linhas) + 1.5))

    # Faixa de ±0,25 desvio em volta da média geral: diferença que não sai dela
    # é pequena demais para orientar qualquer ação.
    ax.axvspan(media_geral - 0.25 * dp, media_geral + 0.25 * dp,
               color=COR["creme"], zorder=0)
    ax.axvline(media_geral, color=COR["marca"], linewidth=1.8, zorder=1)

    for i, (_, _, m, lo, hi) in enumerate(linhas[::-1]):
        ax.plot([lo, hi], [i, i], color=COR["escuro"], linewidth=2.2, zorder=2)
        ax.scatter(m, i, s=80, color=COR["escuro"],
                   edgecolor=COR["superficie"], linewidth=2, zorder=3)

    ax.set_yticks(np.arange(len(linhas)),
                  [f"{g}   n={n}" for g, n, *_ in linhas[::-1]], fontsize=10.5)
    ax.tick_params(axis="y", length=0, pad=8)
    ax.set_xlim(56, 84)
    ax.set_xlabel("nota média, com intervalo de 95%")
    amplitude = max(l[2] for l in linhas) - min(l[2] for l in linhas)
    ax.set_title(f"Do melhor ao pior grupo: {num(amplitude)} pontos "
                 f"({num(amplitude / dp, 2)} desvio)")
    fig.tight_layout()
    return fig


def grafico_impacto(base, modelo):
    """Quanto cada hábito vale em pontos, por desvio-padrão."""
    estilo_base()
    efeitos = pd.Series(
        {c: b * base[c].std() for c, b in zip(MODELO, modelo.coef_)}
    ).sort_values(key=abs)

    fig, ax = plt.subplots(figsize=(9, 3.6))
    # Âmbar e teal são os dois polos da paleta: cobrem sinal positivo e negativo
    # sem precisar de uma terceira cor.
    cores = [COR["marca"] if v > 0 else COR["teal"] for v in efeitos]

    ax.barh(np.arange(len(efeitos)), efeitos.to_numpy(), height=0.55, color=cores,
            edgecolor=COR["superficie"], linewidth=1)
    ax.axvline(0, color=COR["eixo"], linewidth=1)

    for i, v in enumerate(efeitos):
        ax.text(v + (0.35 if v > 0 else -0.35), i, f"{v:+.1f}".replace(".", ","),
                va="center", ha="left" if v > 0 else "right", fontsize=10.5,
                color=COR["tinta_2"])

    ax.set_yticks(np.arange(len(efeitos)), [ROTULOS[c][0] for c in efeitos.index],
                  fontsize=10.5)
    ax.tick_params(axis="y", length=0, pad=8)
    ax.set_xlim(-6.5, 17)
    ax.set_xticks([])
    ax.spines["bottom"].set_visible(False)
    ax.set_xlabel("pontos de nota por 1 desvio-padrão do hábito")
    fig.tight_layout()
    return fig


# ────────────────────────────── Interface ─────────────────────────────────

st.set_page_config(page_title="Triagem de risco acadêmico", layout="wide")

st.markdown(
    f"""
    <style>
      .block-container {{ padding-top: 3rem; padding-bottom: 4.5rem; max-width: 1160px; }}
      section[data-testid="stSidebar"] {{ width: 350px !important; }}
      section[data-testid="stSidebar"] > div {{ padding-top: 2.4rem; }}

      /* Do menu ☰ fica só a limpeza de cache. A troca de tema saiu junto: o app
         tem uma paleta só, e alternar para o escuro do Streamlit desmontaria
         justamente o que essa paleta resolve. */
      [data-testid="stAppDeployButton"],
      [data-testid="stMainMenuItem-rerun"],
      [data-testid="stMainMenuItem-autoRerun"],
      [data-testid="stMainMenuItem-print"],
      [data-testid="stMainMenuItem-recordScreencast"],
      [data-testid="stMainMenuItem-theme-System"],
      [data-testid="stMainMenuItem-theme-Light"],
      [data-testid="stMainMenuItem-theme-Dark"],
      [data-testid="stMainMenuItem-clearCache"] {{ display: none !important; }}

      .chapeu {{ font-size: .82rem; letter-spacing: .16em; text-transform: uppercase;
        color: {COR["marca_tinta"]}; font-weight: 500; margin-bottom: .6rem; }}
      .titulo {{ font-size: 2.4rem; font-weight: 700; letter-spacing: -.022em;
        line-height: 1.12; margin: 0 0 .65rem 0; }}
      .linhafina {{ color: {COR["tinta_2"]}; font-size: 1.06rem; max-width: 62ch;
        margin: 0 0 .5rem 0; line-height: 1.55; }}

      /* Legenda de gráfico não leva o limite de medida da linhafina: ela
         acompanha a largura da figura, senão sobra um vão à direita. As mais
         longas vão em duas colunas, para o texto continuar legível. */
      .legenda {{ color: {COR["tinta_2"]}; font-size: 1.02rem; line-height: 1.55;
        margin: .2rem 0 .4rem 0; }}
      .legenda p {{ margin: 0 0 .5rem 0; }}

      /* Hábitos como lista de definição, e não como caixas de dashboard. */
      .habitos {{ display: grid; grid-template-columns: repeat(3, 1fr);
        gap: 1.6rem 2.6rem; margin: .6rem 0 .2rem 0; }}
      .habitos div {{ border-top: 2px solid {COR["creme"]}; padding-top: .65rem; }}
      .habitos .rot {{ font-size: .94rem; color: {COR["suave"]}; display: block;
        margin-bottom: .22rem; }}
      .habitos .val {{ font-size: 1.55rem; font-weight: 700; }}
      .habitos .un  {{ font-size: .94rem; color: {COR["suave"]}; font-weight: 400;
        margin-left: .26rem; }}

      /* Veredito: régua no topo na cor do estado, e tipografia carregando o
         resto. Sem cartão colorido, sem ícone, sem caixa de alerta. */
      .veredito {{ border-top: 4px solid var(--estado); padding-top: 1.15rem; }}
      .veredito .rot {{ font-size: .82rem; letter-spacing: .14em;
        text-transform: uppercase; color: {COR["suave"]}; }}
      .veredito .nota {{ font-size: 4.8rem; font-weight: 700; line-height: 1;
        letter-spacing: -.035em; margin: .5rem 0 .25rem 0; color: var(--estado); }}
      .veredito .estado {{ font-size: 1.4rem; font-weight: 700;
        color: var(--estado); margin-bottom: .6rem; }}
      .veredito p {{ color: {COR["tinta_2"]}; font-size: 1.04rem;
        margin: 0 0 .6rem 0; max-width: 46ch; line-height: 1.5; }}
      .veredito .meta {{ color: {COR["suave"]}; font-size: .98rem; }}

      .secao {{ font-size: 1.38rem; font-weight: 700; letter-spacing: -.014em;
        margin: .9rem 0 .4rem 0; }}
      .nota-rodape {{ color: {COR["suave"]}; font-size: .94rem;
        border-top: 1px solid {COR["grade"]}; padding-top: 1.1rem; margin-top: 3rem; }}

      /* Barra lateral: número grande e pouco texto. O detalhe fica dobrado
         dentro dos expansores. */
      .lado-num {{ margin: .1rem 0 1.1rem 0; }}
      .lado-num .rot {{ font-size: .88rem; color: {COR["suave"]}; display: block;
        margin-bottom: .1rem; }}
      .lado-num .val {{ font-size: 1.6rem; font-weight: 700; }}
    </style>
    """,
    unsafe_allow_html=True,
)

base = carregar_dados()
modelo, metricas = ajustar_modelo(base)
desvio = metricas["desvio"]

# Limites de cada campo vindos do que existe na base, para não permitir cenário
# fora do domínio em que o modelo foi treinado.
LIMITES = {c: (float(base[c].min()), float(base[c].max())) for c in MODELO}

st.markdown(
    """
    <div class="chapeu">Coordenação pedagógica</div>
    <div class="titulo">Triagem de risco acadêmico</div>
    <p class="linhafina">Quem provavelmente vai ficar abaixo da nota de corte na
    próxima prova, e o que fazer a respeito.</p>
    <p class="linhafina">A partir de seis hábitos declarados pelo aluno, o modelo
    estima a nota e acerta o veredito em <strong>92% dos casos</strong>. Serve a duas
    decisões: <strong>quem chamar</strong> para reforço antes da prova, e
    <strong>o que recomendar</strong> para cada aluno chamado. Os dados são de 1.000
    alunos, e quando o modelo não tem confiança suficiente ele diz isso em vez de
    chutar.</p>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    corte = st.slider(
        "Nota mínima para aprovação",
        min_value=40, max_value=80, value=60, step=5,
        help="A régua é institucional, não sai do dado. O padrão de 60 reprova "
             "28% da base.",
    )

    st.markdown(
        f'<div class="lado-num"><span class="rot">R² em teste</span>'
        f'<span class="val">{num(metricas["r2"], 3)}</span></div>'
        f'<div class="lado-num"><span class="rot">Erro médio</span>'
        f'<span class="val">{num(metricas["mae"])} pontos</span></div>',
        unsafe_allow_html=True,
    )

    with st.expander("Sobre o modelo"):
        st.markdown(
            f"Regressão linear sobre {len(base)} alunos, avaliada em 20% separados "
            "do treino. Escolhida depois de comparar 8 famílias de modelo em 53 "
            "configurações.\n\n"
            f"A zona de incerteza tem ±{num(desvio)} pontos em volta do corte, que "
            "é o tamanho típico do erro.\n\n"
            "Os hábitos desta base são independentes entre si, o que indica dado "
            "sintético: o app demonstra o método e não deve orientar decisão sobre "
            "aluno real."
        )

aba_aluno, aba_turma, aba_insights = st.tabs(
    ["Aluno", "Panorama da turma", "Insights"]
)


def bloco_habitos(habitos):
    """Hábitos como lista de definição, com a unidade recuada."""
    celulas = []
    for variavel in MODELO:
        rotulo, unidade, _ = ROTULOS[variavel]
        valor = habitos[variavel]
        texto = num(valor, 0) if variavel in INTEIRAS else num(valor)
        celulas.append(
            f'<div><span class="rot">{rotulo}</span>'
            f'<span class="val">{texto}</span><span class="un">{unidade}</span></div>'
        )
    st.markdown(f'<div class="habitos">{"".join(celulas)}</div>',
                unsafe_allow_html=True)


def painel(habitos, nota_real=None):
    """Renderiza veredito, posição na turma e simulador para um perfil de hábitos."""
    nota_prevista = prever(modelo, habitos)
    estado, cor_estado, titulo, explicacao = classificar(nota_prevista, corte, desvio)

    # O modelo prevê acima de 100 para os melhores alunos, porque a escala foi
    # cortada em 100 e ele estima o que ela não registrou. Trunco na exibição.
    exibida = min(nota_prevista, 100.0)
    piso, teto = max(nota_prevista - desvio, 0), min(nota_prevista + desvio, 100)

    meta = f"faixa provável de {num(piso, 0)} a {num(teto, 0)} pontos"
    if nota_real is not None:
        meta += (f" · nota real {num(nota_real)} · erro de "
                 f"{num(abs(nota_prevista - nota_real))}")

    esquerda, direita = st.columns([1, 1.25], gap="large")

    with esquerda:
        st.markdown(
            f"""
            <div class="veredito" style="--estado: {cor_estado};">
              <div class="rot">Nota prevista</div>
              <div class="nota">{exibida:.0f}</div>
              <div class="estado">{titulo}</div>
              <p>{explicacao}</p>
              <div class="meta">{meta}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if nota_real == 100 and nota_prevista > 100:
            st.markdown(
                f'<p class="linhafina" style="font-size:.96rem;">O modelo previu '
                f"{nota_prevista:.0f}, acima do máximo da escala. Este aluno é um "
                "dos que a nota máxima de 100 não conseguiu medir.</p>",
                unsafe_allow_html=True,
            )

    with direita:
        st.pyplot(
            grafico_posicao(base, nota_prevista, corte, desvio, cor_estado),
            width="stretch",
        )
        st.markdown(
            '<div class="legenda"><p>Cada barra cinza é um grupo de alunos da base '
            "com aquela nota. A <strong>linha colorida</strong> marca a previsão "
            "deste aluno e a <strong>faixa em volta</strong> é a margem de erro do "
            "modelo, de ±%s pontos. A linha escura é o corte.</p></div>"
            % num(desvio),
            unsafe_allow_html=True,
        )

    st.markdown('<div class="secao">O que mudar primeiro</div>', unsafe_allow_html=True)
    esq, dir_ = st.columns(2, gap="large")
    with esq:
        st.markdown(
            '<div class="legenda"><p>Cada barra responde: <em>se só este hábito '
            "mudasse, e todo o resto ficasse igual, quantos pontos a nota prevista "
            "subiria?</em></p></div>",
            unsafe_allow_html=True,
        )
    with dir_:
        st.markdown(
            '<div class="legenda"><p>A barra em âmbar é a mudança que rende mais. '
            "Mudanças que passariam do máximo observado na base ficam de fora, para "
            "não sugerir o impossível.</p></div>",
            unsafe_allow_html=True,
        )

    ganhos = calcular_alavancas(modelo, habitos, LIMITES)
    if ganhos.empty:
        st.markdown(
            '<p class="linhafina">Este aluno já está no limite da base em todos os '
            "hábitos do modelo.</p>",
            unsafe_allow_html=True,
        )
    else:
        st.pyplot(grafico_alavancas(ganhos), width="stretch")


with aba_aluno:
    modo = st.radio("Origem dos dados", ["Aluno da base", "Cadastrar novo"],
                    horizontal=True, label_visibility="collapsed")

    if modo == "Aluno da base":
        esq, _ = st.columns([1, 2.2], gap="large")
        with esq:
            aluno_id = st.selectbox("Aluno", base["student_id"], index=0)
        aluno = base.loc[base["student_id"] == aluno_id].iloc[0]
        habitos = {c: float(aluno[c]) for c in MODELO}

        bloco_habitos(habitos)
        st.divider()
        painel(habitos, nota_real=float(aluno["exam_score"]))

    else:
        st.markdown(
            '<p class="linhafina">Hábitos de um aluno que não está na base. Os '
            "limites de cada campo vêm do que foi observado nos 1.000 alunos: fora "
            "dessa faixa o modelo estaria extrapolando.</p>",
            unsafe_allow_html=True,
        )

        c1, c2, c3 = st.columns(3, gap="large")
        entrada = {}
        with c1:
            entrada["study_hours_per_day"] = st.slider(
                "Estudo por dia (h)", *LIMITES["study_hours_per_day"], 3.5, 0.1)
            entrada["mental_health_rating"] = st.slider(
                "Saúde mental (1 a 10)", 1, 10, 5, 1)
        with c2:
            entrada["tempo_tela_total"] = st.slider(
                "Tela por lazer (h)", *LIMITES["tempo_tela_total"], 4.3, 0.1)
            entrada["sleep_hours"] = st.slider(
                "Sono por noite (h)", *LIMITES["sleep_hours"], 6.5, 0.1)
        with c3:
            entrada["exercise_frequency"] = st.slider(
                "Exercício (dias por semana)", 0, 6, 3, 1)
            entrada["attendance_percentage"] = st.slider(
                "Frequência às aulas (%)", *LIMITES["attendance_percentage"], 84.0, 0.5)

        st.divider()
        painel({c: float(v) for c, v in entrada.items()})


with aba_turma:
    st.markdown(
        '<p class="linhafina">Escolha um hábito e veja como ele separa a turma. Os '
        "alunos são divididos em faixas, e cada faixa guarda a mesma cor nos dois "
        "painéis.</p>",
        unsafe_allow_html=True,
    )

    habito = st.selectbox("Hábito", MODELO, index=0,
                          format_func=lambda c: ROTULOS[c][0])
    st.pyplot(grafico_habito(base, habito, corte), width="stretch")

    esq, dir_ = st.columns(2, gap="large")
    with esq:
        st.markdown(
            '<div class="legenda"><p><strong>Em cima</strong>, cada caixa cobre a '
            "metade central das notas daquela faixa, e a linha branca dentro dela é "
            "a mediana. Os fios que saem da caixa vão até as notas extremas. Se as "
            "caixas sobem em degraus sem se sobrepor, o hábito separa a turma; se "
            "ficam na mesma altura, não separa.</p></div>",
            unsafe_allow_html=True,
        )
    with dir_:
        st.markdown(
            '<div class="legenda"><p><strong>Embaixo</strong>, quantos alunos daquela '
            "faixa ficam abaixo da nota de corte. É o painel que diz onde concentrar "
            "esforço: compare estudo, onde o risco desaba de 94% para zero, com "
            "exercício, onde ele mal se move.</p></div>",
            unsafe_allow_html=True,
        )

    st.divider()
    st.markdown('<div class="secao">O que se relaciona com o quê</div>',
                unsafe_allow_html=True)
    # O mapa não estica até a página inteira, senão vira um tabuleiro de células
    # enormes sem ganhar legibilidade. A legenda ocupa o espaço que sobra ao lado.
    col_mapa, col_texto = st.columns([1.5, 1], gap="large")
    with col_mapa:
        st.pyplot(grafico_correlacao(base), width="stretch")
    with col_texto:
        st.markdown(
            '<div class="legenda"><p>Cada célula cruza duas variáveis e mostra o '
            "quanto elas andam juntas, de -1 a +1. <strong>Âmbar</strong> quer dizer "
            "que sobem juntas, <strong>verde-azulado</strong> que uma sobe quando a "
            "outra desce, e <strong>cinza</strong> que não têm relação. Quanto mais "
            "forte a cor, mais forte a relação.</p>"
            "<p>A <strong>primeira coluna</strong> é a que responde à pergunta da "
            "análise: é ali que está a relação de cada hábito com a nota.</p>"
            "<p>O resto do mapa é quase todo cinza, e isso também é informação: os "
            "hábitos desta base não se relacionam entre si. Quem estuda mais não "
            "dorme menos, quem usa mais tela não se exercita menos.</p></div>",
            unsafe_allow_html=True,
        )


with aba_insights:
    st.markdown('<div class="secao">Quanto vale cada hábito</div>',
                unsafe_allow_html=True)
    esq, dir_ = st.columns(2, gap="large")
    with esq:
        st.markdown(
            '<div class="legenda"><p>Os hábitos são medidos em unidades diferentes: '
            "horas, dias por semana, uma escala de 1 a 10. Comparar 1 hora com 1 "
            "ponto de escala não diria nada, então cada um aparece aqui pelo quanto "
            "vale uma mudança <strong>típica</strong> dele, do tamanho da variação "
            "que existe na turma.</p></div>",
            unsafe_allow_html=True,
        )
    with dir_:
        st.markdown(
            '<div class="legenda"><p>Assim as barras ficam comparáveis: horas de '
            "estudo vale quase três vezes saúde mental, que por sua vez vale mais que "
            "o resto junto. <strong>Âmbar sobe a nota, verde-azulado derruba.</strong>"
            "</p></div>",
            unsafe_allow_html=True,
        )
    st.pyplot(grafico_impacto(base, modelo), width="stretch")

    st.divider()
    st.markdown('<div class="secao">Há diferença entre grupos?</div>',
                unsafe_allow_html=True)
    st.markdown(
        '<p class="linhafina">Esta é a pergunta que mais convida a pescar resultado: '
        "com seis recortes e mil alunos, sempre dá para achar um grupo à frente e "
        "contar uma história sobre ele. Escolha qualquer recorte e confira você "
        "mesma.</p>",
        unsafe_allow_html=True,
    )

    recorte = st.selectbox("Recorte", list(GRUPOS), index=0,
                           format_func=lambda c: GRUPOS[c])
    st.pyplot(grafico_grupos(base, recorte), width="stretch")

    esq, dir_ = st.columns(2, gap="large")
    with esq:
        st.markdown(
            '<div class="legenda"><p>Cada <strong>ponto</strong> é a nota média de um '
            "grupo, e a <strong>barra em volta</strong> é a incerteza dessa média: "
            "grupo pequeno tem barra larga. Quando as barras de dois grupos se "
            "sobrepõem, não dá para afirmar que um vai melhor que o outro.</p></div>",
            unsafe_allow_html=True,
        )
    with dir_:
        st.markdown(
            '<div class="legenda"><p>A <strong>faixa em âmbar</strong> é a régua. Ela '
            "tem meio desvio-padrão da nota, que é o mínimo para uma diferença valer "
            "alguma ação. Ponto que não sai dela é ruído com cara de achado.</p></div>",
            unsafe_allow_html=True,
        )

    esq, dir_ = st.columns(2, gap="large")
    with esq:
        st.markdown(
            '<div class="legenda"><p><strong>Nenhum recorte demográfico separa as '
            "notas.</strong> Todas as amplitudes ficam abaixo de 0,15 desvio, que é "
            "menos de um terço da régua.</p></div>",
            unsafe_allow_html=True,
        )
    with dir_:
        st.markdown(
            '<div class="legenda"><p>E as maiores nem são monótonas: quem come '
            "<em>Fair</em> tira mais que quem come <em>Good</em>. Efeito real "
            "apareceria como gradiente, não como zigue-zague. A única exceção está "
            "abaixo.</p></div>",
            unsafe_allow_html=True,
        )

    st.divider()
    st.markdown('<div class="secao">A exceção: saúde mental</div>',
                unsafe_allow_html=True)
    cortes_sm, rotulos_sm = FAIXAS["mental_health_rating"]
    st.pyplot(
        grafico_grupos(
            base.assign(faixa_saude=pd.cut(base["mental_health_rating"],
                                           cortes_sm, labels=rotulos_sm, right=False)),
            "faixa_saude",
        ),
        width="stretch",
    )
    esq, dir_ = st.columns(2, gap="large")
    with esq:
        st.markdown(
            '<div class="legenda"><p>É o único agrupamento com <strong>gradiente '
            "limpo</strong>: cada faixa fica acima da anterior, sem inversão em "
            "nenhum degrau. É assim que um efeito real se comporta.</p></div>",
            unsafe_allow_html=True,
        )
    with dir_:
        st.markdown(
            '<div class="legenda"><p>São <strong>13,0 pontos</strong> entre a faixa '
            "mais baixa e a mais alta, dez vezes a diferença de gênero. Na escala de "
            "1 a 10 sem agrupar, a distância entre as pontas chega a 15,6 pontos, ou "
            "0,92 desvio.</p></div>",
            unsafe_allow_html=True,
        )

    st.divider()
    st.markdown('<div class="secao">O que fazer com isso</div>',
                unsafe_allow_html=True)
    st.markdown(
        """
1. **Priorizar quem estuda menos de 3h por dia.** São 334 alunos, um terço da
   turma. Na faixa abaixo de 2h, 94% ficam abaixo de 60; entre 2h e 3h são 51%.
   Tirar um aluno de 2h para 3h derruba o risco de 51% para 16%.
2. **Tratar saúde mental como variável acadêmica.** Segundo maior efeito, maior
   entre os que a escola consegue influenciar, e único recorte de grupo com
   diferença real.
3. **Negociar tempo de tela.** Cada hora a menos vale 2,5 pontos, e a mediana da
   turma está em 4,4 horas por dia.

O maior número não é a melhor recomendação: horas de estudo lidera todas as
métricas e é a mais difícil de mudar por conversa. Saúde mental e tela aparecem
acima apesar de efeitos menores porque têm caminho de ação.
        """
    )


st.markdown(
    '<div class="nota-rodape">Teste prático de Analytics Engineer. '
    "Modelo e decisões de desenho documentados em "
    "<code>notebooks/04_aplicacao_pratica.ipynb</code>.</div>",
    unsafe_allow_html=True,
)
