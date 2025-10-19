# 📊 D_CLASSROOM

:Tipo: **Dimensão**  
:Descrição: Dimensão que armazena informações das salas de aula/turmas do sistema educacional  
:Schema: ``dbo_tia``  
:Database: ``data-warehouse-tag``  
:Responsável: Equipe de Dados

---

## Estrutura de Colunas

| Coluna | Tipo | Restrições | Descrição |
|--------|------|------------|-----------|
| `HASH_ID` | `varchar(256)` | 🔑 PK 🔗 FK `NOT NULL` `UNIQUE` | Chave primária única da sala de aula (hash SHA-256) |
| `F_HASH_ID` | `varchar(256)` | 🔗 FK `NOT NULL` | Chave estrangeira de referência para relacionamentos (hash SHA-256) |
| `inserted_at` | `datetime` | - | Timestamp de inserção do registro no data warehouse |
| `name` | `varchar(80)` | - | Nome identificador da sala de aula/turma (Ex: '3º Ano A', 'Turma Matemática') |
| `stage` | `varchar(100)` | - | Etapa de ensino (Ex: 'Ensino Fundamental I', 'Ensino Médio', 'EJA') |
| `status` | `varchar(22)` | - | Status operacional da sala (Ex: 'Ativa', 'Inativa', 'Suspensa') |
| `serie` | `varchar(150)` | - | Série/ano escolar específico (Ex: '1º Ano', '5ª Série', '3º Colegial') |
| `class_year` | `int` | - | Ano letivo da turma (Ex: 2024, 2025) |
| `updated_at` | `datetime` | - | Timestamp da última atualização do registro |

---

## Relacionamentos


### Referenciada por:

* **[F_CLASS](../dimensoes/F_CLASS.md)**.`classroom_id` → `HASH_ID`
* **[F_ENROLLMENT](../dimensoes/F_ENROLLMENT.md)**.`classroom_id` → `HASH_ID`


---

## Exemplos SQL

### Consulta Básica

```sql
SELECT * FROM dbo_tia.D_CLASSROOM LIMIT 10;
```

### Contar Registros

```sql
SELECT COUNT(*) FROM dbo_tia.D_CLASSROOM;
```


---

:Schema: ``dbo_tia``  
:Database: ``data-warehouse-tag``  
:Responsável: Equipe de Dados
