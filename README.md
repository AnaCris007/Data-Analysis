# Hábitos e desempenho estudantil

Uma [base](data/raw/habitos_e_desempenho_estudantil.csv) de 1.000 alunos relaciona hábitos de estudo, sono, tela, exercício e saúde mental com a nota de prova. Este repositório descreve essa base, mede o que de fato explica a nota, e termina numa ferramenta que a coordenação pedagógica pode usar: dado um aluno, ela diz se ele está em rota de reprovação e qual mudança de hábito renderia mais pontos.

<div align="center">

**[Abrir o site](https://data-analysis-007.streamlit.app/)** · Triagem de risco acadêmico

</div>

![Triagem de risco acadêmico](assets/img/app.png)

---

## Como rodar

Para isolar as dependências e garantir que o projeto rode em qualquer ambiente, utilize um ambiente virtual (`venv`).

### O app

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

### Os notebooks

```bash
pip install -r requirements-notebooks.txt
jupyter lab
```

**Nota*:* Eles estão salvos **com as saídas**, então dá para ler tudo direto no GitHub sem rodar nada.

### A verificação

Para validar a execução dos notebooks foram desenvolvidos alguns testes simples que podem ser executados via linha de comando:

```bash
python tests/teste_notebooks.py
```

---

## Estrutura de pastas

```
app.py                       o app Streamlit, autocontido
README.md

data/
  raw/                       o CSV original, nunca alterado

notebooks/                   um por tarefa do desafio, executados
  01_exploracao_inicial.ipynb
  02_engenharia_de_dados.ipynb
  03_analise_estatistica.ipynb
  04_aplicacao_pratica.ipynb
  05_visualizacao.ipynb
  06_sintese_de_insights.ipynb

tests/
  teste_notebooks.py         a verificação do projeto inteiro

assets/
  fonts/                     Red Hat Text, para os gráficos usarem a
                             mesma fonte da interface
  img/                       capturas do app, usadas no README e nos
                             notebooks 04 a 06

.streamlit/
  config.toml                tema do app, versionado para sobreviver ao deploy

requirements.txt             o que o app precisa
requirements-notebooks.txt   o mesmo, mais o Jupyter
```

**Por que dois arquivos de dependência.** O Streamlit Cloud instala o `requirements.txt` a cada deploy. Se o Jupyter estivesse ali, seriam oitenta pacotes a mais para baixar e resolver em toda publicação, sem nenhum deles ser usado pelo app. O `requirements-notebooks.txt` faz `-r requirements.txt` e acrescenta só o que falta para abrir os notebooks.

**`data/raw/` não tem um `data/processed/` ao lado.** Nenhuma base tratada é gravada em disco. Os notebooks 02 a 06 e o app compartilham a mesma função `preparar_dados()`, e o teste confere que os cinco chegam a um DataFrame idêntico. Um arquivo intermediário só criaria a chance de ele ficar desatualizado em relação ao código que o gerou.

---

## Os notebooks

Um por tarefa do desafio, cada um fechando com o gancho para o seguinte.

| Notebook | O que responde | Achado que mudou a análise |
|---|---|---|
| [01 Exploração inicial](notebooks/01_exploracao_inicial.ipynb) | A base é confiável? | O `read_csv` padrão **fabrica 91 ausentes** que o arquivo não tem |
| [02 Engenharia de dados](notebooks/02_engenharia_de_dados.ipynb) | Que variáveis criar? | Seis de sete derivadas **pioram** o sinal |
| [03 Análise estatística](notebooks/03_analise_estatistica.ipynb) | O que explica a nota? | A correlação simples **subestima** todo hábito que não seja estudo |
| [04 Aplicação prática](notebooks/04_aplicacao_pratica.ipynb) | O que dá para fazer? | Perto da linha de corte o modelo acerta 67,5%, **pior que chutar** |
| [05 Visualização](notebooks/05_visualizacao.ipynb) | Como comunicar? | Abaixo de 2h de estudo, **94% reprovam**; de 5h em diante, ninguém |
| [06 Síntese de insights](notebooks/06_sintese_de_insights.ipynb) | Há diferença entre grupos? | **Nenhuma**, exceto saúde mental |

---

## O app

Três abas, feitas para a coordenação pedagógica.

**Aluno.** Escolhe alguém da base ou cadastra um novo e recebe a nota prevista, o veredito e o simulador de intervenção, que ordena as mudanças de hábito por quantos pontos cada uma renderia.

**Panorama da turma** ([captura](assets/img/app-panorama.png)). Seletor de hábito com dois painéis sobre o mesmo eixo de faixas: em cima a distribuição da nota em cada faixa, embaixo quantos ficam abaixo do corte. Mais o mapa de calor de correlação.

**Insights** ([captura](assets/img/app-insights.png)). Impacto de cada hábito em pontos, um comparador que responde "há diferença entre grupos?" para qualquer recorte, e as recomendações.

### O veredito tem três estados, e o terceiro é o que importa

O modelo acerta 92,1% dos vereditos, contra 72,0% de simplesmente chutar que todo mundo passa. Mas essa é uma média, e ela esconde onde o modelo erra:

| Distância da linha de corte | Alunos | Acerto |
|---|---|---|
| **até 5,1 pontos** | 203 | **67,5%** |
| 5,1 a 10,1 | 196 | 93,9% |
| 10,1 a 15,2 | 199 | 99,5% |
| mais de 15,2 | 402 | 100% |

Perto do corte o modelo fica **pior que não ter modelo nenhum**. São 20% da turma. Esses casos aparecem como **zona de incerteza** em vez de receberem um veredito falsamente confiante, e é justamente neles que vale gastar atenção humana.

---

## As conclusões

### Quais hábitos mais afetam as notas

| Posição | Hábito | r simples | r parcial | Pontos por desvio |
|---|---|---|---|---|
| 1 | Horas de estudo | +0,825 | referência | **+14,1** |
| 2 | Saúde mental | +0,322 | **+0,575** | +5,6 |
| 3 | Tempo de tela | -0,238 | **-0,412** | -3,9 |
| 4 | Exercício | +0,160 | +0,326 | +2,9 |
| 5 | Sono | +0,122 | +0,256 | +2,5 |
| 6 | Frequência às aulas | +0,090 | +0,121 | +1,4 |

Sem efeito detectável: escolaridade dos pais, qualidade da internet, trabalho de meio período, qualidade da dieta, idade e atividade extracurricular. Em todas, o intervalo de 95% da correlação contém o zero.

**A coluna do meio é a que muda a conversa.** Ela mede cada hábito entre alunos que estudam a mesma quantidade, e aí saúde mental sobe de 0,32 para 0,575.

### Recomendações práticas

1. **Priorizar quem estuda menos de 3h por dia.** São 334 alunos, um terço da turma. Abaixo de 2h, 94% ficam abaixo de 60; entre 2h e 3h são 51%. Tirar um aluno de 2h para 3h derruba o risco de **51% para 16%**.
2. **Tratar saúde mental como variável acadêmica.** Segundo maior efeito, maior entre os que uma escola consegue influenciar, e único recorte de grupo com diferença real.
3. **Negociar tempo de tela.** Cada hora a menos vale 2,5 pontos, e a mediana da turma está em 4,4 horas por dia.

O maior número não é a melhor recomendação. Horas de estudo lidera todas as métricas e é a mais difícil de mudar por conversa: "estude mais uma hora por dia" é o conselho que todo aluno em dificuldade já ouviu. Saúde mental e tela aparecem acima apesar de efeitos menores porque têm caminho de ação.

### Há diferença entre grupos?

**Não, com uma exceção.**

| Recorte | Amplitude | Em desvios |
|---|---|---|
| Qualidade da alimentação | 2,30 pts | 0,14 |
| Escolaridade dos pais | 2,19 pts | 0,13 |
| Qualidade da internet | 2,00 pts | 0,12 |
| Gênero | 1,28 pts | 0,08 |
| Trabalha meio período | 1,09 pts | 0,06 |
| Atividade extracurricular | 0,03 pts | 0,00 |
| **Saúde mental** | **15,6 pts** | **0,92** |

As maiores diferenças demográficas nem sequer são monótonas: quem come *Fair* tira mais que quem come *Good*, e internet *Average* supera *Good*. Efeito real apareceria como gradiente, não como zigue-zague.

Saúde mental é o único agrupamento com gradiente limpo e amplitude relevante, doze vezes a diferença de gênero.

---

## O que esta base não permite concluir

**Nada aqui estabelece causa.** Todas as medidas são de associação. O simulador responde "o que o modelo prevê se esse número mudar", não "o que acontece se o aluno mudar de hábito".

**Os hábitos desta base são independentes entre si**, com correlação máxima de 0,072 entre 89 pares. Em estudantes reais eles vêm em pacote: quem dorme mal costuma estudar menos e usar mais tela à noite.

**A base é sintética.** Distribuições suaves, três variáveis quase uniformes, zero duplicata, zero valor fora de domínio, zero rótulo inconsistente. As conclusões valem como exercício analítico, e não como achado sobre estudantes reais.

**A nota está censurada no topo.** 48 alunos com exatamente 100, o que atenua todas as correlações relatadas. Os números aqui são piso, não valor exato, e o notebook 03 mostra que descartar esses alunos piora a estimativa em vez de corrigi-la.

---

## A verificação

`tests/teste_notebooks.py` faz 114 verificações, ou 120 com `--executar`:

1. **Integridade.** Toda célula de código tem saída, contadores em sequência, nenhum erro gravado, e todo link e imagem resolvem.
2. **Igualdade da base.** Extrai `preparar_dados()` de cada notebook por AST, executa e compara os DataFrames.
3. **Recálculo.** Refaz 33 números do zero e compara com o que o texto afirma.
4. **Presença no texto.** Confere que os notebooks citam esses valores. Se um número muda, a parte 3 acusa o valor novo e a parte 4 acusa o texto que ficou para trás.
5. **O app.** Três abas, seis hábitos, seis recortes, com asserção de conteúdo e não só de ausência de erro.
6. **Execução.** Com `--executar`, roda os seis notebooks do zero num kernel limpo.
