# 📈 F_AVALIATION

:Tipo: **Fato**  
:Descrição: Fato de avaliação final - resultado consolidado por estudante e disciplina (aprovado/reprovado)  
:Schema: ``dbo_tia``  
:Database: ``data-warehouse-tag``  
:Responsável: Equipe de Dados

---

## Estrutura de Colunas

| Coluna | Tipo | Restrições | Descrição |
|--------|------|------------|-----------|
| `HASH_ID` | `varchar(256)` | 🔑 PK 🔗 FK `NOT NULL` `UNIQUE` | Chave primária única da avaliação final (hash SHA-256) |
| `student_id` | `varchar(256)` | 🔗 FK `NOT NULL` | Referência ao estudante avaliado |
| `discipline_id` | `varchar(256)` | 🔗 FK `NOT NULL` | Referência à disciplina avaliada (relaciona com histórico de notas) |
| `inserted_at` | `datetime` | - | Timestamp de inserção do resultado no data warehouse |
| `situation` | `varchar(20)` | - | Situação final do estudante (Aprovado, Reprovado, Transferido, Abandono) |
| `updated_at` | `datetime` | - | Timestamp da última atualização do resultado |

---

## Relacionamentos

### Esta tabela referencia:

* `student_id` → **[D_STUDENT](../fatos/D_STUDENT.md)**.`HASH_ID`
* `discipline_id` → **[D_STUDENT_DISCIPLINE](../fatos/D_STUDENT_DISCIPLINE.md)**.`HASH_ID`


---

## Exemplos SQL

### Consulta Básica

```sql
SELECT * FROM dbo_tia.F_AVALIATION LIMIT 10;
```

### Contar Registros

```sql
SELECT COUNT(*) FROM dbo_tia.F_AVALIATION;
```


---

:Schema: ``dbo_tia``  
:Database: ``data-warehouse-tag``  
:Responsável: Equipe de Dados
