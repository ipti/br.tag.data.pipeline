# Diagrama Visual de Schema (Estilo DBeaver)

Este diagrama mostra a estrutura completa do banco com todas as tabelas e suas relações PK/FK.

```mermaid
%%{init: {'theme':'base', 'themeVariables': { 'primaryColor':'#e3f2fd','primaryTextColor':'#000','primaryBorderColor':'#1976d2','lineColor':'#666','secondaryColor':'#fff3e0','tertiaryColor':'#f3e5f5'}}}%%
flowchart TB
    
    DCLASSROOM["D_CLASSROOM<br/><small>🔑 HASH_ID</small><br/><small>🔗 F_HASH_ID</small>"]
    style DCLASSROOM fill:#e3f2fd,stroke:#1976d2,stroke-width:3px
    DHEALTH["D_HEALTH<br/><small>🔑 HASH_ID</small><br/><small>🔗 F_HASH_ID</small>"]
    style DHEALTH fill:#e3f2fd,stroke:#1976d2,stroke-width:3px
    DSCHOOL["D_SCHOOL<br/><small>🔑 HASH_ID</small><br/><small>🔗 F_HASH_ID</small>"]
    style DSCHOOL fill:#e3f2fd,stroke:#1976d2,stroke-width:3px
    DSCHOOLGEOGRAPH["D_SCHOOL_GEOGRAPH<br/><small>🔑 HASH_ID</small><br/><small>🔗 F_HASH_ID</small>"]
    style DSCHOOLGEOGRAPH fill:#e3f2fd,stroke:#1976d2,stroke-width:3px
    DSTUDENT["D_STUDENT<br/><small>🔑 HASH_ID</small><br/><small>🔗 F_HASH_ID</small>"]
    style DSTUDENT fill:#e3f2fd,stroke:#1976d2,stroke-width:3px
    DSTUDENTDISCIPLINE["D_STUDENT_DISCIPLINE<br/><small>🔑 HASH_ID</small><br/><small>🔗 F_HASH_ID</small>"]
    style DSTUDENTDISCIPLINE fill:#e3f2fd,stroke:#1976d2,stroke-width:3px
    FAVALIATION["F_AVALIATION<br/><small>🔑 HASH_ID</small><br/><small>🔗 student_id, discipline_id</small>"]
    style FAVALIATION fill:#fff3e0,stroke:#f57c00,stroke-width:3px
    FCLASS["F_CLASS<br/><small>🔑 HASH_ID</small><br/><small>🔗 teacher_id, classroom_id +2</small>"]
    style FCLASS fill:#fff3e0,stroke:#f57c00,stroke-width:3px
    FENROLLMENT["F_ENROLLMENT<br/><small>🔑 HASH_ID</small><br/><small>🔗 school_id, classroom_id +2</small>"]
    style FENROLLMENT fill:#fff3e0,stroke:#f57c00,stroke-width:3px
    FSTUDENTCLASS["F_STUDENT_CLASS<br/><small>🔑 HASH_ID</small><br/><small>🔗 F_HASH_ID, student_id +2</small>"]
    style FSTUDENTCLASS fill:#fff3e0,stroke:#f57c00,stroke-width:3px
    classroom["classroom<br/><small>🔑 N/A</small>"]
    style classroom fill:#f3e5f5,stroke:#7b1fa2,stroke-width:2px

    DSCHOOL -->|F_HASH_ID| DSCHOOLGEOGRAPH
    DSTUDENT -->|F_HASH_ID| DSTUDENTDISCIPLINE
    DCLASSROOM -->|classroom_id| FCLASS
    DSCHOOL -->|school_id| FCLASS
    DSTUDENT -->|student_id| FSTUDENTCLASS
    FCLASS -->|class_id| FSTUDENTCLASS
    DSTUDENT -->|student_id| FAVALIATION
    DSTUDENTDISCIPLINE -->|discipline_id| FAVALIATION
    DSCHOOL -->|school_id| FENROLLMENT
    DCLASSROOM -->|classroom_id| FENROLLMENT
    DSTUDENT -->|student_id| FENROLLMENT
    DHEALTH -->|health_id| FENROLLMENT

```

## Legenda

### Símbolos

* 🔑 = **Primary Key** (Chave Primária)
* 🔗 = **Foreign Keys** (Chaves Estrangeiras)
* → = Relacionamento (da tabela pai para filha)

### Cores

* 🔵 **Azul** - Tabelas Dimensão (D_*)
* 🟠 **Laranja** - Tabelas Fato (F_*)
* 🟣 **Roxo** - Outras Tabelas

### Como Ler

* As **setas** mostram a direção do relacionamento
* A tabela de onde **sai a seta** é a tabela **pai** (contém a PK referenciada)
* A tabela para onde **vai a seta** é a tabela **filha** (contém a FK)
* O **label da seta** mostra o nome da coluna FK

### Exemplo

```
D_STUDENT -->|student_id| F_ENROLLMENT
```

Significa: `F_ENROLLMENT.student_id` é FK que referencia `D_STUDENT.HASH_ID`

## Estrutura do Schema


### 📊 Dimensões (6)

* **D_CLASSROOM**
* **D_HEALTH**
* **D_SCHOOL**
* **D_SCHOOL_GEOGRAPH**
* **D_STUDENT**
* **D_STUDENT_DISCIPLINE**

### 📈 Fatos (4)

* **F_AVALIATION**
* **F_CLASS**
* **F_ENROLLMENT**
* **F_STUDENT_CLASS**

### 📋 Outras (1)

* **classroom**
