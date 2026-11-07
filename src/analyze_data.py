#!/usr/bin/env python3
"""
Data Analysis Script for the Timeout, Supplements and Distress Datasets

This script analyzes LLM processed data from the xlsx files, generating tables and plots
for sentiment over time, popularity trends, and other research questions.
"""

import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
from datetime import datetime
import re
from collections import Counter
import warnings

from clean_supplements import canonicalize, remove_duplicates, split_supplements

warnings.filterwarnings('ignore')

# Set plot style
sns.set_style("whitegrid")
plt.rcParams['figure.figsize'] = (12, 6)

# Paths
DATA_DIR = Path("data")
PLOTS_DIR = Path("plots")
PLOTS_DIR.mkdir(exist_ok=True)

README_PATH = Path("README.md")


def load_and_filter_data():
    """Load and filter the datasets based on menopause and timeout columns."""
    print("Loading datasets...")

    # Load supplements data
    supplements_df = pd.read_excel(DATA_DIR / "supplements_LLM_results.xlsx")
    print(f"Loaded supplements dataset: {len(supplements_df)} rows")

    # Load timeout data
    timeout_df = pd.read_excel(DATA_DIR / "timeout_LLM_results.xlsx")
    print(f"Loaded timeout dataset: {len(timeout_df)} rows")

    # Filter to specific platforms (YouTube, TikTok, Facebook, Instagram)
    allowed_platforms = ['youtube', 'tiktok', 'facebook', 'instagram']

    # Normalize extractor to lowercase before filtering
    supplements_df['extractor'] = supplements_df['extractor'].str.lower()
    supplements_df = supplements_df[
        supplements_df['extractor'].isin(allowed_platforms)
    ].copy()
    print(f"Filtered supplements to allowed platforms: {len(supplements_df)} rows")

    # Normalize extractor to lowercase before filtering
    timeout_df['extractor'] = timeout_df['extractor'].str.lower()
    timeout_df = timeout_df[
        timeout_df['extractor'].isin(allowed_platforms)
    ].copy()
    print(f"Filtered timeout to allowed platforms: {len(timeout_df)} rows")

    # Filter datasets by menopause/timeout columns
    supplements_filtered = supplements_df[supplements_df['menopause'] == True].copy()
    print(f"Filtered supplements (menopause=True): {len(supplements_filtered)} rows")

    # Remove duplicates (same video posted across multiple platforms).
    # Conservative heuristic: same normalized title and same duration; the
    # copy with the highest view count is kept.
    supplements_filtered = remove_duplicates(supplements_filtered)
    print(f"After duplicate removal: {len(supplements_filtered)} rows")

    timeout_filtered = timeout_df[timeout_df['timeout'] == True].copy()
    print(f"Filtered timeout (timeout=True): {len(timeout_filtered)} rows")

    # Load distress data: videos the LLM judged to be about psychological distress
    distress_df = pd.read_excel(DATA_DIR / "distress_LLM_results.xlsx")
    print(f"Loaded distress dataset: {len(distress_df)} rows")
    distress_df['extractor'] = distress_df['extractor'].str.lower()
    distress_df = distress_df[distress_df['extractor'].isin(allowed_platforms)].copy()
    distress_filtered = distress_df[answer(distress_df['distress']) == 'true'].copy()
    print(f"Filtered distress (distress=True): {len(distress_filtered)} rows")
    distress_filtered = remove_duplicates(distress_filtered)
    print(f"After duplicate removal: {len(distress_filtered)} rows")

    return supplements_filtered, timeout_filtered, distress_filtered


def parse_upload_date(df):
    """Parse upload_date column to datetime."""
    # upload_date is in YYYYMMDD format
    df['upload_datetime'] = pd.to_datetime(df['upload_date'], format='%Y%m%d', errors='coerce')
    df['year'] = df['upload_datetime'].dt.year
    df['month'] = df['upload_datetime'].dt.to_period('M')
    df['year_month'] = df['upload_datetime'].dt.strftime('%Y-%m')
    return df


def analyze_supplements(df):
    """Analyze supplements dataset and answer research questions."""
    print("\n" + "="*80)
    print("SUPPLEMENTS DATASET ANALYSIS")
    print("="*80)

    df = parse_upload_date(df)

    analysis_results = {
        'tables': {},
        'plots': [],
        'summary': []
    }

    # 1. Quantitative descriptive analyses of form and content
    print("\n1. Descriptive Analysis of Form and Content")
    form_analysis = df.groupby('extractor').agg({
        'id': 'count',
        'like_count': 'sum',
        'view_count': 'sum',
        'comment_count': 'sum'
    }).rename(columns={'id': 'count'})
    form_analysis = form_analysis.sort_values('count', ascending=False)
    print(form_analysis)
    analysis_results['tables']['form_analysis'] = form_analysis
    analysis_results['summary'].append(f"**Video Distribution by Platform:**\n{form_analysis.to_markdown()}")

    # 1.5. Division 1: content type (informative / marketing / other)
    if 'content_type' in df.columns:
        print("\n1.5. Division 1: Content Type")
        ct = (df['content_type'].astype(str).str.strip().str.lower()
              .value_counts().rename_axis('Content type').reset_index(name='Post Count'))
        print(f"Total posts after filtering: {len(df)}")
        print(ct.to_string(index=False))
        analysis_results['tables']['content_type_counts'] = ct
        analysis_results['summary'].append(
            f"\n**Division 1 — Content Type ({len(df)} posts total):**\n{ct.to_markdown(index=False)}")

    # 2. Sentiment trends over time
    print("\n2. Sentiment Trends Over Time")
    sentiment_order = ['negative', 'neutral', 'positive']
    sentiment_labels = {
        'negative': 'Negative',
        'neutral': 'Neutral',
        'positive': 'Positive'
    }
    sentiment_colors = {
        'negative': '#d62728',
        'neutral': '#7f7f7f',
        'positive': '#2ca02c'
    }
    sentiment_over_time = (
        df.groupby(['year_month', 'sentiment'])
        .size()
        .unstack(fill_value=0)
        .rename(columns=lambda col: str(col).strip().lower())
        .reindex(columns=sentiment_order, fill_value=0)
    )
    print(sentiment_over_time)

    # Plot sentiment over time
    fig, ax = plt.subplots(figsize=(14, 6))
    sentiment_over_time.plot(
        kind='bar',
        stacked=True,
        ax=ax,
        color=[sentiment_colors[col] for col in sentiment_over_time.columns]
    )
    ax.set_title('Sentiment Trends Over Time - Supplements Dataset', fontsize=16, fontweight='bold')
    ax.set_xlabel('Month', fontsize=12)
    ax.set_ylabel('Number of Videos', fontsize=12)
    ax.legend(title='Sentiment', labels=[sentiment_labels[col] for col in sentiment_over_time.columns])
    plt.xticks(rotation=45, ha='right')
    plt.tight_layout()
    plot_path = PLOTS_DIR / 'supplements_sentiment_over_time.png'
    plt.savefig(plot_path, dpi=300, bbox_inches='tight')
    plt.close()
    analysis_results['plots'].append(('supplements_sentiment_over_time.png', 'Sentiment trends over time'))
    print(f"Saved plot: {plot_path}")

    # 2.5. Normalized sentiment over time
    fig, ax = plt.subplots(figsize=(14, 6))
    sentiment_over_time_normalized = sentiment_over_time.div(sentiment_over_time.sum(axis=1), axis=0)
    sentiment_over_time_normalized.plot(
        kind='bar',
        stacked=True,
        ax=ax,
        color=[sentiment_colors[col] for col in sentiment_over_time_normalized.columns]
    )
    ax.set_title('Sentiment Trends Over Time - Supplements Dataset', fontsize=16, fontweight='bold')
    ax.set_xlabel('Month', fontsize=12)
    ax.set_ylabel('Proportion of Videos', fontsize=12)
    ax.legend(title='Sentiment', labels=[sentiment_labels[col] for col in sentiment_over_time_normalized.columns])
    plt.xticks(rotation=45, ha='right')
    plt.tight_layout()
    plot_path = PLOTS_DIR / 'supplements_relative_sentiment_over_time.png'
    plt.savefig(plot_path, dpi=300, bbox_inches='tight')
    plt.close()
    analysis_results['plots'].append(('supplements_relative_sentiment_over_time.png', 'Relative sentiment trends over time'))
    print(f"Saved plot: {plot_path}")

    # 3. Popularity of topic over time (number of posts and likes)
    print("\n3. Popularity Over Time")
    popularity = df.groupby('year_month').agg({
        'id': 'count',
        'like_count': 'sum',
        'view_count': 'sum'
    }).rename(columns={'id': 'video_count'})

    fig, axes = plt.subplots(3, 1, figsize=(14, 10))

    # Videos over time
    axes[0].plot(range(len(popularity)), popularity['video_count'].values, marker='o', linewidth=2)
    axes[0].set_title('Number of Videos Over Time', fontsize=14, fontweight='bold')
    axes[0].set_ylabel('Video Count', fontsize=12)
    axes[0].grid(True, alpha=0.3)
    axes[0].set_xticks(range(len(popularity)))
    axes[0].set_xticklabels(popularity.index, rotation=45, ha='right')

    # Likes over time
    axes[1].plot(range(len(popularity)), popularity['like_count'].values, marker='o', linewidth=2, color='#ff7f0e')
    axes[1].set_title('Total Likes Over Time', fontsize=14, fontweight='bold')
    axes[1].set_ylabel('Total Likes', fontsize=12)
    axes[1].grid(True, alpha=0.3)
    axes[1].set_xticks(range(len(popularity)))
    axes[1].set_xticklabels(popularity.index, rotation=45, ha='right')

    # Views over time
    axes[2].plot(range(len(popularity)), popularity['view_count'].values, marker='o', linewidth=2, color='#2ca02c')
    axes[2].set_title('Total Views Over Time', fontsize=14, fontweight='bold')
    axes[2].set_ylabel('Total Views', fontsize=12)
    axes[2].set_xlabel('Month', fontsize=12)
    axes[2].grid(True, alpha=0.3)
    axes[2].set_xticks(range(len(popularity)))
    axes[2].set_xticklabels(popularity.index, rotation=45, ha='right')

    plt.tight_layout()
    plot_path = PLOTS_DIR / 'supplements_popularity_over_time.png'
    plt.savefig(plot_path, dpi=300, bbox_inches='tight')
    plt.close()
    analysis_results['plots'].append(('supplements_popularity_over_time.png', 'Popularity metrics over time'))
    print(f"Saved plot: {plot_path}")

    # 4. What supplements are promoted (top products)
    print("\n4. Supplements Promoted")
    all_supplements = []
    sentinel_values = {'none', 'no supplements mentioned', 'yes', 'n/a', 'na', ''}
    for supp_list in df['supplements'].dropna():
        for supplement in split_supplements(supp_list):
            # Collapse spelling/formulation/synonym variants to their
            # canonical grouping (see clean_supplements.py)
            all_supplements.append(canonicalize(supplement.lower()))

    supplement_counts = Counter(all_supplements)
    top_supplements = supplement_counts.most_common(10)
    print("\nTop 10 Supplements Mentioned:")
    for i, (supp, count) in enumerate(top_supplements, 1):
        print(f"{i}. {supp}: {count} videos")

    # Create table
    top_supp_df = pd.DataFrame(top_supplements, columns=['Supplement', 'Video Count'])
    analysis_results['tables']['top_supplements'] = top_supp_df
    analysis_results['summary'].append(f"\n**Top 10 Supplements Promoted:**\n{top_supp_df.to_markdown(index=False)}")

    # Plot top supplements
    fig, ax = plt.subplots(figsize=(12, 8))
    supp_names = [s[0] for s in top_supplements]
    supp_counts = [s[1] for s in top_supplements]
    ax.barh(supp_names, supp_counts, color='skyblue')
    ax.set_xlabel('Number of Videos', fontsize=12)
    ax.set_title('Top 10 Supplements Promoted for Menopause', fontsize=16, fontweight='bold')
    ax.invert_yaxis()
    plt.tight_layout()
    plot_path = PLOTS_DIR / 'supplements_top_products.png'
    plt.savefig(plot_path, dpi=300, bbox_inches='tight')
    plt.close()
    analysis_results['plots'].append(('supplements_top_products.png', 'Top 10 supplements promoted'))
    print(f"Saved plot: {plot_path}")

    # 5. Supplements promoted over time (changes in popularity)
    print("\n5. Supplements Promoted Over Time")
    if len(top_supplements) >= 3:
        top_3_names = [s[0] for s in top_supplements[:3]]

        # Track top 3 over time
        supplement_time_data = {name: [] for name in top_3_names}
        time_periods = sorted(df['year_month'].dropna().unique())

        for period in time_periods:
            period_df = df[df['year_month'] == period]
            period_supplements = []
            for supp_list in period_df['supplements'].dropna():
                if isinstance(supp_list, str):
                    items = split_supplements(supp_list)
                    # Filter out sentinel values and canonicalize, matching the top-10 counting
                    period_supplements.extend([
                        canonicalize(s) for s in items if s and s.lower() not in sentinel_values
                    ])

            period_counts = Counter(period_supplements)
            for name in top_3_names:
                supplement_time_data[name].append(period_counts.get(name, 0))

        # Plot
        fig, ax = plt.subplots(figsize=(14, 6))
        for name in top_3_names:
            ax.plot(range(len(time_periods)), supplement_time_data[name], marker='o', linewidth=2, label=name)

        ax.set_title('Top 3 Supplements Mentioned Over Time', fontsize=16, fontweight='bold')
        ax.set_xlabel('Month', fontsize=12)
        ax.set_ylabel('Number of Mentions', fontsize=12)
        ax.legend()
        ax.grid(True, alpha=0.3)
        ax.set_xticks(range(len(time_periods)))
        ax.set_xticklabels(time_periods, rotation=45, ha='right')
        plt.tight_layout()
        plot_path = PLOTS_DIR / 'supplements_top3_over_time.png'
        plt.savefig(plot_path, dpi=300, bbox_inches='tight')
        plt.close()
        analysis_results['plots'].append(('supplements_top3_over_time.png', 'Top 3 supplements trends over time'))
        print(f"Saved plot: {plot_path}")

    # 6. What advice/content about top 3 supplements
    print("\n6. Content Analysis for Top 3 Supplements")
    if len(top_supplements) >= 3:
        top_3_names = [s[0] for s in top_supplements[:3]]

        for supp_name in top_3_names:
            # Find videos mentioning this supplement
            mask = df['supplements'].apply(lambda x: supp_name in str(x) if pd.notna(x) else False)
            supp_videos = df[mask]

            print(f"\n{supp_name}: {len(supp_videos)} videos")
            print(f"  Average sentiment: {supp_videos['sentiment'].value_counts().to_dict()}")
            print(f"  Common symptoms targeted: {supp_videos['symptoms'].value_counts().head(3).to_dict() if 'symptoms' in supp_videos else 'N/A'}")

    # 7. What symptoms are targeted
    print("\n7. Symptoms Targeted by Supplements")
    all_symptoms = []
    for symptoms in df['symptoms'].dropna():
        if isinstance(symptoms, str) and symptoms.lower() != 'none':
            items = [s.strip().strip("'\"") for s in symptoms.strip('[]').split(',')]
            # Lowercase symptoms for consistent counting
            for symptom in items:
                symptom = symptom.lower()
                if symptom in ['none', 'n/a', 'no symptoms mentioned', 'menopause', 'perimenopause']:
                    continue
                if symptom in ["mood swings", "mood changes", "anxiety", "stress", "depression", "irritability"]:
                    symptom = "mood changes"
                all_symptoms.append(symptom.title())

    symptom_counts = Counter(all_symptoms)
    top_symptoms = symptom_counts.most_common(10)
    print("\nTop 10 Symptoms Targeted:")
    for i, (symptom, count) in enumerate(top_symptoms, 1):
        print(f"{i}. {symptom}: {count} mentions")

    top_symptoms_df = pd.DataFrame(top_symptoms, columns=['Symptom', 'Mention Count'])
    analysis_results['tables']['top_symptoms'] = top_symptoms_df
    analysis_results['summary'].append(f"\n**Top 10 Symptoms Targeted:**\n{top_symptoms_df.to_markdown(index=False)}")

    # Plot symptoms
    fig, ax = plt.subplots(figsize=(12, 8))
    symptom_names = [s[0] for s in top_symptoms]
    symptom_counts = [s[1] for s in top_symptoms]
    ax.barh(symptom_names, symptom_counts, color='lightcoral')
    ax.set_xlabel('Number of Mentions', fontsize=12)
    ax.set_title('Top 10 Menopause Symptoms Targeted by Supplements', fontsize=16, fontweight='bold')
    ax.invert_yaxis()
    plt.tight_layout()
    plot_path = PLOTS_DIR / 'supplements_top_symptoms.png'
    plt.savefig(plot_path, dpi=300, bbox_inches='tight')
    plt.close()
    analysis_results['plots'].append(('supplements_top_symptoms.png', 'Top 10 symptoms targeted'))
    print(f"Saved plot: {plot_path}")

    return analysis_results


def analyze_timeout(df):
    """Analyze timeout dataset."""
    print("\n" + "="*80)
    print("TIMEOUT DATASET ANALYSIS")
    print("="*80)

    df = parse_upload_date(df)

    analysis_results = {
        'tables': {},
        'plots': [],
        'summary': []
    }

    # Descriptive analysis
    print("\n1. Descriptive Analysis")
    form_analysis = df.groupby('extractor').agg({
        'id': 'count',
        'like_count': 'sum',
        'view_count': 'sum',
        'comment_count': 'sum'
    }).rename(columns={'id': 'count'})
    form_analysis = form_analysis.sort_values('count', ascending=False)
    print(form_analysis)
    analysis_results['tables']['form_analysis'] = form_analysis
    analysis_results['summary'].append(f"**Video Distribution by Platform:**\n{form_analysis.to_markdown()}")

    # Sentiment over time
    print("\n2. Sentiment Trends Over Time")
    sentiment_order = ['negative', 'neutral', 'positive']
    sentiment_labels = {
        'negative': 'Negative',
        'neutral': 'Neutral',
        'positive': 'Positive'
    }
    sentiment_colors = {
        'negative': '#d62728',
        'neutral': '#7f7f7f',
        'positive': '#2ca02c'
    }
    sentiment_over_time = (
        df.groupby(['year_month', 'sentiment'])
        .size()
        .unstack(fill_value=0)
        .rename(columns=lambda col: str(col).strip().lower())
        .reindex(columns=sentiment_order, fill_value=0)
    )

    fig, ax = plt.subplots(figsize=(14, 6))
    sentiment_over_time.plot(
        kind='bar',
        stacked=True,
        ax=ax,
        color=[sentiment_colors[col] for col in sentiment_over_time.columns]
    )
    ax.set_title('Sentiment Trends Over Time - Timeout Dataset', fontsize=16, fontweight='bold')
    ax.set_xlabel('Month', fontsize=12)
    ax.set_ylabel('Number of Videos', fontsize=12)
    ax.legend(title='Sentiment', labels=[sentiment_labels[col] for col in sentiment_over_time.columns])
    plt.xticks(rotation=45, ha='right')
    plt.tight_layout()
    plot_path = PLOTS_DIR / 'timeout_sentiment_over_time.png'
    plt.savefig(plot_path, dpi=300, bbox_inches='tight')
    plt.close()
    analysis_results['plots'].append(('timeout_sentiment_over_time.png', 'Sentiment trends over time'))
    print(f"Saved plot: {plot_path}")

    # Number of videos over time
    print("\n3. Number of Videos Over Time")
    videos_over_time = df.groupby('year_month').size()

    fig, ax = plt.subplots(figsize=(14, 6))
    ax.plot(range(len(videos_over_time)), videos_over_time.values, marker='o', linewidth=2, color='#1f77b4')
    ax.set_title('Number of Timeout Videos Over Time', fontsize=16, fontweight='bold')
    ax.set_xlabel('Month', fontsize=12)
    ax.set_ylabel('Number of Videos', fontsize=12)
    ax.grid(True, alpha=0.3)
    ax.set_xticks(range(len(videos_over_time)))
    ax.set_xticklabels(videos_over_time.index, rotation=45, ha='right')
    plt.tight_layout()
    plot_path = PLOTS_DIR / 'timeout_videos_over_time.png'
    plt.savefig(plot_path, dpi=300, bbox_inches='tight')
    plt.close()
    analysis_results['plots'].append(('timeout_videos_over_time.png', 'Number of videos over time'))
    print(f"Saved plot: {plot_path}")

    # Sentiment distribution
    sentiment_dist = df['sentiment'].value_counts()
    print("\nSentiment Distribution:")
    print(sentiment_dist)
    analysis_results['summary'].append(f"\n**Sentiment Distribution:**\n{sentiment_dist.to_markdown()}")

    return analysis_results


# Answer options from the distress prompt (batch_LLM.py), for fields that allow several. Some options contain
# commas, e.g. "clinical or diagnostic terms (e.g. depression, panic disorder)", so answers are counted by
# matching these labels rather than splitting on commas
DISTRESS_CATEGORIES = ["stress or pressure", "anxiety or panic", "low mood or depression", "burnout or exhaustion",
                       "overwhelm", "loneliness or isolation", "anger or irritability", "grief or loss", "trauma",
                       "self-harm", "suicidal thoughts"]
VOCABULARY_REGISTERS = ["clinical or diagnostic terms", "everyday emotional language", "slang or internet language",
                        "euphemism or algospeak", "metaphor or imagery", "te reo māori or other cultural concepts"]
SUPPORT_SOURCES = ["friends or peers", "whānau or family", "school or university", "gp or doctor",
                   "counsellor or therapist", "helpline or text service", "online community",
                   "cultural or spiritual support", "medication"]
FRAMINGS = ["individual struggle", "normal part of life", "medical condition needing treatment",
            "caused by external pressures", "relational or whānau context", "holistic or cultural wellbeing",
            "stigma or shame", "recovery or hope"]


def answer(series):
    """Normalise a single-choice LLM answer for counting."""
    return series.astype(str).str.strip().str.lower()


def count_labels(series, labels):
    """Number (and share) of videos whose answer includes each label."""
    text = answer(series)
    display = [label.replace('gp ', 'GP ').replace('māori', 'Māori') for label in labels]
    display = [label[0].upper() + label[1:] for label in display]
    counts = pd.DataFrame({'videos': [int(text.str.contains(label, regex=False).sum()) for label in labels]},
                          index=display)
    counts['share'] = (counts['videos'] / len(series) * 100).round(1).astype(str) + '%'
    return counts.sort_values('videos', ascending=False)


NON_ANSWERS = {'no', 'none', 'n/a', 'na', 'not applicable', 'nan'}


def count_terms(series, none_prefix, sep):
    """Most common free-text terms in a list field (e.g. algospeak quotes), ignoring "none" answers.
    Returns the top 10 and the number of videos with at least one term."""
    terms, videos = Counter(), 0
    for value in series.dropna().astype(str):
        if value.strip().lower().startswith(none_prefix):
            continue
        found = {t.strip(" '\"[]").lower() for t in value.split(sep)} - NON_ANSWERS - {''}
        terms.update(found)
        videos += bool(found)
    return pd.DataFrame(terms.most_common(10), columns=['term', 'videos']), videos


def barh_plot(counts, title, filename, color):
    """Horizontal bar chart of a count_labels table."""
    fig, ax = plt.subplots(figsize=(12, 6))
    counts['videos'].iloc[::-1].plot(kind='barh', ax=ax, color=color)
    ax.set_title(title, fontsize=16, fontweight='bold')
    ax.set_xlabel('Number of Videos', fontsize=12)
    plt.tight_layout()
    plot_path = PLOTS_DIR / filename
    plt.savefig(plot_path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"Saved plot: {plot_path}")


def analyze_distress(df):
    """Analyze the youth psychological distress (NZ) dataset."""
    print("\n" + "="*80)
    print("DISTRESS DATASET ANALYSIS")
    print("="*80)

    df = parse_upload_date(df)

    analysis_results = {
        'tables': {},
        'plots': [],
        'summary': []
    }

    # Descriptive analysis
    print("\n1. Descriptive Analysis")
    form_analysis = df.groupby('extractor').agg({
        'id': 'count',
        'like_count': 'sum',
        'view_count': 'sum',
        'comment_count': 'sum'
    }).rename(columns={'id': 'count'})
    form_analysis = form_analysis.sort_values('count', ascending=False)
    print(form_analysis)
    analysis_results['summary'].append(f"**Video Distribution by Platform:**\n{form_analysis.to_markdown()}")

    # Who is speaking, and to whom
    print("\n2. Speakers")
    young = answer(df['young_person']).value_counts()
    nz = (answer(df['new_zealand']) == 'true').sum()
    analysis_results['summary'].append(
        f"\n**Speakers:** the main speaker appears to be a young person (about 12–24) in {young.get('yes', 0)} videos "
        f"({young.get('yes', 0) / len(df):.0%}), is unclear in {young.get('unclear', 0)}, and {nz} videos ({nz / len(df):.0%}) "
        f"show a New Zealand connection.")
    source = answer(df['messaging_source']).value_counts().head(8).rename('videos')
    print(source)
    analysis_results['summary'].append(f"\n**Who Is Communicating:**\n{source.to_frame().to_markdown()}")

    # How distress is described
    print("\n3. Distress Experiences and Language")
    categories = count_labels(df['distress_categories'], DISTRESS_CATEGORIES)
    print(categories)
    analysis_results['summary'].append(f"\n**Distress Experiences Described:**\n{categories.to_markdown()}")
    barh_plot(categories, 'Distress Experiences Described - Distress Dataset', 'distress_categories.png', '#9467bd')
    analysis_results['plots'].append(('distress_categories.png', 'Distress experiences described'))

    registers = count_labels(df['vocabulary_register'], VOCABULARY_REGISTERS)
    print(registers)
    analysis_results['summary'].append(f"\n**Vocabulary Used for Distress:**\n{registers.to_markdown()}")
    barh_plot(registers, 'Vocabulary Used for Distress - Distress Dataset', 'distress_vocabulary_register.png', '#1f77b4')
    analysis_results['plots'].append(('distress_vocabulary_register.png', 'Vocabulary used for distress'))

    algospeak, n_algospeak = count_terms(df['algospeak'], 'no algospeak', ';')
    analysis_results['summary'].append(
        f"\n**Top 10 Algospeak and Euphemisms** (in {n_algospeak} videos; as quoted by the LLM, which sometimes includes "
        f"plain words or helpline numbers):\n{algospeak.to_markdown(index=False)}")
    te_reo, n_te_reo = count_terms(df['te_reo_maori'], 'no te reo', ',')
    analysis_results['summary'].append(
        f"\n**Top 10 Te Reo Māori Words** (in {n_te_reo} videos):\n{te_reo.to_markdown(index=False)}")

    framing = count_labels(df['framing'], FRAMINGS)
    analysis_results['summary'].append(f"\n**Framing of Distress:**\n{framing.to_markdown()}")

    # Help-seeking and public health messaging
    print("\n4. Help-seeking and Messaging")
    help_seeking = answer(df['help_seeking']).value_counts().rename('videos')
    analysis_results['summary'].append(f"\n**Help-seeking:**\n{help_seeking.to_frame().to_markdown()}")
    support = count_labels(df['support_sources'], SUPPORT_SOURCES)
    analysis_results['summary'].append(f"\n**Sources of Support Mentioned:**\n{support.to_markdown()}")
    suicide = df[answer(df['distress_categories']).str.contains('suicidal thoughts|self-harm')]
    safe = answer(suicide['safe_messaging']).value_counts().rename('videos')
    analysis_results['summary'].append(
        f"\n**Safe Messaging** (the {len(suicide)} videos discussing suicide or self-harm):\n{safe.to_frame().to_markdown()}")
    risk = answer(df['risk_disclosure']).value_counts().rename('videos')
    analysis_results['summary'].append(f"\n**Self-disclosed Risk:**\n{risk.to_frame().to_markdown()}")

    source_counts = source.to_frame()
    barh_plot(source_counts, 'Who Is Communicating - Distress Dataset', 'distress_messaging_source.png', '#ff7f0e')
    analysis_results['plots'].append(('distress_messaging_source.png', 'Who is communicating'))

    # Number of videos over time
    print("\n5. Number of Videos Over Time")
    videos_over_time = df.groupby('year_month').size()
    fig, ax = plt.subplots(figsize=(14, 6))
    ax.plot(range(len(videos_over_time)), videos_over_time.values, marker='o', linewidth=2, color='#1f77b4')
    ax.set_title('Number of Distress Videos Over Time', fontsize=16, fontweight='bold')
    ax.set_xlabel('Month', fontsize=12)
    ax.set_ylabel('Number of Videos', fontsize=12)
    ax.grid(True, alpha=0.3)
    ax.set_xticks(range(len(videos_over_time)))
    ax.set_xticklabels(videos_over_time.index, rotation=45, ha='right')
    # label every few months so long ranges stay readable
    for i, label in enumerate(ax.get_xticklabels()):
        label.set_visible(i % max(1, len(videos_over_time) // 24) == 0)
    plt.tight_layout()
    plot_path = PLOTS_DIR / 'distress_videos_over_time.png'
    plt.savefig(plot_path, dpi=300, bbox_inches='tight')
    plt.close()
    analysis_results['plots'].append(('distress_videos_over_time.png', 'Number of videos over time'))
    print(f"Saved plot: {plot_path}")

    return analysis_results


def update_readme(supplements_results, timeout_results, distress_results, supplements_count, timeout_count, distress_count):
    """Update README.md with analysis findings."""
    print("\nUpdating README...")

    # Read current README
    with open(README_PATH, 'r') as f:
        readme_content = f.read()

    # Create analysis section
    timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')

    analysis_section = f"""
## Data Analysis

*Last updated: {timestamp}*

This section contains automated analysis of the LLM-processed video data. The analysis is automatically updated when the Excel files are modified.

> **Note on Dataset Sizes:** The numbers in this Data Analysis section are smaller than those reported in the Dataset Statistics section above. This is expected and occurs for several reasons:
> - **Download failures**: Not all videos can be successfully downloaded with yt-dlp (some may be deleted, geo-restricted, or platform-restricted)
> - **LLM processing**: Not all downloaded videos are successfully processed by the LLM
> - **Content filtering**: Not all scraped videos are actually about the topic of interest—sometimes search terms return unrelated videos, which are identified and filtered out by the LLM (e.g., videos where `menopause=False`, `timeout=False` or `distress=False`)

### Supplements Dataset Analysis (Menopause-Related Content)

The supplements dataset was filtered to include only videos where `menopause=True` from YouTube, TikTok, Facebook, and Instagram (n={supplements_count} videos).

#### Key Findings

"""

    # Add supplements summary
    for item in supplements_results['summary']:
        analysis_section += item + "\n\n"

    # Add plots
    analysis_section += "#### Visualizations\n\n"
    for plot_file, description in supplements_results['plots']:
        analysis_section += f"**{description}**\n\n"
        analysis_section += f"![{description}](plots/{plot_file})\n\n"

    # Add timeout analysis
    analysis_section += f"""
### Timeout Dataset Analysis

The timeout dataset was filtered to include only videos where `timeout=True` from YouTube, TikTok, Facebook, and Instagram (n={timeout_count} videos).

#### Key Findings

"""

    # Add timeout summary
    for item in timeout_results['summary']:
        analysis_section += item + "\n\n"

    # Add plots
    analysis_section += "#### Visualizations\n\n"
    for plot_file, description in timeout_results['plots']:
        analysis_section += f"**{description}**\n\n"
        analysis_section += f"![{description}](plots/{plot_file})\n\n"

    # Add distress analysis
    analysis_section += f"""
### Distress Dataset Analysis (Youth Psychological Distress, New Zealand)

The distress dataset was filtered to include only videos where `distress=True` from YouTube, TikTok, Facebook, and Instagram, with cross-platform duplicates removed (n={distress_count} videos). Its coding scheme is a first draft (see `get_prompt_distress` in `src/batch_LLM.py`), so these figures are indicative until the coding is validated. Search results favour recent videos, so counts over time reflect when the data was collected more than how posting has changed.

#### Key Findings

"""

    for item in distress_results['summary']:
        analysis_section += item + "\n\n"

    analysis_section += "#### Visualizations\n\n"
    for plot_file, description in distress_results['plots']:
        analysis_section += f"**{description}**\n\n"
        analysis_section += f"![{description}](plots/{plot_file})\n\n"

    # Find where to insert the analysis section
    # Look for existing "## Data Analysis" section or insert before "## License"
    if "## Data Analysis" in readme_content:
        # Replace existing analysis section (everything from "## Data Analysis" to the next "## " or end of file)
        pattern = r'\n## Data Analysis.*?(?=\n## |\Z)'
        readme_content = re.sub(pattern, '\n' + analysis_section.strip(), readme_content, flags=re.DOTALL)
    elif "## License" in readme_content:
        # Insert before License section
        readme_content = readme_content.replace("\n## License", "\n" + analysis_section + "\n## License")
    else:
        # Append at the end
        readme_content += "\n" + analysis_section

    # Write updated README
    with open(README_PATH, 'w') as f:
        f.write(readme_content)

    print(f"README updated successfully!")


def main():
    """Main analysis function."""
    print("Starting data analysis...")
    print(f"Working directory: {Path.cwd()}")

    # Load and filter data
    supplements_df, timeout_df, distress_df = load_and_filter_data()

    # Analyze supplements dataset
    supplements_results = analyze_supplements(supplements_df)

    # Analyze timeout dataset
    timeout_results = analyze_timeout(timeout_df)

    # Analyze distress dataset
    distress_results = analyze_distress(distress_df)

    # Update README with counts
    update_readme(supplements_results, timeout_results, distress_results,
                  len(supplements_df), len(timeout_df), len(distress_df))

    print("\n" + "="*80)
    print("Analysis completed successfully!")
    print("="*80)
    print(f"Plots saved to: {PLOTS_DIR}/")
    print(f"README updated: {README_PATH}")


if __name__ == "__main__":
    main()
