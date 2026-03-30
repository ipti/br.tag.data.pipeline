📊 PNAD - Pesquisa Nacional por Amostra de Domicílios
======================================================

:Schema: ``raw``
:Database: ``data-warehouse-tag``
:Fonte: IBGE - PNAD
:Período: Múltiplos anos
:Granularidade: Estadual
:Responsável: Equipe de Dados

----

Descrição
---------

Dados da **Pesquisa Nacional por Amostra de Domicílios (PNAD)** realizada pelo IBGE. Estes dados são utilizados para enriquecer nossa base de estudantes com contexto socioeconômico e educacional em nível estadual.

A PNAD é uma das principais pesquisas sobre características socioeconômicas da população brasileira.

----

Tabelas Disponíveis
-------------------

1. Atlas_PNAD_Estados_Total
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Indicadores gerais por estado, sem desagregações.

**Principais Indicadores:**

**Desenvolvimento Humano (IDH)**

* ``IDHM``: Índice de Desenvolvimento Humano Municipal
* ``IDHM_L``: IDH Longevidade
* ``IDHM_E``: IDH Educação
* ``IDHM_R``: IDH Renda
* ``IDHMAD``: IDH ajustado por desigualdade

**Longevidade**

* ``ESPVIDA``: Esperança de vida ao nascer
* ``MORT1``: Mortalidade infantil

**Educação**

* ``ANOSEST``: Anos médios de estudo
* ``T_ANALF[Faixa]``: Taxa de analfabetismo (15+, 18+, 25+ anos)
* ``T_FREQ[Faixa]``: Taxa de frequência escolar por faixa etária
* ``T_FUND[Faixa]``: Taxa com Fundamental completo
* ``T_MED[Faixa]``: Taxa com Médio completo
* ``T_SUPER[Faixa]``: Taxa com Superior completo
* ``T_ATRASO_2_[NIVEL]``: Taxa de atraso escolar (2+ anos)

**Renda e Desigualdade**

* ``RDPC``: Renda per capita
* ``GINI``: Coeficiente de Gini
* ``THEIL``: Índice de Theil
* ``PIND``, ``PMPOB``, ``PPOB``: Proporção de extremamente pobres, pobres e vulneráveis

**População**

* Múltiplas colunas populacionais por faixa etária (POP5A6, POP6A14, etc.)

----

2. Atlas_PNAD_Estados_Total_Cor
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Mesmos indicadores da tabela anterior, desagregados por **raça/cor**.

**Campo adicional:**

* ``COR``: Classificação racial (Branco, Negro, etc.)

----

3. Atlas_PNAD_Estados_Total_Sexo
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Mesmos indicadores da tabela anterior, desagregados por **sexo**.

**Campos adicionais:**

* ``SEXO``: Masculino ou Feminino
* ``IDHM_AJUSTADO``: IDH ajustado por sexo
* ``IDHM_R_AJUSTADO``: IDH Renda ajustado

----

Estrutura Comum das Tabelas
----------------------------

.. list-table::
   :header-rows: 1
   :widths: 25 15 60

   * - Campo
     - Tipo
     - Descrição
   * - ``ANO``
     - int
     - Ano de referência
   * - ``AGREGACAO``
     - varchar(50)
     - Tipo de agregação (Estado)
   * - ``CODIGO``
     - real/int
     - Código IBGE do estado
   * - ``NOME``
     - varchar(50)
     - Nome do estado
   * - ``IDHM``
     - real
     - Índice de Desenvolvimento Humano Municipal
   * - ``ESPVIDA``
     - real
     - Esperança de vida ao nascer
   * - ``ANOSEST``
     - real
     - Média de anos de estudo
   * - ``RDPC``
     - real
     - Renda per capita
   * - ``GINI``
     - real
     - Coeficiente de Gini (desigualdade)
   * - ``POPTOT``
     - varchar(50)
     - População total

----

Exemplos de Uso
---------------

**Comparar IDH entre estados**

.. code-block:: sql

   SELECT 
       NOME,
       ANO,
       IDHM,
       IDHM_E AS IDH_Educacao,
       IDHM_R AS IDH_Renda,
       IDHM_L AS IDH_Longevidade
   FROM raw.Atlas_PNAD_Estados_Total
   WHERE ANO = 2021
   ORDER BY IDHM DESC;

**Analisar desigualdade de gênero na educação**

.. code-block:: sql

   SELECT 
       NOME,
       ANO,
       SEXO,
       T_ANALF25M AS Taxa_Analfabetismo_25plus,
       T_SUPER25M AS Taxa_Superior_25plus,
       ANOSEST AS Media_Anos_Estudo
   FROM raw.Atlas_PNAD_Estados_Total_Sexo
   WHERE ANO = 2021
   ORDER BY NOME, SEXO;

**Desigualdade racial no acesso à educação**

.. code-block:: sql

   SELECT 
       NOME,
       ANO,
       COR,
       T_FREQ15A17 AS Taxa_Freq_15_17,
       T_MED25M AS Taxa_Medio_Completo,
       ANOSEST AS Media_Anos_Estudo
   FROM raw.Atlas_PNAD_Estados_Total_Cor
   WHERE ANO = 2021
   ORDER BY NOME, COR;

----

Observações Importantes
-----------------------

* **Granularidade**: Dados agregados a nível **estadual** (não há dados municipais na PNAD)
* **Desagregações**: Total, por Cor/Raça e por Sexo
* **Uso**: Análises de contexto socioeconômico, estudos de desigualdade, benchmarking estadual
* **Integração**: Usado para enriquecer análises de estudantes quando não há dados municipais disponíveis

----

:Schema: ``raw``
:Database: ``data-warehouse-tag``
:Responsável: Equipe de Dados
