# 📊 D_STUDENT

:Tipo: **Dimensão**  
:Descrição: Dimensão central com dados pessoais, socioeconômicos e demográficos dos estudantes  
:Schema: ``dbo_tia``  
:Database: ``data-warehouse-tag``  
:Responsável: Equipe de Dados

---

## Estrutura de Colunas

| Coluna | Tipo | Restrições | Descrição |
|--------|------|------------|-----------|
| `HASH_ID` | `varchar(256)` | 🔑 PK 🔗 FK `NOT NULL` `UNIQUE` | Chave primária única do estudante (hash SHA-256) |
| `F_HASH_ID` | `varchar(256)` | 🔗 FK | Chave para relacionamentos adicionais |
| `inserted_at` | `datetime` | - | Timestamp de inserção do registro no data warehouse |
| `name` | `varchar(100)` | - | Nome completo do estudante (dado sensível) |
| `street_addrees` | `varchar(170)` | - | Endereço residencial completo do estudante |
| `bolsa_familia_participator` | `bit` | - | Indica participação no Programa Bolsa Família (indicador socioeconômico) |
| `gender` | `varchar(9)` | - | Gênero do estudante para análises de equidade |
| `ethnicity` | `varchar(13)` | - | Autodeclaração étnico-racial (IBGE) para políticas de inclusão |
| `birth_city` | `varchar(150)` | - | Município de nascimento do estudante |
| `deficiency` | `varchar(150)` | - | Tipo de deficiência ou necessidade especial (para inclusão) |
| `birthday` | `varchar(12)` | - | Data de nascimento (para cálculo de idade e faixa etária) |
| `neighborhood_address` | `varchar(100)` | - | Bairro de residência (para análise de vulnerabilidade social) |
| `cep` | `varchar(10)` | - | CEP da residência do estudante |
| `public_transport` | `varchar(5)` | - | Utiliza transporte escolar público (impacta logística) |
| `city_address` | `varchar(170)` | - | Cidade de residência do estudante |
| `mother_name` | `varchar(120)` | - | Nome da mãe (filiação e contato de emergência) |
| `father_name` | `varchar(120)` | - | Nome do pai (filiação e contato de emergência) |
| `residence_zone` | `varchar(6)` | - | Zona de residência (Urbana/Rural) para análises socioeconômicas |
| `student_cpf` | `varchar(12)` | - | CPF do estudante (documento único, dado sensível) |
| `responsable_cpf` | `varchar(12)` | - | CPF do responsável legal (para contatos e benefícios) |
| `uf` | `varchar(3)` | - | UF da residência do estudante |
| `mapped_city` | `varchar(150)` | - | Cidade normalizada/padronizada para análises |

---

## Relacionamentos


### Referenciada por:

* **[D_STUDENT_DISCIPLINE](../dimensoes/D_STUDENT_DISCIPLINE.md)**.`F_HASH_ID` → `HASH_ID`
* **[F_STUDENT_CLASS](../dimensoes/F_STUDENT_CLASS.md)**.`student_id` → `HASH_ID`
* **[F_AVALIATION](../dimensoes/F_AVALIATION.md)**.`student_id` → `HASH_ID`
* **[F_ENROLLMENT](../dimensoes/F_ENROLLMENT.md)**.`student_id` → `HASH_ID`


---

## Exemplos SQL

### Consulta Básica

```sql
SELECT * FROM dbo_tia.D_STUDENT LIMIT 10;
```

### Contar Registros

```sql
SELECT COUNT(*) FROM dbo_tia.D_STUDENT;
```


---

:Schema: ``dbo_tia``  
:Database: ``data-warehouse-tag``  
:Responsável: Equipe de Dados
