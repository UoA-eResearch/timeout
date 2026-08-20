#!/usr/bin/env python3
"""
Deterministic cleaning and coding of supplement terms extracted by the LLM.

Implements the coding framework from the research team's documents:
  - "Dividing data plan 18.8.26" (canonical grouping, 9 categories, target groups)
  - "data_cleaning_for_combining_supplement_categories_9_categories"
  - "supplement_coding_instructions_for_data_cleaning"
  - "marketing_target_grouping_instruction_table"

Three coding layers per raw term:
  1. Canonical name  - collapse spelling/formulation/synonym variants before counting
  2. Status category - one of nine broad product / clinical-regulatory categories
  3. Target group    - the marketing/target-function the term is typically framed for

Terms that match no rule are flagged "Unmatched (manual review)" rather than
being forced into a category, per the coding instructions.

Run as a script to produce data/supplement_categories.xlsx from
data/supplements_LLM_results.xlsx:
  - counts and popularity metrics (likes, views) per category and target group
  - posts listed in rows grouped under each category / target group
  - the full raw term -> canonical -> category -> target mapping for review
"""

import re
from collections import Counter
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Layer 1: canonical ingredient grouping (Table 1 of coding instructions)
# ---------------------------------------------------------------------------
# regex pattern -> canonical name; checked in order, first match wins
CANONICAL_PATTERNS = [
    (r"vitamin\s*d3?\b|cholecalciferol|ergocalciferol|\bd3\b", "Vitamin D"),
    (r"magnesium", "Magnesium"),
    (r"omega[\s-]*3|fish oil|krill oil|cod liver oil", "Omega-3 / marine oils"),
    (r"\bb[\s-]*(vitamins?|complex)|vitamin b\s*(complex|12|6|5|2|1)?\b|\bb12\b|\bb6\b|folate|folic acid|methylcobalamin|thiamine", "B vitamins"),
    (r"black cohosh", "Black cohosh"),
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
# Layer 2: nine broad product / clinical-regulatory status categories
# ---------------------------------------------------------------------------
STATUS_CATEGORIES = {
    "Hormone therapies": [
        "hrt", "hormone replacement therapy", "hormone therapy",
        "menopausal hormone therapy", "mht", "menopause hormone therapy",
        "estrogen", "oestrogen", "estradiol", "estradiol patch",
        "estrogen patch", "oral estradiol", "vaginal estrogen",
        "topical estrogen", "estrogen cream", "estrogen gel", "progesterone",
        "micronized progesterone", "bioidentical progesterone",
        "progesterone cream", "progesterone pill", "testosterone",
        "testosterone therapy", "testosterone gel", "dhea", "vaginal dhea",
        "bioidentical hormones", "bioidenticals", "estriol", "progestin",
        "medroxyprogesterone acetate", "premarin", "estradot", "divigel",
        "oestrogel", "prometrium", "birth control", "birth control pills",
    ],
    "Prescription and over-the-counter medications": [
        "ssri", "ssris", "snri", "snris", "antidepressant", "antidepressants",
        "gabapentin", "clonidine", "glp-1", "glp1", "ozempic", "semaglutide",
        "pepcid", "pepcid ac", "zyrtec", "allegra", "claritin", "flonase",
        "antihistamine", "antihistamines", "spironolactone", "minoxidil",
        "ibuprofen", "antibiotics", "addyi", "vyleesi", "viagra", "tretinoin",
        "retinol",
    ],
    "Vitamins and minerals": [
        "vitamin d", "vitamin d3", "vitamin d supplement", "vitamin d3 + k2",
        "vitamin d + k2", "vitamin d3 with k2", "vitamin c", "vitamin e",
        "vitamin k", "vitamin k2", "vitamin a", "b vitamins",
        "vitamin b complex", "b complex", "b-complex", "b12", "vitamin b12",
        "methylcobalamin", "b6", "vitamin b6", "b5", "b2", "b1", "thiamine",
        "folate", "folic acid", "calcium", "calcium supplements", "magnesium",
        "magnesium glycinate", "magnesium citrate", "magnesium l-threonate",
        "magnesium threonate", "magnesium malate", "magnesium bisglycinate",
        "magnesium taurate", "magnesium oil", "magnesium complex", "zinc",
        "iron", "selenium", "chromium", "iodine", "boron", "copper",
        "potassium", "phosphorus", "choline", "silica", "multivitamin",
        "multivitamins", "vitamins and minerals",
    ],
    "Herbals, botanicals and phytoestrogenic products": [
        "black cohosh", "black cohosh root", "ashwagandha", "turmeric",
        "curcumin", "shatavari", "red clover", "maca", "maca root",
        "maca powder", "sage", "dong quai", "chasteberry", "vitex",
        "chaste tree", "chaste tree berry", "soy", "soy isoflavones",
        "isoflavones", "phytoestrogens", "phytoestrogen", "rhodiola",
        "rhodiola rosea", "ginseng", "saffron", "saffron extract",
        "milk thistle", "quercetin", "st john's wort", "st johns wort",
        "motherwort", "moringa", "aloe vera", "ginger", "reishi", "hops",
        "passionflower", "valerian", "lemon balm", "wild yam",
        "wild yam cream", "pueraria mirifica", "green tea extract",
        "saw palmetto", "brahmi", "sea moss", "pomegranate",
    ],
    "Fatty acids and oils": [
        "omega-3", "omega 3", "omega-3s", "omega-3 fatty acids",
        "omega-3 supplement", "omega-3 fish oil", "omega 3 fish oil",
        "fish oil", "krill oil", "krill oil softgels", "cod liver oil",
        "omega-6", "omega 6", "evening primrose oil", "evening primrose",
        "flaxseed oil", "flax", "flaxseed", "chia seeds", "hemp seeds",
        "pumpkin seed oil", "sacha inchi", "mct oil",
    ],
    "Protein, amino acids, creatine, body-composition and sports/performance supplements": [
        "creatine", "creatine monohydrate", "pause nutrition creatine",
        "collagen", "collagen peptides", "collagen powder",
        "collagen tablets", "verisol collagen", "collagen therapy",
        "skin and bone collagen", "protein", "protein powder",
        "protein supplement", "whey protein", "plant protein", "peptides",
        "bcaa", "bcaas", "l-theanine", "glycine", "taurine", "tryptophan",
        "5-htp", "gaba", "l-glutamine", "electrolytes",
    ],
    "Gut/microbiome products, including probiotics, prebiotics, postbiotics, symbiotics and fibre": [
        "probiotic", "probiotics", "prebiotic", "prebiotics", "postbiotic",
        "symbiotic", "synbiotic", "fibre", "fiber", "fibre supplement",
        "fiber supplement", "fiber gdx", "the pause life fiber",
        "psyllium husk", "digestive enzymes", "pancreatic enzymes",
        "dao enzymes", "slippery elm", "marshmallow root",
    ],
    "Branded menopause or symptom-targeted formulations": [
        "perimeno health", "snap perimeno health", "perimenopause health",
        "meno-chill", "menochill", "meno chill",
        "black girl vitamins meno-chill", "black girl vitamins",
        "hormone harmony", "komi wellness hormone harmony", "amberen",
        "amberen complete menopause relief", "superbalance",
        "nello superbalance", "ever balance", "estroven", "estrovera",
        "menopace", "menofix", "meno active",
        "meno menopause vitamin capsules", "menopause vitamin capsules",
        "olly mellow menopause",
        "health & her perimenopause multi-nutrient support",
        "a.vogel balance perimenopause multi-nutrient drink",
        "nutrafol women's balance", "nutrafol", "sleep harmony",
        "stress harmony", "gut harmony", "pause sleep", "daily brain boost",
        "fabu brain", "meno vaginal moisture capsules",
        "peach perfect menopause multivitamin",
        "nature's bounty advanced menopause relief", "provitalize",
        "thermella", "menovital", "cleanmarine menomin", "promensil",
        "yuzucare menopause support", "midi supplements",
        "kind patches menopause patches", "unbreakable bone health formula",
        "skin & bone dietary supplement", "skin boost plus", "key collagen",
        "beam glow", "lioness ready performance", "primal queen",
        "revive active",
    ],
    "Other, vague, ambiguous or non-classifiable terms": [
        "supplement", "supplements", "supplementation", "vitamins",
        "minerals", "herbs", "natural supplements", "menopause supplement",
        "menopause supplements", "menopause support", "menopause complex",
        "natural menopause support formulas", "menopause herbs",
        "hormone balance", "hormones", "pills", "pill", "capsules", "capsule",
        "tablets", "gummies", "patches", "gels", "creams", "gel", "hair",
        "micronutrients",
    ],
}

UNMATCHED = "Unmatched (manual review)"

# exact-match lookup; categories are checked in dict order so more specific
# categories (e.g. hormone therapies) win over the vague catch-all
_STATUS_LOOKUP = {}
for _cat, _terms in STATUS_CATEGORIES.items():
    for _t in _terms:
        _STATUS_LOOKUP.setdefault(_t, _cat)


def status_category(term):
    """Assign a raw term to one of the nine broad status categories.

    Exact match on the documented term lists first; then a small set of
    pattern fallbacks for formulation variants; unmatched terms are flagged
    for manual review rather than forced into a category.
    """
    t = term.strip().lower().rstrip(".")
    if t in _STATUS_LOOKUP:
        return _STATUS_LOOKUP[t]
    # formulation/spelling variant fallbacks
    if re.search(r"vitamin\s*[a-ek]\d*\b|\bk2\b|folate|folic acid", t):
        return "Vitamins and minerals"
    if re.search(r"magnesium|calcium|zinc|iron\b|selenium|multivitamin", t):
        return "Vitamins and minerals"
    if re.search(r"omega[\s-]*[36]|fish oil|krill|cod liver|primrose|flax", t):
        return "Fatty acids and oils"
    if re.search(r"collagen|creatine|protein|peptide|amino acid|electrolyte", t):
        return "Protein, amino acids, creatine, body-composition and sports/performance supplements"
    if re.search(r"probiotic|prebiotic|postbiotic|fibre|fiber|digestive enzyme", t):
        return "Gut/microbiome products, including probiotics, prebiotics, postbiotics, symbiotics and fibre"
    if re.search(r"estrogen|oestrogen|estradiol|progesterone|testosterone|hormone (replacement|therapy)|\bhrt\b|\bmht\b", t):
        return "Hormone therapies"
    if re.search(r"meno(pause)?[\s-]", t):
        return "Branded menopause or symptom-targeted formulations"
    return UNMATCHED


# ---------------------------------------------------------------------------
# Layer 3: marketing/target-function groups (Division 3 table)
# ---------------------------------------------------------------------------
TARGET_GROUPS = {
    "Bone / musculoskeletal support": [
        "vitamin d", "calcium", "vitamin k2", "vitamin k", "magnesium",
        "collagen", "creatine", "protein", "protein powder", "whey protein",
        "bcaa", "bcaas", "electrolytes", "bone", "joint", "muscle",
        "strength",
    ],
    "Phytoestrogenic or hormone-modulating claims": [
        "soy isoflavones", "soy", "isoflavones", "red clover",
        "phytoestrogen", "phytoestrogens", "flaxseed", "flax", "maca",
        "wild yam", "dim", "chasteberry", "vitex", "chaste tree", "hrt",
        "hormone replacement therapy", "estrogen", "oestrogen",
        "progesterone", "testosterone", "dhea", "hormone balance",
    ],
    "Vasomotor symptom / hot-flush relief": [
        "black cohosh", "sage", "evening primrose oil", "evening primrose",
        "amberen", "estroven", "meno-chill", "menochill", "meno chill",
        "hot flush", "hot flash", "night sweat", "cooling", "thermella",
    ],
    "Sleep / stress / mood / cognition support": [
        "magnesium glycinate", "magnesium l-threonate", "l-theanine",
        "melatonin", "ashwagandha", "rhodiola", "saffron", "gaba", "glycine",
        "valerian", "passionflower", "lion's mane", "lions mane", "coq10",
        "nmn", "5-htp", "tryptophan", "lemon balm", "sleep", "stress",
        "mood", "brain", "calm",
    ],
    "Metabolic / weight / insulin framing": [
        "berberine", "inositol", "myo-inositol", "chromium",
        "apple cider vinegar", "mct oil", "glp-1", "glp1", "ozempic",
        "semaglutide", "weight", "metabolism", "blood sugar", "insulin",
    ],
    "Gut / inflammation / detox framing": [
        "probiotic", "probiotics", "prebiotic", "prebiotics", "postbiotic",
        "fibre", "fiber", "psyllium husk", "digestive enzymes", "turmeric",
        "curcumin", "milk thistle", "slippery elm", "l-glutamine",
        "vitamin c", "gut", "detox", "bloating",
    ],
    "Skin / hair / beauty ageing": [
        "collagen peptides", "biotin", "hyaluronic acid", "nutrafol", "zinc",
        "minoxidil", "retinol", "tretinoin", "skin", "hair", "nails",
        "beauty",
    ],
    "Sexual / vaginal symptoms": [
        "vaginal estrogen", "vaginal dhea", "addyi", "vyleesi", "viagra",
        "libido", "vaginal", "cranberry",
    ],
}

GENERAL_TARGET = "General menopause / multisymptom / unclear target"


def target_group(term):
    """Assign a raw term to a marketing/target-function group.

    Term-based coding: the group whose item list or keywords match the term.
    Falls back to the general/unclear group, which the instructions specify
    as the default when the target cannot be inferred from the term alone.
    NB the instructions allow multi-label coding from post text; this
    term-level pass assigns the first matching (primary) group only.
    """
    t = term.strip().lower().rstrip(".")
    for group, terms in TARGET_GROUPS.items():
        for item in terms:
            if t == item or (len(item) > 3 and item in t):
                return group
    return GENERAL_TARGET


# ---------------------------------------------------------------------------
# Post-level processing
# ---------------------------------------------------------------------------
SENTINEL_VALUES = {
    "none", "no supplements mentioned", "yes", "n/a", "na", "", "nan",
    "no supplements", "not mentioned", "no",
}


def split_supplements(value):
    """Split the LLM's supplements field into individual raw terms."""
    if not isinstance(value, str):
        return []
    items = [s.strip().strip("'\"") for s in value.strip("[]").split(",")]
    return [s for s in items if s and s.lower() not in SENTINEL_VALUES]


def code_dataset(df):
    """Explode posts to one row per (post, supplement term) with all coding layers."""
    rows = []
    for _, post in df.iterrows():
        for raw in split_supplements(post.get("supplements")):
            rows.append({
                "id": post.get("id"),
                "extractor": post.get("extractor"),
                "title": post.get("title"),
                "webpage_url": post.get("webpage_url"),
                "like_count": post.get("like_count"),
                "view_count": post.get("view_count"),
                "raw_term": raw,
                "canonical": canonicalize(raw),
                "status_category": status_category(raw),
                "target_group": target_group(raw),
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

    # menopause==True scope, per the dividing data plan
    if "menopause" in df.columns:
        df = df[df["menopause"] == True].copy()
        print(f"menopause=True posts: {len(df)}")

    coded = code_dataset(df)
    print(f"Coded {len(coded)} supplement mentions "
          f"({coded['raw_term'].nunique()} unique raw terms, "
          f"{coded['canonical'].nunique()} canonical groups)")
    unmatched = coded[coded["status_category"] == UNMATCHED]["raw_term"].nunique()
    print(f"Raw terms flagged for manual review: {unmatched}")

    out_path = Path("data/supplement_categories.xlsx")
    with pd.ExcelWriter(out_path) as writer:
        group_summary(coded, "status_category").to_excel(
            writer, sheet_name="category_counts")
        group_summary(coded, "target_group").to_excel(
            writer, sheet_name="target_counts")
        # posts in rows grouped under each category, as requested
        coded.sort_values(["status_category", "canonical"]).to_excel(
            writer, sheet_name="posts_by_category", index=False)
        coded.sort_values(["target_group", "canonical"]).to_excel(
            writer, sheet_name="posts_by_target", index=False)
        # full mapping for review
        mapping = (coded.groupby(["raw_term", "canonical", "status_category",
                                  "target_group"])
                   .size().reset_index(name="count")
                   .sort_values("count", ascending=False))
        mapping.to_excel(writer, sheet_name="term_mapping", index=False)
    print(f"Saved {out_path}")


if __name__ == "__main__":
    main()
