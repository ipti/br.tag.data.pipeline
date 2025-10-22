# 📋 classroom

:Tipo: **Tabela**  
:Descrição: Tabela de salas de aula importada do MySQL - dados brutos sem transformação  
:Schema: ``raw``  
:Database: ``data-warehouse-tag``  
:Responsável: Equipe de Dados

---

## Estrutura de Colunas

| Coluna | Tipo | Restrições | Descrição |
|--------|------|------------|-----------|
| `id` | `int` | `NOT NULL` `UNIQUE` | ID original da sala de aula no sistema MySQL |
| `school_inep_fk` | `varchar(50)` | - | Chave estrangeira para escola (código INEP) |
| `created_at` | `datetime2` | - | Data de criação do registro no sistema origem |
| `updated_at` | `datetime2` | - | Data de última atualização no sistema origem |
| `inserted_at` | `datetime2` | `NOT NULL` | Timestamp de inserção no data warehouse |
| `database_name` | `varchar(255)` | - | Nome do banco de dados de origem |
| `edcenso_stage_vs_modality_fk` | `varchar(50)` | - | Chave estrangeira para modalidade de ensino |
| `school_year` | `int` | - | Ano letivo |


---

## Exemplos SQL

### Consulta Básica

```sql
SELECT * FROM raw.classroom LIMIT 10;
```

### Contar Registros

```sql
SELECT COUNT(*) FROM raw.classroom;
```


---

:Schema: ``dbo_tia``  
:Database: ``data-warehouse-tag``  
:Responsável: Equipe de Dados
