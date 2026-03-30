📈 QEdu - Dados Educacionais
============================

:Schema: ``raw``
:Database: ``data-warehouse-tag``
:Fonte: QEdu (qedu.org.br)
:Período: Múltiplos anos
:Granularidade: Municipal
:Responsável: Equipe de Dados

----

Descrição
---------

Dados do **QEdu**, plataforma que disponibiliza e analisa dados educacionais públicos do Brasil. Todos os dados estão na **versão mais atualizada disponível**.

O QEdu processa dados do Censo Escolar, Prova Brasil e outras fontes oficiais, oferecendo indicadores educacionais consolidados.

----

Tabelas Disponíveis
-------------------

1. QeduAprendizadoTodosAnos
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Indicadores de **aprendizado adequado** baseados na Prova Brasil/SAEB, por município.

**Estrutura:**

.. list-table::
   :header-rows: 1
   :widths: 25 15 60

   * - Campo
     - Tipo
     - Descrição
   * - ``ibge_id``
     - int
     - Código IBGE do município
   * - ``ano``
     - int
     - Ano de referência
   * - ``ciclo_id``
     - varchar(50)
     - Ciclo escolar (Anos Iniciais/Finais)
   * - ``dependencia_id``
     - int
     - Dependência administrativa (Pública/Privada)
   * - ``lp_adequado``
     - real
     - % de alunos com aprendizado adequado em Língua Portuguesa
   * - ``mt_adequado``
     - real
     - % de alunos com aprendizado adequado em Matemática
   * - ``lp_insuficiente``
     - real
     - % em nível insuficiente - LP
   * - ``lp_basico``
     - real
     - % em nível básico - LP
   * - ``lp_proficiente``
     - real
     - % em nível proficiente - LP
   * - ``lp_avancado``
     - real
     - % em nível avançado - LP
   * - ``mt_insuficiente``
     - real
     - % em nível insuficiente - MT
   * - ``mt_basico``
     - real
     - % em nível básico - MT
   * - ``mt_proficiente``
     - real
     - % em nível proficiente - MT
   * - ``mt_avancado``
     - real
     - % em nível avançado - MT

**Níveis de Proficiência:**

* **Insuficiente**: Não demonstrou conhecimentos básicos
* **Básico**: Demonstrou desenvolvimento parcial
* **Proficiente**: Demonstrou conhecimentos esperados
* **Avançado**: Superou o esperado para a série

----

2. QeduIDEBTodosAnos
~~~~~~~~~~~~~~~~~~~~

Dados do **IDEB (Índice de Desenvolvimento da Educação Básica)** por município.

**Estrutura:**

.. list-table::
   :header-rows: 1
   :widths: 25 15 60

   * - Campo
     - Tipo
     - Descrição
   * - ``ibge_id``
     - int
     - Código IBGE do município
   * - ``dependencia_id``
     - int
     - Dependência administrativa
   * - ``ciclo_id``
     - varchar(50)
     - Ciclo escolar
   * - ``ano``
     - int
     - Ano de referência
   * - ``ideb``
     - real
     - Índice IDEB (0-10)
   * - ``fluxo``
     - real
     - Taxa de aprovação
   * - ``aprendizado``
     - real
     - Nota de aprendizado
   * - ``nota_mt``
     - real
     - Nota de Matemática
   * - ``nota_lp``
     - real
     - Nota de Língua Portuguesa

.. note::
   **Cálculo do IDEB:** IDEB = Aprendizado × Fluxo

----

3. QeduPermanenciaTodosAnos
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Análise de **permanência escolar** por coorte de nascimento.

**Estrutura:**

.. list-table::
   :header-rows: 1
   :widths: 25 15 60

   * - Campo
     - Tipo
     - Descrição
   * - ``ibge_id``
     - int
     - Código IBGE do município
   * - ``ano_nascimento``
     - int
     - Ano de nascimento da coorte
   * - ``ano_censo``
     - int
     - Ano do Censo analisado
   * - ``permanencia``
     - real
     - % de estudantes que permaneceram na escola
   * - ``fora``
     - real
     - % de estudantes fora da escola
   * - ``Origem``
     - varchar(50)
     - Fonte dos dados

----

4. QeduTaxaDeDistorcaoTodosAnos
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Taxa de distorção idade-série** detalhada por ano escolar.

**Principais campos:**

* ``ef_1ano`` até ``ef_9ano``: Taxa de distorção por ano do EF
* ``ef_total_ai``: Total anos iniciais EF
* ``ef_total_af``: Total anos finais EF
* ``ef_total``: Total Ensino Fundamental
* ``em_1ano`` até ``em_4ano``: Taxa de distorção por ano do EM
* ``em_total``: Total Ensino Médio

----

5. QeduTaxaDeRendimentoTodosAnos
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Taxas de aprovação, reprovação e abandono** por série.

**Estrutura:**

.. list-table::
   :header-rows: 1
   :widths: 25 15 60

   * - Campo
     - Tipo
     - Descrição
   * - ``ibge_id``
     - int
     - Código IBGE do município
   * - ``ano``
     - int
     - Ano de referência
   * - ``serie_id``
     - int
     - Identificador da série
   * - ``matriculas``
     - real
     - Total de matrículas
   * - ``aprovados``
     - real
     - Taxa de aprovação (%)
   * - ``reprovados``
     - real
     - Taxa de reprovação (%)
   * - ``abandonos``
     - real
     - Taxa de abandono (%)

----

Exemplos de Uso
---------------

**Municípios com melhor aprendizado em LP e MT**

.. code-block:: sql

   SELECT 
       ibge_id,
       ano,
       ciclo_id,
       lp_adequado,
       mt_adequado,
       (lp_adequado + mt_adequado) / 2 AS Media_Adequado
   FROM raw.QeduAprendizadoTodosAnos
   WHERE ano = 2021
   ORDER BY Media_Adequado DESC
   LIMIT 10;

**Evolução do IDEB ao longo do tempo**

.. code-block:: sql

   SELECT 
       ibge_id,
       ciclo_id,
       ano,
       ideb,
       fluxo,
       aprendizado
   FROM raw.QeduIDEBTodosAnos
   WHERE ibge_id = 3550308  -- São Paulo
   ORDER BY ano, ciclo_id;

**Análise de distorção por dependência**

.. code-block:: sql

   SELECT 
       ano,
       dependencia_id,
       AVG(ef_total) AS Media_Distorcao_EF,
       AVG(em_total) AS Media_Distorcao_EM
   FROM raw.QeduTaxaDeDistorcaoTodosAnos
   GROUP BY ano, dependencia_id
   ORDER BY ano, dependencia_id;

**Taxa de abandono por série**

.. code-block:: sql

   SELECT 
       ano,
       serie_id,
       dependencia_id,
       AVG(abandonos) AS Taxa_Media_Abandono
   FROM raw.QeduTaxaDeRendimentoTodosAnos
   WHERE ano >= 2018
   GROUP BY ano, serie_id, dependencia_id
   ORDER BY ano, serie_id;

----

Observações Importantes
-----------------------

* **Granularidade**: Dados a nível **municipal**
* **Periodicidade**: Dados do Censo Escolar (anual) e Prova Brasil (bienal)
* **Fonte confiável**: QEdu processa dados oficiais do INEP
* **Uso**: Análises de qualidade educacional, identificação de municípios/escolas em risco, monitoramento de políticas públicas
* **Integração**: Complementa dados do software de gestão escolar com contexto municipal

----

:Schema: ``raw``
:Database: ``data-warehouse-tag``
:Responsável: Equipe de Dados
