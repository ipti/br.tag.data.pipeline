# 📊 D_SCHOOL_GEOGRAPH

:Tipo: **Dimensão**  
:Descrição: Dimensão geográfica complementar das escolas (CEP, cidade, UF) para análises regionais  
:Schema: ``dbo_tia``  
:Database: ``data-warehouse-tag``  
:Responsável: Equipe de Dados

---

## Estrutura de Colunas

| Coluna | Tipo | Restrições | Descrição |
|--------|------|------------|-----------|
| `HASH_ID` | `varchar(256)` | 🔑 PK 🔗 FK `NOT NULL` `UNIQUE` | Chave primária única da localização geográfica (hash SHA-256) |
| `cep` | `varchar(10)` | - | Código de Endereçamento Postal da escola |
| `city` | `varchar(120)` | - | Município onde a escola está localizada |
| `uf` | `varchar(4)` | - | Unidade Federativa (estado) da escola |
| `F_HASH_ID` | `varchar(256)` | 🔗 FK | Chave estrangeira de referência à escola (D_SCHOOL) |
| `inserted_at` | `datetime` | - | Timestamp de inserção do registro no data warehouse |

---

## Relacionamentos

### Esta tabela referencia:

* `F_HASH_ID` → **[D_SCHOOL](../dimensoes/D_SCHOOL.md)**.`HASH_ID`


---

## Exemplos SQL

### Consulta Básica

```sql
SELECT * FROM dbo_tia.D_SCHOOL_GEOGRAPH LIMIT 10;
```

### Contar Registros

```sql
SELECT COUNT(*) FROM dbo_tia.D_SCHOOL_GEOGRAPH;
```


---

:Schema: ``dbo_tia``  
:Database: ``data-warehouse-tag``  
:Responsável: Equipe de Dados
