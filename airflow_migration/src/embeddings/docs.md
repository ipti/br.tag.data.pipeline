# Embeddings Generation Layer (`src/embeddings`)

Esta pasta contém o módulo responsável por transformar features de Machine Learning ou atributos agrupados da infraestrutura em representações vetoriais densas. Elas são gravadas diretamente no Neo4J e servem como principal atalho de similaridade e contexto para a infraestrutura RAG (Retrieval-Augmented Generation). O processamento semântico usa o standard local HuggingFace para não onerar APIs externas (`sentence-transformers`).

## Arquivos do Módulo

**`student_embedder.py`**
Responsável por transformar todo o subconjunto paramétrico processado do estudante (`DEMO_FEATURES`, `HEALTH_FEATURES`, `FREQ_FEATURES`) em um descritivo linear de linguagem natural (~ 200 palavras). Ele então invoca o modelo vetorial nativo (ex: `paraphrase-multilingual-MiniLM-L12-v2`) via NumPy arrays e retorna um embedding multilingue altamente compatível. Tolerante a dados nulos, evitando corrupções no espaço vetorial.

**`school_embedder.py`**
Executa lógica semelhante ao módulo do aluno, mas agregando o espaço da escola. Foca em transformar atributos estatísticos como os níveis de saúde baseados em Q-Dimensions, notas de dependência (EF1/EF2) e infraestrutura do IBGE. Isso aproxima escolas localizadas em municípios diferentes baseando-se unicamente nas dores e carências em comum, tornando a inteligência acrônica a fronteiras estaduais fechadas.

**`neo4j_vector_writer.py`**
Wrapper transacional exclusivo para escrever os blocos matemáticos (`N, 384`) de forma serializada usando loteamento (Batches via `UNWIND`). Ele não consulta os Grafos (mantendo desacoplado da análise pura), mas aloca nos nós centrais `(Student)` e `(School)` de forma leve. Recomenda-se um batch maximo de 500 para mitigar riscos de OOM em instâncias menores de banco.
