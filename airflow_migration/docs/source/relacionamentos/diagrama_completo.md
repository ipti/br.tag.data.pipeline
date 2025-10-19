# Diagrama ER Completo (Todas as Colunas)

Este diagrama mostra todas as tabelas com TODAS as suas colunas e relacionamentos.

```mermaid
erDiagram

    D_CLASSROOM {
        VARCHAR HASH_ID "PK, FK"
        VARCHAR F_HASH_ID "FK, NOT NULL"
        DATETIME inserted_at
        VARCHAR name
        VARCHAR stage
        VARCHAR status
        VARCHAR serie
        INT class_year
        DATETIME updated_at
    }

    D_HEALTH {
        VARCHAR HASH_ID "PK, FK"
        DATETIME inserted_at
        VARCHAR F_HASH_ID "FK"
        BIT celiac_desase
        BIT diabetes_desease
        BIT iron_deficiency_anemia_desease
        BIT lactose_intolerance_desease
        BIT malnutrition_desease
        BIT hypertension_desease
        BIT obesity_desease
        VARCHAR other_health_problems
        DATETIME updated_at
        BIT sickle_cell_anemia
    }

    D_SCHOOL {
        VARCHAR HASH_ID "PK, FK"
        VARCHAR F_HASH_ID "FK"
        DATETIME inserted_at
        VARCHAR latitude
        VARCHAR longitude
        VARCHAR name
        VARCHAR address
        VARCHAR number_address
        VARCHAR address_complement
        VARCHAR address_neighborhood
        INT situation
        INT exported_educacenso
        VARCHAR join_at
    }

    D_SCHOOL_GEOGRAPH {
        VARCHAR HASH_ID "PK, FK"
        VARCHAR cep
        VARCHAR city
        VARCHAR uf
        VARCHAR F_HASH_ID "FK"
        DATETIME inserted_at
    }

    D_STUDENT {
        VARCHAR HASH_ID "PK, FK"
        VARCHAR F_HASH_ID "FK"
        DATETIME inserted_at
        VARCHAR name
        VARCHAR street_addrees
        BIT bolsa_familia_participator
        VARCHAR gender
        VARCHAR ethnicity
        VARCHAR birth_city
        VARCHAR deficiency
        VARCHAR birthday
        VARCHAR neighborhood_address
        VARCHAR cep
        VARCHAR public_transport
        VARCHAR city_address
        VARCHAR mother_name
        VARCHAR father_name
        VARCHAR residence_zone
        VARCHAR student_cpf
        VARCHAR responsable_cpf
        VARCHAR uf
        VARCHAR mapped_city
    }

    D_STUDENT_DISCIPLINE {
        VARCHAR HASH_ID "PK, FK"
        DATETIME inserted_at
        VARCHAR F_HASH_ID "FK"
        VARCHAR discipline_name
        FLOAT grade_1
        FLOAT grade_2
        FLOAT grade_3
        FLOAT grade_4
        FLOAT rec_bim_1
        FLOAT rec_bim_2
        FLOAT rec_sem_1
        FLOAT rec_sem_2
        FLOAT rec_sem_3
        FLOAT rec_sem_4
        FLOAT rec_final
        FLOAT final_mean
        DATETIME updated_at
    }

    F_AVALIATION {
        VARCHAR HASH_ID "PK, FK"
        VARCHAR student_id "FK, NOT NULL"
        VARCHAR discipline_id "FK, NOT NULL"
        DATETIME inserted_at
        VARCHAR situation
        DATETIME updated_at
    }

    F_CLASS {
        VARCHAR HASH_ID "PK, FK"
        DATETIME inserted_at
        VARCHAR teacher_id "FK"
        VARCHAR classroom_id "FK"
        INT scheduled_class_days
        INT scheduled_month
        INT scheduled_lessons_per_day
        INT scheduled_year
        VARCHAR school_id "FK"
        VARCHAR discipline_id "FK"
        DATETIME updated_at
        VARCHAR discipline_name
        INT scheduled_day
    }

    F_ENROLLMENT {
        VARCHAR HASH_ID "PK, FK"
        VARCHAR school_id "FK"
        VARCHAR classroom_id "FK"
        VARCHAR student_id "FK"
        VARCHAR db_name
        VARCHAR data_origin
        DATETIME inserted_at
        DATETIME log_lineage
        VARCHAR health_id "FK"
        VARCHAR status
        BIT enrollment_status
        VARCHAR gender
        VARCHAR ethnicity
        VARCHAR birth_city
        VARCHAR deficiency
        VARCHAR birthday
        VARCHAR neighborhood_address
        VARCHAR cep
        VARCHAR public_transport
        VARCHAR city_address
        VARCHAR mother_name
        VARCHAR father_name
        VARCHAR residence_zone
        VARCHAR student_cpf
        VARCHAR responsable_cpf
        VARCHAR uf
        VARCHAR mapped_city
    }

    F_STUDENT_CLASS {
        VARCHAR HASH_ID "PK, FK"
        VARCHAR F_HASH_ID "FK"
        VARCHAR student_id "FK"
        VARCHAR discipline_id "FK"
        INT total_faults_per_day
        INT total_faults_per_discipline
        DATETIME inserted_at
        DATETIME updated_at
        INT scheduled_student_class_days
        VARCHAR class_id "FK"
    }

    classroom {
        INT id "NOT NULL"
        VARCHAR school_inep_fk
        DATETIME2 created_at
        DATETIME2 updated_at
        DATETIME2 inserted_at "NOT NULL"
        VARCHAR database_name
        VARCHAR edcenso_stage_vs_modality_fk
        INT school_year
    }

    %% Relacionamentos
    D_SCHOOL ||--o{ D_SCHOOL_GEOGRAPH : "F_HASH_ID -> HASH_ID"
    D_STUDENT ||--o{ D_STUDENT_DISCIPLINE : "F_HASH_ID -> HASH_ID"
    D_CLASSROOM ||--o{ F_CLASS : "classroom_id -> HASH_ID"
    D_SCHOOL ||--o{ F_CLASS : "school_id -> HASH_ID"
    D_STUDENT ||--o{ F_STUDENT_CLASS : "student_id -> HASH_ID"
    F_CLASS ||--o{ F_STUDENT_CLASS : "class_id -> HASH_ID"
    D_STUDENT ||--o{ F_AVALIATION : "student_id -> HASH_ID"
    D_STUDENT_DISCIPLINE ||--o{ F_AVALIATION : "discipline_id -> HASH_ID"
    D_SCHOOL ||--o{ F_ENROLLMENT : "school_id -> HASH_ID"
    D_CLASSROOM ||--o{ F_ENROLLMENT : "classroom_id -> HASH_ID"
    D_STUDENT ||--o{ F_ENROLLMENT : "student_id -> HASH_ID"
    D_HEALTH ||--o{ F_ENROLLMENT : "health_id -> HASH_ID"
```

## Legenda

### Notação de Relacionamentos

* `||--o{` : Um para Muitos (One to Many)
* A tabela à esquerda é a **referenciada** (tabela pai)
* A tabela à direita é a que **referencia** (tabela filha com FK)

### Indicadores de Colunas

* **PK** : Primary Key (Chave Primária)
* **FK** : Foreign Key (Chave Estrangeira)  
* **NOT NULL** : Campo obrigatório

## Estatísticas

* **Total de Tabelas**: 11
  * Dimensões: 6
  * Fatos: 4
  * Outras: 1
* **Total de Relacionamentos**: 12

### Tabelas Dimensão

* **D_CLASSROOM** (9 colunas)
* **D_HEALTH** (13 colunas)
* **D_SCHOOL** (13 colunas)
* **D_SCHOOL_GEOGRAPH** (6 colunas)
* **D_STUDENT** (22 colunas)
* **D_STUDENT_DISCIPLINE** (17 colunas)

### Tabelas Fato

* **F_AVALIATION** (6 colunas)
* **F_CLASS** (13 colunas)
* **F_ENROLLMENT** (27 colunas)
* **F_STUDENT_CLASS** (10 colunas)

## Tabela de Relacionamentos

| Tabela Origem (FK) | Coluna FK | Tabela Destino (PK) | Coluna PK |
|-------------------|-----------|---------------------|----------|
| D_SCHOOL_GEOGRAPH | `F_HASH_ID` | D_SCHOOL | `HASH_ID` |
| D_STUDENT_DISCIPLINE | `F_HASH_ID` | D_STUDENT | `HASH_ID` |
| F_AVALIATION | `student_id` | D_STUDENT | `HASH_ID` |
| F_AVALIATION | `discipline_id` | D_STUDENT_DISCIPLINE | `HASH_ID` |
| F_CLASS | `classroom_id` | D_CLASSROOM | `HASH_ID` |
| F_CLASS | `school_id` | D_SCHOOL | `HASH_ID` |
| F_ENROLLMENT | `classroom_id` | D_CLASSROOM | `HASH_ID` |
| F_ENROLLMENT | `health_id` | D_HEALTH | `HASH_ID` |
| F_ENROLLMENT | `school_id` | D_SCHOOL | `HASH_ID` |
| F_ENROLLMENT | `student_id` | D_STUDENT | `HASH_ID` |
| F_STUDENT_CLASS | `student_id` | D_STUDENT | `HASH_ID` |
| F_STUDENT_CLASS | `class_id` | F_CLASS | `HASH_ID` |
