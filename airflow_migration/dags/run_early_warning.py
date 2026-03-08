import pandas as pd
import numpy as np
import shap
from neo4j import GraphDatabase
from sklearn.ensemble import GradientBoostingRegressor
import warnings
warnings.filterwarnings('ignore')

pd.set_option('display.max_columns', 50)
NEO4J_URI = 'bolt://neo4j:7687'
NEO4J_USER = 'neo4j'
NEO4J_PASSWORD = 'password'

def get_classroom_mapping():
    try:
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        with driver.session() as session:
            result = session.run("""
                MATCH (s:Student)-[:ENROLLED_IN]->(c:Classroom)
                MATCH (c)-[:LOCATED_IN]->(sch:School)
                RETURN s.id AS student_id, c.name AS classroom, sch.name AS school
            """)
            data = [record.data() for record in result]
        df = pd.DataFrame(data)
        return df.drop_duplicates(subset=['student_id'], keep='last')
    except Exception as e:
        print(f"[{e}] Neo4j Offline - Gerando Mock de Dados (Fallback)...")
        # Mocking values for demonstration
        ids = [f'aluno_{i}' for i in range(2000)]
        turmas = [f'Turma 9o Ano {np.random.choice(["A", "B", "C"])}' for _ in range(2000)]
        escolas = [f'Escola {np.random.choice(["Alvorada", "Sertaozinho", "Liberdade", "Esperanca"])}' for _ in range(2000)]
        return pd.DataFrame({'student_id': ids, 'classroom': turmas, 'school': escolas})

df_geo = get_classroom_mapping()
print(f"Total de alunos rastreados geograficamente: {len(df_geo)}")

np.random.seed(42)
ids = df_geo['student_id'].values

# Simulating Model Input Features
df_features = pd.DataFrame({
    'student_id': ids,
    'nota_mat_norm': np.random.uniform(3, 9, len(ids)),
    'nota_lp_norm': np.random.uniform(4, 9, len(ids)),
    'nota_ciencias_norm': np.random.uniform(4, 9, len(ids)),
    'nota_hist_norm': np.random.uniform(4, 9, len(ids)),
    'pct_disciplinas_abaixo5': np.random.uniform(0.01, 0.4, len(ids)),
    'nota_dispersao': np.random.uniform(0.1, 1.5, len(ids)),
    'taxa_ausencia_pct': np.random.uniform(2, 10, len(ids))
})

# Plant a known extreme anomaly for demonstration (e.g. at the first classroom)
print("Injetando perfil crônico de Risco em 150 alunos base...")
df_features.loc[0:150, 'nota_mat_norm'] = np.random.uniform(1.2, 3.5, 151)
df_features.loc[0:150, 'taxa_ausencia_pct'] = np.random.uniform(30, 48, 151)
df_features.loc[0:150, 'pct_disciplinas_abaixo5'] = np.random.uniform(0.7, 0.98, 151)

X = df_features.drop(columns=['student_id'])
# Real math baseline logic to simulate correct tree fitting
y_matematico = (X['nota_mat_norm'] * 0.3) + (X['nota_lp_norm'] * 0.25) + (X['nota_ciencias_norm'] * 0.15) - (X['pct_disciplinas_abaixo5'] * 2.5) - (X['taxa_ausencia_pct'] * 0.05)
y_matematico = np.clip(y_matematico, 0, 10)

print("Treinando Instância Local (Simulando ML Pipeline do Airflow)...")
model_ef2 = GradientBoostingRegressor(n_estimators=100, max_depth=4, random_state=42)
model_ef2.fit(X, y_matematico)

print("Cruzando matriz ML Cega com Neo4J Físico via Pandas Join...")
df_features['pred_nota_final'] = model_ef2.predict(X)
df_merged = df_features.merge(df_geo, on="student_id", how="inner")

painel_turmas = df_merged.groupby(['school', 'classroom']).agg(
    media_prevista=('pred_nota_final', 'mean'),
    total_alunos=('student_id', 'count')
).reset_index()

# Filter low count noise
painel_turmas = painel_turmas[painel_turmas['total_alunos'] >= 8]
top_5_emergencias = painel_turmas.sort_values('media_prevista', ascending=True).head(5)

print("\n=======================================================")
print("🚨 AS 5 TURMAS COM RISCO BRUTAL DE DEFASAGEM DE NOTAS:")
print("=======================================================")
print(top_5_emergencias.to_string(index=False))

alvo_escola = top_5_emergencias.iloc[0]['school']
alvo_turma = top_5_emergencias.iloc[0]['classroom']

print(f"\n=======================================================")
print(f"🔍 DIAGNÓSTICO SHAP: A causa raiz da turma {alvo_turma} | {alvo_escola}:")
print("=======================================================")

df_alunos_isolados = df_merged[(df_merged['school'] == alvo_escola) & (df_merged['classroom'] == alvo_turma)]
X_isolado = df_alunos_isolados.drop(columns=['student_id', 'pred_nota_final', 'school', 'classroom'])

explainer = shap.TreeExplainer(model_ef2)
shap_values = explainer.shap_values(X_isolado)
impacto_na_media_geral = np.mean(shap_values, axis=0)

diagnostico_df = pd.DataFrame({
    'Fator Crítico': X_isolado.columns,
    'Impacto Matemático na Nota GERAL da Turma (Pontos)': np.round(impacto_na_media_geral, 2)
}).sort_values('Impacto Matemático na Nota GERAL da Turma (Pontos)', ascending=True)

# Select components destroying the mean
print(diagnostico_df.head(5).to_string(index=False))
import numpy as np
import shap
from neo4j import GraphDatabase
from sklearn.ensemble import GradientBoostingRegressor
import warnings
warnings.filterwarnings('ignore')

pd.set_option('display.max_columns', 50)
NEO4J_URI = 'bolt://localhost:7687'
NEO4J_USER = 'neo4j'
NEO4J_PASSWORD = 'password'

def get_classroom_mapping():
    try:
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        with driver.session() as session:
            result = session.run("""
                MATCH (s:Student)-[:ENROLLED_IN]->(c:Classroom)
                MATCH (c)-[:LOCATED_IN]->(sch:School)
                RETURN s.id AS student_id, c.name AS classroom, sch.name AS school
            """)
            data = [record.data() for record in result]
        df = pd.DataFrame(data)
        return df.drop_duplicates(subset=['student_id'], keep='last')
    except:
        print('Neo4j Offline - Gerando Mock (Fallback)...')
        ids = [f'aluno_{i}' for i in range(2000)]
        turmas = [f'Turma 9o Ano {np.random.choice(["A", "B", "C"])}' for _ in range(2000)]
        escolas = [f'Escola {np.random.choice(["Alvorada", "Sertaozinho", "Liberdade", "Esperanca"])}' for _ in range(2000)]
        return pd.DataFrame({'student_id': ids, 'classroom': turmas, 'school': escolas})

df_geo = get_classroom_mapping()

np.random.seed(42)
ids = df_geo['student_id'].values

df_features = pd.DataFrame({
    'student_id': ids,
    'nota_mat_norm': np.random.uniform(3, 9, len(ids)),
    'nota_lp_norm': np.random.uniform(4, 9, len(ids)),
    'nota_ciencias_norm': np.random.uniform(4, 9, len(ids)),
    'nota_hist_norm': np.random.uniform(4, 9, len(ids)),
    'pct_disciplinas_abaixo5': np.random.uniform(0.01, 0.4, len(ids)),
    'nota_dispersao': np.random.uniform(0.1, 1.5, len(ids)),
    'taxa_ausencia_pct': np.random.uniform(2, 10, len(ids))
})

# Plant Anomaly
df_features.loc[0:150, 'nota_mat_norm'] = np.random.uniform(1.2, 3.5, 151)
df_features.loc[0:150, 'taxa_ausencia_pct'] = np.random.uniform(30, 48, 151)
df_features.loc[0:150, 'pct_disciplinas_abaixo5'] = np.random.uniform(0.7, 0.98, 151)

X = df_features.drop(columns=['student_id'])
y_matematico = (X['nota_mat_norm'] * 0.3) + (X['nota_lp_norm'] * 0.25) + (X['nota_ciencias_norm'] * 0.15) - (X['pct_disciplinas_abaixo5'] * 2.5) - (X['taxa_ausencia_pct'] * 0.05)
y_matematico = np.clip(y_matematico, 0, 10)

model_ef2 = GradientBoostingRegressor(n_estimators=100, max_depth=4, random_state=42)
model_ef2.fit(X, y_matematico)

df_features['pred_nota_final'] = model_ef2.predict(X)

df_merged = df_features.merge(df_geo, on="student_id", how="inner")
painel_turmas = df_merged.groupby(['school', 'classroom']).agg(
    media_prevista=('pred_nota_final', 'mean'),
    total_alunos=('student_id', 'count')
).reset_index()

painel_turmas = painel_turmas[painel_turmas['total_alunos'] >= 8]
top_5_emergencias = painel_turmas.sort_values('media_prevista', ascending=True).head(5)

print("\n🚨 AS 5 TURMAS COM RISCO BRUTAL DE DEFASAGEM DE NOTAS:")
print(top_5_emergencias.to_string(index=False))

alvo_escola = top_5_emergencias.iloc[0]['school']
alvo_turma = top_5_emergencias.iloc[0]['classroom']

print(f"\n🔍 DIAGNÓSTICO: A causa raiz da turma de maior risco ({alvo_turma} | {alvo_escola}):")

df_alunos_isolados = df_merged[(df_merged['school'] == alvo_escola) & (df_merged['classroom'] == alvo_turma)]
X_isolado = df_alunos_isolados.drop(columns=['student_id', 'pred_nota_final', 'school', 'classroom'])

explainer = shap.TreeExplainer(model_ef2)
shap_values = explainer.shap_values(X_isolado)
impacto_na_media_geral = np.mean(shap_values, axis=0)

diagnostico_df = pd.DataFrame({
    'Fator Crítico': X_isolado.columns,
    'Impacto (SHAP Value)': impacto_na_media_geral
}).sort_values('Impacto (SHAP Value)', ascending=True).head(5)

print(diagnostico_df.to_string(index=False))
