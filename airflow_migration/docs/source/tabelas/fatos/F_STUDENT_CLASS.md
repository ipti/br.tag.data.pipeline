# 📈 F_STUDENT_CLASS

:Tipo: **Fato**  
:Descrição: Fato de participação estudantil - registra presença/falta dos alunos por aula e disciplina  
:Schema: ``dbo_tia``  
:Database: ``data-warehouse-tag``  
:Responsável: Equipe de Dados

---

## Estrutura de Colunas

| Coluna | Tipo | Restrições | Descrição |
|--------|------|------------|-----------|
| `HASH_ID` | `varchar(256)` | 🔑 PK 🔗 FK `NOT NULL` `UNIQUE` | Chave primária única do registro de participação (hash SHA-256) |
| `F_HASH_ID` | `varchar(256)` | 🔗 FK | Chave de relacionamento adicional |
| `student_id` | `varchar(256)` | 🔗 FK | Referência ao estudante participante |
| `discipline_id` | `varchar(256)` | 🔗 FK | Referência à disciplina (relaciona com D_STUDENT_DISCIPLINE) |
| `total_faults_per_day` | `int` | - | Total de faltas do estudante no dia específico |
| `total_faults_per_discipline` | `int` | - | Total acumulado de faltas na disciplina (para controle de 75% mínimo) |
| `inserted_at` | `datetime` | - | Timestamp de inserção do registro no data warehouse |
| `updated_at` | `datetime` | - | Timestamp da última atualização da frequência |
| `scheduled_student_class_days` | `int` | - | Total de dias de aula programados para este estudante |
| `class_id` | `varchar(256)` | 🔗 FK | Referência à aula específica (relaciona com F_CLASS) |

---

## Relacionamentos

### Esta tabela referencia:

* `student_id` → **[D_STUDENT](../fatos/D_STUDENT.md)**.`HASH_ID`
* `class_id` → **[F_CLASS](../fatos/F_CLASS.md)**.`HASH_ID`


---

## Exemplos SQL

### Consulta Básica

```sql
SELECT * FROM dbo_tia.F_STUDENT_CLASS LIMIT 10;
```

### Contar Registros

```sql
SELECT COUNT(*) FROM dbo_tia.F_STUDENT_CLASS;
```


---

:Schema: ``dbo_tia``  
:Database: ``data-warehouse-tag``  
:Responsável: Equipe de Dados
