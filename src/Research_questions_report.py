import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from datetime import datetime, timedelta

# 1. GENERATE SYNTHETIC DATASET (Simulating Artifact 2)
np.random.seed(42)
n_records = 350

platforms = ['TikTok', 'IG_Reels', 'YT_Shorts']
creators = ['Medical_MD', 'Allied_Health', 'Influencer', 'Brand_Commercial', 'Lay_User']
supplements = ['Magnesium', 'Ashwagandha', 'Black Cohosh', 'Maca Root', 'Probiotics', 'CBD Oil', 'Vitamin D3']
symptoms_pool = ['Hot_Flashes', 'Weight_Gain', 'Brain_Fog', 'Insomnia', 'Anxiety', 'Libido']
framings = ['Scientific_Data_Claim', 'Personal_Testimonial', 'Product_Review', 'Symptom_Fear_Mongering']

start_date = datetime(2024, 1, 1)
date_list = [start_date + timedelta(days=int(np.random.randint(0, 850))) for _ in range(n_records)]

data = {
    'video_id': [f"vid_{np.random.randint(100000, 999999)}" for _ in range(n_records)],
    'platform': np.random.choice(platforms, n_records, p=[0.5, 0.3, 0.2]),
    'upload_date': date_list,
    'creator_type': np.random.choice(creators, n_records, p=[0.15, 0.25, 0.35, 0.15, 0.10]),
    'view_count': np.random.negative_binomial(1, 0.00002, n_records), # Heavily right-skewed social metrics
    'likes': np.random.randint(100, 50000, n_records),
    'comments': np.random.randint(10, 2000, n_records),
    'shares': np.random.randint(5, 5000, n_records),
    'primary_intervention': np.random.choice(['Supplement', 'Dietary_Change', 'Lifestyle_Exercise'], n_records, p=[0.7, 0.15, 0.15]),
    'supplement_name': np.random.choice(supplements, n_records, p=[0.3, 0.2, 0.15, 0.1, 0.1, 0.1, 0.05]),
    'targeted_symptoms': [",".join(list(np.random.choice(symptoms_pool, np.random.randint(1, 4), replace=False))) for _ in range(n_records)],
    'advice_framing': np.random.choice(framings, n_records),
    'scientific_caution': np.random.choice([0, 1], n_records, p=[0.75, 0.25])
}

df_raw = pd.DataFrame(data)

# Inject synthetic duplicates to test the De-duplication Protocol
df_duplicates = df_raw.sample(n=30, random_state=42)
df_pipeline = pd.concat([df_raw, df_duplicates], ignore_index=True)

print(f"--- Pipeline Initialized: {df_pipeline.shape[0]} raw records ingested. ---")

# 2. DE-DUPLICATION & PROCESSING
df_clean = df_pipeline.drop_duplicates(subset=['video_id']).copy()
print(f"Post De-duplication: {df_clean.shape[0]} unique videos retained.")

# Calculate Engagement Score using standard metric weights
df_clean['engagement_score'] = df_clean['likes'] + df_clean['comments'] + df_clean['shares']
df_clean['year_quarter'] = df_clean['upload_date'].dt.to_period('Q')

# 3. ANALYSIS: RQ2 (Top 3 Supplements by Frequency and Reach)
top_supplements = df_clean['supplement_name'].value_counts()
top_3_names = top_supplements.head(3).index.tolist()
print("\n[RQ2] Top 3 Most Promoted Supplements:")
print(top_supplements.head(3))

# 4. ANALYSIS: RQ3 (Temporal Shifts 2024 - 2026)
temporal_mix = df_clean[df_clean['supplement_name'].isin(top_3_names)]
temporal_trend = temporal_mix.groupby(['year_quarter', 'supplement_name']).size().unstack(fill_value=0)

# 5. ANALYSIS: RQ5 (Symptom Co-occurrence Matrix)
# Explode the comma-separated symptoms column into a clean binary matrix
symptom_df = df_clean[['supplement_name', 'targeted_symptoms']].copy()
symptom_df = symptom_df.assign(targeted_symptoms=symptom_df['targeted_symptoms'].str.split(',')).explode('targeted_symptoms')
matrix_data = pd.crosstab(symptom_df['supplement_name'], symptom_df['targeted_symptoms'])

print("\n[RQ5] Symptom Targeting Matrix (Top 3 Ingredients):")
print(matrix_data.loc[top_3_names])

# 6. VISUALIZATION EXPORT
plt.figure(figsize=(12, 5))
sns.lineplot(data=temporal_trend, markers=True, linewidth=2.5)
plt.title('Temporal Prominence Shifts of Top 3 Menopause Supplements (2024-2026)')
plt.ylabel('Video Count')
plt.xlabel('Year-Quarter')
plt.grid(True, linestyle='--', alpha=0.6)
plt.tight_layout()
plt.savefig('menopause_supplement_trends.png')
print("\n--- Pipeline Execution Complete. Trend analysis exported to 'menopause_supplement_trends.png' ---")