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
    """
    RAG orchestrator routing questions through granularity detection and hierarchical synthesis.

    This class encapsulates the complete retrieval-augmented generation workflow:
    1. Granularity detection: Map natural language questions to entity scopes
    2. Context retrieval: Execute Neo4j Cypher queries and embed-based similarity search
    3. Context serialization: Format retrieved data into prompt-ready natural language
    4. LLM synthesis: Invoke the configured LLM provider with structured prompts
    5. Latency tracking: Record end-to-end pipeline duration for monitoring
    """

    def __init__(self, driver: Driver):
        """
        Initialize the RAG pipeline with Neo4j driver and LLM provider.

        Args:
            driver (Driver): Active Neo4j driver for executing Cypher queries.
        """
        self._retriever = Retriever(driver)
        self._llm = get_llm_client()

    def answer_question(
        self, question: str, entity_id: str, hint: str | None = None
    ) -> dict[str, Any]:
        """
        Execute the RAG pipeline and return a synthesized response with latency metadata.

        This method orchestrates the complete flow: granularity detection → context retrieval →
        LLM synthesis → metadata assembly. It is the primary entry point for UI and API clients.

        Args:
            question (str): Free-form question from an educational manager or administrator,
                in Portuguese (e.g., "Como vai o João?", "A turma 7A está com muita falta").
            entity_id (str): The specific entity identifier for the question context
                (student ID, classroom ID, school ID, municipality ID, or state abbreviation).
            hint (str, optional): Explicit granularity hint (e.g., 'aluno', 'escola', 'estado').
                If provided and valid, overrides automatic granularity detection. Defaults to None.

        Returns:
            dict[str, Any]: Response dictionary with keys:
                - 'answer' (str): LLM-synthesized response (up to 1024 tokens), formatted
                  according to the detected granularity-specific template.
                - 'latency_seconds' (float): End-to-end pipeline duration (rounded to 2 decimals).
                - 'metadata' (dict): Debugging context with keys:
                    - 'granularity': Detected granularity level (string).
                    - 'entity_id': Entity identifier passed to this method.

        Raises:
            No exceptions raised; returns response with error message if entity not found.
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
            "metadata": metadata,
        }

    def ask_about_student(self, student_id: str, question: str) -> str:
        """
        Answer a question about a specific student.

        Retrieves the student's comprehensive profile from Neo4j, generates a narrative
        text representation, performs embedding-based similarity search for contextual
        peer comparison, serializes the full context, and invokes the LLM with the
        student-specific analysis template.

        Args:
            student_id (str): Student identifier (Neo4j node property).
            question (str): Educational manager's question about the student.

        Returns:
            str: LLM-synthesized response addressing the question in the format specified
                by the STUDENT_ANALYSIS template (situation, risks, context, interventions, confidence).

        Raises:
            No exceptions raised; returns error message if student not found.
        """
        ctx_dict = self._retriever.get_student_context(student_id)
        if not ctx_dict:
            return f"Student {student_id} not found in database."

        flat_series = pd.Series()
        if "perfil" in ctx_dict:
            flat_series = pd.concat([flat_series, pd.Series(ctx_dict["perfil"])])
        if "frequencia" in ctx_dict:
            flat_series = pd.concat([flat_series, pd.Series(ctx_dict["frequencia"])])

        text_rep = student_to_text(flat_series)
        similar = self._retriever.find_similar_students(student_id, text_rep, top_k=5)
        context_str = build_student_context(ctx_dict, similar)

        return self._llm.ask(context_str, question, STUDENT_ANALYSIS)

    def ask_about_classroom(self, classroom_id: str, question: str) -> str:
        """
        Answer a question about a specific classroom.

        Retrieves the classroom's aggregated metrics (composition, attendance, performance,
        risk signals) from Neo4j, serializes the context, and invokes the LLM with the
        classroom-specific analysis template.

        Args:
            classroom_id (str): Classroom identifier (Neo4j node property).
            question (str): Educational manager's question about the classroom.

        Returns:
            str: LLM-synthesized response addressing the question in the format specified
                by the CLASSROOM_ANALYSIS template (diagnosis, risk dimensions, social profile,
                IBGE comparison, interventions, confidence).

        Raises:
            No exceptions raised; returns error message if classroom not found.
        """
        ctx_dict = self._retriever.get_classroom_context(classroom_id)
        if not ctx_dict:
            return f"Classroom {classroom_id} not found."

        context_str = build_classroom_context(ctx_dict)
        return self._llm.ask(context_str, question, CLASSROOM_ANALYSIS)

    def ask_about_school(self, school_id: str, question: str) -> str:
        """
        Answer a question about a specific school.

        Retrieves the school's comprehensive analytics across four dimensions (presence,
        performance, equity, health) from Neo4j, generates a narrative text representation,
        performs embedding-based similarity search for comparative school reference,
        serializes the context, and invokes the LLM with the school-specific analysis template.

        Args:
            school_id (str): School identifier (Neo4j node property).
            question (str): Educational manager's question about the school.

        Returns:
            str: LLM-synthesized response addressing the question in the format specified
                by the SCHOOL_ANALYSIS template (general diagnosis, most critical dimension,
                critical points, positive aspects, priority interventions, confidence).

        Raises:
            No exceptions raised; returns error message if school not found.
        """
        ctx_dict = self._retriever.get_school_context(school_id)
        if not ctx_dict:
            return f"School {school_id} not found."

        text_rep = school_to_text(pd.Series(ctx_dict))
        similar = self._retriever.find_similar_schools(school_id, text_rep, top_k=3)
        context_str = build_school_context(ctx_dict, similar)

        return self._llm.ask(context_str, question, SCHOOL_ANALYSIS)

    def ask_about_municipality(self, municipality_id: str, question: str) -> str:
        """
        Answer a question about a specific municipality.

        Retrieves the municipality's school census and aggregated metrics (enrollment,
        digital coverage, performance rankings) from Neo4j, serializes the context with
        IBGE socioeconomic and QEDU benchmark data, and invokes the LLM with the
        municipality-specific analysis template for secretariat decision-making.

        Args:
            municipality_id (str): Municipality identifier (Neo4j node property).
            question (str): Educational secretariat question about the municipality.

        Returns:
            str: LLM-synthesized response addressing the question in the format specified
                by the MUNICIPALITY_ANALYSIS template (municipal overview, critical schools,
                digital coverage, equity analysis, secretariat interventions, confidence).

        Raises:
            No exceptions raised; returns error message if municipality not found.
        """
        ctx_dict = self._retriever.get_municipality_context(municipality_id)
        if not ctx_dict:
            return f"Municipality {municipality_id} not found."

        context_str = build_municipality_context(ctx_dict)
        return self._llm.ask(context_str, question, MUNICIPALITY_ANALYSIS)

    def ask_about_state(self, uf: str, question: str) -> str:
        """
        Answer a question about a specific state.

        Retrieves the state's comprehensive quality (QEDU IDEB, flux, proficiency) and
        equity indicators (PNAD racial and gender gaps) from Neo4j, serializes the context
        with municipal vulnerability rankings, and invokes the LLM with the state-specific
        analysis template for state education policy decision-making.

        Args:
            uf (str): State abbreviation (e.g., 'BA', 'RJ', 'MG'). Case-insensitive.
            question (str): State education policy question.

        Returns:
            str: LLM-synthesized response addressing the question in the format specified
                by the STATE_ANALYSIS template (state panorama, racial inequality, gender
                inequality, vulnerable municipalities, priority policies, confidence).

        Raises:
            No exceptions raised; returns error message if state not found.
        """
        ctx_dict = self._retriever.get_state_context(uf)
        if not ctx_dict:
            return f"State {uf} not found."

        context_str = build_state_context(ctx_dict)
        return self._llm.ask(context_str, question, STATE_ANALYSIS)
