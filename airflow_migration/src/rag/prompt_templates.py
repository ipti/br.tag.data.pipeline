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
