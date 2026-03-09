import logging
import time
from typing import Any
import pandas as pd
from neo4j import Driver

from src.rag.granularity import identify_granularity, Granularity
from src.rag.retriever import Retriever
from src.rag.context_builder import (
    build_student_context,
    build_classroom_context,
    build_school_context,
    build_municipality_context,
    build_state_context,
)
from src.rag.prompt_templates import (
    STUDENT_ANALYSIS,
    CLASSROOM_ANALYSIS,
    SCHOOL_ANALYSIS,
    MUNICIPALITY_ANALYSIS,
    STATE_ANALYSIS,
    GENERIC_QUESTION,
)
from src.rag.llm_client import get_llm_client
from src.embeddings.student_embedder import student_to_text
from src.embeddings.school_embedder import school_to_text

logger = logging.getLogger(__name__)


class RAGPipeline:
    """Orquestrador do RAG: Granularidade -> Neo4j -> Contexto -> LLM."""

    def __init__(self, driver: Driver):
        self._retriever = Retriever(driver)
        self._llm = get_llm_client()

    def answer_question(self, question: str, entity_id: str, hint: str | None = None) -> dict[str, Any]:
        """
        Ponto de entrada principal comum para a UI/API.
        Descobre a granularidade, constrói e roteia a inferência.
        Retorna o dicionário com a resposta interpretada em linguagem natural e a latência.
        """
        t0 = time.time()
        gran = identify_granularity(question, hint)
        logger.info("RAG request recebida. Granularidade identificada: %s", gran)

        answer = ""
        metadata = {"granularity": gran.value, "entity_id": entity_id}

        if gran == Granularity.ALUNO:
            answer = self.ask_about_student(entity_id, question)
        elif gran == Granularity.TURMA:
            answer = self.ask_about_classroom(entity_id, question)
        elif gran == Granularity.ESCOLA:
            answer = self.ask_about_school(entity_id, question)
        elif gran == Granularity.MUNICIPIO:
            answer = self.ask_about_municipality(entity_id, question)
        elif gran == Granularity.ESTADO:
            answer = self.ask_about_state(entity_id, question)
        else:
            answer = "Granularidade não reconhecida para a pergunta."

        t1 = time.time()
        logger.info("Resposta compilada em %.2f segundos.", t1 - t0)
        
        return {
            "answer": answer,
            "latency_seconds": round(t1 - t0, 2),
            "metadata": metadata
        }

    def ask_about_student(self, student_id: str, question: str) -> str:
        ctx_dict = self._retriever.get_student_context(student_id)
        if not ctx_dict:
            return f"Aluno {student_id} não encontrado na base de dados."

        flat_series = pd.Series()
        if "perfil" in ctx_dict: flat_series = pd.concat([flat_series, pd.Series(ctx_dict["perfil"])])
        if "frequencia" in ctx_dict: flat_series = pd.concat([flat_series, pd.Series(ctx_dict["frequencia"])])
        
        text_rep = student_to_text(flat_series)
        similar = self._retriever.find_similar_students(student_id, text_rep, top_k=5)
        context_str = build_student_context(ctx_dict, similar)

        return self._llm.ask(context_str, question, STUDENT_ANALYSIS)

    def ask_about_classroom(self, classroom_id: str, question: str) -> str:
        ctx_dict = self._retriever.get_classroom_context(classroom_id)
        if not ctx_dict:
            return f"Turma {classroom_id} não encontrada."
            
        context_str = build_classroom_context(ctx_dict)
        return self._llm.ask(context_str, question, CLASSROOM_ANALYSIS)

    def ask_about_school(self, school_id: str, question: str) -> str:
        ctx_dict = self._retriever.get_school_context(school_id)
        if not ctx_dict:
            return f"Escola {school_id} não encontrada."
            
        text_rep = school_to_text(pd.Series(ctx_dict))
        similar = self._retriever.find_similar_schools(school_id, text_rep, top_k=3)
        context_str = build_school_context(ctx_dict, similar)
        
        return self._llm.ask(context_str, question, SCHOOL_ANALYSIS)

    def ask_about_municipality(self, municipality_id: str, question: str) -> str:
        ctx_dict = self._retriever.get_municipality_context(municipality_id)
        if not ctx_dict:
            return f"Município {municipality_id} não encontrado."
            
        context_str = build_municipality_context(ctx_dict)
        return self._llm.ask(context_str, question, MUNICIPALITY_ANALYSIS)

    def ask_about_state(self, uf: str, question: str) -> str:
        ctx_dict = self._retriever.get_state_context(uf)
        if not ctx_dict:
            return f"Estado {uf} não encontrado."
            
        context_str = build_state_context(ctx_dict)
        return self._llm.ask(context_str, question, STATE_ANALYSIS)
