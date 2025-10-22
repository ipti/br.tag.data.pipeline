# 📊 D_HEALTH

:Tipo: **Dimensão**  
:Descrição: Dimensão que armazena condições de saúde dos estudantes para acompanhamento nutricional e médico  
:Schema: ``dbo_tia``  
:Database: ``data-warehouse-tag``  
:Responsável: Equipe de Dados

---

## Estrutura de Colunas

| Coluna | Tipo | Restrições | Descrição |
|--------|------|------------|-----------|
| `HASH_ID` | `varchar(256)` | 🔑 PK 🔗 FK `NOT NULL` `UNIQUE` | Chave primária única do registro de saúde (hash SHA-256) |
| `inserted_at` | `datetime` | - | Timestamp de inserção do registro no data warehouse |
| `F_HASH_ID` | `varchar(256)` | 🔗 FK | Referência ao estudante (relaciona com D_STUDENT) |
| `celiac_desase` | `bit` | - | Indica se o estudante possui doença celíaca (impacta alimentação escolar) |
| `diabetes_desease` | `bit` | - | Indica se o estudante possui diabetes (requer cuidados especiais) |
| `iron_deficiency_anemia_desease` | `bit` | - | Indica se possui anemia ferropriva (afeta rendimento escolar) |
| `lactose_intolerance_desease` | `bit` | - | Indica intolerância à lactose (impacta merenda escolar) |
| `malnutrition_desease` | `bit` | - | Indica quadro de desnutrição (prioritário para programas sociais) |
| `hypertension_desease` | `bit` | - | Indica se possui hipertensão (limita atividades físicas) |
| `obesity_desease` | `bit` | - | Indica quadro de obesidade (requer acompanhamento nutricional) |
| `other_health_problems` | `varchar(256)` | - | Outras condições de saúde relatadas pela família (texto livre) |
| `updated_at` | `datetime` | - | Timestamp da última atualização das informações de saúde |
| `sickle_cell_anemia` | `bit` | - | Indica se possui anemia falciforme (requer cuidados médicos especiais) |

---

## Relacionamentos


### Referenciada por:

* **[F_ENROLLMENT](../dimensoes/F_ENROLLMENT.md)**.`health_id` → `HASH_ID`


---

## Exemplos SQL

### Consulta Básica

```sql
SELECT * FROM dbo_tia.D_HEALTH LIMIT 10;
```

### Contar Registros

```sql
SELECT COUNT(*) FROM dbo_tia.D_HEALTH;
```


---

:Schema: ``dbo_tia``  
:Database: ``data-warehouse-tag``  
:Responsável: Equipe de Dados
