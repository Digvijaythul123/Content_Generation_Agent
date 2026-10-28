#!/usr/bin/env python3
"""Score a Reel hook (the first line on screen) before it is posted.

Five properties, 0-100 each, and a verdict that is 60% the mean and 40% the
weakest one: a hook with four strong properties and one dead one leaks at the
dead one, and averaging hides that.

    python3 hook_score.py --hook "one line"
    python3 hook_score.py hooks.txt            # one hook per line, ranked

Weights were raised from the YouTube original so a calm, sourced hook
without "you" is not marked weak. A heuristic, not a predictor: a low score is a reason to look again, a high
score is not a promise. The Performance report (grouped by hook formula) is
what tells us which hooks this audience actually watches.

Adapted from hookscore.py in Jakeschincariol/youtube-agent-skill
(https://github.com/Jakeschincariol/youtube-agent-skill), MIT License,
Copyright (c) 2026 Jake Schincariol. Permission is hereby granted, free of
charge, to any person obtaining a copy of this software and associated
documentation files (the "Software"), to deal in the Software without
restriction, including without limitation the rights to use, copy, modify,
merge, publish, distribute, sublicense, and/or sell copies of the Software,
subject to the condition that the above copyright notice and this permission
notice are included in all copies or substantial portions of the Software.
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.

Changes for 10-second Reels: the brevity band is 6-14 words (our on-screen
hook limit), spiritual cliches count as vague, and everyday suffering words
(anger, grief, worry...) count as stakes.
"""

from functools import lru_cache
import json
import re
import sys

from project_paths import CONFIG_DIRECTORY


FORMULAS_PATH = CONFIG_DIRECTORY / "hook_formulas.json"

FILLER = {"basically", "actually", "literally", "just", "really", "very", "so", "kind", "sort",
          "like", "guys", "hey", "welcome", "today", "video", "subscribe", "channel"}
VAGUE = {"amazing", "incredible", "insane", "crazy", "huge", "massive", "game", "changer",
         "secret", "powerful", "ultimate", "best", "revolutionary", "mind", "blowing",
         "unbelievable",
         # Spiritual cliches say nothing a viewer can picture.
         "universe", "vibes", "vibe", "energy", "manifest", "journey", "divine", "magic",
         "magical", "abundance", "cosmic", "higher"}
CONCRETE = re.compile(
    r"\b(\d[\d,.]*\s?(%|k|m|x|s|h)?|\$\d|\d+\s?(second|minute|hour|day|week|month|year)s?)\b",
    re.I,
)
YOU = re.compile(r"\b(you|your|you're|youre|yourself)\b", re.I)
STAKE = re.compile(
    r"\b(lose|lost|wasting|waste|quit|fail|broke|cost|costs|risk|before|stop|never|die|dying|"
    r"dead|death|anger|angry|grief|grieving|worry|worries|fear|afraid|pain|suffer|suffering|"
    r"regret|alone|lonely|craving|hurt|stress|stressed|hate|jealous|envy|died|sword|killer|"
    r"bandit|storm|chase|chases|runs|cry|cries|tears)\b",
    re.I,
)
CURIOSITY = re.compile(
    r"\b(why|how|what|which|until|before|but|nobody|almost|except|reason|actually|never|real|"
    r"really|then)\b",
    re.I,
)

FIX = {
    "SPECIFICITY": "swap one vague word for a name, a number, or a source",
    "ADDRESS": "say 'you' (or name who it is for) in the first six words",
    "STAKES": "name the real struggle: anger, worry, grief, fear",
    "CURIOSITY": "cut the half of the line that answers itself",
    "BREVITY": "6 to 14 words, readable in two seconds",
}


def _plain(text):
    return re.sub(r"\*\*(.+?)\*\*", r"\1", str(text or "")).strip()


def _words(text):
    return re.findall(r"[a-z0-9'%$.]+", text.lower())


def specificity(text):
    words = _words(text)
    if not words:
        return 0
    numbers = len(CONCRETE.findall(text))
    vague = sum(1 for word in words if word in VAGUE)
    filler = sum(1 for word in words if word in FILLER)
    score = 40 + numbers * 22 - vague * 16 - filler * 5
    # Capitalised words after the first read as named things (the Buddha, Dhammapada).
    score += min(18, 6 * sum(1 for word in text.split()[1:] if word[:1].isupper()))
    return max(0, min(100, score))


def address(text):
    count = len(YOU.findall(text))
    first = 30 if YOU.search(" ".join(text.split()[:6])) else 0
    named = 30 if re.match(r"^(for|if) (anyone|you|those|the one|whoever)\b", text, re.I) else 0
    # A question speaks to the viewer even without "you"; on this page a
    # story hook about the Buddha is fine too, so the floor is higher.
    asked = 20 if text.strip().endswith("?") else 0
    return max(0, min(100, 40 + count * 20 + first + named + asked))


def stakes(text):
    count = len(STAKE.findall(text))
    return max(0, min(100, 30 + count * 26 + (14 if CONCRETE.search(text) else 0)))


def curiosity(text):
    count = len(CURIOSITY.findall(text))
    question = 18 if text.strip().endswith("?") else 0
    # A hook that resolves itself has no gap left.
    closed = -18 if re.search(r"\b(because|so that|which means)\b", text, re.I) else 0
    return max(0, min(100, 30 + count * 17 + question + closed))


def brevity(text):
    count = len(_words(text))
    if count == 0:
        return 0
    if 6 <= count <= 14:
        return 100
    if count < 6:
        return max(30, 100 - (6 - count) * 14)
    return max(10, 100 - (count - 14) * 9)


PROPERTIES = (("SPECIFICITY", specificity), ("ADDRESS", address), ("STAKES", stakes),
              ("CURIOSITY", curiosity), ("BREVITY", brevity))


@lru_cache(maxsize=1)
def _library():
    return json.loads(FORMULAS_PATH.read_text(encoding="utf-8"))


def all_formulas():
    return list(_library()["hooks"])


def hook_rules():
    return list(_library()["rules"])


def formulas_for(profile_id=None):
    """The formulas a content profile uses: its hook_formulas list, or all."""
    formulas = all_formulas()
    if not profile_id:
        return formulas
    from config_loader import load_profile_hook_formulas

    chosen = load_profile_hook_formulas(profile_id)
    if not chosen:
        return formulas
    return [formula for formula in formulas if formula["id"] in chosen]


def formula_example(formula, profile_id=None):
    return (formula.get("examples_by_profile") or {}).get(profile_id) or formula["example"]


def classify(text, formulas=None):
    best, hits = None, 0
    for formula in formulas or all_formulas():
        count = sum(1 for pattern in formula["match"] if re.search(pattern, text, re.I))
        if count > hits:
            best, hits = formula, count
    return best


def band(verdict):
    # Lower than the YouTube original (72/55): short on-screen lines score lower.
    return "STRONG" if verdict >= 65 else "WORKABLE" if verdict >= 50 else "WEAK"


def score_hook(text, formulas=None):
    """Score one hook; returns properties, verdict, band, formula, and a fix."""
    text = _plain(text)
    properties = {name: rule(text) for name, rule in PROPERTIES}
    formula = classify(text, formulas)
    if formula:
        # A proven hook shape opens a gap even without question words.
        properties["CURIOSITY"] = min(100, properties["CURIOSITY"] + 20)
    values = list(properties.values())
    verdict = round(0.6 * (sum(values) / len(values)) + 0.4 * min(values))
    weakest = min(properties, key=properties.get)
    return {
        "hook": text,
        "properties": properties,
        "verdict": verdict,
        "band": band(verdict),
        "formula": formula["id"] if formula else None,
        "formula_name": formula["name"] if formula else "Unclassified",
        "weakest": weakest,
        "fix": FIX[weakest],
    }


def rank_hooks(texts, formulas=None):
    scored = [score_hook(text, formulas) for text in texts if _plain(text)]
    return sorted(scored, key=lambda item: -item["verdict"])


def main(argv):
    if "--hook" in argv:
        lines = [argv[argv.index("--hook") + 1]]
    elif argv:
        with open(argv[0], encoding="utf-8") as handle:
            lines = [line for line in handle.read().splitlines() if line.strip()]
    else:
        print(__doc__)
        return 1
    for result in rank_hooks(lines):
        print(f"\n  {result['hook']}")
        for name, value in result["properties"].items():
            print(f"    {name:<12} {value:3d}  {'#' * (value // 5)}")
        print(f"    {'VERDICT':<12} {result['verdict']:3d}  {result['band']}")
        print(f"    formula      {result['formula_name']}")
        print(f"    weakest      {result['weakest']} - {result['fix']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
