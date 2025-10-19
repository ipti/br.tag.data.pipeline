# 📊 D_SCHOOL

:Tipo: **Dimensão**  
:Descrição: Dimensão com dados cadastrais e localização das unidades escolares da rede  
:Schema: ``dbo_tia``  
:Database: ``data-warehouse-tag``  
:Responsável: Equipe de Dados

---

## Estrutura de Colunas

| Coluna | Tipo | Restrições | Descrição |
|--------|------|------------|-----------|
| `HASH_ID` | `varchar(256)` | 🔑 PK 🔗 FK `NOT NULL` `UNIQUE` | Chave primária única da escola (hash SHA-256) |
| `F_HASH_ID` | `varchar(256)` | 🔗 FK | Chave para relacionamento com geografia (D_SCHOOL_GEOGRAPH) |
| `inserted_at` | `datetime` | - | Timestamp de inserção do registro no data warehouse |
| `latitude` | `varchar(20)` | - | Coordenada geográfica - latitude (para geolocalização) |
| `longitude` | `varchar(20)` | - | Coordenada geográfica - longitude (para geolocalização) |
| `name` | `varchar(100)` | - | Nome oficial da unidade escolar |
| `address` | `varchar(170)` | - | Logradouro completo da escola (rua, avenida, etc.) |
| `number_address` | `varchar(30)` | - | Número do endereço da unidade escolar |
| `address_complement` | `varchar(100)` | - | Complemento do endereço (bloco, sala, andar, etc.) |
| `address_neighborhood` | `varchar(100)` | - | Bairro onde a escola está localizada |
| `situation` | `int` | - | Código da situação operacional da escola (1=Ativa, 2=Inativa, etc.) |
| `exported_educacenso` | `int` | - | Flag indicando se os dados foram exportados para o Censo Escolar (INEP) |
| `join_at` | `varchar(15)` | - | Data de adesão da escola ao sistema TIA |

---

## Relacionamentos


### Referenciada por:

* **[D_SCHOOL_GEOGRAPH](../dimensoes/D_SCHOOL_GEOGRAPH.md)**.`F_HASH_ID` → `HASH_ID`
* **[F_CLASS](../dimensoes/F_CLASS.md)**.`school_id` → `HASH_ID`
* **[F_ENROLLMENT](../dimensoes/F_ENROLLMENT.md)**.`school_id` → `HASH_ID`


---

## Exemplos SQL

### Consulta Básica

```sql
SELECT * FROM dbo_tia.D_SCHOOL LIMIT 10;
```

### Contar Registros

```sql
SELECT COUNT(*) FROM dbo_tia.D_SCHOOL;
```


---

:Schema: ``dbo_tia``  
:Database: ``data-warehouse-tag``  
:Responsável: Equipe de Dados
