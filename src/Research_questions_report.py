import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime, timezone
import re
import os
import argparse
from pathlib import Path

def generate_report(data_path, output_txt="report.txt", output_plot="supplements_top3_over_time.png"):
    print(f"Loading data from {data_path}...")
    
    # 1. Read File 
    try:
        if data_path.endswith('.xlsx'):
            df_raw = pd.read_excel(data_path)
        else:
            df_raw = pd.read_csv(data_path)
    except FileNotFoundError:
        print(f"Error: File '{data_path}' not found.")
        return

    total_loaded = len(df_raw)
    
    # 2. PRISMA-SM Filtering
    if 'menopause' in df_raw.columns:
        df = df_raw[df_raw['menopause'].astype(str).str.lower() == 'true'].copy()
    else:
        df = df_raw.copy()
        print("Warning: 'menopause' column not found. Processing all rows.")
        
    included_count = len(df)
    
    # 3. Safe List Parser (Replaces ast.literal_eval to avoid SyntaxWarnings)
    def safe_parse_list(val):
        if pd.isna(val):
            return []
        val_str = str(val).strip()
        if val_str.lower() in ["no supplements mentioned", "none", "no supplements", "n/a", ""]:
            return []
        
        # Extract items safely using regex to find text inside quotes
        if val_str.startswith('[') and val_str.endswith(']'):
            items = re.findall(r"['\"](.*?)['\"]", val_str)
            if items:
                return [x.strip() for x in items if x.strip()]
            # Fallback if no quotes exist but it has brackets: [Magnesium, Calcium]
            content = val_str[1:-1].strip()
            if content:
                return [x.strip() for x in content.split(',') if x.strip()]
            return []
        
        # Fallback for plain comma-separated strings
        return [x.strip() for x in val_str.split(',') if x.strip()]

    # Normalize Title Casing to group identical supplements correctly
    def clean_and_title(val):
        val_str = str(val).strip()
        if val_str.lower() == 'omega-3': return 'Omega-3'
        if val_str.lower() in ['hrt', 'hormone replacement therapy']: return 'HRT'
        if val_str.lower() == 'vitamin d': return 'Vitamin D'
        if val_str.lower() == 'vitamin d3': return 'Vitamin D3'
        return val_str.title()

    # Parse and clean Supplements
    if 'supplements' in df.columns:
        df['supplements_list'] = df['supplements'].apply(safe_parse_list)
        df['supplements_list'] = df['supplements_list'].apply(lambda lst: [clean_and_title(x) for x in lst])
    else:
        df['supplements_list'] = [[] for _ in range(len(df))]
        
    # Parse and clean Symptoms
    if 'symptoms' in df.columns:
        df['symptoms_list'] = df['symptoms'].apply(safe_parse_list)
        df['symptoms_list'] = df['symptoms_list'].apply(lambda lst: [str(x).title() for x in lst])
    else:
        df['symptoms_list'] = [[] for _ in range(len(df))]

    # 4. Custom Date Parser (Handles the 20150127.0 float formats)
    def parse_custom_date(val):
        if pd.isna(val):
            return pd.NaT
        try:
            val_str = str(int(float(val))).strip()
            if len(val_str) == 8:
                return pd.to_datetime(val_str, format='%Y%m%d')
        except (ValueError, TypeError):
            pass
        return pd.to_datetime(val, errors='coerce')

    if 'upload_date' in df.columns:
        df['parsed_date'] = df['upload_date'].apply(parse_custom_date)
    else:
        df['parsed_date'] = pd.NaT

    # 5. Generate the Report Document
    with open(output_txt, 'w', encoding='utf-8') as f:
        current_time = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        f.write("# Menopause Supplements — Findings Report\n\n")
        f.write(f"*Generated: {current_time}*\n\n")
        
        f.write("## PRISMA-SM counts (this snapshot)\n")
        f.write("- Identified (scraped): not available locally\n")
        f.write(f"- Loaded rows: {total_loaded}\n")
        f.write(f"- After platform filter: {total_loaded}\n")
        f.write(f"- **Included (menopause==True): {included_count}**\n\n")

        f.write("## Findings\n\n")
        f.write("**Video distribution by platform** (engagement is platform-dependent; do not pool raw):\n\n")
        
        # Platform Distribution
        if 'extractor' in df.columns:
            platform_stats = df.groupby('extractor').agg(count=('extractor', 'count'))
            for col in ['like_count', 'view_count', 'comment_count']:
                if col in df.columns:
                    # Convert to numeric to avoid sum concatenation errors
                    df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
                    platform_stats[col] = df.groupby('extractor')[col].sum()
                else:
                    platform_stats[col] = 0
                    
            platform_stats = platform_stats.reset_index().sort_values(by='count', ascending=False)
            f.write(platform_stats.to_markdown(index=False))
        else:
            f.write("Platform data ('extractor' column) not found in dataset.\n")
        f.write("\n\n")

        # RQ2 — Top 10 Supplements
        f.write("**RQ2 — Top 10 supplements promoted** (top 3 in bold elsewhere):\n\n")
        
        supplements_exploded = df.explode('supplements_list')
        supplements_exploded = supplements_exploded[supplements_exploded['supplements_list'].astype(bool)]
        top_10_supplements = supplements_exploded['supplements_list'].value_counts().head(10).reset_index()
        top_10_supplements.columns = ['Supplement', 'Video Count']
        
        f.write(top_10_supplements.to_markdown(index=False))
        f.write("\n\n")

        top_3 = top_10_supplements['Supplement'].head(3).tolist()
        f.write(f"**RQ3 — Tracked top 3:** {', '.join(top_3)} (see {os.path.basename(output_plot)}; interpret with rolling-window/survivorship caveats).\n\n")

        # RQ3 — Plot Generation (Now using the safely parsed dates)
        if not supplements_exploded['parsed_date'].isna().all() and len(top_3) > 0:
            top3_data = supplements_exploded[supplements_exploded['supplements_list'].isin(top_3)].dropna(subset=['parsed_date'])
            
            if not top3_data.empty:
                # Group by Month End
                monthly_trends = top3_data.groupby([pd.Grouper(key='parsed_date', freq='ME'), 'supplements_list']).size().unstack(fill_value=0)
                
                plt.figure(figsize=(10, 6))
                monthly_trends.plot(ax=plt.gca(), linewidth=2)
                plt.title('Top 3 Menopause Supplements Promoted Over Time')
                plt.ylabel('Video Count')
                plt.xlabel('Date')
                plt.grid(True, linestyle='--', alpha=0.7)
                plt.legend(title='Supplement')
                plt.tight_layout()
                plt.savefig(output_plot)
                plt.close()
                print(f"Temporal plot successfully saved to {output_plot}")
            else:
                print("No valid dates align with the top 3 supplements. Plot not generated.")
        else:
            print("Date column missing/unparseable or no supplements found. Plot not generated.")

        # RQ4 — Dynamic Advice/Content Profile
        f.write("**RQ4 — Advice/content profile for top 3 supplements:**\n\n")
        for supp in top_3:
            supp_videos = df[df['supplements_list'].apply(lambda x: supp in x)]
            n = len(supp_videos)
            
            if n > 0:
                sentiment_counts = {}
                if 'sentiment' in supp_videos.columns:
                    sentiment_counts = supp_videos['sentiment'].value_counts().to_dict()
                
                marketing_pct = 0
                if 'marketing' in supp_videos.columns:
                    # Convert to boolean handling text representations
                    bool_series = supp_videos['marketing'].astype(str).str.lower().map({'true': True, 'false': False, '1': True, '0': False})
                    bool_series = bool_series.fillna(False).astype(bool)
                    marketing_pct = int(bool_series.mean() * 100)
                    
                median_misleading = 0.0
                if 'misleading' in supp_videos.columns:
                    supp_videos.loc[:, 'misleading'] = pd.to_numeric(supp_videos['misleading'], errors='coerce')
                    median_misleading = supp_videos['misleading'].median()
                
                f.write(f"- **{supp}** (n={n}): sentiment={sentiment_counts}; marketing-present={marketing_pct}%; median misleading={median_misleading:.1f}\n")
        f.write("\n")

        # RQ5 — Top 10 Symptoms
        f.write("**RQ5 — Top 10 symptoms targeted:**\n\n")
        symptoms_exploded = df.explode('symptoms_list')
        symptoms_exploded = symptoms_exploded[symptoms_exploded['symptoms_list'].astype(bool)]
        top_10_symptoms = symptoms_exploded['symptoms_list'].value_counts().head(10).reset_index()
        top_10_symptoms.columns = ['Symptom', 'Mention Count']
        
        f.write(top_10_symptoms.to_markdown(index=False))
        f.write("\n")

    print(f"Report successfully generated and saved to {output_txt}")

if __name__ == "__main__":
    SRC_DIR = Path(__file__).resolve().parent
    ROOT_DIR = SRC_DIR.parent
    
    parser = argparse.ArgumentParser(description="Generate Menopause Supplements Report")
    parser.add_argument("--data", type=str, default= str(ROOT_DIR) + "/data/supplements_LLM_results.xlsx", help="Path to input dataset (.csv or .xlsx)")
    parser.add_argument("--out_txt", type=str, default= str(ROOT_DIR) + "/report/report.txt", help="Path to output report text file")
    parser.add_argument("--out_plot", type=str, default= str(ROOT_DIR) + "/report/supplements_top3_over_time.png", help="Path to output temporal plot")

    args = parser.parse_args()
    generate_report(data_path=args.data, output_txt=args.out_txt, output_plot=args.out_plot)