# 📈 F_CLASS

:Tipo: **Fato**  
:Descrição: Fato que registra aulas programadas/ministradas - base para controle de carga horária e planejamento  
:Schema: ``dbo_tia``  
:Database: ``data-warehouse-tag``  
:Responsável: Equipe de Dados

---

## Estrutura de Colunas

| Coluna | Tipo | Restrições | Descrição |
|--------|------|------------|-----------|
| `HASH_ID` | `varchar(256)` | 🔑 PK 🔗 FK `NOT NULL` `UNIQUE` | Chave primária única da aula (hash SHA-256) |
| `inserted_at` | `datetime` | - | Timestamp de inserção do registro no data warehouse |
| `teacher_id` | `varchar(256)` | 🔗 FK | Identificador do professor responsável pela aula |
| `classroom_id` | `varchar(256)` | 🔗 FK | Referência à turma onde a aula ocorre |
| `scheduled_class_days` | `int` | - | Número total de dias de aula programados no período |
| `scheduled_month` | `int` | - | Mês da programação das aulas (1-12) |
| `scheduled_lessons_per_day` | `int` | - | Quantidade de aulas/períodos por dia para esta disciplina |
| `scheduled_year` | `int` | - | Ano letivo da programação |
| `school_id` | `varchar(256)` | 🔗 FK | Referência à escola onde a aula acontece |
| `discipline_id` | `varchar(256)` | 🔗 FK | Identificador da disciplina sendo ministrada |
| `updated_at` | `datetime` | - | Timestamp da última atualização do cronograma |
| `discipline_name` | `varchar(150)` | - | Nome da disciplina (desnormalizado para performance) |
| `scheduled_day` | `int` | - | Dia específico do mês da aula programada |

---

## Relacionamentos

### Esta tabela referencia:

* `classroom_id` → **[D_CLASSROOM](../fatos/D_CLASSROOM.md)**.`HASH_ID`
* `school_id` → **[D_SCHOOL](../fatos/D_SCHOOL.md)**.`HASH_ID`

### Referenciada por:

* **[F_STUDENT_CLASS](../fatos/F_STUDENT_CLASS.md)**.`class_id` → `HASH_ID`


---

## Exemplos SQL

### Consulta Básica

```sql
SELECT * FROM dbo_tia.F_CLASS LIMIT 10;
```

### Contar Registros

```sql
SELECT COUNT(*) FROM dbo_tia.F_CLASS;
```


---

:Schema: ``dbo_tia``  
:Database: ``data-warehouse-tag``  
:Responsável: Equipe de Dados
