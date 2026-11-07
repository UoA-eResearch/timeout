#!/usr/bin/env python3
"""
Cleaning and coding of the supplement terms and categories produced by the LLM.

Implements the coding framework from the research team's documents:
  - "Dividing data plan 18.8.26" (canonical grouping, 9 categories, target groups)
  - "data_cleaning_for_combining_supplement_categories_9_categories"
  - "supplement_coding_instructions_for_data_cleaning"
  - "marketing_target_grouping_instruction_table"
plus a separate foods category (2 Sep meeting).

Three coding layers:
  1. Canonical name  - collapse spelling/formulation/synonym variants before counting (rules, here)
  2. Status category - one of the broad product / clinical-regulatory categories, per supplement
  3. Target group    - the marketing/target-function the post frames its supplements for
Layers 2 and 3 are assigned by the LLM, which sees the whole video (see get_prompt_supplements in
batch_LLM.py, which defines the categories with examples); this script parses its answers. Answers
that are missing or not one of the categories are flagged "Unmatched (manual review)".

Run as a script to produce data/supplement_categories.xlsx from
data/supplements_LLM_results.xlsx:
  - counts and popularity metrics (likes, views) per category and target group
  - posts listed in rows grouped under each category / target group
  - the full raw term -> canonical -> category mapping for review
"""

import ast
import json
import re
from collections import Counter
from pathlib import Path

import pandas as pd

ALLOWED_PLATFORMS = ["youtube", "tiktok", "facebook", "instagram"]

# ---------------------------------------------------------------------------
# Layer 1: canonical ingredient grouping (Table 1 of coding instructions)
# ---------------------------------------------------------------------------
# regex pattern -> canonical name; checked in order, first match wins
CANONICAL_PATTERNS = [
    (r"vitamin\s*d3?\b|cholecalciferol|ergocalciferol|\bd3\b", "Vitamin D"),
    (r"magnesium", "Magnesium"),
    (r"omega[\s-]*3|fish oil|krill oil|cod liver oil", "Omega-3 / marine oils"),
    (r"\bb[\s-]*(vitamins?|complex)|vitamin b\s*\d*\b|\bb\s*(1|2|3|5|6|12)\b|folate|folic acid|biotin|riboflavin|niacin|pantothenic|methylcobalamin|thiamine", "B vitamins"),
    (r"black cohosh|racemosa", "Black cohosh"),
    (r"chasteberry|vitex|chaste tree", "Vitex / chasteberry"),
    (r"\bmaca\b", "Maca"),
    (r"collagen", "Collagen"),
    (r"probiotic|prebiotic|postbiotic|synbiotic|symbiotic", "Microbiome products"),
    (r"hrt\b|hormone replacement|menopaus\w* hormone therapy|\bmht\b", "Hormone replacement therapy"),
    (r"red clover", "Red clover"),
]


def canonicalize(term):
    """Collapse a raw supplement term to its canonical grouping.

    Returns the canonical name if a grouping rule matches, otherwise the
    title-cased raw term (a term without variants is its own canonical name).
    """
    t = term.strip().lower()
    for pattern, canonical in CANONICAL_PATTERNS:
        if re.search(pattern, t):
            return canonical
    return term.strip().title()


# ---------------------------------------------------------------------------
# Layers 2 and 3: status categories and target groups, as assigned by the LLM
# ---------------------------------------------------------------------------
# The names the LLM chooses from; keep in step with get_prompt_supplements in batch_LLM.py
STATUS_CATEGORIES = [
    "Hormone therapies",
    "Prescription and over-the-counter medications",
    "Vitamins and minerals",
    "Herbals, botanicals and phytoestrogenic products",
    "Fatty acids and oils",
    "Protein, amino acids, creatine, body-composition and sports/performance supplements",
    "Gut/microbiome products, including probiotics, prebiotics, postbiotics, symbiotics and fibre",
    "Branded menopause or symptom-targeted formulations",
    "Foods and dietary items",
    "Other, vague, ambiguous or non-classifiable terms",
]
VAGUE = "Other, vague, ambiguous or non-classifiable terms"

GENERAL_TARGET = "General menopause / multisymptom / unclear target"
TARGET_GROUPS = [
    "Bone / musculoskeletal support",
    "Phytoestrogenic or hormone-modulating claims",
    "Vasomotor symptom / hot-flush relief",
    "Sleep / stress / mood / cognition support",
    "Metabolic / weight / insulin framing",
    "Gut / inflammation / detox framing",
    "Skin / hair / beauty ageing",
    "Sexual / vaginal symptoms",
    GENERAL_TARGET,
]

UNMATCHED = "Unmatched (manual review)"


def match_name(value, names):
    """Match one LLM answer to one of `names`, tolerating case, quotes and shortened names
    (e.g. "Gut/microbiome products" for the full gut category name). None if it matches none."""
    v = str(value).strip().strip(".'\"[] ").lower()
    if len(v) < 5:
        return None
    for name in names:
        if v == name.lower():
            return name
    for name in names:
        stem = re.split(r",| \(| - ", name.lower())[0]
        if v.startswith(stem) or stem.startswith(v):
            return name
    return None


def parse_names(value, names):
    """Split an LLM list of category/group names into one matched name (or UNMATCHED) per entry.

    Entries should be separated by semicolons, but some category names contain commas, so a
    comma separated answer is read by finding the full names in order, falling back to splitting
    on commas when it uses names that aren't written in full."""
    if not isinstance(value, str) or not value.strip():
        return []
    v = value.strip()
    if v.lower().startswith("no supplements"):
        return []
    if ";" in v:
        parts = v.split(";")
    else:
        positions = sorted((m.start(), name) for name in names
                           for m in re.finditer(re.escape(name), v, flags=re.IGNORECASE))
        leftover = v
        for name in names:
            leftover = re.sub(re.escape(name), "", leftover, flags=re.IGNORECASE)
        if positions and not leftover.strip(" ,;.'\"[]"):
            return [name for _, name in positions]
        parts = v.split(",")
    parts = [p.strip(" '\"[]") for p in parts]
    return [match_name(p, names) or UNMATCHED for p in parts if p]


def term_categories(post):
    """The LLM's status category for each of a post's supplements, in the same order; UNMATCHED where
    it gave no usable category (e.g. results from prompts before categories were assigned by the LLM)."""
    return [match_name(o.get("status_category", ""), STATUS_CATEGORIES) or UNMATCHED
            for o in parse_supplements(post.get("supplements"))]


# ---------------------------------------------------------------------------
# Post-level cleaning
# ---------------------------------------------------------------------------
def remove_duplicates(df):
    """Remove cross-platform duplicate posts.

    A post is considered a duplicate when another post has the same
    normalized title (>= 15 chars, so generic titles are never merged) and
    the same duration rounded to the nearest second. Posts without a duration
    are never merged: many Instagram posts have no duration and a title like
    "Video by <account>", which would merge every video from that account.
    The copy with the highest view count is kept.
    """
    df = df.copy()
    title_norm = df['title'].fillna('').str.lower().str.strip()
    duration = df['duration'].round() if 'duration' in df.columns else 0
    df['_dedup_key'] = title_norm + '|' + duration.astype(str)
    eligible = title_norm.str.len() >= 15
    if 'duration' in df.columns:
        eligible &= df['duration'].notna()
    # stable sort with id tie-break so the kept copy is deterministic
    dupes = df[eligible].sort_values(['view_count', 'id'],
                                     ascending=[False, True], kind='mergesort')
    drop_idx = dupes[dupes.duplicated('_dedup_key', keep='first')].index
    if len(drop_idx):
        print(f"Removing {len(drop_idx)} duplicate posts (same title and duration)")
    return df.drop(index=drop_idx).drop(columns='_dedup_key')


# ---------------------------------------------------------------------------
# Post-level processing
# ---------------------------------------------------------------------------
SENTINEL_VALUES = {
    "none", "no supplements mentioned", "yes", "n/a", "na", "", "nan",
    "no supplements", "not mentioned", "no",
}


def parse_supplements(value):
    """The LLM's supplements field as a list of {name, status_category, product_type, ...} objects.

    It's a JSON list of objects, or that list's text as stored in the results spreadsheet. Results
    from earlier prompts are a list or comma separated string of names, giving objects with just a name."""
    items = value
    if isinstance(value, str):
        items = None
        if value.strip().startswith("["):
            for load in (json.loads, ast.literal_eval):
                try:
                    items = load(value)
                    break
                except (ValueError, SyntaxError, TypeError):
                    pass
        if items is None:
            items = [s.strip().strip("'\"") for s in value.strip("[]").split(",")]
    if not isinstance(items, list):
        return []
    objects = [item if isinstance(item, dict) else {"name": item} for item in items]
    return [o for o in objects
            if str(o.get("name") or "").strip() and str(o.get("name")).strip().lower() not in SENTINEL_VALUES]


def split_supplements(value):
    """The supplement names in the LLM's supplements field."""
    return [str(o["name"]).strip() for o in parse_supplements(value)]


def primary_category(post):
    """One status category per post: the LLM's primary category, or else the most frequent
    category among its terms (ties resolved away from the vague catch-all)."""
    if not split_supplements(post.get("supplements")):
        return None
    primary = match_name(post.get("primary_status_category"), STATUS_CATEGORIES)
    if primary:
        return primary
    cats = Counter(c for c in term_categories(post) if c != UNMATCHED)
    if not cats:
        return UNMATCHED
    return sorted(cats.items(), key=lambda kv: (-kv[1], kv[0] == VAGUE))[0][0]


def primary_target(post):
    """One marketing/target group per post: the LLM's primary target group."""
    if not split_supplements(post.get("supplements")):
        return None
    return match_name(post.get("primary_target_group"), TARGET_GROUPS) or UNMATCHED


def code_dataset(df):
    """Explode posts to one row per (post, supplement term) with its canonical name and status category."""
    rows = []
    for _, post in df.iterrows():
        for raw, category in zip(split_supplements(post.get("supplements")), term_categories(post)):
            rows.append({
                "id": post.get("id"),
                "extractor": post.get("extractor"),
                "title": post.get("title"),
                "webpage_url": post.get("webpage_url"),
                "like_count": post.get("like_count"),
                "view_count": post.get("view_count"),
                "raw_term": raw,
                "canonical": canonicalize(raw),
                "status_category": category,
            })
    return pd.DataFrame(rows)


def code_targets(df):
    """Explode posts to one row per (post, target group) the LLM says it frames its supplements for."""
    rows = []
    for _, post in df.iterrows():
        if not split_supplements(post.get("supplements")):
            continue
        for group in dict.fromkeys(parse_names(post.get("target_groups"), TARGET_GROUPS)) or [UNMATCHED]:
            rows.append({
                "id": post.get("id"),
                "extractor": post.get("extractor"),
                "title": post.get("title"),
                "webpage_url": post.get("webpage_url"),
                "like_count": post.get("like_count"),
                "view_count": post.get("view_count"),
                "target_group": group,
            })
    return pd.DataFrame(rows)


def group_summary(coded, group_col):
    """Counts and popularity metrics per group (unique posts, likes, views)."""
    per_post = coded.drop_duplicates(subset=["id", group_col])
    summary = per_post.groupby(group_col).agg(
        post_count=("id", "nunique"),
        total_likes=("like_count", "sum"),
        total_views=("view_count", "sum"),
    ).sort_values("post_count", ascending=False)
    return summary


def main():
    data_path = Path("data/supplements_LLM_results.xlsx")
    df = pd.read_excel(data_path)
    print(f"Loaded {len(df)} posts")

    # Same population as the pipeline Sankey: allowed platforms,
    # menopause==True, duplicates removed
    df["extractor"] = df["extractor"].str.lower()
    df = df[df["extractor"].isin(ALLOWED_PLATFORMS)].copy()
    if "menopause" in df.columns:
        df = df[df["menopause"] == True].copy()
        print(f"menopause=True posts: {len(df)}")
    df = remove_duplicates(df)
    print(f"unique posts: {len(df)}")

    coded = code_dataset(df)
    targets = code_targets(df)
    print(f"Coded {len(coded)} supplement mentions "
          f"({coded['raw_term'].nunique()} unique raw terms, "
          f"{coded['canonical'].nunique()} canonical groups)")
    unmatched = coded[coded["status_category"] == UNMATCHED]["raw_term"].nunique()
    print(f"Raw terms without a usable LLM category (manual review): {unmatched}")

    # primary (one-per-post) counts; these reconcile with the Sankey figures
    supp_mask = df["supplements"].apply(lambda v: len(split_supplements(v)) > 0)
    supp_posts = df[supp_mask]
    primary = pd.DataFrame({
        "id": supp_posts["id"],
        "like_count": supp_posts["like_count"],
        "view_count": supp_posts["view_count"],
        "primary_category": supp_posts.apply(primary_category, axis=1),
        "primary_target": supp_posts.apply(primary_target, axis=1),
    })

    def primary_summary(col):
        # each row is one post, so count rows (ids can be missing or shared)
        return primary.groupby(col).agg(
            post_count=("id", "size"),
            total_likes=("like_count", "sum"),
            total_views=("view_count", "sum"),
        ).sort_values("post_count", ascending=False)

    out_path = Path("data/supplement_categories.xlsx")
    with pd.ExcelWriter(out_path) as writer:
        # any-mention counts: a post appears under every category it mentions,
        # so these columns sum to more than the number of posts
        group_summary(coded, "status_category").to_excel(
            writer, sheet_name="category_counts")
        group_summary(targets, "target_group").to_excel(
            writer, sheet_name="target_counts")
        # primary counts: one category/target per post, matching the Sankey
        primary_summary("primary_category").to_excel(
            writer, sheet_name="primary_category_counts")
        primary_summary("primary_target").to_excel(
            writer, sheet_name="primary_target_counts")
        # posts in rows grouped under each category, as requested
        coded.sort_values(["status_category", "canonical"]).to_excel(
            writer, sheet_name="posts_by_category", index=False)
        targets.sort_values(["target_group", "id"]).to_excel(
            writer, sheet_name="posts_by_target", index=False)
        # full mapping for review
        mapping = (coded.groupby(["raw_term", "canonical", "status_category"])
                   .size().reset_index(name="count")
                   .sort_values("count", ascending=False))
        mapping.to_excel(writer, sheet_name="term_mapping", index=False)
    print(f"Saved {out_path}")


if __name__ == "__main__":
    main()
