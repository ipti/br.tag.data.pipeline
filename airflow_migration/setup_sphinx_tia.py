#!/usr/bin/env python3

import sys
import argparse
import yaml
from typing import Dict, List, Tuple
from dataclasses import dataclass
from typing import Optional
from pathlib import Path


@dataclass
class Column:
    """
    Represents a column within a table definition parsed from YAML.

    Attributes:
        name: Column name.
        data_type: Declared data type as string.
        description: Human readable description for documentation.
        is_pk: True when this column is a primary key.
        is_fk: True when this column references another table.
        is_not_null: True when column has not_null constraint.
        is_unique: True when column has unique constraint.
    """

    name: str
    data_type: str
    description: str
    is_pk: bool = False
    is_fk: bool = False
    is_not_null: bool = False
    is_unique: bool = False


@dataclass
class Relationship:
    """
    Represents a relationship discovered between two tables.

    Attributes:
        from_table: Source table name containing the foreign key.
        from_col: Column name in source table (foreign key).
        to_table: Target table name referenced by foreign key.
        to_col: Column name in target table (primary key).
    """

    from_table: str
    from_col: str
    to_table: str
    to_col: str


@dataclass
class CustomQuery:
    """
    Holds metadata for a custom SQL query to be included in the docs.

    Attributes:
        title: Title for the custom query section.
        description: Optional description for the query.
        sql: The SQL text to include as an example.
    """

    title: str
    description: str
    sql: str


@dataclass
class Table:
    """
    Represents a parsed table and its metadata for documentation generation.

    Attributes:
        name: Table name.
        description: Text description for the table.
        type: One of 'dimension', 'fact' or 'other'.
        tags: List of tags associated with the table.
        columns: List of Column objects.
        relationships_out: Relationships where this table references others.
        relationships_in: Relationships where other tables reference this one.
        schema: Optional schema name.
        database: Optional database identifier.
        custom_queries: Optional list of CustomQuery instances to include.
    """

    name: str
    description: str
    type: str
    tags: List[str]
    columns: List[Column]
    relationships_out: List[Relationship]
    relationships_in: List[Relationship]
    schema: Optional[str] = None
    database: Optional[str] = None
    custom_queries: Optional[List[CustomQuery]] = None

    def __post_init__(self):
        if self.custom_queries is None:
            self.custom_queries = []


class Logger:
    """
    Minimal terminal logger with colored output helpers used by the script.
    Methods print formatted messages for header, success, info, warning and error levels.
    """

    COLORS = {
        "header": "\033[95m",
        "blue": "\033[94m",
        "green": "\033[92m",
        "yellow": "\033[93m",
        "red": "\033[91m",
        "end": "\033[0m",
        "bold": "\033[1m",
    }

    @classmethod
    def header(cls, msg: str):
        print(f"\n{cls.COLORS['bold']}{cls.COLORS['header']}{msg}{cls.COLORS['end']}\n")

    @classmethod
    def success(cls, msg: str):
        print(f"{cls.COLORS['green']}✓{cls.COLORS['end']} {msg}")

    @classmethod
    def info(cls, msg: str):
        print(f"{cls.COLORS['blue']}ℹ{cls.COLORS['end']} {msg}")

    @classmethod
    def warning(cls, msg: str):
        print(f"{cls.COLORS['yellow']}⚠{cls.COLORS['end']} {msg}")

    @classmethod
    def error(cls, msg: str):
        print(f"{cls.COLORS['red']}✗{cls.COLORS['end']} {msg}")


class YAMLParser:
    """
    Parses dbt-style YAML schema files to extract table, column and relationship metadata.

    Usage:
        parser = YAMLParser(Path('path/to/schemas'))
        tables, relationships = parser.parse_all()

    The parser also loads optional custom queries from a docs_config.yml located next to the sources directory.
    """

    def __init__(self, sources_dir: Path, config_file: Optional[Path] = None):
        self.sources_dir = sources_dir
        self.config_file = config_file or (sources_dir.parent / "docs_config.yml")
        self.tables: Dict[str, Table] = {}
        self.relationships: List[Relationship] = []
        self.custom_queries_config = self._load_custom_queries()

    def _load_custom_queries(self) -> Dict[str, List[CustomQuery]]:
        """
        Loads custom query definitions from the docs_config.yml file if present.
        Returns a mapping: table_name -> List[CustomQuery].
        """
        if not self.config_file.exists():
            return {}
        try:
            with open(self.config_file, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
            queries_by_table = {}
            for table_name, queries_data in config.get("custom_queries", {}).items():
                queries = []
                for query_data in queries_data:
                    queries.append(
                        CustomQuery(
                            title=query_data["title"],
                            description=query_data.get("description", ""),
                            sql=query_data["sql"],
                        )
                    )
                queries_by_table[table_name] = queries
            return queries_by_table
        except Exception as e:
            Logger.warning(f"Erro ao carregar queries personalizadas: {e}")
            return {}

    def find_yaml_files(self) -> List[Path]:
        """
        Finds all .yml and .yaml files in the sources directory and returns them sorted.
        """
        yaml_files = list(self.sources_dir.glob("*.yml")) + list(
            self.sources_dir.glob("*.yaml")
        )
        return sorted(yaml_files)

    def parse_all(self) -> Tuple[Dict[str, Table], List[Relationship]]:
        """
        Parses all YAML files found in the sources directory and returns a tuple with
        the parsed tables mapping and the list of discovered relationships.
        """
        yaml_files = self.find_yaml_files()
        if not yaml_files:
            Logger.error("Nenhum arquivo YAML encontrado")
            return {}, []
        Logger.info(f"Encontrados {len(yaml_files)} arquivo(s) YAML:")
        for yf in yaml_files:
            Logger.info(f"  📄 {yf.name}")
        print()
        Logger.info("Processando arquivos...")
        for yaml_file in yaml_files:
            Logger.info(f"\n📖 Lendo: {yaml_file.name}")
            self._parse_file(yaml_file)
        self._link_relationships()
        return self.tables, self.relationships

    def _parse_file(self, file_path: Path):
        """
        Parses a single YAML file, extracting sources and table definitions.
        """
        Logger.info(f"Parsing file: {file_path}")
        with open(file_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        tables_found = 0
        for source in config.get("sources", []):
            source_name = source.get("name", "unknown")
            schema = source.get("schema") or Path(file_path).stem.replace("_schema", "")
            database = source.get("database", "data-warehouse-tag")
            Logger.info(f"  Source: {source_name}")
            Logger.info(f"  Schema detectado: {schema}")
            for table_data in source.get("tables", []):
                self._parse_table(
                    table_data=table_data,
                    schema=schema,
                    database=database,
                )
                tables_found += 1
        Logger.info(f"  Found {tables_found} tables in {file_path}")

    def _parse_table(
        self,
        table_data: dict,
        schema: str = "dbo_tia",
        database: str = "data-warehouse-tag",
    ):
        """
        Builds a Table object from a YAML table definition and registers it in self.tables.
        Duplicated table names are ignored, first occurrence is kept.
        """
        if "name" not in table_data:
            Logger.warning("Tabela sem nome encontrada, ignorando...")
            return
        table_name = table_data["name"]
        if table_name in self.tables:
            Logger.warning(
                f"Tabela duplicada encontrada: {table_name} (usando primeira ocorrência)"
            )
            return
        if table_name.startswith("D_"):
            table_type = "dimension"
        elif table_name.startswith("F_"):
            table_type = "fact"
        else:
            table_type = "other"
        columns = []
        for col_data in table_data.get("columns", []):
            column = self._parse_column(col_data, table_name)
            columns.append(column)
            self._extract_relationships(col_data, table_name)
        table = Table(
            name=table_name,
            description=table_data.get("description", "Sem descrição"),
            type=table_type,
            tags=table_data.get("tags", []),
            columns=columns,
            relationships_out=[],
            relationships_in=[],
            schema=schema,
            database=database,
            custom_queries=self.custom_queries_config.get(table_name, []),
        )
        self.tables[table_name] = table

    def _parse_column(self, col_data: dict, table_name: str) -> Column:
        """
        Parses a column definition dictionary and returns a Column instance.
        Tests and data_tests are inspected to infer not-null, unique and relationship flags.
        """
        col_name = col_data.get("name", "")
        tests = col_data.get("tests", []) or col_data.get("data_tests", [])
        is_not_null = any(
            t == "not_null" or (isinstance(t, dict) and "not_null" in t) for t in tests
        )
        is_unique = any(
            t == "unique" or (isinstance(t, dict) and "unique" in t) for t in tests
        )
        is_fk = (
            any(isinstance(t, dict) and "relationships" in t for t in tests)
            or "_id" in col_name.lower()
        )
        is_pk = col_name == "HASH_ID"
        return Column(
            name=col_name,
            data_type=col_data.get("data_type", "N/A"),
            description=col_data.get("description", ""),
            is_pk=is_pk,
            is_fk=is_fk,
            is_not_null=is_not_null,
            is_unique=is_unique,
        )

    def _extract_relationships(self, col_data: dict, from_table: str):
        """
        Extracts relationship metadata from column tests and appends to self.relationships.
        Supports common dbt 'relationships' test structure and basic heuristics.
        """
        tests = col_data.get("tests", []) or col_data.get("data_tests", [])
        for test in tests:
            if isinstance(test, dict) and "relationships" in test:
                rel_data = test["relationships"]
                to_table = rel_data.get("to", "")
                to_table = to_table.replace("source('dbo_tia', '", "")
                to_table = to_table.replace("ref('", "")
                to_table = to_table.replace("')", "")
                if to_table:
                    rel = Relationship(
                        from_table=from_table,
                        from_col=col_data["name"],
                        to_table=to_table,
                        to_col=rel_data.get("field", "HASH_ID"),
                    )
                    self.relationships.append(rel)

    def _link_relationships(self):
        """
        Links relationships into the Table objects by populating relationships_out and relationships_in lists.
        """
        for rel in self.relationships:
            if rel.from_table in self.tables:
                self.tables[rel.from_table].relationships_out.append(rel)
            if rel.to_table in self.tables:
                self.tables[rel.to_table].relationships_in.append(rel)


class DocumentationBuilder:
    """
    Responsible for creating the Sphinx documentation folder structure and base config files.
    Use create_structure() to ensure directories exist and create_config_files() to write conf/index/makefile.
    """

    def __init__(self, docs_dir: Path = Path("docs")):
        self.docs_dir = docs_dir
        self.source_dir = docs_dir / "source"
        self.build_dir = docs_dir / "build"

    def create_structure(self):
        """
        Creates the full directory tree required by the Sphinx documentation (source, templates, static, tables categories).
        """
        directories = [
            self.docs_dir,
            self.source_dir,
            self.source_dir / "_static",
            self.source_dir / "_templates",
            self.source_dir / "tabelas" / "dimensoes",
            self.source_dir / "tabelas" / "fatos",
            self.source_dir / "tabelas" / "outros",
            self.source_dir / "guias",
            self.source_dir / "relacionamentos",
            self.source_dir / "dados_externos",
            self.build_dir,
        ]
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)

    def create_config_files(self):
        """
        Writes default Sphinx configuration, index, static CSS, Makefile and requirements file into the docs folder.
        """
        self._create_conf_py()
        self._create_index_rst()
        self._create_custom_css()
        self._create_makefile()
        self._create_requirements()

    def _create_conf_py(self):
        content = """# Sphinx Configuration - Sistema TIA
project = 'Sistema TIA - Data Warehouse'
copyright = '2024, Equipe de Dados'
author = 'Equipe de Dados'
release = '1.0.0'

extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.githubpages',
    'myst_parser',
    'sphinx_copybutton',
]

source_suffix = {'.rst': 'restructuredtext', '.md': 'markdown'}
templates_path = ['_templates']
exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']

html_theme = 'sphinx_rtd_theme'
html_static_path = ['_static']
html_css_files = ['custom.css']

html_theme_options = {
    'navigation_depth': 4,
    'collapse_navigation': False,
    'sticky_navigation': True,
    'style_nav_header_background': '#667eea',
}

myst_enable_extensions = ["colon_fence", "deflist", "tasklist"]
"""
        (self.source_dir / "conf.py").write_text(content, encoding="utf-8")

    def _create_index_rst(self):
        content = """Sistema TIA - Data Warehouse Educacional
=========================================

.. toctree::
   :maxdepth: 3
   :caption: Tabelas Dimensão
   :glob:

   tabelas/dimensoes/*

.. toctree::
   :maxdepth: 3
   :caption: Tabelas Fato
   :glob:

   tabelas/fatos/*

.. toctree::
   :maxdepth: 3
   :caption: Outras Tabelas / Schemas
   :glob:

   tabelas/outros/*

.. toctree::
   :maxdepth: 2
   :caption: Dados Externos

   dados_externos/censo_escolar
   dados_externos/pnad
   dados_externos/qedu

.. toctree::
   :maxdepth: 2
   :caption: Relacionamentos

   relacionamentos/diagrama_visual
   relacionamentos/diagrama_completo
   relacionamentos/diagrama_er

.. toctree::
   :maxdepth: 2
   :caption: Guias

   guias/consultas_comuns

:Database: ``data-warehouse-tag``
:Schema: ``dbo_tia``

Índices: :ref:`genindex` | :ref:`search`
"""
        (self.source_dir / "index.rst").write_text(content, encoding="utf-8")

    def _create_custom_css(self):
        content = """/* TIA Styles */
.wy-side-nav-search { 
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important;
}
.rst-content table.docutils { border: 2px solid #667eea; }
.rst-content table.docutils thead { background-color: #f0f4ff; }
.rst-content table.docutils tbody tr:hover { background-color: #f8f9fa; }
"""
        (self.source_dir / "_static" / "custom.css").write_text(
            content, encoding="utf-8"
        )

    def _create_makefile(self):
        content = """SPHINXBUILD = sphinx-build
SOURCEDIR = source
BUILDDIR = build

html:
\t$(SPHINXBUILD) -b html $(SOURCEDIR) $(BUILDDIR)/html
\t@echo ""
\t@echo "✅ HTML estático gerado em: $(BUILDDIR)/html/"
\t@echo "📂 Abra: $(BUILDDIR)/html/index.html"

clean:
\trm -rf $(BUILDDIR)/*
\t@echo "🧹 Arquivos limpos"

.PHONY: html clean
"""
        (self.docs_dir / "Makefile").write_text(content, encoding="utf-8")

    def _create_requirements(self):
        content = """sphinx>=7.0.0
sphinx-rtd-theme>=2.0.0
sphinx-copybutton>=0.5.0
myst-parser>=2.0.0
pyyaml>=6.0.0
"""
        (self.docs_dir / "requirements.txt").write_text(content, encoding="utf-8")


class TableDocGenerator:
    """
    Generates a Markdown document for a single Table instance.
    The generated document includes columns, constraints, relationships and example queries.
    """

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir

    def generate(self, table: Table):
        """
        Build and write the Markdown file for the provided Table object.
        """
        emoji = {"dimension": "📊", "fact": "📈", "other": "📋"}.get(table.type, "📋")
        category = {"dimension": "dimensoes", "fact": "fatos", "other": "outros"}.get(
            table.type, "outros"
        )
        tipo = {"dimension": "Dimensão", "fact": "Fato", "other": "Tabela"}.get(
            table.type, "Tabela"
        )
        content = f"""# {emoji} {table.name}

:Tipo: **{tipo}**  
:Descrição: {table.description}  
:Schema: ``{table.schema}``  
:Database: ``{table.database}``  
:Responsável: Equipe de Dados

---

## Estrutura de Colunas

| Coluna | Tipo | Restrições | Descrição |
|--------|------|------------|-----------|
"""
        for col in table.columns:
            constraints = []
            if col.is_pk:
                constraints.append("🔑 PK")
            if col.is_fk:
                constraints.append("🔗 FK")
            if col.is_not_null:
                constraints.append("`NOT NULL`")
            if col.is_unique:
                constraints.append("`UNIQUE`")
            constraints_str = " ".join(constraints) or "-"
            content += f"| `{col.name}` | `{col.data_type}` | {constraints_str} | {col.description} |\n"
        if table.relationships_out or table.relationships_in:
            content += "\n---\n\n## Relacionamentos\n\n"
            if table.relationships_out:
                content += "### Esta tabela referencia:\n\n"
                for rel in table.relationships_out:
                    content += f"* `{rel.from_col}` → **[{rel.to_table}](../{category}/{rel.to_table}.md)**.`{rel.to_col}`\n"
            if table.relationships_in:
                content += "\n### Referenciada por:\n\n"
                for rel in table.relationships_in:
                    content += f"* **[{rel.from_table}](../{category}/{rel.from_table}.md)**.`{rel.from_col}` → `{rel.to_col}`\n"
        content += f"""

---

## Exemplos SQL

### Consulta Básica

```sql
SELECT * FROM {table.schema}.{table.name} LIMIT 10;
```

### Contar Registros

```sql
SELECT COUNT(*) FROM {table.schema}.{table.name};
```
"""
        if table.custom_queries:
            content += "\n### Consultas Personalizadas\n\n"
            for query in table.custom_queries:
                content += f"#### {query.title}\n\n"
                if query.description:
                    content += f"{query.description}\n\n"
                content += f"```sql\n{query.sql}\n```\n\n"
        content += """

---

:Schema: ``dbo_tia``  
:Database: ``data-warehouse-tag``  
:Responsável: Equipe de Dados
"""
        output_file = self.output_dir / "tabelas" / category / f"{table.name}.md"
        output_file.write_text(content, encoding="utf-8")


class ERDiagramGenerator:
    """
    Produces several ER diagram representations (mermaid) based on discovered relationships and tables.
    """

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir

    def generate_simple(self, relationships: List[Relationship]):
        """
        Generates a simple ER diagram (mermaid) listing relationships as one-to-many lines.
        """
        content = """# Diagrama ER - Relacionamentos

```mermaid
erDiagram
"""
        for rel in relationships:
            content += (
                f'    {rel.from_table} ||--o{{ {rel.to_table} : "{rel.from_col}"\n'
            )
        content += "```\n\n**Legenda:** `||--o{` = Um para Muitos\n"
        output_file = self.output_dir / "relacionamentos" / "diagrama_er.md"
        output_file.write_text(content, encoding="utf-8")

    def generate_visual_schema(
        self, tables: Dict[str, Table], relationships: List[Relationship]
    ):
        """
        Generates a visual schema (mermaid flowchart) rendering tables with PK/FK summaries and relationship arrows.
        """
        content = """# Diagrama Visual de Schema (Estilo DBeaver)

Este diagrama mostra a estrutura completa do banco com todas as tabelas e suas relações PK/FK.

```mermaid
%%{init: {'theme':'base', 'themeVariables': { 'primaryColor':'#e3f2fd','primaryTextColor':'#000','primaryBorderColor':'#1976d2','lineColor':'#666','secondaryColor':'#fff3e0','tertiaryColor':'#f3e5f5'}}}%%
flowchart TB
    
"""
        dimensions = []
        facts = []
        others = []
        for table_name, table in sorted(tables.items()):
            pk_cols = [c.name for c in table.columns if c.is_pk]
            fk_cols = [c.name for c in table.columns if c.is_fk and not c.is_pk]
            pk_text = pk_cols[0] if pk_cols else "N/A"
            fk_text = ""
            if fk_cols:
                if len(fk_cols) <= 2:
                    fk_text = f"<br/><small>🔗 {', '.join(fk_cols)}</small>"
                else:
                    fk_text = f"<br/><small>🔗 {', '.join(fk_cols[:2])} +{len(fk_cols)-2}</small>"
            node_id = table_name.replace("_", "")
            label = f'"{table_name}<br/><small>🔑 {pk_text}</small>{fk_text}"'
            if table.type == "dimension":
                content += f"    {node_id}[{label}]\n"
                content += f"    style {node_id} fill:#e3f2fd,stroke:#1976d2,stroke-width:3px\n"
                dimensions.append(node_id)
            elif table.type == "fact":
                content += f"    {node_id}[{label}]\n"
                content += f"    style {node_id} fill:#fff3e0,stroke:#f57c00,stroke-width:3px\n"
                facts.append(node_id)
            else:
                content += f"    {node_id}[{label}]\n"
                content += f"    style {node_id} fill:#f3e5f5,stroke:#7b1fa2,stroke-width:2px\n"
                others.append(node_id)
        content += "\n"
        added_relations = set()
        for rel in relationships:
            from_id = rel.to_table.replace("_", "")
            to_id = rel.from_table.replace("_", "")
            rel_key = (from_id, to_id, rel.from_col)
            if rel_key not in added_relations:
                content += f"    {from_id} -->|{rel.from_col}| {to_id}\n"
                added_relations.add(rel_key)
        content += """
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

"""
        if dimensions:
            content += f"\n### 📊 Dimensões ({len(dimensions)})\n\n"
            dim_names = [t for t in tables.keys() if tables[t].type == "dimension"]
            for name in sorted(dim_names):
                content += f"* **{name}**\n"
        if facts:
            content += f"\n### 📈 Fatos ({len(facts)})\n\n"
            fact_names = [t for t in tables.keys() if tables[t].type == "fact"]
            for name in sorted(fact_names):
                content += f"* **{name}**\n"
        if others:
            content += f"\n### 📋 Outras ({len(others)})\n\n"
            other_names = [t for t in tables.keys() if tables[t].type == "other"]
            for name in sorted(other_names):
                content += f"* **{name}**\n"
        output_file = self.output_dir / "relacionamentos" / "diagrama_visual.md"
        output_file.write_text(content, encoding="utf-8")

    def generate_interactive(
        self, tables: Dict[str, Table], relationships: List[Relationship]
    ):
        """
        Generates a detailed ER diagram including every column and indicators (PK, FK, NOT NULL).
        Also writes statistics and a relationship table for reference.
        """
        content = """# Diagrama ER Completo (Todas as Colunas)

Este diagrama mostra todas as tabelas com TODAS as suas colunas e relacionamentos.

```mermaid
erDiagram
"""
        dimensions = {k: v for k, v in tables.items() if v.type == "dimension"}
        facts = {k: v for k, v in tables.items() if v.type == "fact"}
        others = {k: v for k, v in tables.items() if v.type == "other"}
        for table_name, table in sorted(tables.items()):
            content += f"\n    {table_name} {{\n"
            for col in table.columns:
                col_type = col.data_type.upper().split("(")[0]
                indicators = []
                if col.is_pk:
                    indicators.append("PK")
                if col.is_fk:
                    indicators.append("FK")
                if col.is_not_null and not col.is_pk:
                    indicators.append("NOT NULL")
                indicator_str = f" \"{', '.join(indicators)}\"" if indicators else ""
                content += f"        {col_type} {col.name}{indicator_str}\n"
            content += "    }\n"
        content += "\n    %% Relacionamentos\n"
        for rel in relationships:
            content += f'    {rel.to_table} ||--o{{ {rel.from_table} : "{rel.from_col} -> {rel.to_col}"\n'
        content += """```

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

"""
        content += f"* **Total de Tabelas**: {len(tables)}\n"
        content += f"  * Dimensões: {len(dimensions)}\n"
        content += f"  * Fatos: {len(facts)}\n"
        if others:
            content += f"  * Outras: {len(others)}\n"
        content += f"* **Total de Relacionamentos**: {len(relationships)}\n"
        if dimensions:
            content += "\n### Tabelas Dimensão\n\n"
            for table_name in sorted(dimensions.keys()):
                table = dimensions[table_name]
                content += f"* **{table_name}** ({len(table.columns)} colunas)\n"
        if facts:
            content += "\n### Tabelas Fato\n\n"
            for table_name in sorted(facts.keys()):
                table = facts[table_name]
                content += f"* **{table_name}** ({len(table.columns)} colunas)\n"
        if relationships:
            content += "\n## Tabela de Relacionamentos\n\n"
            content += (
                "| Tabela Origem (FK) | Coluna FK | Tabela Destino (PK) | Coluna PK |\n"
            )
            content += (
                "|-------------------|-----------|---------------------|----------|\n"
            )
            for rel in sorted(relationships, key=lambda x: (x.from_table, x.to_table)):
                content += f"| {rel.from_table} | `{rel.from_col}` | {rel.to_table} | `{rel.to_col}` |\n"
        output_file = self.output_dir / "relacionamentos" / "diagrama_completo.md"
        output_file.write_text(content, encoding="utf-8")

class ExternalDataDocGenerator:
    """
    Generates documentation for external data sources (Censo Escolar, PNAD, QEdu).
    """

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir / "dados_externos"

    def generate_all(self):
        """
        Generates all external data documentation files.
        """
        self._generate_censo_escolar()
        self._generate_pnad()
        self._generate_qedu()

    def _generate_censo_escolar(self):
        content = """📚 Censo Escolar - Atlas Brasil
=====================================

:Schema: ``raw``
:Database: ``data-warehouse-tag``
:Fonte: Atlas Brasil (atlasbrasil.org.br)
:Período: 1991, 2000, 2010, 2011-2014
:Granularidade: Municipal
:Responsável: Equipe de Dados

----

Descrição
---------

Dados do **Censo Escolar brasileiro** extraídos do site do Atlas Brasil. O Atlas realiza um trabalho de agregação e enriquecimento dos dados originais do INEP (Instituto Nacional de Estudos e Pesquisas Educacionais Anísio Teixeira).

Estes dados são utilizados para enriquecer nossa base de estudantes e fornecer contexto educacional em nível municipal.

----

Tabela: Atlas_CensoEscolar_2011a2014_TodosMunc
----------------------------------------------

Contém indicadores educacionais agregados por município para o período de 2011 a 2014.

Principais Categorias de Dados
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**1. Matrículas por Rede (Pública/Privada)**

* Ensino Fundamental (2013-2017)
* Ensino Médio (2013-2017)

**2. Taxa de Distorção Idade-Série**

* Ensino Fundamental geral e por rede
* Ensino Médio geral e por rede
* Período: 2013-2017

**3. Taxa de Evasão**

* Ensino Fundamental e Médio
* Desagregado por rede (pública/privada)
* Período: 2013-2014

**4. IDEB (Índice de Desenvolvimento da Educação Básica)**

* Anos iniciais do Ensino Fundamental (2013, 2015, 2017)
* Anos finais do Ensino Fundamental (2013, 2015, 2017)

**5. Infraestrutura Escolar**

* Percentual de alunos em escolas com laboratório de informática
* Percentual de alunos em escolas com internet
* Por nível de ensino (Fundamental/Médio)

**6. Formação Docente**

* Percentual de docentes com formação adequada
* Desagregado por nível e rede de ensino

**7. Indicadores de Escolarização da População**

* Taxa de analfabetismo (15+, 18+, 25+ anos)
* Média de anos de estudo
* Taxa de frequência líquida (básico, fundamental, médio, superior)
* Percentual de conclusão por faixa etária

**8. Desagregações Demográficas (Censo 2013-2014)**

* Por raça/cor (Branco/Negro)
* Por sexo (Homem/Mulher)
* Por localização (Rural/Urbano)

----

Estrutura de Colunas
--------------------

.. list-table::
   :header-rows: 1
   :widths: 30 15 55

   * - Campo
     - Tipo
     - Descrição
   * - ``Territorialidades``
     - varchar(150)
     - Nome do município
   * - ``DeMatrculasDaRedePblicaNoEnsinoFundamental[Ano]``
     - real
     - Percentual de matrículas na rede pública - Ensino Fundamental
   * - ``DeMatrculasDaRedePblicaNoEnsinoMdio[Ano]``
     - real
     - Percentual de matrículas na rede pública - Ensino Médio
   * - ``TaxaDeDistoroIdadeSrieNoFundamental[Ano]``
     - real
     - Taxa de distorção idade-série no Fundamental
   * - ``TaxaDeEvasoNoEnsinoFundamental[Ano]``
     - real
     - Taxa de evasão no Ensino Fundamental
   * - ``IdebAnosIniciaisDoEnsinoFundamental[Ano]``
     - real
     - IDEB dos anos iniciais
   * - ``IdebAnosFinaisDoEnsinoFundamental[Ano]``
     - real
     - IDEB dos anos finais
   * - ``DeDocentesDoFundamentalComFormaoAdequada[Ano]``
     - real
     - % de docentes com formação adequada
   * - ``TaxaDeAnalfabetismo[Faixa][Ano]``
     - real
     - Taxa de analfabetismo por faixa etária
   * - ``MdiaDeAnosDeEstudo[Ano]``
     - real
     - Média de anos de estudo da população

.. note::
   [Ano] representa os anos disponíveis (2012-2017, conforme a métrica)

----

Exemplos de Uso
---------------

**Consultar IDEB por município (2017)**

.. code-block:: sql

   SELECT 
       Territorialidades,
       IdebAnosIniciaisDoEnsinoFundamental2017,
       IdebAnosFinaisDoEnsinoFundamental2017
   FROM raw.Atlas_CensoEscolar_2011a2014_TodosMunc
   WHERE IdebAnosIniciaisDoEnsinoFundamental2017 IS NOT NULL
   ORDER BY IdebAnosIniciaisDoEnsinoFundamental2017 DESC;

**Analisar evolução da taxa de distorção**

.. code-block:: sql

   SELECT 
       Territorialidades,
       TaxaDeDistoroIdadeSrieNoFundamental2013 AS Taxa_2013,
       TaxaDeDistoroIdadeSrieNoFundamental2017 AS Taxa_2017,
       (TaxaDeDistoroIdadeSrieNoFundamental2017 - 
        TaxaDeDistoroIdadeSrieNoFundamental2013) AS Variacao
   FROM raw.Atlas_CensoEscolar_2011a2014_TodosMunc
   ORDER BY Variacao;

----

Observações Importantes
-----------------------

* **Granularidade**: Dados agregados a nível **municipal**
* **Período**: Múltiplos anos (1991, 2000, 2010, 2011-2017 dependendo da métrica)
* **Fonte confiável**: Dados oficiais processados pelo Atlas Brasil
* **Uso**: Análises de contexto educacional, benchmarking municipal, séries históricas

----

:Schema: ``raw``
:Database: ``data-warehouse-tag``
:Responsável: Equipe de Dados
"""
        output_file = self.output_dir / "censo_escolar.rst"
        output_file.write_text(content, encoding="utf-8")

    def _generate_pnad(self):
        content = """📊 PNAD - Pesquisa Nacional por Amostra de Domicílios
======================================================

:Schema: ``raw``
:Database: ``data-warehouse-tag``
:Fonte: IBGE - PNAD
:Período: Múltiplos anos
:Granularidade: Estadual
:Responsável: Equipe de Dados

----

Descrição
---------

Dados da **Pesquisa Nacional por Amostra de Domicílios (PNAD)** realizada pelo IBGE. Estes dados são utilizados para enriquecer nossa base de estudantes com contexto socioeconômico e educacional em nível estadual.

A PNAD é uma das principais pesquisas sobre características socioeconômicas da população brasileira.

----

Tabelas Disponíveis
-------------------

1. Atlas_PNAD_Estados_Total
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Indicadores gerais por estado, sem desagregações.

**Principais Indicadores:**

**Desenvolvimento Humano (IDH)**

* ``IDHM``: Índice de Desenvolvimento Humano Municipal
* ``IDHM_L``: IDH Longevidade
* ``IDHM_E``: IDH Educação
* ``IDHM_R``: IDH Renda
* ``IDHMAD``: IDH ajustado por desigualdade

**Longevidade**

* ``ESPVIDA``: Esperança de vida ao nascer
* ``MORT1``: Mortalidade infantil

**Educação**

* ``ANOSEST``: Anos médios de estudo
* ``T_ANALF[Faixa]``: Taxa de analfabetismo (15+, 18+, 25+ anos)
* ``T_FREQ[Faixa]``: Taxa de frequência escolar por faixa etária
* ``T_FUND[Faixa]``: Taxa com Fundamental completo
* ``T_MED[Faixa]``: Taxa com Médio completo
* ``T_SUPER[Faixa]``: Taxa com Superior completo
* ``T_ATRASO_2_[NIVEL]``: Taxa de atraso escolar (2+ anos)

**Renda e Desigualdade**

* ``RDPC``: Renda per capita
* ``GINI``: Coeficiente de Gini
* ``THEIL``: Índice de Theil
* ``PIND``, ``PMPOB``, ``PPOB``: Proporção de extremamente pobres, pobres e vulneráveis

**População**

* Múltiplas colunas populacionais por faixa etária (POP5A6, POP6A14, etc.)

----

2. Atlas_PNAD_Estados_Total_Cor
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Mesmos indicadores da tabela anterior, desagregados por **raça/cor**.

**Campo adicional:**

* ``COR``: Classificação racial (Branco, Negro, etc.)

----

3. Atlas_PNAD_Estados_Total_Sexo
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Mesmos indicadores da tabela anterior, desagregados por **sexo**.

**Campos adicionais:**

* ``SEXO``: Masculino ou Feminino
* ``IDHM_AJUSTADO``: IDH ajustado por sexo
* ``IDHM_R_AJUSTADO``: IDH Renda ajustado

----

Estrutura Comum das Tabelas
----------------------------

.. list-table::
   :header-rows: 1
   :widths: 25 15 60

   * - Campo
     - Tipo
     - Descrição
   * - ``ANO``
     - int
     - Ano de referência
   * - ``AGREGACAO``
     - varchar(50)
     - Tipo de agregação (Estado)
   * - ``CODIGO``
     - real/int
     - Código IBGE do estado
   * - ``NOME``
     - varchar(50)
     - Nome do estado
   * - ``IDHM``
     - real
     - Índice de Desenvolvimento Humano Municipal
   * - ``ESPVIDA``
     - real
     - Esperança de vida ao nascer
   * - ``ANOSEST``
     - real
     - Média de anos de estudo
   * - ``RDPC``
     - real
     - Renda per capita
   * - ``GINI``
     - real
     - Coeficiente de Gini (desigualdade)
   * - ``POPTOT``
     - varchar(50)
     - População total

----

Exemplos de Uso
---------------

**Comparar IDH entre estados**

.. code-block:: sql

   SELECT 
       NOME,
       ANO,
       IDHM,
       IDHM_E AS IDH_Educacao,
       IDHM_R AS IDH_Renda,
       IDHM_L AS IDH_Longevidade
   FROM raw.Atlas_PNAD_Estados_Total
   WHERE ANO = 2021
   ORDER BY IDHM DESC;

**Analisar desigualdade de gênero na educação**

.. code-block:: sql

   SELECT 
       NOME,
       ANO,
       SEXO,
       T_ANALF25M AS Taxa_Analfabetismo_25plus,
       T_SUPER25M AS Taxa_Superior_25plus,
       ANOSEST AS Media_Anos_Estudo
   FROM raw.Atlas_PNAD_Estados_Total_Sexo
   WHERE ANO = 2021
   ORDER BY NOME, SEXO;

**Desigualdade racial no acesso à educação**

.. code-block:: sql

   SELECT 
       NOME,
       ANO,
       COR,
       T_FREQ15A17 AS Taxa_Freq_15_17,
       T_MED25M AS Taxa_Medio_Completo,
       ANOSEST AS Media_Anos_Estudo
   FROM raw.Atlas_PNAD_Estados_Total_Cor
   WHERE ANO = 2021
   ORDER BY NOME, COR;

----

Observações Importantes
-----------------------

* **Granularidade**: Dados agregados a nível **estadual** (não há dados municipais na PNAD)
* **Desagregações**: Total, por Cor/Raça e por Sexo
* **Uso**: Análises de contexto socioeconômico, estudos de desigualdade, benchmarking estadual
* **Integração**: Usado para enriquecer análises de estudantes quando não há dados municipais disponíveis

----

:Schema: ``raw``
:Database: ``data-warehouse-tag``
:Responsável: Equipe de Dados
"""
        output_file = self.output_dir / "pnad.rst"
        output_file.write_text(content, encoding="utf-8")

    def _generate_qedu(self):
        content = """📈 QEdu - Dados Educacionais
============================

:Schema: ``raw``
:Database: ``data-warehouse-tag``
:Fonte: QEdu (qedu.org.br)
:Período: Múltiplos anos
:Granularidade: Municipal
:Responsável: Equipe de Dados

----

Descrição
---------

Dados do **QEdu**, plataforma que disponibiliza e analisa dados educacionais públicos do Brasil. Todos os dados estão na **versão mais atualizada disponível**.

O QEdu processa dados do Censo Escolar, Prova Brasil e outras fontes oficiais, oferecendo indicadores educacionais consolidados.

----

Tabelas Disponíveis
-------------------

1. QeduAprendizadoTodosAnos
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Indicadores de **aprendizado adequado** baseados na Prova Brasil/SAEB, por município.

**Estrutura:**

.. list-table::
   :header-rows: 1
   :widths: 25 15 60

   * - Campo
     - Tipo
     - Descrição
   * - ``ibge_id``
     - int
     - Código IBGE do município
   * - ``ano``
     - int
     - Ano de referência
   * - ``ciclo_id``
     - varchar(50)
     - Ciclo escolar (Anos Iniciais/Finais)
   * - ``dependencia_id``
     - int
     - Dependência administrativa (Pública/Privada)
   * - ``lp_adequado``
     - real
     - % de alunos com aprendizado adequado em Língua Portuguesa
   * - ``mt_adequado``
     - real
     - % de alunos com aprendizado adequado em Matemática
   * - ``lp_insuficiente``
     - real
     - % em nível insuficiente - LP
   * - ``lp_basico``
     - real
     - % em nível básico - LP
   * - ``lp_proficiente``
     - real
     - % em nível proficiente - LP
   * - ``lp_avancado``
     - real
     - % em nível avançado - LP
   * - ``mt_insuficiente``
     - real
     - % em nível insuficiente - MT
   * - ``mt_basico``
     - real
     - % em nível básico - MT
   * - ``mt_proficiente``
     - real
     - % em nível proficiente - MT
   * - ``mt_avancado``
     - real
     - % em nível avançado - MT

**Níveis de Proficiência:**

* **Insuficiente**: Não demonstrou conhecimentos básicos
* **Básico**: Demonstrou desenvolvimento parcial
* **Proficiente**: Demonstrou conhecimentos esperados
* **Avançado**: Superou o esperado para a série

----

2. QeduIDEBTodosAnos
~~~~~~~~~~~~~~~~~~~~

Dados do **IDEB (Índice de Desenvolvimento da Educação Básica)** por município.

**Estrutura:**

.. list-table::
   :header-rows: 1
   :widths: 25 15 60

   * - Campo
     - Tipo
     - Descrição
   * - ``ibge_id``
     - int
     - Código IBGE do município
   * - ``dependencia_id``
     - int
     - Dependência administrativa
   * - ``ciclo_id``
     - varchar(50)
     - Ciclo escolar
   * - ``ano``
     - int
     - Ano de referência
   * - ``ideb``
     - real
     - Índice IDEB (0-10)
   * - ``fluxo``
     - real
     - Taxa de aprovação
   * - ``aprendizado``
     - real
     - Nota de aprendizado
   * - ``nota_mt``
     - real
     - Nota de Matemática
   * - ``nota_lp``
     - real
     - Nota de Língua Portuguesa

.. note::
   **Cálculo do IDEB:** IDEB = Aprendizado × Fluxo

----

3. QeduPermanenciaTodosAnos
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Análise de **permanência escolar** por coorte de nascimento.

**Estrutura:**

.. list-table::
   :header-rows: 1
   :widths: 25 15 60

   * - Campo
     - Tipo
     - Descrição
   * - ``ibge_id``
     - int
     - Código IBGE do município
   * - ``ano_nascimento``
     - int
     - Ano de nascimento da coorte
   * - ``ano_censo``
     - int
     - Ano do Censo analisado
   * - ``permanencia``
     - real
     - % de estudantes que permaneceram na escola
   * - ``fora``
     - real
     - % de estudantes fora da escola
   * - ``Origem``
     - varchar(50)
     - Fonte dos dados

----

4. QeduTaxaDeDistorcaoTodosAnos
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Taxa de distorção idade-série** detalhada por ano escolar.

**Principais campos:**

* ``ef_1ano`` até ``ef_9ano``: Taxa de distorção por ano do EF
* ``ef_total_ai``: Total anos iniciais EF
* ``ef_total_af``: Total anos finais EF
* ``ef_total``: Total Ensino Fundamental
* ``em_1ano`` até ``em_4ano``: Taxa de distorção por ano do EM
* ``em_total``: Total Ensino Médio

----

5. QeduTaxaDeRendimentoTodosAnos
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Taxas de aprovação, reprovação e abandono** por série.

**Estrutura:**

.. list-table::
   :header-rows: 1
   :widths: 25 15 60

   * - Campo
     - Tipo
     - Descrição
   * - ``ibge_id``
     - int
     - Código IBGE do município
   * - ``ano``
     - int
     - Ano de referência
   * - ``serie_id``
     - int
     - Identificador da série
   * - ``matriculas``
     - real
     - Total de matrículas
   * - ``aprovados``
     - real
     - Taxa de aprovação (%)
   * - ``reprovados``
     - real
     - Taxa de reprovação (%)
   * - ``abandonos``
     - real
     - Taxa de abandono (%)

----

Exemplos de Uso
---------------

**Municípios com melhor aprendizado em LP e MT**

.. code-block:: sql

   SELECT 
       ibge_id,
       ano,
       ciclo_id,
       lp_adequado,
       mt_adequado,
       (lp_adequado + mt_adequado) / 2 AS Media_Adequado
   FROM raw.QeduAprendizadoTodosAnos
   WHERE ano = 2021
   ORDER BY Media_Adequado DESC
   LIMIT 10;

**Evolução do IDEB ao longo do tempo**

.. code-block:: sql

   SELECT 
       ibge_id,
       ciclo_id,
       ano,
       ideb,
       fluxo,
       aprendizado
   FROM raw.QeduIDEBTodosAnos
   WHERE ibge_id = 3550308  -- São Paulo
   ORDER BY ano, ciclo_id;

**Análise de distorção por dependência**

.. code-block:: sql

   SELECT 
       ano,
       dependencia_id,
       AVG(ef_total) AS Media_Distorcao_EF,
       AVG(em_total) AS Media_Distorcao_EM
   FROM raw.QeduTaxaDeDistorcaoTodosAnos
   GROUP BY ano, dependencia_id
   ORDER BY ano, dependencia_id;

**Taxa de abandono por série**

.. code-block:: sql

   SELECT 
       ano,
       serie_id,
       dependencia_id,
       AVG(abandonos) AS Taxa_Media_Abandono
   FROM raw.QeduTaxaDeRendimentoTodosAnos
   WHERE ano >= 2018
   GROUP BY ano, serie_id, dependencia_id
   ORDER BY ano, serie_id;

----

Observações Importantes
-----------------------

* **Granularidade**: Dados a nível **municipal**
* **Periodicidade**: Dados do Censo Escolar (anual) e Prova Brasil (bienal)
* **Fonte confiável**: QEdu processa dados oficiais do INEP
* **Uso**: Análises de qualidade educacional, identificação de municípios/escolas em risco, monitoramento de políticas públicas
* **Integração**: Complementa dados do software de gestão escolar com contexto municipal

----

:Schema: ``raw``
:Database: ``data-warehouse-tag``
:Responsável: Equipe de Dados
"""
        output_file = self.output_dir / "qedu.rst"
        output_file.write_text(content, encoding="utf-8")


class DocumentationOrchestrator:
    """
    Orchestrates the full documentation generation process:
    - parses YAML schemas
    - builds folder structure and base config files
    - generates per-table docs and ER diagrams
    - attempts to run sphinx-build to produce static HTML
    """

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.sources_dir = project_root / "docs" / "schemas_definitions"
        self.docs_dir = project_root / "docs"

    def run(self):
        """
        Runs the end-to-end documentation generation pipeline.
        Exits with code 1 when the source directory is missing.
        """
        Logger.header("=" * 60)
        Logger.header("SPHINX DOCUMENTATION GENERATOR - SISTEMA TIA")
        Logger.header("=" * 60)
        if not self.sources_dir.exists():
            Logger.error(f"Diretório não encontrado: {self.sources_dir}")
            sys.exit(1)
        Logger.info("Parseando arquivos YAML...")
        parser = YAMLParser(self.sources_dir)
        tables, relationships = parser.parse_all()
        Logger.success(f"{len(tables)} tabelas | {len(relationships)} relacionamentos")
        Logger.info("Criando estrutura de diretórios...")
        builder = DocumentationBuilder(self.docs_dir)
        builder.create_structure()
        builder.create_config_files()
        Logger.success("Estrutura criada")
        Logger.info("Gerando documentação das tabelas...")
        doc_gen = TableDocGenerator(self.docs_dir / "source")
        Logger.info(f"  Total de tabelas a documentar: {len(tables)}")
        for table_name in sorted(tables.keys()):
            table = tables[table_name]
            Logger.info(
                f"  • {table_name} ({table.type}) - {len(table.columns)} colunas"
            )
            doc_gen.generate(table)
        Logger.success(f"{len(tables)} tabelas documentadas")
        Logger.info("Gerando diagramas ER...")
        er_gen = ERDiagramGenerator(self.docs_dir / "source")
        er_gen.generate_simple(relationships)
        er_gen.generate_visual_schema(tables, relationships)
        er_gen.generate_interactive(tables, relationships)
        Logger.success("Diagramas ER criados (3 tipos)")
        Logger.info("Gerando documentação de Dados Externos...")
        ext_gen = ExternalDataDocGenerator(self.docs_dir / "source")
        ext_gen.generate_all()
        Logger.success("Dados Externos documentados")
        Logger.info("Construindo HTML com Sphinx...")
        self._build_html()
        Logger.header("\n✅ DOCUMENTAÇÃO GERADA COM SUCESSO!")
        Logger.info(
            f"\n📂 HTML estático: {self.docs_dir / 'build' / 'html' / 'index.html'}"
        )
        Logger.info("💡 Abra o arquivo index.html no navegador")
        Logger.info("🔄 Para atualizar: execute este script novamente\n")

    def _build_html(self):
        """
        Attempts to execute sphinx-build to produce HTML output. If sphinx-build is not installed,
        a warning is shown with instructions to install the docs requirements.
        """
        import subprocess

        try:
            result = subprocess.run(
                [
                    "sphinx-build",
                    "-b",
                    "html",
                    str(self.docs_dir / "source"),
                    str(self.docs_dir / "build" / "html"),
                ],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                Logger.success("Build HTML concluído")
            else:
                Logger.warning("Build teve avisos (verifique logs)")
        except FileNotFoundError:
            Logger.warning(
                "sphinx-build não encontrado. Execute: pip install -r docs/requirements.txt"
            )

    def clean(self):
        """
        Removes the docs directory tree produced by this tool.
        """
        import shutil

        Logger.info("Limpando arquivos gerados...")
        if self.docs_dir.exists():
            shutil.rmtree(self.docs_dir)
        Logger.success("Limpeza concluída")


def main():
    """
    CLI entrypoint that either runs the documentation generation pipeline or cleans generated docs.
    """
    parser = argparse.ArgumentParser(
        description="Gerador de Documentação Sphinx Estática - TIA"
    )
    parser.add_argument("--clean", action="store_true", help="Limpar arquivos gerados")
    args = parser.parse_args()
    orchestrator = DocumentationOrchestrator(Path.cwd())
    if args.clean:
        orchestrator.clean()
    else:
        orchestrator.run()


if __name__ == "__main__":
    main()
