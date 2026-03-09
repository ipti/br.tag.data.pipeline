# PLAN-ML-02 — RAG + LLM (v2)

> **Série:** ML Layer (2/3)
> **Depende de:** `PLAN-ML-01-FEATURE-ML-MLOPS.md` + `PLAN-ML-01-PATCHES.md`
> **Schema Neo4j:** `NEO4J-SCHEMA-REFERENCE.md` §2.8 (Municipality), §2.9 (State), §3 (relacionamentos)
> **Queries analíticas:** `CYPHER-QUERY-MATRIX-ML.md` Q1–Q15 · `Q_RISCO_EVASAO_EF2.md` · `Q_SAUDE_ESCOLA.md` · `Q_PROXIMIDADE_ALUNOS.md`
> **Implementação real:** `Architecture-EWS-doc` (GradientBoosting, random under-sampling, MLflow S3, `df_features.merge(df_geo, on='student_id')` para enriquecimento geográfico)

---

## O que é RAG neste contexto

RAG aqui não é busca em documentos — é **síntese de contexto multi-fonte e multi-granularidade**. O gestor educacional faz perguntas em quatro camadas hierárquicas. Cada camada tem fontes de dados diferentes, benchmarks diferentes, e intervenções possíveis diferentes:

| Granularidade | Quem usa | Pergunta típica | Fonte primária |
|---|---|---|---|
| **Aluno** | Orientador / professor | "Por que João tem 85% de risco?" | Grafo Neo4j (perfil individual) + vector similarity |
| **Turma** | Coordenador pedagógico | "Qual turma do 7º ano precisa de reforço urgente?" | Q15 God Matrix + Q8 composite risk + SHAP por turma |
| **Escola** | Gestor local | "Como nossa escola está vs o município?" | Q_SAUDE_ESCOLA + Q_RISCO_EVASAO + IBGE municipal |
| **Município** | Secretaria municipal | "Quais escolas do município estão em colapso?" | Agregação escola → município + benchmarks IBGE |
| **Estado** | Secretaria estadual / SEDUC | "Como nosso estado compara vs IDEB nacional?" | Agregação estado + QEdu + PNAD racial |

O LLM nunca acessa o banco. Toda lógica de busca é determinística, testável sem API key, e retorna contexto estruturado antes de qualquer chamada LLM.

**Separação de responsabilidades local vs remoto:**
- **Embedding (local, sempre):** `sentence-transformers` roda no container. Sem chamada de rede, sem API key, sem custo proporcional ao volume de alunos.
- **LLM remoto (por request do gestor):** OpenAI GPT, Gemini ou Ollama local — configurável via `LLM_PROVIDER`. O volume é baixo (perguntas de gestores, não N alunos), então custo de API é aceitável.

---

## Fluxo Completo

```
Pergunta do gestor (texto livre)
  │
  ├─ identify_granularity()   → "escola" | "municipio" | "estado" | "turma" | "aluno"
  │
  ▼
Retriever (pure graph — sem LLM)
  ├─ get_student_context(student_id)          → perfil + freq + notas + saúde + IBGE
  ├─ get_classroom_context(school_id, turma)  → Q15 + Q8 composite + SHAP pivot
  ├─ get_school_context(school_id)            → Q_SAUDE_ESCOLA (4 dims) + top turmas risco
  ├─ get_municipality_context(muni_name, uf)  → ranking escolas + IBGE + delta vs UF
  ├─ get_state_context(uf)                    → ranking municípios + QEdu + PNAD racial
  ├─ find_similar_students(embedding, id)     → top-5 via vector index
  └─ find_similar_schools(embedding, id)      → top-5 via vector index
  │
  ▼
ContextBuilder (por granularidade)
  → monta dict estruturado → serializa em texto ≤ 16.000 chars (~4.000 tokens)
  │
  ▼
PromptBuilder
  → template estático por granularidade + contexto + pergunta
  │
  ▼
LLMClient (OpenAI GPT | Gemini Flash | Ollama local)
  → resposta estruturada: diagnóstico + fatores + intervenções sugeridas
```

---

## Estrutura de Arquivos

```
src/
├── embeddings/
│   ├── student_embedder.py        # features → texto → embedding
│   ├── school_embedder.py         # agregados escola → texto → embedding
│   └── neo4j_vector_writer.py     # writeback em batch (UNWIND)
└── rag/
    ├── granularity.py             # identify_granularity() — roteador de contexto
    ├── retriever.py               # todos os get_*_context() + find_similar_*()
    ├── context_builder.py         # dict → string ≤ 16k chars por granularidade
    ├── prompt_templates.py        # templates por granularidade (sem lógica)
    ├── llm_client.py              # interface única: OpenAI | Gemini | Ollama
    └── rag_pipeline.py            # orquestra retriever → context → prompt → LLM

dags/
└── dag__rag_embedding_refresh.py  # refresh semanal (alunos + escolas)
```

---

## Princípios de Código

- **Retrieval sem LLM.** `retriever.py` é 100% testável sem API key — todo método retorna dict ou lista de dicts.
- **Contexto com teto de tokens.** `context_builder.py` garante ≤ 16.000 chars — cabe em qualquer modelo.
- **Interface única para LLM.** `llm_client.py` tem `ask(context, question, template) → str`. Trocar de OpenAI para Gemini ou Ollama é uma variável de ambiente (`LLM_PROVIDER`).
- **Templates são strings, não código.** Nenhuma lógica condicional em `prompt_templates.py`.
- **Granularidade explícita em toda chamada.** Cada método de retriever recebe o identificador correto — não existe "auto-detect" no backend.
- **Logs sem dados pessoais.** Hash da pergunta + latência, nunca `student_id` nem texto completo da pergunta.
- **Stateless por request.** Nenhuma memória de conversa no servidor — contexto remontado do grafo a cada request.
- **Comparações com IBGE sempre explicadas.** Quando o contexto inclui um benchmark IBGE, ele vem com `fonte_ibge` para o LLM saber se é valor municipal real ou média da UF (proxy).

---

## 1. Vector Indexes — Setup Neo4j

Executar uma vez antes de qualquer embedding:

```cypher
// Student embedding — 384 dimensões (paraphrase-multilingual-MiniLM-L12-v2)
CREATE VECTOR INDEX student_embedding IF NOT EXISTS
FOR (s:Student) ON s.embedding
OPTIONS {indexConfig: {`vector.dimensions`: 384, `vector.similarity_function`: 'cosine'}};

// School embedding — mesmo modelo, representação de agregados de escola
CREATE VECTOR INDEX school_embedding IF NOT EXISTS
FOR (s:School) ON s.embedding
OPTIONS {indexConfig: {`vector.dimensions`: 384, `vector.similarity_function`: 'cosine'}};

// Verificar status — deve ser ONLINE antes de usar
SHOW INDEXES WHERE type = 'VECTOR'
```

**Modelo:** `paraphrase-multilingual-MiniLM-L12-v2`
- Suporte nativo a português
- 384 dimensões nativas (sem projeção)
- Roda localmente sem GPU — compatível com Docker

---

## 2. `src/embeddings/student_embedder.py`

```python
# src/embeddings/student_embedder.py
"""
Serializa features de aluno em texto e gera embedding via sentence-transformers.

A representação textual é robusta a valores nulos e permite que o modelo de
linguagem capture relações semânticas (ex: "bolsa família" + "zona rural" →
contexto socioeconômico vulnerável).

References:
  - Feature contracts: PLAN-ML-01 schema.py (DEMO_FEATURES, HEALTH_FEATURES)
  - Serialization: cada campo usa descrição legível para português
"""
import logging
import numpy as np
import pandas as pd
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

_MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
_model: SentenceTransformer | None = None


def get_model() -> SentenceTransformer:
    """Carrega modelo uma vez (singleton). Thread-safe para uso em API."""
    global _model
    if _model is None:
        logger.info("Carregando modelo de embedding: %s", _MODEL_NAME)
        _model = SentenceTransformer(_MODEL_NAME)
    return _model


def student_to_text(row: pd.Series) -> str:
    """
    Serializa uma linha de features de aluno em texto descritivo.

    Valores nulos são substituídos por frases neutras — ausência de dado é
    informação diferente de condição negativa.

    Args:
        row: Series com colunas do DEMO_FEATURES + HEALTH_FEATURES + FREQ_FEATURES.

    Returns:
        String de ~100–200 palavras descrevendo o perfil do aluno.
    """
    def fmt_nota(v) -> str:
        if pd.isna(v): return "sem nota registrada"
        return f"{v:.1f}"

    def fmt_ausencia(taxa, tem_diario) -> str:
        if not tem_diario: return "sem diário eletrônico na escola"
        if pd.isna(taxa): return "ausência não informada"
        return f"{taxa * 100:.0f}% de faltas"

    health_flags = []
    for cond in ["has_malnutrition", "has_diabetes", "has_hypertension", "has_obesity", "has_anemia", "has_celiac"]:
        if row.get(cond, 0):
            health_flags.append(cond.replace("has_", ""))
    health_str = ", ".join(health_flags) if health_flags else "sem condições registradas"

    return (
        f"Aluno: gênero {'feminino' if row.get('gender_bin') else 'masculino'}, "
        f"etnia {row.get('ethnicity_raw', 'não declarada')}, "
        f"zona {'rural' if row.get('residence_zone_enc', 1) == 0 else 'urbana'}, "
        f"bolsa família {'sim' if row.get('bolsa_familia') else 'não'}, "
        f"deficiência {'sim' if row.get('has_deficiency') else 'não'}. "
        f"Frequência: {fmt_ausencia(row.get('taxa_ausencia'), row.get('tem_diario', 0))}. "
        f"Nota: {fmt_nota(row.get('nota_final_norm'))}. "
        f"Saúde: {health_str}. "
        f"Contexto: UF {row.get('uf', '?')}, "
        f"IBGE freq_liq_muni {row.get('muni_freq_liq_fund', '?')}, "
        f"IDEB estadual {row.get('est_ideb_af', '?')}, "
        f"abandono estadual {row.get('est_taxa_abandono', 0):.1%}. "
        f"Cluster de risco: {row.get('risk_cluster', 'não atribuído')}."
    )


def embed_students(df: pd.DataFrame, batch_size: int = 256) -> np.ndarray:
    """
    Gera embeddings para todos os alunos no DataFrame.

    Args:
        df: DataFrame com colunas de features de aluno.
        batch_size: Tamanho do batch para controle de memória.

    Returns:
        ndarray shape (N, 384) com embeddings normalizados.
    """
    model = get_model()
    texts = [student_to_text(row) for _, row in df.iterrows()]
    logger.info("Gerando embeddings para %d alunos (batch_size=%d)", len(texts), batch_size)
    embeddings = model.encode(texts, batch_size=batch_size, show_progress_bar=False, normalize_embeddings=True)
    logger.info("Embeddings gerados: shape=%s", embeddings.shape)
    return embeddings
```

---

## 3. `src/embeddings/school_embedder.py`

```python
# src/embeddings/school_embedder.py
"""
Serializa métricas de escola em texto e gera embedding para busca de escolas similares.

Usa a saída de school_aggregator.compute_school_metrics() —
não acessa Neo4j diretamente.

References:
  - school_aggregator.py: score_saude, nivel_saude, flags de qualidade
  - Q_SAUDE_ESCOLA.md: modelo de score 4 dimensões (35% presença + 35% desempenho + 20% equidade + 10% cobertura)
  - Q_PROXIMIDADE_ALUNOS.md: grupos Aprovado / À Beira (4–4.9) / Intermediário (3–3.9) / Crítico (<3) + trajetória grade_1 → final_mean + Potencial_Impacto
"""
import logging
import numpy as np
import pandas as pd
from .student_embedder import get_model

logger = logging.getLogger(__name__)


def school_to_text(row: pd.Series) -> str:
    """
    Serializa métricas de escola em texto descritivo para embedding.

    Args:
        row: Series com saída de compute_school_metrics() — inclui score_saude,
             taxa_ausencia_pct, media_nota_escola, pct_bolsa_familia, etc.

    Returns:
        String descrevendo perfil da escola (~80–120 palavras).
    """
    ausencia = row.get("taxa_ausencia_pct", None)
    ausencia_str = f"{ausencia:.1f}%" if ausencia is not None else "sem diário"
    nota     = row.get("media_nota_escola", None)
    nota_str = f"{nota:.1f}" if nota is not None else "sem notas"
    bf_pct   = row.get("pct_bolsa_familia", None)
    bf_str   = f"{bf_pct:.0f}%" if bf_pct is not None else "não informado"
    pcd_pct  = row.get("pct_pcd", None)
    pcd_str  = f"{pcd_pct:.1f}%" if pcd_pct is not None else "não informado"

    flags = row.get("data_quality", "completo")

    return (
        f"Escola: UF {row.get('uf', '?')}, município {row.get('municipio', '?')}, "
        f"saúde {row.get('nivel_saude', '?')} (score {row.get('score_saude', '?')}), "
        f"ausência {ausencia_str}, nota média {nota_str}, "
        f"Bolsa Família {bf_str}, PCD {pcd_str}, "
        f"IBGE freq_liq {row.get('muni_freq_liq_fund', '?')}, "
        f"IDEB EF-AF {row.get('est_ideb_af', '?')}, "
        f"abandono estadual {row.get('est_taxa_abandono', '?')}, "
        f"qualidade dos dados: {flags}."
    )


def embed_schools(df: pd.DataFrame, batch_size: int = 64) -> np.ndarray:
    """
    Gera embeddings para todas as escolas no DataFrame.

    Args:
        df: DataFrame com saída de compute_school_metrics().
        batch_size: Tamanho do batch.

    Returns:
        ndarray shape (N, 384).
    """
    model = get_model()
    texts = [school_to_text(row) for _, row in df.iterrows()]
    logger.info("Gerando embeddings para %d escolas", len(texts))
    return model.encode(texts, batch_size=batch_size, show_progress_bar=False, normalize_embeddings=True)
```

---

## 4. `src/embeddings/neo4j_vector_writer.py`

```python
# src/embeddings/neo4j_vector_writer.py
"""
Escreve embeddings de volta no Neo4j em batches via UNWIND.
Uma transação por batch — evita N round-trips individuais.
"""
import logging
import numpy as np
from neo4j import Driver

logger = logging.getLogger(__name__)

_WRITE_STUDENT = """
UNWIND $rows AS row
MATCH (stu:Student {id: row.student_id})
SET stu.embedding = row.embedding
"""

_WRITE_SCHOOL = """
UNWIND $rows AS row
MATCH (sch:School {id: row.school_id})
SET sch.embedding = row.embedding
"""


def write_embeddings(
    driver: Driver,
    ids: list[str],
    embeddings: np.ndarray,
    entity: str = "student",     # "student" | "school"
    batch_size: int = 500,
) -> None:
    """
    Escreve embeddings em lote no Neo4j.

    Args:
        driver: Neo4j driver (de Neo4jExtractor.from_env() ou dep injection).
        ids: Lista de student_id ou school_id correspondendo às linhas de embeddings.
        embeddings: ndarray shape (N, 384).
        entity: 'student' ou 'school'.
        batch_size: Tamanho do batch — 500 é o limite seguro para evitar OOM no Neo4j.

    Raises:
        ValueError: se entity não for 'student' nem 'school'.
    """
    if entity not in ("student", "school"):
        raise ValueError(f"entity deve ser 'student' ou 'school', recebido '{entity}'")

    query  = _WRITE_STUDENT if entity == "student" else _WRITE_SCHOOL
    id_key = "student_id" if entity == "student" else "school_id"
    total  = len(ids)

    with driver.session() as session:
        for start in range(0, total, batch_size):
            end  = min(start + batch_size, total)
            rows = [
                {id_key: ids[i], "embedding": embeddings[i].tolist()}
                for i in range(start, end)
            ]
            session.run(query, rows=rows)
            logger.info("Embeddings escritos: %d/%d (%s)", end, total, entity)

    logger.info("Writeback completo: %d embeddings de %s", total, entity)
```

---

## 5. `src/rag/granularity.py`

```python
# src/rag/granularity.py
"""
Identifica a granularidade de uma pergunta do gestor.

Isso permite que o rag_pipeline.py chame o método correto do Retriever
sem precisar de lógica condicional espalhada.

A identificação é baseada em palavras-chave — não usa LLM.
Se ambíguo, retorna 'escola' como padrão conservador.
"""
from enum import Enum


class Granularity(str, Enum):
    ALUNO     = "aluno"
    TURMA     = "turma"
    ESCOLA    = "escola"
    MUNICIPIO = "municipio"
    ESTADO    = "estado"


# Palavras-chave por granularidade (verificação em lowercase)
_KEYWORDS: dict[Granularity, list[str]] = {
    Granularity.ALUNO:     ["aluno", "estudante", "criança", "ele", "ela", "matrícula"],
    Granularity.TURMA:     ["turma", "sala", "classe", "7º ano", "8º ano", "9º ano",
                            "6º ano", "1º ano", "2º ano", "3º ano", "4º ano", "5º ano"],
    Granularity.ESCOLA:    ["escola", "unidade", "colégio", "instituição", "estabelecimento"],
    Granularity.MUNICIPIO: ["município", "municipio", "cidade", "prefeitura",
                            "secretaria municipal"],
    Granularity.ESTADO:    ["estado", "uf", "seduc", "secretaria estadual", "governo estadual",
                            "nordeste", "sudeste", "sul", "norte", "centro-oeste"],
}


def identify_granularity(question: str, hint: str | None = None) -> Granularity:
    """
    Identifica a granularidade da pergunta por palavras-chave.

    Args:
        question: Pergunta do gestor em texto livre.
        hint: Granularidade explícita se o frontend já sabe (ex: 'escola').
              Sobrescreve a detecção automática.

    Returns:
        Granularity enum.
    """
    if hint:
        try:
            return Granularity(hint.lower())
        except ValueError:
            pass

    q = question.lower()
    for gran in [Granularity.ALUNO, Granularity.TURMA, Granularity.MUNICIPIO,
                 Granularity.ESTADO, Granularity.ESCOLA]:
        if any(kw in q for kw in _KEYWORDS[gran]):
            return gran

    return Granularity.ESCOLA  # default conservador
```

---

## 6. `src/rag/retriever.py`

O Retriever tem um método por granularidade. Cada método retorna um dict estruturado com os dados necessários para o ContextBuilder montar o prompt. Nenhum método faz chamada LLM.

### 6a — Queries Cypher internas

```python
# src/rag/retriever.py
"""
Recupera contexto estruturado do Neo4j para o pipeline RAG.

Um método por granularidade:
  get_student_context()      → aluno + escola + turma + IBGE + saúde + notas
  get_classroom_context()    → Q15 God Matrix + Q8 composite risk + top alunos
  get_school_context()       → Q_SAUDE_ESCOLA (4 dims) + top turmas risco
  get_municipality_context() → ranking escolas + IBGE + delta vs UF
  get_state_context()        → ranking municípios + QEdu + PNAD racial/gênero
  find_similar_students()    → vector search top-K
  find_similar_schools()     → vector search top-K

Todos os métodos são 100% testáveis sem LLM.

References:
  - CYPHER-QUERY-MATRIX-ML.md Q2, Q4, Q7, Q8, Q11, Q12, Q15
  - Q_RISCO_EVASAO_EF2.md (score_risco: 40/35/25 weights)
  - Q_SAUDE_ESCOLA.md (score_saude 4 dimensões: Presença/Desempenho/Equidade/Cobertura — pesos 35/35/20/10)
  - Q_PROXIMIDADE_ALUNOS.md (grupos À Beira/Intermediário/Crítico + Distancia_Media_Beira + Tendencia_Turma + Potencial_Impacto)
  - NEO4J-SCHEMA-REFERENCE.md §2.8 (Municipality) §2.9 (State)
"""
import logging
from typing import Any
import numpy as np
from neo4j import Driver

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Query: contexto completo de um aluno (granularidade: aluno)
# ─────────────────────────────────────────────────────────────────────────────
_STUDENT_CONTEXT = """
MATCH (stu:Student {id: $student_id})
OPTIONAL MATCH (stu)<-[:ENROLLED_AT_SCHOOL]-(sch:School)
OPTIONAL MATCH (sch)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)
              -[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)
              -[:BELONGS_TO_STATE]->(st:State)
OPTIONAL MATCH (sc:StudentClass)-[:ATTENDED]->(stu)
OPTIONAL MATCH (stu)-[:HAS_HEALTH]->(h:Health)
OPTIONAL MATCH (stu)-[:HAS_DISCIPLINE]->(sd:StudentDiscipline)
OPTIONAL MATCH (stu)-[:ENROLLED_IN]->(cr:Classroom)

WITH stu, sch, m, st, h, cr,
     collect(DISTINCT sc) AS SCs,
     collect(DISTINCT sd) AS SDs

RETURN
  {
    gender:         stu.gender,
    ethnicity:      stu.ethnicity,
    bolsa_familia:  coalesce(stu.bolsa_familia, false),
    has_deficiency: coalesce(stu.deficiency, 'Não') STARTS WITH 'Possui',
    residence_zone: stu.residence_zone,
    risk_cluster:   stu.risk_cluster,
    risk_score:     stu.risk_score
  } AS perfil,

  {
    tem_diario:    size(SCs) > 0,
    total_faltas:  reduce(s = 0, sc IN SCs | s + coalesce(sc.total_faults_per_day, 0)),
    total_dias:    reduce(s = 0, sc IN SCs | s + coalesce(sc.scheduled_student_class_days, 200)),
    taxa_ausencia: CASE WHEN size(SCs) > 0 AND
                             reduce(s=0, sc IN SCs | s + coalesce(sc.scheduled_student_class_days,200)) > 0
                        THEN round(
                          toFloat(reduce(s=0, sc IN SCs | s + coalesce(sc.total_faults_per_day,0))) /
                          reduce(s=0, sc IN SCs | s + coalesce(sc.scheduled_student_class_days,200)) * 100,
                          1)
                        ELSE null END
  } AS frequencia,

  [sd IN SDs WHERE sd IS NOT NULL |
    {
      disciplina:  coalesce(sd.discipline_name, 'Global'),
      nota_final:  CASE WHEN coalesce(sd.final_mean, sd.grade_1) > 10
                        THEN coalesce(sd.final_mean, sd.grade_1) / 10.0
                        ELSE coalesce(sd.final_mean, sd.grade_1) END,
      nota_g1:     CASE WHEN sd.grade_1 IS NOT NULL AND sd.grade_1 > 10
                        THEN sd.grade_1 / 10.0 ELSE sd.grade_1 END,
      nota_g2:     CASE WHEN sd.grade_2 IS NOT NULL AND sd.grade_2 > 10
                        THEN sd.grade_2 / 10.0 ELSE sd.grade_2 END
    }
  ] AS notas,

  {
    tem_registro:   h IS NOT NULL,
    malnutrition:   coalesce(h.malnutrition, false),
    diabetes:       coalesce(h.diabetes, false),
    obesity:        coalesce(h.obesity, false),
    hypertension:   coalesce(h.hypertension, false),
    celiac:         coalesce(h.celiac, false),
    anemia:         coalesce(h.iron_deficiency_anemia, false) OR coalesce(h.sickle_cell_anemia, false)
  } AS saude,

  {
    nome:               sch.name,
    school_id:          sch.id,
    municipio:          m.name,
    uf:                 st.sigla,
    muni_freq_liq:      m.atl_freq_liq_fund,
    muni_analf_adulto:  m.atl_t_analf25m,
    muni_atraso_2anos:  m.atl_atraso_2_fund,
    muni_expectativa:   m.atl_expectativa_estudo_18,
    est_ideb_af:        st.qedu_ideb_af,
    est_taxa_abandono:  st.qedu_taxa_abandono,
    est_taxa_reprovacao:st.qedu_taxa_reprovacao,
    est_distorcao_af:   st.qedu_distorcao_ef_af,
    est_analf_negro:    st.negro_pnad_t_analf25m,
    est_analf_branco:   st.branco_pnad_t_analf25m
  } AS escola_ibge,

  {
    nome:        cr.name,
    grade_level: cr.grade_level,
    stage:       cr.stage,
    ano_letivo:  cr.year
  } AS turma
LIMIT 1
"""

# ─────────────────────────────────────────────────────────────────────────────
# Query: contexto de turma (granularidade: turma)
# Implementa Q15 God Matrix + Q8 composite signal
# Fonte: CYPHER-QUERY-MATRIX-ML.md Q8 + Q15
# ─────────────────────────────────────────────────────────────────────────────
_CLASSROOM_CONTEXT = """
MATCH (sch:School {id: $school_id})
MATCH (sch)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)
      -[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)
      -[:BELONGS_TO_STATE]->(st:State)

// Fallback IBGE UF
CALL (st) {
  MATCH (m2:Municipality)-[:BELONGS_TO_STATE]->(st)
  WHERE m2.atl_freq_liq_fund IS NOT NULL AND m2.atl_freq_liq_fund > 0
  RETURN avg(m2.atl_freq_liq_fund) AS uf_avg_freq
}

// Coleta alunos da turma específica
MATCH (sch)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
WHERE cr.name = $classroom_name

WITH sch, m, st, cr, uf_avg_freq,
     collect(DISTINCT stu) AS AlunosDaTurma
WHERE size(AlunosDaTurma) > 0

// Dimensão 1: notas (Q15 pattern — discipline_name = '' para EF1, regex para EF2)
CALL (AlunosDaTurma) {
  UNWIND AlunosDaTurma AS stu
  OPTIONAL MATCH (stu)-[:HAS_DISCIPLINE]->(sd:StudentDiscipline)
  WHERE coalesce(sd.discipline_name, '') = $discipline_filter
    AND coalesce(sd.final_mean, sd.grade_1) IS NOT NULL
  WITH CASE WHEN coalesce(sd.final_mean, sd.grade_1) > 10
            THEN coalesce(sd.final_mean, sd.grade_1) / 10.0
            ELSE coalesce(sd.final_mean, sd.grade_1)
       END AS Nota
  WHERE Nota IS NOT NULL
  RETURN round(avg(Nota), 2)    AS cr_media_nota,
         round(stDev(Nota), 2)  AS cr_dispersao_nota,
         count(Nota)            AS cr_n_notas,
         count(CASE WHEN Nota < 5.0 THEN 1 END) AS cr_n_abaixo5
}

// Dimensão 2: faltas (Q15 + Q8 pattern)
CALL (AlunosDaTurma) {
  UNWIND AlunosDaTurma AS stu
  OPTIONAL MATCH (sc:StudentClass)-[:ATTENDED]->(stu)
  RETURN
    sum(coalesce(sc.total_faults_per_day, 0))           AS cr_total_faltas,
    sum(coalesce(sc.scheduled_student_class_days, 200)) AS cr_total_dias,
    count(DISTINCT CASE WHEN sc IS NOT NULL AND sc.total_faults_per_day > 0 THEN stu END) AS cr_n_com_falta
}

// Dimensão 3: saúde (Q8 pattern)
CALL (AlunosDaTurma) {
  UNWIND AlunosDaTurma AS stu
  OPTIONAL MATCH (stu)-[:HAS_HEALTH]->(h:Health)
  RETURN
    count(CASE WHEN h IS NOT NULL AND (
                 coalesce(h.malnutrition, false)
              OR coalesce(h.iron_deficiency_anemia, false)
              OR coalesce(h.diabetes, false)
              OR coalesce(h.obesity, false)
            ) THEN 1 END) AS cr_n_risco_saude
}

WITH sch, m, st, cr, AlunosDaTurma, uf_avg_freq,
     cr_media_nota, cr_dispersao_nota, cr_n_notas, cr_n_abaixo5,
     cr_total_faltas, cr_total_dias, cr_n_com_falta, cr_n_risco_saude

RETURN {
  classroom_name:  cr.name,
  grade_level:     cr.grade_level,
  stage:           cr.stage,
  n_alunos:        size(AlunosDaTurma),
  n_bolsistas:     size([s IN AlunosDaTurma WHERE coalesce(s.bolsa_familia, false) = true]),
  n_pcd:           size([s IN AlunosDaTurma WHERE coalesce(s.deficiency, 'Não') STARTS WITH 'Possui']),
  n_rural:         size([s IN AlunosDaTurma WHERE coalesce(s.residence_zone, '') =~ '(?i).*rural.*']),
  n_risco_saude:   coalesce(cr_n_risco_saude, 0),

  media_nota:      cr_media_nota,
  dispersao_nota:  cr_dispersao_nota,
  cv_nota_pct:     CASE WHEN cr_media_nota > 0 AND cr_dispersao_nota IS NOT NULL
                        THEN round(cr_dispersao_nota / cr_media_nota * 100, 1) ELSE null END,
  pct_abaixo5:     CASE WHEN cr_n_notas > 0
                        THEN round(toFloat(cr_n_abaixo5) / cr_n_notas * 100, 1) ELSE null END,

  taxa_ausencia_pct: CASE WHEN cr_total_dias > 0
                          THEN round(toFloat(cr_total_faltas) / cr_total_dias * 100, 2) ELSE null END,
  pct_com_falta:   CASE WHEN size(AlunosDaTurma) > 0
                        THEN round(toFloat(cr_n_com_falta) / size(AlunosDaTurma) * 100, 1) ELSE null END,

  // Q8 composite risk score (normalizado 0–1)
  // Pesos alinhados com Q_RISCO_EVASAO_EF2.md: 40% faltas + 35% notas + 25% saúde
  soma_sinais_risco: CASE WHEN size(AlunosDaTurma) > 0 THEN round(
    (toFloat(cr_n_com_falta) / size(AlunosDaTurma)) * 0.40
    + coalesce(toFloat(cr_n_abaixo5) / NULLIF(cr_n_notas, 0), 0.5) * 0.35
    + (toFloat(cr_n_risco_saude) / size(AlunosDaTurma)) * 0.25,
    4) ELSE null END,

  // IBGE com fallback UF
  muni_freq_liq:   coalesce(m.atl_freq_liq_fund, uf_avg_freq),
  fonte_freq_ibge: CASE WHEN m.atl_freq_liq_fund IS NOT NULL THEN 'Municipal' ELSE 'Media_UF_Proxy' END,
  muni_analf:      m.atl_t_analf25m,
  est_ideb_af:     st.qedu_ideb_af,
  est_abandono:    st.qedu_taxa_abandono,
  est_distorcao_af:st.qedu_distorcao_ef_af,

  // Flags de qualidade
  tem_diario:   cr_n_com_falta > 0,
  tem_notas:    cr_n_notas > 0
} AS classroom_context
LIMIT 1
"""

# ─────────────────────────────────────────────────────────────────────────────
# Query: contexto de escola (granularidade: escola)
# Implementa Q_SAUDE_ESCOLA 4 dimensões + ranking turmas
# Fonte: Q_SAUDE_ESCOLA.md (score) + Q_PROXIMIDADE_ALUNOS.md (grupos beira/intermediário/crítico)
# ─────────────────────────────────────────────────────────────────────────────
_SCHOOL_CONTEXT = """
MATCH (sch:School {id: $school_id})
MATCH (sch)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)
      -[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)
      -[:BELONGS_TO_STATE]->(st:State)

CALL (st) {
  MATCH (m2:Municipality)-[:BELONGS_TO_STATE]->(st)
  WHERE m2.atl_freq_liq_fund IS NOT NULL AND m2.atl_freq_liq_fund > 0
  RETURN avg(m2.atl_freq_liq_fund) AS uf_avg_freq
}

// Todos os alunos da escola
CALL (sch) {
  MATCH (sch)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
  RETURN count(DISTINCT stu) AS n_alunos,
         count(DISTINCT cr)  AS n_turmas,
         collect(DISTINCT stu) AS TodosAlunos
}

// Dimensão Presença: faltas e cobertura de diário
CALL (TodosAlunos) {
  UNWIND TodosAlunos AS stu
  OPTIONAL MATCH (sc:StudentClass)-[:ATTENDED]->(stu)
  RETURN
    count(DISTINCT CASE WHEN sc IS NOT NULL AND sc.total_faults_per_day > 0 THEN stu END) AS n_com_falta,
    count(DISTINCT CASE WHEN sc IS NOT NULL THEN stu END)                                  AS n_com_diario,
    sum(coalesce(sc.total_faults_per_day, 0))                                             AS total_faltas,
    sum(coalesce(sc.scheduled_student_class_days, 200))                                   AS total_dias,
    count(DISTINCT CASE WHEN sc IS NOT NULL AND
          toFloat(coalesce(sc.total_faults_per_day,0)) /
          toFloat(coalesce(sc.scheduled_student_class_days,200)) > 0.25
          THEN stu END)                                                                    AS n_falta_critica
}

// Dimensão Desempenho: notas (global EF1, discipline_name = '')
CALL (TodosAlunos) {
  UNWIND TodosAlunos AS stu
  OPTIONAL MATCH (stu)-[:HAS_DISCIPLINE]->(sd:StudentDiscipline)
  WHERE coalesce(sd.discipline_name, '') = ''
    AND coalesce(sd.final_mean, sd.grade_1) IS NOT NULL
  WITH CASE WHEN coalesce(sd.final_mean, sd.grade_1) > 10
            THEN coalesce(sd.final_mean, sd.grade_1) / 10.0
            ELSE coalesce(sd.final_mean, sd.grade_1)
       END AS Nota
  WHERE Nota IS NOT NULL
  RETURN round(avg(Nota), 2)   AS media_nota,
         round(stDev(Nota), 2) AS dispersao_nota,
         count(Nota)           AS n_notas,
         count(CASE WHEN Nota < 5.0 THEN 1 END) AS n_abaixo5
}

// Dimensão Equidade: BF vs não-BF, PCD, rural, saúde
CALL (TodosAlunos) {
  UNWIND TodosAlunos AS stu
  OPTIONAL MATCH (stu)-[:HAS_DISCIPLINE]->(sd_eq:StudentDiscipline)
  WHERE coalesce(sd_eq.discipline_name, '') = ''
  WITH stu,
       CASE WHEN coalesce(sd_eq.final_mean, sd_eq.grade_1) > 10
            THEN coalesce(sd_eq.final_mean, sd_eq.grade_1) / 10.0
            ELSE coalesce(sd_eq.final_mean, sd_eq.grade_1) END AS NotaEq
  RETURN
    count(CASE WHEN coalesce(stu.bolsa_familia, false) THEN 1 END)              AS n_bolsa_familia,
    round(avg(CASE WHEN coalesce(stu.bolsa_familia, false) THEN NotaEq END), 2) AS media_nota_bf,
    round(avg(CASE WHEN NOT coalesce(stu.bolsa_familia, false) THEN NotaEq END), 2) AS media_nota_nobf,
    count(CASE WHEN coalesce(stu.deficiency,'Não') STARTS WITH 'Possui' THEN 1 END) AS n_pcd,
    count(CASE WHEN coalesce(stu.residence_zone,'') =~ '(?i).*rural.*' THEN 1 END)  AS n_rural
}

// Dimensão Saúde: condições de saúde
CALL (TodosAlunos) {
  UNWIND TodosAlunos AS stu
  OPTIONAL MATCH (stu)-[:HAS_HEALTH]->(h:Health)
  RETURN
    count(CASE WHEN h IS NOT NULL THEN 1 END)                                    AS n_com_saude,
    count(CASE WHEN coalesce(h.malnutrition, false) THEN 1 END)                  AS n_desnutridos,
    count(CASE WHEN coalesce(h.diabetes, false) THEN 1 END)                      AS n_diabetes,
    count(CASE WHEN coalesce(h.obesity, false) THEN 1 END)                       AS n_obesidade
}

RETURN {
  school_id:    sch.id,
  school_name:  sch.name,
  municipio:    m.name,
  uf:           st.sigla,
  n_alunos:     n_alunos,
  n_turmas:     n_turmas,

  // Presença
  n_com_diario:      n_com_diario,
  n_com_falta:       n_com_falta,
  total_faltas:      total_faltas,
  taxa_ausencia_pct: CASE WHEN total_dias > 0
                          THEN round(toFloat(total_faltas) / total_dias * 100, 2) ELSE null END,
  n_falta_critica:   n_falta_critica,

  // Desempenho
  media_nota:      media_nota,
  dispersao_nota:  dispersao_nota,
  n_notas:         n_notas,
  pct_abaixo5:     CASE WHEN n_notas > 0 THEN round(toFloat(n_abaixo5) / n_notas * 100, 1) ELSE null END,

  // Equidade
  n_bolsa_familia:   n_bolsa_familia,
  pct_bolsa_familia: CASE WHEN n_alunos > 0 THEN round(toFloat(n_bolsa_familia) / n_alunos * 100, 1) ELSE null END,
  media_nota_bf:     media_nota_bf,
  media_nota_nobf:   media_nota_nobf,
  gap_bf:            CASE WHEN media_nota_nobf IS NOT NULL AND media_nota_bf IS NOT NULL
                          THEN round(media_nota_nobf - media_nota_bf, 2) ELSE null END,
  n_pcd:             n_pcd,
  n_rural:           n_rural,

  // Saúde
  n_com_saude:   n_com_saude,
  n_desnutridos: n_desnutridos,
  n_diabetes:    n_diabetes,
  n_obesidade:   n_obesidade,

  // IBGE com fallback
  muni_freq_liq:   coalesce(m.atl_freq_liq_fund, uf_avg_freq),
  fonte_freq_ibge: CASE WHEN m.atl_freq_liq_fund IS NOT NULL THEN 'Municipal' ELSE 'Media_UF_Proxy' END,
  muni_analf:      m.atl_t_analf25m,
  muni_atraso:     m.atl_atraso_2_fund,
  muni_expectativa:m.atl_expectativa_estudo_18,

  // QEdu estado
  est_ideb_af:       st.qedu_ideb_af,
  est_ideb_ai:       st.qedu_ideb_ai,
  est_abandono:      st.qedu_taxa_abandono,
  est_reprovacao:    st.qedu_taxa_reprovacao,
  est_distorcao_af:  st.qedu_distorcao_ef_af,
  est_lp_adequado:   st.qedu_lp_adequado_af,
  est_mat_adequado:  st.qedu_mt_adequado_af,

  // Flags
  tem_diario: n_com_diario > 0,
  tem_notas:  n_notas > 0
} AS school_context
LIMIT 1
"""

# ─────────────────────────────────────────────────────────────────────────────
# Query: contexto de município (granularidade: municipio)
# Agrega escolas → ranking interno + comparativo IBGE municipal vs UF
# Fonte: CYPHER-QUERY-MATRIX-ML.md Q2, Q6, Q9, Q12
# ─────────────────────────────────────────────────────────────────────────────
_MUNICIPALITY_CONTEXT = """
MATCH (m:Municipality {name: $municipio_name})-[:BELONGS_TO_STATE]->(st:State)
WHERE st.sigla = $uf

// Fallback UF para campos IBGE nulos
CALL (st) {
  MATCH (m2:Municipality)-[:BELONGS_TO_STATE]->(st)
  WHERE m2.atl_freq_liq_fund IS NOT NULL AND m2.atl_freq_liq_fund > 0
  RETURN avg(m2.atl_freq_liq_fund) AS uf_avg_freq
}
CALL (st) {
  MATCH (m2:Municipality)-[:BELONGS_TO_STATE]->(st)
  WHERE m2.atl_atraso_2_fund IS NOT NULL AND m2.atl_atraso_2_fund > 0
  RETURN avg(m2.atl_atraso_2_fund) AS uf_avg_atraso
}

// Todas as escolas do município
MATCH (:SchoolGeograph {municipality_id: m.id})<-[:HAS_GEOGRAPHY]-(sch:School)

// Agrega por escola
CALL (sch) {
  MATCH (sch)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)
  OPTIONAL MATCH (sc:StudentClass)-[:ATTENDED]->(stu)
  OPTIONAL MATCH (stu)-[:HAS_DISCIPLINE]->(sd:StudentDiscipline)
  WHERE coalesce(sd.discipline_name,'') = ''
  WITH sch,
       count(DISTINCT stu) AS n_stu,
       count(DISTINCT CASE WHEN sc IS NOT NULL THEN stu END) AS n_diario,
       sum(coalesce(sc.total_faults_per_day,0)) AS total_faltas,
       sum(coalesce(sc.scheduled_student_class_days,200)) AS total_dias,
       round(avg(CASE WHEN coalesce(sd.final_mean,sd.grade_1) > 10
                      THEN coalesce(sd.final_mean,sd.grade_1)/10.0
                      ELSE coalesce(sd.final_mean,sd.grade_1) END), 2) AS media_nota,
       count(DISTINCT CASE WHEN coalesce(stu.bolsa_familia,false) THEN stu END) AS n_bf
  RETURN {
    school_id:    sch.id,
    school_name:  sch.name,
    n_alunos:     n_stu,
    tem_diario:   n_diario > 0,
    taxa_ausencia:CASE WHEN total_dias > 0 THEN round(toFloat(total_faltas)/total_dias*100,2) ELSE null END,
    media_nota:   media_nota,
    pct_bf:       CASE WHEN n_stu > 0 THEN round(toFloat(n_bf)/n_stu*100,1) ELSE null END
  } AS escola_resumo
}

WITH m, st, uf_avg_freq, uf_avg_atraso, collect(escola_resumo) AS Escolas

RETURN {
  municipio:    m.name,
  uf:           st.sigla,
  n_escolas:    size(Escolas),
  escolas:      Escolas,

  // Resumo agregado do município (para o LLM comparar)
  total_alunos: reduce(s=0, e IN Escolas | s + coalesce(e.n_alunos, 0)),
  escolas_sem_diario: size([e IN Escolas WHERE NOT e.tem_diario]),
  media_ausencia_muni: round(avg([e IN Escolas WHERE e.taxa_ausencia IS NOT NULL | e.taxa_ausencia]), 2),
  media_nota_muni:     round(avg([e IN Escolas WHERE e.media_nota IS NOT NULL    | e.media_nota]), 2),

  // IBGE municipal
  muni_freq_liq:     coalesce(m.atl_freq_liq_fund, uf_avg_freq),
  fonte_freq_ibge:   CASE WHEN m.atl_freq_liq_fund IS NOT NULL THEN 'Municipal' ELSE 'Media_UF_Proxy' END,
  muni_atraso_2anos: coalesce(m.atl_atraso_2_fund, uf_avg_atraso),
  muni_analf:        m.atl_t_analf25m,
  muni_expectativa:  m.atl_expectativa_estudo_18,
  muni_negro_pub:    m.atl_negro_mat_pub_fund,
  muni_negro_internet: m.atl_negro_internet_fund,

  // QEdu estado (referência comparativa)
  est_ideb_af:     st.qedu_ideb_af,
  est_abandono:    st.qedu_taxa_abandono,
  est_reprovacao:  st.qedu_taxa_reprovacao,
  est_distorcao_af:st.qedu_distorcao_ef_af,
  est_pct_fora_escola: st.qedu_pct_fora_escola,

  // PNAD racial estadual — para equidade municipal
  est_analf_negro:  st.negro_pnad_t_analf25m,
  est_analf_branco: st.branco_pnad_t_analf25m,
  est_atraso_negro: st.negro_pnad_t_atraso_fund,
  est_atraso_branco:st.branco_pnad_t_atraso_fund
} AS municipio_context
LIMIT 1
"""

# ─────────────────────────────────────────────────────────────────────────────
# Query: contexto de estado (granularidade: estado)
# Fonte: CYPHER-QUERY-MATRIX-ML.md Q11, Q12, Q13, Q14
# ─────────────────────────────────────────────────────────────────────────────
_STATE_CONTEXT = """
MATCH (st:State {sigla: $uf})

// Todos os municípios do estado
MATCH (m:Municipality)-[:BELONGS_TO_STATE]->(st)
OPTIONAL MATCH (:SchoolGeograph {municipality_id: m.id})<-[:HAS_GEOGRAPHY]-(sch:School)

WITH st, m, collect(DISTINCT sch) AS Escolas

// Agrega por município
WITH st,
  collect({
    municipio: m.name,
    n_escolas: size(Escolas),
    muni_freq_liq:   m.atl_freq_liq_fund,
    muni_analf:      m.atl_t_analf25m,
    muni_atraso:     m.atl_atraso_2_fund,
    muni_expectativa:m.atl_expectativa_estudo_18
  }) AS Municipios

RETURN {
  uf:            st.sigla,
  nome_estado:   st.name,
  n_municipios:  size(Municipios),
  municipios:    Municipios,

  // QEdu por segmento
  ideb_ai:       st.qedu_ideb_ai,
  ideb_af:       st.qedu_ideb_af,
  ideb_em:       st.qedu_ideb_em,
  abandono:      st.qedu_taxa_abandono,
  reprovacao:    st.qedu_taxa_reprovacao,
  aprovacao:     st.qedu_taxa_aprovacao,
  fluxo_ai:      st.qedu_fluxo_ai,
  fluxo_af:      st.qedu_fluxo_af,
  distorcao_ai:  st.qedu_distorcao_ef_ai,
  distorcao_af:  st.qedu_distorcao_ef_af,
  pct_fora_escola: st.qedu_pct_fora_escola,
  total_matriculas:st.qedu_total_matriculas,

  // Proficiência
  lp_adequado_ai:  st.qedu_lp_adequado_ai,
  mat_adequado_ai: st.qedu_mt_adequado_ai,
  lp_adequado_af:  st.qedu_lp_adequado_af,
  mat_adequado_af: st.qedu_mt_adequado_af,
  lp_insuf_af:     st.qedu_lp_insuficiente_af,
  mat_insuf_af:    st.qedu_mt_insuficiente_af,

  // PNAD racial (só em State — não existe em Municipality)
  analf_negro:     st.negro_pnad_t_analf25m,
  analf_branco:    st.branco_pnad_t_analf25m,
  atraso_negro:    st.negro_pnad_t_atraso_fund,
  atraso_branco:   st.branco_pnad_t_atraso_fund,
  idhm_e_negro:    st.negro_pnad_idhm_e,
  idhm_e_branco:   st.branco_pnad_idhm_e,
  ppob_negro:      st.negro_pnad_ppob,
  ppob_branco:     st.branco_pnad_ppob,
  freq_fund_negro: st.negro_pnad_t_flfund,
  freq_fund_branco:st.branco_pnad_t_flfund,
  med18_negro:     st.negro_pnad_t_med18a20,
  med18_branco:    st.branco_pnad_t_med18a20,

  // PNAD gênero
  analf_homem:      st.homem_pnad_t_analf25m,
  analf_mulher:     st.mulher_pnad_t_analf25m,
  freq_fund_homem:  st.homem_pnad_t_flfund,
  freq_fund_mulher: st.mulher_pnad_t_flfund,
  anosest_homem:    st.homem_pnad_anosest,
  anosest_mulher:   st.mulher_pnad_anosest
} AS state_context
LIMIT 1
"""

# ─────────────────────────────────────────────────────────────────────────────
# Vector similarity queries
# ─────────────────────────────────────────────────────────────────────────────
_SIMILAR_STUDENTS = """
CALL db.index.vector.queryNodes('student_embedding', $top_k, $embedding)
YIELD node AS sim_stu, score
WHERE sim_stu.id <> $student_id
  AND sim_stu.risk_cluster IS NOT NULL
OPTIONAL MATCH (sim_stu)<-[:ENROLLED_AT_SCHOOL]-(sch:School)
OPTIONAL MATCH (sc:StudentClass)-[:ATTENDED]->(sim_stu)
OPTIONAL MATCH (sim_stu)-[:HAS_DISCIPLINE]->(sd:StudentDiscipline)
WHERE coalesce(sd.discipline_name, '') = ''
RETURN sim_stu.id          AS student_id,
       score                AS similarity,
       sim_stu.risk_cluster  AS cluster,
       sim_stu.risk_score    AS risk_score,
       sch.name              AS escola,
       CASE
         WHEN sc IS NOT NULL AND
              sum(coalesce(sc.total_faults_per_day,0)) /
              NULLIF(sum(coalesce(sc.scheduled_student_class_days,200)), 0) > 0.25
         THEN 'evadiu_provável'
         WHEN coalesce(sd.final_mean, sd.grade_1) IS NOT NULL AND
              CASE WHEN coalesce(sd.final_mean, sd.grade_1) > 10
                   THEN coalesce(sd.final_mean, sd.grade_1) / 10.0
                   ELSE coalesce(sd.final_mean, sd.grade_1) END >= 5.0
         THEN 'aprovado'
         WHEN coalesce(sd.final_mean, sd.grade_1) IS NOT NULL
         THEN 'reprovado'
         ELSE 'sem_dado'
       END AS desfecho
ORDER BY score DESC
LIMIT $top_k
"""

_SIMILAR_SCHOOLS = """
CALL db.index.vector.queryNodes('school_embedding', $top_k, $embedding)
YIELD node AS sim_sch, score
WHERE sim_sch.id <> $school_id
OPTIONAL MATCH (sim_sch)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)
              -[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)
              -[:BELONGS_TO_STATE]->(st:State)
RETURN sim_sch.id     AS school_id,
       sim_sch.name   AS escola,
       score          AS similarity,
       m.name         AS municipio,
       st.sigla       AS uf,
       sim_sch.nivel_saude AS nivel_saude,
       sim_sch.score_saude AS score_saude
ORDER BY score DESC
LIMIT $top_k
"""
```

### 6b — Classe Retriever

```python
class Retriever:
    """
    Recupera contexto do Neo4j para o pipeline RAG.
    Sem LLM, sem efeitos colaterais. Todos os métodos retornam dict ou lista.
    """

    def __init__(self, driver: Driver) -> None:
        self._driver = driver

    def get_student_context(self, student_id: str) -> dict[str, Any] | None:
        """
        Contexto completo do aluno: perfil + frequência + notas + saúde + IBGE.

        Args:
            student_id: ID do aluno no Neo4j.

        Returns:
            Dict com chaves: perfil, frequencia, notas, saude, escola_ibge, turma.
            None se aluno não encontrado.
        """
        with self._driver.session() as session:
            result = session.run(_STUDENT_CONTEXT, student_id=student_id)
            record = result.single()
        if record is None:
            logger.warning("Aluno não encontrado: [id redacted]")
            return None
        return dict(record)

    def get_classroom_context(
        self,
        school_id: str,
        classroom_name: str,
        discipline_filter: str = "",
    ) -> dict[str, Any] | None:
        """
        Contexto de turma: Q15 God Matrix + Q8 composite risk.

        Args:
            school_id: ID da escola.
            classroom_name: Nome da turma (cr.name).
            discipline_filter: '' para nota global (EF1), regex para matéria específica (EF2).

        Returns:
            Dict com classroom_context ou None se turma não encontrada.
        """
        with self._driver.session() as session:
            result = session.run(
                _CLASSROOM_CONTEXT,
                school_id=school_id,
                classroom_name=classroom_name,
                discipline_filter=discipline_filter,
            )
            record = result.single()
        if record is None:
            logger.warning("Turma não encontrada: school=%s turma=%s", school_id, classroom_name)
            return None
        return dict(record.get("classroom_context", {}))

    def get_school_context(self, school_id: str) -> dict[str, Any] | None:
        """
        Contexto de escola: Q_SAUDE_ESCOLA 4 dimensões + IBGE + QEdu.

        Args:
            school_id: ID da escola (sch.id no Neo4j).

        Returns:
            Dict com school_context ou None se escola não encontrada.
        """
        with self._driver.session() as session:
            result = session.run(_SCHOOL_CONTEXT, school_id=school_id)
            record = result.single()
        if record is None:
            logger.warning("Escola não encontrada: school_id=%s", school_id)
            return None
        return dict(record.get("school_context", {}))

    def get_municipality_context(
        self, municipio_name: str, uf: str
    ) -> dict[str, Any] | None:
        """
        Contexto de município: ranking escolas + IBGE + QEdu estadual.

        Args:
            municipio_name: Nome do município (m.name no Neo4j).
            uf: Sigla do estado para filtro e benchmarks.

        Returns:
            Dict com municipio_context ou None se município não encontrado.
        """
        with self._driver.session() as session:
            result = session.run(
                _MUNICIPALITY_CONTEXT, municipio_name=municipio_name, uf=uf
            )
            record = result.single()
        if record is None:
            logger.warning("Município não encontrado: %s-%s", municipio_name, uf)
            return None
        return dict(record.get("municipio_context", {}))

    def get_state_context(self, uf: str) -> dict[str, Any] | None:
        """
        Contexto de estado: QEdu + PNAD racial + PNAD gênero + ranking municípios.

        Args:
            uf: Sigla do estado (ex: 'SE', 'BA', 'SP').

        Returns:
            Dict com state_context ou None se UF não encontrada.
        """
        with self._driver.session() as session:
            result = session.run(_STATE_CONTEXT, uf=uf)
            record = result.single()
        if record is None:
            logger.warning("Estado não encontrado: uf=%s", uf)
            return None
        return dict(record.get("state_context", {}))

    def find_similar_students(
        self,
        embedding: np.ndarray,
        student_id: str,
        top_k: int = 5,
    ) -> list[dict]:
        """
        Busca top-K alunos similares via vector index.

        Args:
            embedding: ndarray (384,) do aluno consultado.
            student_id: ID do aluno para excluir da busca.
            top_k: Número de similares retornados.

        Returns:
            Lista de dicts com student_id, similarity, cluster, escola, desfecho.
        """
        with self._driver.session() as session:
            result = session.run(
                _SIMILAR_STUDENTS,
                embedding=embedding.tolist(),
                student_id=student_id,
                top_k=top_k,
            )
            similar = [dict(r) for r in result]
        logger.info("Similares encontrados: %d/%d", len(similar), top_k)
        return similar

    def find_similar_schools(
        self,
        embedding: np.ndarray,
        school_id: str,
        top_k: int = 5,
    ) -> list[dict]:
        """
        Busca top-K escolas similares via vector index.

        Args:
            embedding: ndarray (384,) da escola consultada.
            school_id: ID da escola para excluir da busca.
            top_k: Número de similares retornadas.

        Returns:
            Lista de dicts com school_id, escola, similarity, municipio, uf, nivel_saude.
        """
        with self._driver.session() as session:
            result = session.run(
                _SIMILAR_SCHOOLS,
                embedding=embedding.tolist(),
                school_id=school_id,
                top_k=top_k,
            )
        return [dict(r) for r in result]
```

---

## 7. `src/rag/context_builder.py`

```python
# src/rag/context_builder.py
"""
Constrói o contexto textual para cada granularidade.
Único responsável pelo teto de tokens: nunca produz mais que _MAX_CHARS.

Uma função build_*_context() por granularidade — sem condicional central.
"""
import logging
from typing import Any

logger = logging.getLogger(__name__)

_MAX_CHARS = 16_000    # ~4.000 tokens @ 4 chars/token


def _truncate(text: str) -> str:
    if len(text) > _MAX_CHARS:
        logger.warning("Contexto truncado de %d para %d chars", len(text), _MAX_CHARS)
        return text[:_MAX_CHARS] + "\n[contexto truncado por limite de tokens]"
    return text


# ─────────────────────────────────────────────────────────────────────────────
# Granularidade: ALUNO
# ─────────────────────────────────────────────────────────────────────────────
def build_student_context(
    student_ctx: dict[str, Any],
    similar: list[dict],
    include_ibge: bool = True,
) -> str:
    """
    Serializa contexto de aluno para o prompt.

    Args:
        student_ctx: Saída de Retriever.get_student_context().
        similar: Saída de Retriever.find_similar_students().
        include_ibge: Se False, omite seção IBGE (reduz tokens).

    Returns:
        String ≤ 16.000 chars.
    """
    parts: list[str] = []

    # Perfil
    p = student_ctx.get("perfil", {})
    risk_str = ""
    if p.get("risk_score") is not None:
        risk_str = f", risco_predito={p['risk_score']:.0f}%, cluster={p.get('risk_cluster', '?')}"
    parts.append(
        f"[PERFIL] gênero={p.get('gender','?')}, etnia={p.get('ethnicity','não declarada')}, "
        f"bolsa_família={p.get('bolsa_familia', False)}, PCD={p.get('has_deficiency', False)}, "
        f"zona={p.get('residence_zone','?')}{risk_str}"
    )

    # Frequência
    f = student_ctx.get("frequencia", {})
    if not f.get("tem_diario"):
        parts.append("[FREQUÊNCIA] escola sem diário eletrônico — dado ausente")
    elif f.get("taxa_ausencia") is not None:
        alerta = " ⚠️ CRÍTICO: acima de 25%" if f["taxa_ausencia"] > 25 else ""
        parts.append(
            f"[FREQUÊNCIA] ausência={f['taxa_ausencia']}% dos dias "
            f"({f.get('total_faltas', 0)} faltas / {f.get('total_dias', 200)} dias){alerta}"
        )

    # Notas
    notas = [n for n in (student_ctx.get("notas") or []) if n.get("nota_final") is not None]
    if not notas:
        parts.append("[NOTAS] sem notas cadastradas no sistema")
    else:
        nota_lines = []
        for n in notas:
            traj = ""
            if n.get("nota_g1") is not None and n.get("nota_final") is not None:
                delta = n["nota_final"] - n["nota_g1"]
                traj  = f" (Δ1ºbim: {'+' if delta >= 0 else ''}{delta:.1f})"
            alerta = " ⚠️" if n.get("nota_final", 10) < 5 else ""
            nota_lines.append(f"  {n['disciplina']}: {n['nota_final']:.1f}{traj}{alerta}")
        parts.append("[NOTAS]\n" + "\n".join(nota_lines))

    # Saúde
    s = student_ctx.get("saude", {})
    if s.get("tem_registro"):
        conds = [k for k in ["malnutrition","diabetes","obesity","hypertension","celiac","anemia"] if s.get(k)]
        parts.append(f"[SAÚDE] condições: {', '.join(conds) or 'nenhuma registrada'}")
    else:
        parts.append("[SAÚDE] sem registro de saúde para este aluno")

    # Escola + IBGE
    if include_ibge:
        ei = student_ctx.get("escola_ibge", {})
        if ei.get("nome"):
            fonte = ei.get("fonte_freq_ibge", "?")
            ibge_parts = [
                f"escola={ei.get('nome','?')}, município={ei.get('municipio','?')}, UF={ei.get('uf','?')}"
            ]
            if ei.get("muni_freq_liq"):
                ibge_parts.append(f"IBGE_freq_liq_muni={ei['muni_freq_liq']:.1f}% [{fonte}]")
            if ei.get("muni_analf_adulto"):
                ibge_parts.append(f"analf_adulto_muni={ei['muni_analf_adulto']:.1f}%")
            if ei.get("est_ideb_af"):
                ibge_parts.append(f"IDEB_AF_estado={ei['est_ideb_af']}")
            if ei.get("est_taxa_abandono"):
                ibge_parts.append(f"abandono_estado={ei['est_taxa_abandono']:.1f}%")
            parts.append("[CONTEXTO IBGE] " + ", ".join(ibge_parts))

    # Turma
    t = student_ctx.get("turma", {})
    if t.get("nome"):
        parts.append(f"[TURMA] {t.get('nome','?')} | {t.get('grade_level','?')} | ano={t.get('ano_letivo','?')}")

    # Similares
    if similar:
        sim_lines = [
            f"  similarity={s['similarity']:.2f}: cluster={s.get('cluster','?')}, "
            f"escola={s.get('escola','?')}, desfecho={s.get('desfecho','?')}"
            for s in similar[:5]
        ]
        parts.append("[ALUNOS SIMILARES — o que aconteceu com perfis parecidos]\n" + "\n".join(sim_lines))

    return _truncate("\n".join(parts))


# ─────────────────────────────────────────────────────────────────────────────
# Granularidade: TURMA
# ─────────────────────────────────────────────────────────────────────────────
def build_classroom_context(classroom_ctx: dict[str, Any]) -> str:
    """
    Serializa contexto de turma para o prompt.

    Inclui Q15 features + Q8 composite risk + IBGE com fonte.
    """
    if not classroom_ctx:
        return "[TURMA] dados não encontrados"

    c = classroom_ctx
    n = c.get("n_alunos", 0)

    alerta_risco = ""
    risco = c.get("soma_sinais_risco")
    if risco is not None:
        nivel = "CRÍTICO ⚠️" if risco > 0.6 else "ALERTA" if risco > 0.35 else "MODERADO"
        alerta_risco = f" → risco composto={risco:.2f} ({nivel})"

    parts = [
        f"[TURMA] {c.get('classroom_name','?')} | {c.get('grade_level','?')} | {c.get('stage','?')}",
        f"[COMPOSIÇÃO] {n} alunos: BF={c.get('n_bolsistas',0)} ({c.get('n_bolsistas',0)/max(n,1)*100:.0f}%), "
        f"PCD={c.get('n_pcd',0)}, rural={c.get('n_rural',0)}, risco_saúde={c.get('n_risco_saude',0)}",
        f"[FREQUÊNCIA] ausência={c.get('taxa_ausencia_pct','?')}%, "
        f"alunos_com_falta={c.get('pct_com_falta','?')}%, "
        f"diário={'disponível' if c.get('tem_diario') else '⚠️ SEM DIÁRIO'}",
        f"[NOTAS] média={c.get('media_nota','?')}, dispersão={c.get('dispersao_nota','?')}, "
        f"CV%={c.get('cv_nota_pct','?')}%, "
        f"abaixo_5={c.get('pct_abaixo5','?')}%, "
        f"notas={'disponíveis' if c.get('tem_notas') else '⚠️ SEM NOTAS'}",
        f"[RISCO COMPOSTO Q8]{alerta_risco}",
        f"[IBGE] freq_liq_muni={c.get('muni_freq_liq','?')} [{c.get('fonte_freq_ibge','?')}], "
        f"abandono_estado={c.get('est_abandono','?')}, IDEB_AF={c.get('est_ideb_af','?')}",
    ]
    return _truncate("\n".join(parts))


# ─────────────────────────────────────────────────────────────────────────────
# Granularidade: ESCOLA
# ─────────────────────────────────────────────────────────────────────────────
def build_school_context(
    school_ctx: dict[str, Any],
    similar_schools: list[dict] | None = None,
) -> str:
    """
    Serializa contexto de escola em 4 dimensões + IBGE + escolas similares.
    """
    if not school_ctx:
        return "[ESCOLA] não encontrada"

    s = school_ctx
    n = s.get("n_alunos", 0)

    parts = [
        f"[ESCOLA] {s.get('school_name','?')} | município={s.get('municipio','?')}, UF={s.get('uf','?')}",
        f"[ESCOPO] {n} alunos em {s.get('n_turmas','?')} turmas",
    ]

    # Dimensão Presença
    aus = s.get("taxa_ausencia_pct")
    aus_str = f"{aus:.1f}%" if aus is not None else "sem diário"
    freq_ibge = s.get("muni_freq_liq")
    delta_freq = ""
    if aus is not None and freq_ibge is not None:
        delta = aus - (100 - freq_ibge)   # comparar com inverso da freq líquida IBGE
        delta_str = f"+{delta:.1f}pp acima" if delta > 0 else f"{delta:.1f}pp abaixo"
        delta_freq = f" ({delta_str} da ref. IBGE [{s.get('fonte_freq_ibge','?')}])"
    parts.append(
        f"[PRESENÇA] ausência={aus_str}{delta_freq} | "
        f"diário={'disponível' if s.get('tem_diario') else '⚠️ SEM DIÁRIO'} | "
        f"falta_crítica(>25%)={s.get('n_falta_critica',0)} alunos"
    )

    # Dimensão Desempenho
    nota = s.get("media_nota")
    nota_str = f"{nota:.1f}" if nota is not None else "sem notas"
    parts.append(
        f"[DESEMPENHO] média={nota_str}, dispersão={s.get('dispersao_nota','?')}, "
        f"abaixo_5={s.get('pct_abaixo5','?')}% | "
        f"notas={'disponíveis' if s.get('tem_notas') else '⚠️ SEM NOTAS'}"
    )

    # Dimensão Equidade
    gap_bf = s.get("gap_bf")
    gap_str = f"{gap_bf:+.2f}" if gap_bf is not None else "N/A"
    parts.append(
        f"[EQUIDADE] BF={s.get('pct_bolsa_familia','?')}% dos alunos | "
        f"nota_BF={s.get('media_nota_bf','?')} vs nota_não-BF={s.get('media_nota_nobf','?')} (gap={gap_str}) | "
        f"PCD={s.get('n_pcd',0)}, rural={s.get('n_rural',0)}"
    )

    # Dimensão Saúde
    parts.append(
        f"[SAÚDE] com_registro={s.get('n_com_saude',0)} | "
        f"desnutrição={s.get('n_desnutridos',0)}, diabetes={s.get('n_diabetes',0)}, obesidade={s.get('n_obesidade',0)}"
    )

    # IBGE
    parts.append(
        f"[IBGE] freq_liq_muni={s.get('muni_freq_liq','?')} [{s.get('fonte_freq_ibge','?')}], "
        f"analf_adulto={s.get('muni_analf','?')}, atraso_2anos={s.get('muni_atraso','?')}, "
        f"expectativa_estudo={s.get('muni_expectativa','?')} anos"
    )

    # Benchmarks estaduais
    parts.append(
        f"[BENCHMARKS ESTADO] IDEB_AF={s.get('est_ideb_af','?')}, "
        f"abandono={s.get('est_abandono','?')}%, reprovação={s.get('est_reprovacao','?')}%, "
        f"distorção_AF={s.get('est_distorcao_af','?')}%, "
        f"LP_adequado={s.get('est_lp_adequado','?')}%, Mat_adequado={s.get('est_mat_adequado','?')}%"
    )

    # Escolas similares
    if similar_schools:
        sim_lines = [
            f"  similarity={sc['similarity']:.2f}: {sc.get('escola','?')} "
            f"({sc.get('municipio','?')}-{sc.get('uf','?')}), nível={sc.get('nivel_saude','?')}"
            for sc in similar_schools[:3]
        ]
        parts.append("[ESCOLAS SIMILARES — referência comparativa]\n" + "\n".join(sim_lines))

    return _truncate("\n".join(parts))


# ─────────────────────────────────────────────────────────────────────────────
# Granularidade: MUNICÍPIO
# ─────────────────────────────────────────────────────────────────────────────
def build_municipality_context(municipio_ctx: dict[str, Any]) -> str:
    """
    Serializa contexto de município: ranking escolas + IBGE + benchmarks.
    Ordena escolas por taxa de ausência desc para destacar as mais críticas.
    """
    if not municipio_ctx:
        return "[MUNICÍPIO] não encontrado"

    m = municipio_ctx
    escolas = sorted(
        [e for e in (m.get("escolas") or []) if e.get("taxa_ausencia") is not None],
        key=lambda e: e.get("taxa_ausencia", 0), reverse=True,
    )
    sem_diario = [e for e in (m.get("escolas") or []) if not e.get("tem_diario", True)]

    parts = [
        f"[MUNICÍPIO] {m.get('municipio','?')} — UF {m.get('uf','?')}",
        f"[ESCOPO] {m.get('n_escolas','?')} escolas, {m.get('total_alunos','?')} alunos",
    ]

    if sem_diario:
        nomes = ", ".join(e.get("school_name", e.get("school_id", "?")) for e in sem_diario[:5])
        parts.append(f"[COBERTURA DIGITAL] {len(sem_diario)} escola(s) sem diário eletrônico: {nomes}")

    # Resumo municipal
    parts.append(
        f"[RESUMO MUNICÍPIO] ausência_média={m.get('media_ausencia_muni','?')}%, "
        f"nota_média={m.get('media_nota_muni','?')}"
    )

    # Top 5 escolas com maior ausência
    if escolas:
        escola_lines = [
            f"  {e.get('school_name', e.get('school_id','?'))}: "
            f"ausência={e.get('taxa_ausencia','?')}%, nota={e.get('media_nota','?')}, "
            f"BF={e.get('pct_bf','?')}%, alunos={e.get('n_alunos','?')}"
            for e in escolas[:5]
        ]
        parts.append("[TOP ESCOLAS — MAIOR AUSÊNCIA]\n" + "\n".join(escola_lines))

    # IBGE municipal
    fonte = m.get("fonte_freq_ibge", "?")
    parts.append(
        f"[IBGE MUNICIPAL] freq_liq={m.get('muni_freq_liq','?')} [{fonte}], "
        f"atraso_2anos={m.get('muni_atraso_2anos','?')}%, analf_adulto={m.get('muni_analf','?')}%, "
        f"expectativa_estudo={m.get('muni_expectativa','?')} anos"
    )

    # Equidade racial IBGE municipal
    if m.get("muni_negro_pub") or m.get("muni_negro_internet"):
        parts.append(
            f"[EQUIDADE RACIAL MUNI] negro_mat_pub_fund={m.get('muni_negro_pub','?')}%, "
            f"negro_internet_fund={m.get('muni_negro_internet','?')}%"
        )

    # Benchmarks estaduais
    parts.append(
        f"[BENCHMARKS ESTADO] IDEB_AF={m.get('est_ideb_af','?')}, "
        f"abandono={m.get('est_abandono','?')}%, reprovação={m.get('est_reprovacao','?')}%, "
        f"distorção_AF={m.get('est_distorcao_af','?')}%, "
        f"fora_escola={m.get('est_pct_fora_escola','?')}%"
    )

    # PNAD racial estadual (contexto para análise de equidade)
    if m.get("est_analf_negro") or m.get("est_analf_branco"):
        parts.append(
            f"[PNAD RACIAL ESTADO] analf_negro={m.get('est_analf_negro','?')}%, "
            f"analf_branco={m.get('est_analf_branco','?')}%, "
            f"atraso_negro={m.get('est_atraso_negro','?')}%, atraso_branco={m.get('est_atraso_branco','?')}%"
        )

    return _truncate("\n".join(parts))


# ─────────────────────────────────────────────────────────────────────────────
# Granularidade: ESTADO
# ─────────────────────────────────────────────────────────────────────────────
def build_state_context(state_ctx: dict[str, Any]) -> str:
    """
    Serializa contexto de estado: QEdu + PNAD racial + PNAD gênero + municípios.
    """
    if not state_ctx:
        return "[ESTADO] não encontrado"

    s = state_ctx

    # Ranking municípios com maior analfabetismo (proxy de fragilidade)
    municipios = [m for m in (s.get("municipios") or []) if m.get("muni_analf") is not None]
    municipios_sorted = sorted(municipios, key=lambda m: m.get("muni_analf", 0), reverse=True)

    parts = [
        f"[ESTADO] {s.get('nome_estado','?')} — UF {s.get('uf','?')}",
        f"[ESCOPO] {s.get('n_municipios','?')} municípios | {s.get('total_matriculas','?')} matrículas",

        # QEdu
        f"[IDEB] AI={s.get('ideb_ai','?')}, AF={s.get('ideb_af','?')}, EM={s.get('ideb_em','?')}",
        f"[FLUXO] fluxo_AI={s.get('fluxo_ai','?')}, fluxo_AF={s.get('fluxo_af','?')}",
        f"[DISTORÇÃO] EF_AI={s.get('distorcao_ai','?')}%, EF_AF={s.get('distorcao_af','?')}%",
        f"[ABANDONO/REPROVAÇÃO] abandono={s.get('abandono','?')}%, reprovação={s.get('reprovacao','?')}%, "
        f"fora_escola={s.get('pct_fora_escola','?')}%",

        # Proficiência
        f"[PROFICIÊNCIA] LP_adequado_AI={s.get('lp_adequado_ai','?')}%, Mat_adequado_AI={s.get('mat_adequado_ai','?')}%, "
        f"LP_adequado_AF={s.get('lp_adequado_af','?')}%, Mat_adequado_AF={s.get('mat_adequado_af','?')}%, "
        f"LP_insuf_AF={s.get('lp_insuf_af','?')}%, Mat_insuf_AF={s.get('mat_insuf_af','?')}%",

        # PNAD racial
        f"[PNAD RACIAL] analf_negro={s.get('analf_negro','?')}% vs analf_branco={s.get('analf_branco','?')}% | "
        f"atraso_negro={s.get('atraso_negro','?')}% vs atraso_branco={s.get('atraso_branco','?')}% | "
        f"IDHM_e_negro={s.get('idhm_e_negro','?')} vs IDHM_e_branco={s.get('idhm_e_branco','?')} | "
        f"freq_fund_negro={s.get('freq_fund_negro','?')}% vs freq_fund_branco={s.get('freq_fund_branco','?')}% | "
        f"médio_completo(18–20)_negro={s.get('med18_negro','?')}% vs branco={s.get('med18_branco','?')}%",

        # PNAD gênero
        f"[PNAD GÊNERO] analf_homem={s.get('analf_homem','?')}% vs analf_mulher={s.get('analf_mulher','?')}% | "
        f"anos_estudo_homem={s.get('anosest_homem','?')} vs mulher={s.get('anosest_mulher','?')} | "
        f"freq_fund_homem={s.get('freq_fund_homem','?')}% vs mulher={s.get('freq_fund_mulher','?')}%",
    ]

    # Top municípios mais frágeis por analfabetismo adulto
    if municipios_sorted:
        muni_lines = [
            f"  {m.get('municipio','?')}: analf={m.get('muni_analf','?')}%, "
            f"atraso={m.get('muni_atraso','?')}%, expectativa={m.get('muni_expectativa','?')} anos"
            for m in municipios_sorted[:5]
        ]
        parts.append("[MUNICÍPIOS COM MAIOR FRAGILIDADE (top 5 por analfabetismo adulto)]\n" + "\n".join(muni_lines))

    return _truncate("\n".join(parts))
```

---

## 8. `src/rag/prompt_templates.py`

```python
# src/rag/prompt_templates.py
"""
Templates de prompt por granularidade. Sem lógica — apenas strings.
Todo conteúdo dinâmico injetado via .format() no rag_pipeline.

Princípio: o LLM deve receber instruções sobre granularidade e formato.
Resposta aberta gera texto bonito mas não acionável pelo gestor.
"""

STUDENT_ANALYSIS = """\
Você é um analista pedagógico especializado em prevenção de evasão escolar no Brasil.
Analise os dados do aluno abaixo e produza uma resposta objetiva para o gestor.

=== DADOS DO ALUNO ===
{context}

=== PERGUNTA DO GESTOR ===
{question}

=== FORMATO ESPERADO ===
1. SITUAÇÃO ATUAL (2–3 frases): resumo dos indicadores mais críticos
2. PRINCIPAIS RISCOS (até 3): o que mais preocupa e por quê
3. CONTEXTO (1–2 frases): como este aluno se compara ao estado/município e a alunos similares
4. INTERVENÇÕES SUGERIDAS (até 3): ações concretas e viáveis para a escola agir agora
5. CONFIANÇA: Alta | Média | Baixa — e por quê (ex: "Baixa — escola sem diário eletrônico")

Seja direto. Não repita os dados brutos. Se dado estiver ausente, diga e ajuste a confiança.
"""

CLASSROOM_ANALYSIS = """\
Você é um coordenador pedagógico especializado em análise de turmas no sistema educacional brasileiro.
Analise os dados da turma abaixo e produza um diagnóstico acionável para o coordenador ou diretor.

=== DADOS DA TURMA ===
{context}

=== PERGUNTA DO GESTOR ===
{question}

=== FORMATO ESPERADO ===
1. DIAGNÓSTICO DA TURMA (2–3 frases): situação geral com destaque para o risco composto (Q8)
2. DIMENSÃO MAIS CRÍTICA (1): entre frequência, desempenho e saúde — qual está puxando o risco?
3. PERFIL SOCIAL (1–2 frases): concentração de BF, PCD, rural e impacto esperado
4. COMPARAÇÃO IBGE (1 frase): a turma está acima ou abaixo do esperado para o município?
5. INTERVENÇÕES (até 3): ações específicas para esta turma — busca ativa, reforço, articulação saúde
6. CONFIANÇA: Alta | Média | Baixa — justificativa
"""

SCHOOL_ANALYSIS = """\
Você é um analista de redes de ensino especializado em dados educacionais brasileiros.
Analise os indicadores da escola nas 4 dimensões abaixo: Presença, Desempenho, Equidade e Saúde.

=== DADOS DA ESCOLA ===
{context}

=== PERGUNTA DO GESTOR ===
{question}

=== FORMATO ESPERADO ===
1. DIAGNÓSTICO GERAL (2–3 frases): situação vs benchmarks IBGE e estaduais
2. DIMENSÃO MAIS CRÍTICA (1): Presença | Desempenho | Equidade | Saúde — qual está pior?
3. PONTOS CRÍTICOS (até 3): com dados específicos (ex: "ausência 32% vs IBGE 18%")
4. PONTOS POSITIVOS (até 2): o que a escola faz melhor que o contexto regional
5. INTERVENÇÕES PRIORITÁRIAS (até 3): por impacto esperado, do maior para o menor
6. CONFIANÇA: Alta | Média | Baixa — se dados parciais, especifique qual dimensão está cega
"""

MUNICIPALITY_ANALYSIS = """\
Você é um especialista em gestão de redes educacionais municipais no Brasil.
Analise o diagnóstico do município abaixo e produza orientações para a secretaria municipal de educação.

=== DADOS DO MUNICÍPIO ===
{context}

=== PERGUNTA DO GESTOR ===
{question}

=== FORMATO ESPERADO ===
1. PANORAMA MUNICIPAL (2–3 frases): situação geral vs contexto IBGE e estado
2. ESCOLAS EM SITUAÇÃO CRÍTICA (até 5): listar com o dado mais preocupante de cada
3. COBERTURA DIGITAL (1 frase): % de escolas sem diário eletrônico e impacto na visibilidade dos dados
4. EQUIDADE (1–2 frases): análise racial e socioeconômica se dados disponíveis
5. INTERVENÇÕES MUNICIPAIS (até 3): ações que a secretaria pode tomar — não a escola individual
6. CONFIANÇA: Alta | Média | Baixa — com base na cobertura de dados disponíveis
"""

STATE_ANALYSIS = """\
Você é um especialista em políticas educacionais estaduais no Brasil.
Analise os indicadores do estado abaixo e produza orientações para a SEDUC.

=== DADOS DO ESTADO ===
{context}

=== PERGUNTA DO GESTOR ===
{question}

=== FORMATO ESPERADO ===
1. PANORAMA ESTADUAL (2–3 frases): IDEB, fluxo e distorção — comparação implícita com meta nacional
2. DESIGUALDADE RACIAL (2–3 frases): o que os dados PNAD revelam sobre equidade racial no estado
3. DESIGUALDADE DE GÊNERO (1–2 frases): gaps por gênero em analfabetismo e anos de estudo
4. MUNICÍPIOS MAIS VULNERÁVEIS (até 5): destacar por analfabetismo adulto e atraso escolar
5. POLÍTICAS PRIORITÁRIAS (até 3): por impacto esperado — foco em reduções de disparidade
6. CONFIANÇA: Alta | Média | Baixa — especificar se municípios têm dados IBGE incompletos
"""

GENERIC_QUESTION = """\
Você é um especialista em dados educacionais brasileiros.
Responda com base apenas nos dados fornecidos. Não invente informações.

=== CONTEXTO DISPONÍVEL ===
{context}

=== PERGUNTA ===
{question}

Seja objetivo. Se os dados não forem suficientes para responder com confiança, diga isso.
"""
```

---

## 9. `src/rag/llm_client.py`

```python
# src/rag/llm_client.py
"""
Interface única para LLM remoto. Suporta OpenAI (GPT), Gemini Flash e Ollama.
Trocar provider = mudar LLM_PROVIDER no ambiente.

── DECISÃO ARQUITETURAL ─────────────────────────────────────────────────────
  Embedding (sentence-transformers) → SEMPRE LOCAL
    • Roda no mesmo container Airflow/API, sem chamada de rede
    • Modelo: paraphrase-multilingual-MiniLM-L12-v2 carregado em RAM (~90MB)
    • Motivo: volume alto (N alunos por refresh), custo zero, latência < 1s/batch
    • Não usar API de embedding (OpenAI, Google) — custo proporcional ao volume

  LLM (síntese / resposta ao gestor) → REMOTO via API
    • Chamada pontual por pergunta do gestor — baixo volume, latência tolerada
    • Provider padrão: OpenAI GPT-4o-mini (melhor custo/benefício para português)
    • Alternativa: Gemini Flash (free tier para prototipação)
    • Fallback local: Ollama (desenvolvimento offline / sem acesso à internet)
─────────────────────────────────────────────────────────────────────────────

Env vars:
  LLM_PROVIDER:    "openai" (padrão) | "gemini" | "ollama"
  OPENAI_API_KEY:  chave da API OpenAI
  OPENAI_MODEL:    gpt-4o-mini (padrão) | gpt-4o | gpt-3.5-turbo
  GEMINI_API_KEY:  chave da API Google AI Studio
  OLLAMA_BASE_URL: http://localhost:11434 (padrão)
  OLLAMA_MODEL:    llama3.2 (padrão)
"""
import logging
import os
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

_MAX_TOKENS_OUT  = 1024
_TEMPERATURE     = 0.2    # baixo — respostas mais determinísticas e factuais


class LLMProvider(ABC):
    @abstractmethod
    def ask(self, context: str, question: str, template: str) -> str: ...


class OpenAIProvider(LLMProvider):
    """OpenAI GPT — provider padrão. Melhor custo/benefício para português."""

    def __init__(self) -> None:
        from openai import OpenAI
        self._client     = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        self._model_name = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

    def ask(self, context: str, question: str, template: str) -> str:
        prompt = template.format(context=context, question=question)
        response = self._client.chat.completions.create(
            model=self._model_name,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=_MAX_TOKENS_OUT,
            temperature=_TEMPERATURE,
        )
        return response.choices[0].message.content


class GeminiProvider(LLMProvider):
    """Google Gemini Flash — free tier suficiente para uso inicial."""

    def __init__(self) -> None:
        import google.generativeai as genai
        genai.configure(api_key=os.environ["GEMINI_API_KEY"])
        self._model = genai.GenerativeModel("gemini-1.5-flash")

    def ask(self, context: str, question: str, template: str) -> str:
        prompt = template.format(context=context, question=question)
        response = self._model.generate_content(
            prompt,
            generation_config={"max_output_tokens": _MAX_TOKENS_OUT, "temperature": _TEMPERATURE},
        )
        return response.text


class OllamaProvider(LLMProvider):
    """Ollama local — sem custo de API, requer CPU/GPU adequada."""

    def __init__(self) -> None:
        import ollama
        self._client     = ollama.Client(host=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"))
        self._model_name = os.environ.get("OLLAMA_MODEL", "llama3.2")

    def ask(self, context: str, question: str, template: str) -> str:
        prompt = template.format(context=context, question=question)
        response = self._client.generate(
            model=self._model_name,
            prompt=prompt,
            options={"num_predict": _MAX_TOKENS_OUT, "temperature": _TEMPERATURE},
        )
        return response["response"]


def get_llm_client() -> LLMProvider:
    """
    Factory — lê LLM_PROVIDER do ambiente. Falha rápido se mal configurado.

    Não confundir com o modelo de embedding: sentence-transformers é sempre
    local (get_model() em student_embedder.py) e nunca passa por aqui.
    Este factory é exclusivo para o LLM de síntese/resposta ao gestor.
    """
    provider = os.environ.get("LLM_PROVIDER", "openai").lower()
    if provider == "openai":
        logger.info("LLM provider: OpenAI (%s)", os.environ.get("OPENAI_MODEL", "gpt-4o-mini"))
        return OpenAIProvider()
    elif provider == "gemini":
        logger.info("LLM provider: Gemini Flash")
        return GeminiProvider()
    elif provider == "ollama":
        logger.info("LLM provider: Ollama (%s)", os.environ.get("OLLAMA_MODEL", "llama3.2"))
        return OllamaProvider()
    raise ValueError(f"LLM_PROVIDER inválido: '{provider}'. Use 'openai', 'gemini' ou 'ollama'.")
```

---

## 10. `src/rag/rag_pipeline.py`

```python
# src/rag/rag_pipeline.py
"""
Orquestra o pipeline RAG completo por granularidade.
Stateless — contexto remontado por request.

Cada ask_about_*() segue o mesmo padrão:
  1. Log hash da pergunta (sem conteúdo)
  2. Retrieval do contexto via Retriever
  3. Construção do contexto textual via context_builder
  4. Chamada LLM com template correto
  5. Retorno RAGResponse com métricas de qualidade
"""
import hashlib
import logging
import time
from dataclasses import dataclass
from typing import Any
import numpy as np
import pandas as pd

from .retriever import Retriever
from .context_builder import (
    build_student_context, build_classroom_context, build_school_context,
    build_municipality_context, build_state_context,
)
from .prompt_templates import (
    STUDENT_ANALYSIS, CLASSROOM_ANALYSIS, SCHOOL_ANALYSIS,
    MUNICIPALITY_ANALYSIS, STATE_ANALYSIS, GENERIC_QUESTION,
)
from .llm_client import LLMProvider
from .granularity import Granularity
from ..embeddings.student_embedder import embed_students, student_to_text

logger = logging.getLogger(__name__)


@dataclass
class RAGResponse:
    answer:       str
    context_len:  int        # chars do contexto enviado ao LLM
    latency_ms:   int
    model_used:   str
    data_quality: str        # "completo" | "sem_diario" | "sem_notas" | "parcial"
    granularity:  str        # granularidade da resposta


def _qhash(q: str) -> str:
    return hashlib.md5(q.encode()).hexdigest()[:8]


def _assess_quality(ctx: dict[str, Any] | None) -> str:
    if ctx is None:
        return "not_found"
    tem_diario = ctx.get("tem_diario", True)
    tem_notas  = ctx.get("tem_notas",  True)
    if tem_diario and tem_notas:
        return "completo"
    if not tem_diario and not tem_notas:
        return "parcial"
    return "sem_diario" if not tem_diario else "sem_notas"


class RAGPipeline:
    """
    Instanciar uma vez por processo (lifespan FastAPI).
    Retriever e LLM são injetados para facilitar testes.
    """

    def __init__(self, retriever: Retriever, llm: LLMProvider) -> None:
        self._retriever = retriever
        self._llm       = llm

    # ── Aluno ─────────────────────────────────────────────────────────────────
    def ask_about_student(self, student_id: str, question: str) -> RAGResponse:
        t0 = time.monotonic()
        logger.info("RAG:aluno hash=%s", _qhash(question))

        ctx = self._retriever.get_student_context(student_id)
        if ctx is None:
            return RAGResponse("Aluno não encontrado.", 0, 0, "none", "not_found", "aluno")

        # Embedding para busca de similares
        row       = _ctx_to_student_series(ctx)
        embedding = embed_students(pd.DataFrame([row]))[0]
        similar   = self._retriever.find_similar_students(embedding, student_id)

        context  = build_student_context(ctx, similar)
        quality  = _assess_quality(ctx)
        answer   = self._llm.ask(context, question, STUDENT_ANALYSIS)
        latency  = int((time.monotonic() - t0) * 1000)
        logger.info("RAG:aluno done latency=%dms quality=%s", latency, quality)
        return RAGResponse(answer, len(context), latency, type(self._llm).__name__, quality, "aluno")

    # ── Turma ─────────────────────────────────────────────────────────────────
    def ask_about_classroom(
        self, school_id: str, classroom_name: str, question: str,
        discipline_filter: str = "",
    ) -> RAGResponse:
        t0 = time.monotonic()
        logger.info("RAG:turma hash=%s", _qhash(question))

        ctx     = self._retriever.get_classroom_context(school_id, classroom_name, discipline_filter)
        context = build_classroom_context(ctx or {})
        quality = _assess_quality(ctx)
        answer  = self._llm.ask(context, question, CLASSROOM_ANALYSIS)
        latency = int((time.monotonic() - t0) * 1000)
        logger.info("RAG:turma done latency=%dms", latency)
        return RAGResponse(answer, len(context), latency, type(self._llm).__name__, quality, "turma")

    # ── Escola ────────────────────────────────────────────────────────────────
    def ask_about_school(self, school_id: str, question: str) -> RAGResponse:
        t0 = time.monotonic()
        logger.info("RAG:escola hash=%s", _qhash(question))

        ctx = self._retriever.get_school_context(school_id)
        if ctx is None:
            return RAGResponse("Escola não encontrada.", 0, 0, "none", "not_found", "escola")

        # Escolas similares via vector index
        similar_schools: list[dict] = []
        if ctx.get("escola_embedding") is not None:
            sim_emb = np.array(ctx["escola_embedding"])
            similar_schools = self._retriever.find_similar_schools(sim_emb, school_id)

        context = build_school_context(ctx, similar_schools)
        quality = _assess_quality(ctx)
        answer  = self._llm.ask(context, question, SCHOOL_ANALYSIS)
        latency = int((time.monotonic() - t0) * 1000)
        logger.info("RAG:escola done latency=%dms quality=%s", latency, quality)
        return RAGResponse(answer, len(context), latency, type(self._llm).__name__, quality, "escola")

    # ── Município ─────────────────────────────────────────────────────────────
    def ask_about_municipality(
        self, municipio_name: str, uf: str, question: str
    ) -> RAGResponse:
        t0 = time.monotonic()
        logger.info("RAG:municipio hash=%s", _qhash(question))

        ctx     = self._retriever.get_municipality_context(municipio_name, uf)
        if ctx is None:
            return RAGResponse("Município não encontrado.", 0, 0, "none", "not_found", "municipio")
        context = build_municipality_context(ctx)
        answer  = self._llm.ask(context, question, MUNICIPALITY_ANALYSIS)
        latency = int((time.monotonic() - t0) * 1000)
        logger.info("RAG:municipio done latency=%dms", latency)
        return RAGResponse(answer, len(context), latency, type(self._llm).__name__, "completo", "municipio")

    # ── Estado ────────────────────────────────────────────────────────────────
    def ask_about_state(self, uf: str, question: str) -> RAGResponse:
        t0 = time.monotonic()
        logger.info("RAG:estado hash=%s", _qhash(question))

        ctx     = self._retriever.get_state_context(uf)
        if ctx is None:
            return RAGResponse("Estado não encontrado.", 0, 0, "none", "not_found", "estado")
        context = build_state_context(ctx)
        answer  = self._llm.ask(context, question, STATE_ANALYSIS)
        latency = int((time.monotonic() - t0) * 1000)
        logger.info("RAG:estado done latency=%dms", latency)
        return RAGResponse(answer, len(context), latency, type(self._llm).__name__, "completo", "estado")


def _ctx_to_student_series(ctx: dict) -> pd.Series:
    """Converte contexto Neo4j para Series compatível com student_to_text."""
    p  = ctx.get("perfil", {})
    f  = ctx.get("frequencia", {})
    ei = ctx.get("escola_ibge", {})
    nota = next((n["nota_final"] for n in ctx.get("notas", []) if n.get("nota_final")), None)
    return pd.Series({
        "gender_bin":         1 if str(p.get("gender","")).upper().startswith("F") else 0,
        "ethnicity_raw":      p.get("ethnicity", "Não Declarada"),
        "has_deficiency":     1 if p.get("has_deficiency") else 0,
        "bolsa_familia":      1 if p.get("bolsa_familia") else 0,
        "residence_zone_enc": 0 if str(p.get("residence_zone","")).lower() == "rural" else 1,
        "tem_diario":         1 if f.get("tem_diario") else 0,
        "taxa_ausencia":      (f.get("taxa_ausencia") or 0) / 100,
        "nota_final_norm":    nota,
        "has_malnutrition":   0,
        "has_diabetes":       0,
        "has_hypertension":   0,
        "has_obesity":        0,
        "has_anemia":         0,
        "has_celiac":         0,
        "uf":                 ei.get("uf", "?"),
        "muni_freq_liq_fund": ei.get("muni_freq_liq"),
        "est_ideb_af":        ei.get("est_ideb_af"),
        "est_taxa_abandono":  ei.get("est_taxa_abandono") or 0,
        "risk_cluster":       p.get("risk_cluster"),
    })
```

---

## 11. `dags/dag__rag_embedding_refresh.py`

```python
# dags/dag__rag_embedding_refresh.py
"""
Refresh semanal de embeddings: EF1 (alunos) + escolas.
Executa após dag__ml_feature_engineering (segunda-feira 5h).
"""
from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator

_DEFAULT_ARGS = {
    "owner":        "ml-team",
    "retries":      1,
    "retry_delay":  timedelta(minutes=10),
}


def refresh_student_embeddings(**ctx):
    """Gera embeddings para alunos EF1 e escreve no Neo4j."""
    import os
    import pandas as pd
    from neo4j import GraphDatabase
    from src.embeddings.student_embedder import embed_students
    from src.embeddings.neo4j_vector_writer import write_embeddings
    from src.ml.features.neo4j_extractor import Neo4jExtractor
    from src.ml.features.feature_pipeline import encode_categoricals

    ext = Neo4jExtractor.from_env()
    df  = encode_categoricals(ext.extract_ef1())
    ext.close()

    embeddings = embed_students(df)
    driver     = GraphDatabase.driver(
        os.environ["NEO4J_URI"],
        auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]),
    )
    write_embeddings(driver, df["student_id"].tolist(), embeddings, entity="student")
    driver.close()
    ctx["ti"].xcom_push(key="n_students_embedded", value=len(df))


def refresh_school_embeddings(**ctx):
    """
    Gera embeddings para escolas usando school_aggregator + school_embedder.
    Escreve os vetores e também score_saude/nivel_saude no nó School.
    """
    import os
    import pandas as pd
    from neo4j import GraphDatabase
    from src.embeddings.school_embedder import embed_schools
    from src.embeddings.neo4j_vector_writer import write_embeddings
    from src.ml.features.neo4j_extractor import Neo4jExtractor
    from src.ml.features.school_aggregator import compute_school_metrics

    ext = Neo4jExtractor.from_env()
    df_raw = ext.extract_school_features()
    ext.close()

    df_schools = compute_school_metrics(df_raw)
    embeddings = embed_schools(df_schools)

    driver = GraphDatabase.driver(
        os.environ["NEO4J_URI"],
        auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]),
    )
    write_embeddings(driver, df_schools["school_id"].tolist(), embeddings, entity="school")

    # Persiste score_saude e nivel_saude no nó School para o Retriever ler
    with driver.session() as session:
        rows = [
            {"school_id": row["school_id"], "score": row["score_saude"], "nivel": row["nivel_saude"]}
            for _, row in df_schools.iterrows()
        ]
        session.run(
            "UNWIND $rows AS r MATCH (sch:School {id: r.school_id}) "
            "SET sch.score_saude = r.score, sch.nivel_saude = r.nivel",
            rows=rows,
        )
    driver.close()
    ctx["ti"].xcom_push(key="n_schools_embedded", value=len(df_schools))


with DAG(
    dag_id="dag__rag_embedding_refresh",
    default_args=_DEFAULT_ARGS,
    schedule_interval="0 5 * * 1",    # segunda-feira 5h — após feature engineering (3h)
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["rag", "embeddings", "ml"],
) as dag:
    t_students = PythonOperator(
        task_id="refresh_student_embeddings",
        python_callable=refresh_student_embeddings,
    )
    t_schools = PythonOperator(
        task_id="refresh_school_embeddings",
        python_callable=refresh_school_embeddings,
    )
    # Paraleliza — alunos e escolas são independentes
    [t_students, t_schools]
```

---

## 12. Mapa de Perguntas por Granularidade

### Aluno
| Pergunta | Retriever | Template |
|---|---|---|
| "Por que João tem 85% de risco de evadir?" | `get_student_context` + `find_similar_students` | `STUDENT_ANALYSIS` |
| "O que aconteceu com alunos com o mesmo perfil de João?" | `find_similar_students` (desfecho) | `STUDENT_ANALYSIS` |
| "Qual a trajetória de notas do bimestre 1 para 2?" | `get_student_context` (notas.nota_g1 → nota_g2) | `STUDENT_ANALYSIS` |
| "Esse aluno tem condições de saúde que explicam as faltas?" | `get_student_context` (saude + frequencia) | `STUDENT_ANALYSIS` |

### Turma
| Pergunta | Retriever | Template |
|---|---|---|
| "Qual o nível de risco da Turma C do 7º ano?" | `get_classroom_context` (Q8 soma_sinais_risco) | `CLASSROOM_ANALYSIS` |
| "A turma está pior que o esperado para o município?" | `get_classroom_context` (delta_freq vs IBGE) | `CLASSROOM_ANALYSIS` |
| "Qual o gap de nota dentro da turma?" | `get_classroom_context` (cv_nota_pct, dispersao_nota) | `CLASSROOM_ANALYSIS` |
| "Quantos alunos da turma são de zona rural + Bolsa Família?" | `get_classroom_context` (n_rural, n_bolsistas) | `CLASSROOM_ANALYSIS` |

### Escola
| Pergunta | Retriever | Template |
|---|---|---|
| "Como nossa escola está comparada ao município?" | `get_school_context` (delta vs IBGE) | `SCHOOL_ANALYSIS` |
| "Qual dimensão está puxando nosso score de saúde pra baixo?" | `get_school_context` (4 dims) | `SCHOOL_ANALYSIS` |
| "Alunos de Bolsa Família têm nota muito menor que os outros?" | `get_school_context` (gap_bf) | `SCHOOL_ANALYSIS` |
| "Escolas similares à nossa conseguem resultados melhores?" | `get_school_context` + `find_similar_schools` | `SCHOOL_ANALYSIS` |
| "Qual turma da escola tem maior risco composto?" | `get_school_context` (top_turmas_risco) | `SCHOOL_ANALYSIS` |

### Município
| Pergunta | Retriever | Template |
|---|---|---|
| "Quais escolas do município estão em colapso?" | `get_municipality_context` (ranking ausência) | `MUNICIPALITY_ANALYSIS` |
| "Quantas escolas ainda não têm diário eletrônico?" | `get_municipality_context` (escolas_sem_diario) | `MUNICIPALITY_ANALYSIS` |
| "Como nosso município compara com o benchmark IBGE do estado?" | `get_municipality_context` (IBGE + QEdu estado) | `MUNICIPALITY_ANALYSIS` |
| "A desigualdade racial na rede é preocupante?" | `get_municipality_context` (PNAD racial estadual) | `MUNICIPALITY_ANALYSIS` |
| "Quais escolas têm maior concentração de BF e piores notas?" | `get_municipality_context` (escolas + pct_bf) | `MUNICIPALITY_ANALYSIS` |

### Estado
| Pergunta | Retriever | Template |
|---|---|---|
| "Como nosso estado está no IDEB vs a meta nacional?" | `get_state_context` (ideb_ai, ideb_af) | `STATE_ANALYSIS` |
| "A desigualdade racial no estado é pior que a nacional?" | `get_state_context` (PNAD racial) | `STATE_ANALYSIS` |
| "Quais municípios têm maior analfabetismo adulto?" | `get_state_context` (ranking municípios) | `STATE_ANALYSIS` |
| "O gap de gênero nos anos de estudo é grande?" | `get_state_context` (anosest_homem vs mulher) | `STATE_ANALYSIS` |
| "Que % de crianças estão fora da escola no estado?" | `get_state_context` (pct_fora_escola) | `STATE_ANALYSIS` |

---

## 13. Checklist de Implementação

### Vector Index
- [ ] `SHOW INDEXES WHERE type = 'VECTOR'` retorna ONLINE para `student_embedding` e `school_embedding`
- [ ] `student_embedding` dimension = 384 (não 512)
- [ ] `embed_students(df)` retorna shape `(N, 384)` sem erros

### Retriever
- [ ] `get_student_context(id)` retorna dict com chaves `perfil`, `frequencia`, `notas`, `saude`, `escola_ibge`, `turma` em < 2s
- [ ] `get_classroom_context(school_id, turma)` retorna `soma_sinais_risco` entre 0 e 1
- [ ] `get_school_context(school_id)` retorna `gap_bf`, `pct_abaixo5`, `taxa_ausencia_pct`
- [ ] `get_municipality_context(nome, uf)` retorna lista de escolas ordenada por ausência
- [ ] `get_state_context(uf)` retorna `analf_negro`, `analf_branco`, `ideb_af`
- [ ] `find_similar_students(emb, id)` retorna 5 resultados com `desfecho` preenchido
- [ ] `find_similar_schools(emb, id)` retorna 5 resultados com `nivel_saude`
- [ ] Nenhum método lança exceção quando Neo4j retorna null em campos IBGE

### Context Builder
- [ ] Nenhuma saída ultrapassa 16.000 chars
- [ ] `build_classroom_context` inclui `soma_sinais_risco` com nível (CRÍTICO/ALERTA/MODERADO)
- [ ] `build_school_context` inclui `delta_freq` vs IBGE com fonte (Municipal / Media_UF_Proxy)
- [ ] `build_municipality_context` ordena escolas por taxa_ausencia desc
- [ ] `build_state_context` inclui PNAD racial e PNAD gênero

### LLM
- [ ] `LLM_PROVIDER=openai` funciona com template correto por granularidade (padrão de produção)
- [ ] `LLM_PROVIDER=gemini` funciona para prototipação
- [ ] `LLM_PROVIDER=ollama` funciona para desenvolvimento offline
- [ ] Embedding não usa `LLM_PROVIDER` — `get_model()` de `student_embedder.py` é sempre local
- [ ] Resposta completa para aluno (retrieval + LLM) em < 15s P95

### Logs e Privacidade
- [ ] Nenhum log contém `student_id` completo
- [ ] Nenhum log contém texto da pergunta — apenas hash MD5 8 chars
- [ ] Log de latência por granularidade em cada chamada

### DAG
- [ ] `dag__rag_embedding_refresh` executa sem erro na segunda-feira
- [ ] Task `refresh_school_embeddings` persiste `score_saude` e `nivel_saude` no nó School
- [ ] Tasks de aluno e escola rodam em paralelo (sem dependência entre si)