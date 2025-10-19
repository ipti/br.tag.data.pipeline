# 📈 F_ENROLLMENT

:Tipo: **Fato**  
:Descrição: FATO PRINCIPAL - Matrícula dos estudantes, conecta todas as dimensões do sistema educacional  
:Schema: ``dbo_tia``  
:Database: ``data-warehouse-tag``  
:Responsável: Equipe de Dados

---

## Estrutura de Colunas

| Coluna | Tipo | Restrições | Descrição |
|--------|------|------------|-----------|
| `HASH_ID` | `varchar(256)` | 🔑 PK 🔗 FK `NOT NULL` `UNIQUE` | Chave primária única da matrícula (hash SHA-256) |
| `school_id` | `varchar(256)` | 🔗 FK | Referência à escola onde o estudante está matriculado |
| `classroom_id` | `varchar(256)` | 🔗 FK | Referência à turma/sala de aula do estudante |
| `student_id` | `varchar(256)` | 🔗 FK | Referência ao estudante matriculado |
| `db_name` | `varchar(100)` | - | Nome do banco de origem (para auditoria de lineage) |
| `data_origin` | `varchar(100)` | - | Sistema fonte dos dados (TIA Municipal, TIA Estadual, etc.) |
| `inserted_at` | `datetime` | - | Timestamp de inserção da matrícula no data warehouse |
| `log_lineage` | `datetime` | - | Log de rastreamento da origem e transformação dos dados |
| `health_id` | `varchar(256)` | 🔗 FK | Referência opcional às informações de saúde do estudante |
| `status` | `varchar(25)` | - | Status geral da matrícula (Ativa, Cancelada, Suspensa) |
| `enrollment_status` | `bit` | - | Status específico detalhado (Matriculado, Transferido, Evadido, Concluído) |
| `gender` | `varchar(9)` | - | Gênero do estudante |
| `ethnicity` | `varchar(13)` | - | Etnia/raça do estudante |
| `birth_city` | `varchar(150)` | - | Cidade de nascimento |
| `deficiency` | `varchar(150)` | - | Tipo de deficiência (se houver) |
| `birthday` | `varchar(12)` | - | Data de nascimento |
| `neighborhood_address` | `varchar(100)` | - | Bairro de residência |
| `cep` | `varchar(10)` | - | CEP da residência |
| `public_transport` | `varchar(5)` | - | Utiliza transporte público escolar (Sim/Não) |
| `city_address` | `varchar(170)` | - | Cidade de residência |
| `mother_name` | `varchar(120)` | - | Nome da mãe |
| `father_name` | `varchar(120)` | - | Nome do pai |
| `residence_zone` | `varchar(6)` | - | Zona de residência (Urbana/Rural) |
| `student_cpf` | `varchar(12)` | - | CPF do estudante |
| `responsable_cpf` | `varchar(12)` | - | CPF do responsável |
| `uf` | `varchar(3)` | - | UF da residência |
| `mapped_city` | `varchar(150)` | - | Cidade mapeada/normalizada |

---

## Relacionamentos

### Esta tabela referencia:

* `school_id` → **[D_SCHOOL](../fatos/D_SCHOOL.md)**.`HASH_ID`
* `classroom_id` → **[D_CLASSROOM](../fatos/D_CLASSROOM.md)**.`HASH_ID`
* `student_id` → **[D_STUDENT](../fatos/D_STUDENT.md)**.`HASH_ID`
* `health_id` → **[D_HEALTH](../fatos/D_HEALTH.md)**.`HASH_ID`


---

## Exemplos SQL

### Consulta Básica

```sql
SELECT * FROM dbo_tia.F_ENROLLMENT LIMIT 10;
```

### Contar Registros

```sql
SELECT COUNT(*) FROM dbo_tia.F_ENROLLMENT;
```


---

:Schema: ``dbo_tia``  
:Database: ``data-warehouse-tag``  
:Responsável: Equipe de Dados
