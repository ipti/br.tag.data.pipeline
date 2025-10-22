# Diagrama ER Detalhado

```mermaid
erDiagram
    D_CLASSROOM {
        varchar HASH_ID PK FK
        varchar F_HASH_ID FK
        datetime inserted_at
        varchar name
        varchar stage
    }
    D_HEALTH {
        varchar HASH_ID PK FK
        datetime inserted_at
        varchar F_HASH_ID FK
        bit celiac_desase
        bit diabetes_desease
    }
    D_SCHOOL {
        varchar HASH_ID PK FK
        varchar F_HASH_ID FK
        datetime inserted_at
        varchar latitude
        varchar longitude
    }
    D_SCHOOL_GEOGRAPH {
        varchar HASH_ID PK FK
        varchar cep
        varchar city
        varchar uf
        varchar F_HASH_ID FK
    }
    D_STUDENT {
        varchar HASH_ID PK FK
        varchar F_HASH_ID FK
        datetime inserted_at
        varchar name
        varchar street_addrees
    }
    D_STUDENT_DISCIPLINE {
        varchar HASH_ID PK FK
        datetime inserted_at
        varchar F_HASH_ID FK
        varchar discipline_name
        float grade_1
    }
    F_CLASS {
        varchar HASH_ID PK FK
        datetime inserted_at
        varchar teacher_id FK
        varchar classroom_id FK
        int scheduled_class_days
    }
    F_STUDENT_CLASS {
        varchar HASH_ID PK FK
        varchar F_HASH_ID FK
        varchar student_id FK
        varchar discipline_id FK
        int total_faults_per_day
    }
    F_AVALIATION {
        varchar HASH_ID PK FK
        varchar student_id FK
        varchar discipline_id FK
        datetime inserted_at
        varchar situation
    }
    F_ENROLLMENT {
        varchar HASH_ID PK FK
        varchar school_id FK
        varchar classroom_id FK
        varchar student_id FK
        varchar db_name
    }
    classroom {
        int id
        varchar school_inep_fk
        datetime2 created_at
        datetime2 updated_at
        datetime2 inserted_at
    }
    D_SCHOOL_GEOGRAPH ||--o{ D_SCHOOL : "F_HASH_ID"
    D_STUDENT_DISCIPLINE ||--o{ D_STUDENT : "F_HASH_ID"
    F_CLASS ||--o{ D_CLASSROOM : "classroom_id"
    F_CLASS ||--o{ D_SCHOOL : "school_id"
    F_STUDENT_CLASS ||--o{ D_STUDENT : "student_id"
    F_STUDENT_CLASS ||--o{ F_CLASS : "class_id"
    F_AVALIATION ||--o{ D_STUDENT : "student_id"
    F_AVALIATION ||--o{ D_STUDENT_DISCIPLINE : "discipline_id"
    F_ENROLLMENT ||--o{ D_SCHOOL : "school_id"
    F_ENROLLMENT ||--o{ D_CLASSROOM : "classroom_id"
    F_ENROLLMENT ||--o{ D_STUDENT : "student_id"
    F_ENROLLMENT ||--o{ D_HEALTH : "health_id"
    F_AVALIATION ||--o{ D_STUDENT : "student_id"
    F_AVALIATION ||--o{ D_STUDENT_DISCIPLINE : "discipline_id"
    F_ENROLLMENT ||--o{ D_SCHOOL : "school_id"
    F_ENROLLMENT ||--o{ D_CLASSROOM : "classroom_id"
    F_ENROLLMENT ||--o{ D_STUDENT : "student_id"
    F_ENROLLMENT ||--o{ D_HEALTH : "health_id"
```
