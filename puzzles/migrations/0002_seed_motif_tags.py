"""Seed the mechanism taxonomy (Design.md §5): 13 tags + OTHER.

No sub-motifs (smothered mate, Greek gift, …) until the data demands them —
with one player's games most sub-motifs would have n < 5.
"""

from django.db import migrations

RULE, FUZZY = 1, 2

TAGS = [
    # Tier 1 — rule-detectable (python-chess, SEE, ray logic)
    ("hanging-piece", "Hanging piece", RULE,
     "A piece was (or was left) capturable at a loss, by SEE."),
    ("fork", "Fork / double attack", RULE,
     "One move attacks two or more undefended or higher-value targets."),
    ("pin", "Pin", RULE,
     "A piece cannot or should not move because a ray attack hits a more "
     "valuable piece behind it."),
    ("skewer", "Skewer", RULE,
     "A ray attack forces a valuable piece to move, exposing one behind it."),
    ("discovered-attack", "Discovered attack", RULE,
     "Moving one piece unmasks an attack from another."),
    ("back-rank", "Back rank", RULE,
     "Mate or material win exploiting a confined king on its first rank."),
    ("trapped-piece", "Trapped piece", RULE,
     "A piece has no safe square and is lost to attack."),
    ("counting-error", "Counting error", RULE,
     "A capture sequence resolves negatively — the exchange was miscounted."),
    ("mate-threat", "Mate threat", RULE,
     "A forced mate existed or was allowed."),
    ("promotion", "Promotion / passed pawn", RULE,
     "A passed pawn ran or should have run."),
    # Tier 2 — LLM-proposed (miserable to rule-detect)
    ("deflection", "Deflection / overloading", FUZZY,
     "A defender was lured away, overloaded, or removed."),
    ("zwischenzug", "Zwischenzug", FUZZY,
     "An in-between move changes the result of the expected sequence."),
    ("king-safety", "King-safety error", FUZZY,
     "Structural or piece-placement decisions fatally weakened the king."),
    # The evidence-driven expansion mechanism — reviewed periodically
    ("other", "Other", FUZZY,
     "Doesn't fit the taxonomy; recurring OTHERs justify a new tag."),
]


def seed(apps, schema_editor):
    MotifTag = apps.get_model("puzzles", "MotifTag")
    for slug, name, tier, description in TAGS:
        MotifTag.objects.update_or_create(
            slug=slug, defaults={"name": name, "tier": tier, "description": description}
        )


def unseed(apps, schema_editor):
    MotifTag = apps.get_model("puzzles", "MotifTag")
    MotifTag.objects.filter(slug__in=[t[0] for t in TAGS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('puzzles', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
