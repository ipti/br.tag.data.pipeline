# RAG (Retrieval-Augmented Generation) Layer (`src/rag`)

Este módulo é o núcleo de comunicação de inteligência com o gestor educacional. Ele consolida o acesso contextual (Retrieval) extraindo as métricas do Grafo, executa restrições textuais baseadas no teto de tokens, seleciona os templates do framework do assistente RAG e invoca as chaves para os LLMs isoladamente.

O conceito chave implementado é que *o retriever não processa respostas de prompt e o LLM jamais acessa o Neo4j diretamente*. Tudo é determinístico até a fase do `rag_pipeline`.

## Estrutura do Módulo

- **`granularity.py`**: Intercepta a pergunta orgânica e categoriza de acordo com o contexto operacional (ex: Aluno, Município, Estado etc.) usando RegEx e sem gastar quotas de API de rede.
- **`retriever.py`**: Core class que contém queries padronizadas em `Cypher` desenhadas para extrair métricas multi-esfera com suporte unificado aos Fallbacks do IBGE, SHAP Matrix Risk, e vetorização local de similaridade de nós próximos usando `Vector Search`.
- **`context_builder.py`**: Faz parser dos dicts crus passados pelo `retriever` para Strings compactas não excedendo limites fixos de aproximadamente 4000 tokens (16.000 chars delimitados conservadoramente), prevenindo falha de "Janela Excedida" em LLMs de baixo escopo.
- **`prompt_templates.py`**: Concentra exclusivamente as Strings paramétricas estáticas que irão orientar as diretrizes do Bot/Assitente educacional em sua formulação formativa e de diagnóstico, divididas por esferas hierárquicas.
- **`llm_client.py`**: Driver de interface Factory e escalável suportando perfeitamente a mudança local/remota provida pelo `LLM_PROVIDER`. Integra instâncias para GPT, Gemini e local com Ollama.
- **`rag_pipeline.py`**: Maestro de requests Stateless instanciado pelas requisições superiores via Controllers ou FastAPI. Orquestra a injeção do Retrieval -> Template -> Chaining limitante e a saída padronizada das latências de operação e "saúde" do dado devolvido na consulta (por exemplo, relatando se o dado do EWS é cego de Notas).
