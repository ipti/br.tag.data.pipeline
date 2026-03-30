📚 Censo Escolar - Atlas Brasil
=====================================

:Schema: ``raw``
:Database: ``data-warehouse-tag``
:Fonte: Atlas Brasil (atlasbrasil.org.br)
:Período: 1991, 2000, 2010, 2011-2014
:Granularidade: Municipal
:Responsável: Equipe de Dados

----

Descrição
---------

Dados do **Censo Escolar brasileiro** extraídos do site do Atlas Brasil. O Atlas realiza um trabalho de agregação e enriquecimento dos dados originais do INEP (Instituto Nacional de Estudos e Pesquisas Educacionais Anísio Teixeira).

Estes dados são utilizados para enriquecer nossa base de estudantes e fornecer contexto educacional em nível municipal.

----

Tabela: Atlas_CensoEscolar_2011a2014_TodosMunc
----------------------------------------------

Contém indicadores educacionais agregados por município para o período de 2011 a 2014.

Principais Categorias de Dados
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**1. Matrículas por Rede (Pública/Privada)**

* Ensino Fundamental (2013-2017)
* Ensino Médio (2013-2017)

**2. Taxa de Distorção Idade-Série**

* Ensino Fundamental geral e por rede
* Ensino Médio geral e por rede
* Período: 2013-2017

**3. Taxa de Evasão**

* Ensino Fundamental e Médio
* Desagregado por rede (pública/privada)
* Período: 2013-2014

**4. IDEB (Índice de Desenvolvimento da Educação Básica)**

* Anos iniciais do Ensino Fundamental (2013, 2015, 2017)
* Anos finais do Ensino Fundamental (2013, 2015, 2017)

**5. Infraestrutura Escolar**

* Percentual de alunos em escolas com laboratório de informática
* Percentual de alunos em escolas com internet
* Por nível de ensino (Fundamental/Médio)

**6. Formação Docente**

* Percentual de docentes com formação adequada
* Desagregado por nível e rede de ensino

**7. Indicadores de Escolarização da População**

* Taxa de analfabetismo (15+, 18+, 25+ anos)
* Média de anos de estudo
* Taxa de frequência líquida (básico, fundamental, médio, superior)
* Percentual de conclusão por faixa etária

**8. Desagregações Demográficas (Censo 2013-2014)**

* Por raça/cor (Branco/Negro)
* Por sexo (Homem/Mulher)
* Por localização (Rural/Urbano)

----

Estrutura de Colunas
--------------------

.. list-table::
   :header-rows: 1
   :widths: 30 15 55

   * - Campo
     - Tipo
     - Descrição
   * - ``Territorialidades``
     - varchar(150)
     - Nome do município
   * - ``DeMatrculasDaRedePblicaNoEnsinoFundamental[Ano]``
     - real
     - Percentual de matrículas na rede pública - Ensino Fundamental
   * - ``DeMatrculasDaRedePblicaNoEnsinoMdio[Ano]``
     - real
     - Percentual de matrículas na rede pública - Ensino Médio
   * - ``TaxaDeDistoroIdadeSrieNoFundamental[Ano]``
     - real
     - Taxa de distorção idade-série no Fundamental
   * - ``TaxaDeEvasoNoEnsinoFundamental[Ano]``
     - real
     - Taxa de evasão no Ensino Fundamental
   * - ``IdebAnosIniciaisDoEnsinoFundamental[Ano]``
     - real
     - IDEB dos anos iniciais
   * - ``IdebAnosFinaisDoEnsinoFundamental[Ano]``
     - real
     - IDEB dos anos finais
   * - ``DeDocentesDoFundamentalComFormaoAdequada[Ano]``
     - real
     - % de docentes com formação adequada
   * - ``TaxaDeAnalfabetismo[Faixa][Ano]``
     - real
     - Taxa de analfabetismo por faixa etária
   * - ``MdiaDeAnosDeEstudo[Ano]``
     - real
     - Média de anos de estudo da população

.. note::
   [Ano] representa os anos disponíveis (2012-2017, conforme a métrica)

----

Exemplos de Uso
---------------

**Consultar IDEB por município (2017)**

.. code-block:: sql

   SELECT 
       Territorialidades,
       IdebAnosIniciaisDoEnsinoFundamental2017,
       IdebAnosFinaisDoEnsinoFundamental2017
   FROM raw.Atlas_CensoEscolar_2011a2014_TodosMunc
   WHERE IdebAnosIniciaisDoEnsinoFundamental2017 IS NOT NULL
   ORDER BY IdebAnosIniciaisDoEnsinoFundamental2017 DESC;

**Analisar evolução da taxa de distorção**

.. code-block:: sql

   SELECT 
       Territorialidades,
       TaxaDeDistoroIdadeSrieNoFundamental2013 AS Taxa_2013,
       TaxaDeDistoroIdadeSrieNoFundamental2017 AS Taxa_2017,
       (TaxaDeDistoroIdadeSrieNoFundamental2017 - 
        TaxaDeDistoroIdadeSrieNoFundamental2013) AS Variacao
   FROM raw.Atlas_CensoEscolar_2011a2014_TodosMunc
   ORDER BY Variacao;

----

Observações Importantes
-----------------------

* **Granularidade**: Dados agregados a nível **municipal**
* **Período**: Múltiplos anos (1991, 2000, 2010, 2011-2017 dependendo da métrica)
* **Fonte confiável**: Dados oficiais processados pelo Atlas Brasil
* **Uso**: Análises de contexto educacional, benchmarking municipal, séries históricas

----

:Schema: ``raw``
:Database: ``data-warehouse-tag``
:Responsável: Equipe de Dados
