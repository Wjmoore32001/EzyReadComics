from catalog.current_reading_era.shared import build_timeline


PUBLISHER_SLUG_ALIASES = {
    "marvel",
    "marvel comics",
    "marvel-comics",
}
PUBLISHER_NAME_ALIASES = {
    "marvel",
    "marvel comics",
}
SORT_ORDER = 0

EXCLUDED_TITLE_PREFIXES = (
    "ULTIMATE",
    "WHAT IF",
    "MARVEL ZOMBIES",
    "X-MEN '97",
    "X-MEN 97",
    "OLD MAN",
    "STAR WARS",
    "ALIEN",
    "PREDATOR",
    "GODZILLA",
    "PLANET OF THE APES",
    "ULTRAMAN",
    "WARHAMMER",
    "HALO",
    "FORTNITE",
    "DISNEY",
    "MARVEL & DISNEY",
    "MARVEL DISNEY",
)

EXCLUDED_TITLE_TERMS = (
    " STAR WARS",
    " ALIEN",
    " ALIENS",
    " PREDATOR",
    " GODZILLA",
    " 2099",
    "WHAT IF",
    "MARVEL ZOMBIES",
    "X-MEN '97",
    "X-MEN 97",
    "PLANET OF THE APES",
    "ULTRAMAN",
    "WARHAMMER",
    "FORTNITE",
    "MARVEL & DISNEY",
    "MARVEL DISNEY",
)


def normalized_run_title(run):
    return " ".join(str(run.title or "").upper().replace("’", "'").split())


def get_exclusion_reason(run):
    title = normalized_run_title(run)

    for prefix in EXCLUDED_TITLE_PREFIXES:
        if title.startswith(prefix):
            return f'title begins with excluded Marvel line or franchise "{prefix}"'

    padded_title = f" {title} "

    for term in EXCLUDED_TITLE_TERMS:
        if term in padded_title:
            return f'title contains excluded Marvel line or franchise "{term.strip()}"'

    return ""


def is_eligible_run(run):
    return not get_exclusion_reason(run)


def build_publisher_timeline(runs):
    return build_timeline(runs, is_eligible_run=is_eligible_run)
