# 📊 D_STUDENT_DISCIPLINE

:Tipo: **Dimensão**  
:Descrição: Dimensão com histórico acadêmico detalhado - notas por bimestre e recuperações de cada disciplina  
:Schema: ``dbo_tia``  
:Database: ``data-warehouse-tag``  
:Responsável: Equipe de Dados

---

## Estrutura de Colunas

| Coluna | Tipo | Restrições | Descrição |
|--------|------|------------|-----------|
| `HASH_ID` | `varchar(256)` | 🔑 PK 🔗 FK `NOT NULL` `UNIQUE` | Chave primária única do registro estudante-disciplina (hash SHA-256) |
| `inserted_at` | `datetime` | - | Timestamp de inserção do registro no data warehouse |
| `F_HASH_ID` | `varchar(256)` | 🔗 FK | Referência ao estudante (relaciona com D_STUDENT) |
| `discipline_name` | `varchar(120)` | - | Nome da disciplina/matéria (Ex: 'Matemática', 'Português', 'História') |
| `grade_1` | `float` | - | Nota obtida no 1º bimestre (escala 0-10) |
| `grade_2` | `float` | - | Nota obtida no 2º bimestre (escala 0-10) |
| `grade_3` | `float` | - | Nota obtida no 3º bimestre (escala 0-10) |
| `grade_4` | `float` | - | Nota obtida no 4º bimestre (escala 0-10) |
| `rec_bim_1` | `float` | - | Nota da recuperação do 1º bimestre (substitui grade_1 se maior) |
| `rec_bim_2` | `float` | - | Nota da recuperação do 2º bimestre (substitui grade_2 se maior) |
| `rec_sem_1` | `float` | - | Nota da recuperação do 1º semestre (média bim 1+2) |
| `rec_sem_2` | `float` | - | Nota da recuperação do 2º semestre (média bim 3+4) |
| `rec_sem_3` | `float` | - | Nota da recuperação do 3º semestre (sistema semestral) |
| `rec_sem_4` | `float` | - | Nota da recuperação do 4º semestre (sistema semestral) |
| `rec_final` | `float` | - | Nota da recuperação final (última chance de aprovação) |
| `final_mean` | `float` | - | Média final calculada da disciplina (define aprovação/reprovação) |
| `updated_at` | `datetime` | - | Timestamp da última atualização das notas |

---

## Relacionamentos

### Esta tabela referencia:

* `F_HASH_ID` → **[D_STUDENT](../dimensoes/D_STUDENT.md)**.`HASH_ID`

### Referenciada por:

* **[F_AVALIATION](../dimensoes/F_AVALIATION.md)**.`discipline_id` → `HASH_ID`


---

## Exemplos SQL

### Consulta Básica

```sql
SELECT * FROM dbo_tia.D_STUDENT_DISCIPLINE LIMIT 10;
```

### Contar Registros

```sql
SELECT COUNT(*) FROM dbo_tia.D_STUDENT_DISCIPLINE;
```


---

:Schema: ``dbo_tia``  
:Database: ``data-warehouse-tag``  
:Responsável: Equipe de Dados
