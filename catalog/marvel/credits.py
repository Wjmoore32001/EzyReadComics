import re

from catalog.marvel.text import clean_text


ROLE_DISPLAY_ORDER = {
    "Writer": 10,
    "Artist": 20,
    "Penciller": 30,
    "Inker": 40,
    "Colorist": 50,
    "Letterer": 60,
    "Cover Artist": 70,
    "Editor": 80,
}

DETAIL_CREDIT_LABELS = {
    "WRITER": "Writer",
    "WRITERS": "Writer",
    "ARTIST": "Artist",
    "ARTISTS": "Artist",
    "PENCILLER": "Penciller",
    "PENCILLERS": "Penciller",
    "PENCILER": "Penciller",
    "PENCILERS": "Penciller",
    "INKER": "Inker",
    "INKERS": "Inker",
    "COLORIST": "Colorist",
    "COLORISTS": "Colorist",
    "COLOURIST": "Colorist",
    "COLOURISTS": "Colorist",
    "LETTERER": "Letterer",
    "LETTERERS": "Letterer",
    "COVER ARTIST": "Cover Artist",
    "COVER ARTISTS": "Cover Artist",
    "EDITOR": "Editor",
    "EDITORS": "Editor",
}


def extract_detail_credits_from_page(page):
    try:
        return normalize_credit_list(
            page.eval_on_selector_all(
                "li, dd, dt, div, p",
                """
                elements => {
                    const roleMap = {
                        "WRITER": "Writer",
                        "WRITERS": "Writer",
                        "ARTIST": "Artist",
                        "ARTISTS": "Artist",
                        "PENCILLER": "Penciller",
                        "PENCILLERS": "Penciller",
                        "PENCILER": "Penciller",
                        "PENCILERS": "Penciller",
                        "INKER": "Inker",
                        "INKERS": "Inker",
                        "COLORIST": "Colorist",
                        "COLORISTS": "Colorist",
                        "COLOURIST": "Colorist",
                        "COLOURISTS": "Colorist",
                        "LETTERER": "Letterer",
                        "LETTERERS": "Letterer",
                        "COVER ARTIST": "Cover Artist",
                        "COVER ARTISTS": "Cover Artist",
                        "EDITOR": "Editor",
                        "EDITORS": "Editor"
                    };

                    const skipNames = new Set([
                        "skip menu",
                        "log in",
                        "sign up",
                        "marvel unlimited",
                        "subscribe",
                        "news",
                        "comics",
                        "characters",
                        "games",
                        "movies",
                        "tv shows",
                        "videos",
                        "more",
                        "back to series",
                        "prev",
                        "next",
                        "see all",
                        "see variant covers",
                        "digital issue",
                        "read online"
                    ]);

                    function normalizeText(value) {
                        return String(value || "")
                            .replace(/\\u00a0/g, " ")
                            .replace(/[ \\t]+/g, " ")
                            .replace(/\\n[ \\t]+/g, "\\n")
                            .replace(/[ \\t]+\\n/g, "\\n")
                            .trim();
                    }

                    function normalizeLabel(value) {
                        return normalizeText(value)
                            .replace(/\\s*\\([^)]*\\)\\s*/g, " ")
                            .replace(/:.*$/, "")
                            .replace(/:$/, "")
                            .replace(/\\s+/g, " ")
                            .trim()
                            .toUpperCase();
                    }

                    function roleFromText(text) {
                        const lines = normalizeText(text)
                            .split(/\\n+/)
                            .map((line) => line.trim())
                            .filter(Boolean);

                        if (!lines.length) {
                            return null;
                        }

                        const firstLine = lines[0];
                        const label = normalizeLabel(firstLine);

                        return roleMap[label] || null;
                    }

                    function roleLabelCount(text) {
                        const lines = normalizeText(text)
                            .split(/\\n+/)
                            .map((line) => line.trim())
                            .filter(Boolean);
                        let count = 0;

                        for (const line of lines) {
                            if (roleFromText(line)) {
                                count += 1;
                            }
                        }

                        return count;
                    }

                    function isVisible(element) {
                        const style = window.getComputedStyle(element);

                        if (!style || style.display === "none" || style.visibility === "hidden") {
                            return false;
                        }

                        const rect = element.getBoundingClientRect();

                        return rect.width > 0 && rect.height > 0;
                    }

                    function cleanName(value) {
                        return normalizeText(value)
                            .replace(/^by\\s+/i, "")
                            .replace(/^[•\\-*]+\\s*/, "")
                            .replace(/\\s+/g, " ")
                            .replace(/^[,;:]+|[,;:]+$/g, "")
                            .trim();
                    }

                    function acceptableName(text, href) {
                        const name = cleanName(text);

                        if (!name) {
                            return false;
                        }

                        const key = name.toLowerCase();

                        if (skipNames.has(key)) {
                            return false;
                        }

                        if (/\\(\\d{4}/.test(name) || /#\\d/.test(name)) {
                            return false;
                        }

                        if (/^(published|writer|writers|artist|artists|penciller|pencillers|inker|inkers|colorist|colorists|letterer|letterers|cover artist|cover artists|editor|editors)$/i.test(name)) {
                            return false;
                        }

                        if (href && href.includes("/comics/issue/")) {
                            return false;
                        }

                        if (href && href.includes("/comics/series/")) {
                            return false;
                        }

                        return true;
                    }

                    const credits = [];

                    for (const element of elements) {
                        if (!isVisible(element)) {
                            continue;
                        }

                        const text = normalizeText(element.innerText || element.textContent || "");

                        if (!text || text.length > 600) {
                            continue;
                        }

                        const role = roleFromText(text);

                        if (!role) {
                            continue;
                        }

                        if (roleLabelCount(text) > 1) {
                            continue;
                        }

                        const links = Array.from(element.querySelectorAll("a"));
                        let names = links
                            .map((link) => ({
                                name: cleanName(link.innerText || link.textContent || ""),
                                href: link.href || ""
                            }))
                            .filter((item) => acceptableName(item.name, item.href))
                            .map((item) => item.name);

                        if (!names.length) {
                            const lines = text
                                .split(/\\n+/)
                                .map((line) => line.trim())
                                .filter(Boolean);
                            let inlineValue = "";

                            if (lines.length && lines[0].includes(":")) {
                                inlineValue = lines[0].split(":").slice(1).join(":").trim();
                            }

                            const fallbackParts = [];

                            if (inlineValue) {
                                fallbackParts.push(inlineValue);
                            }

                            for (const line of lines.slice(1)) {
                                if (!roleFromText(line)) {
                                    fallbackParts.push(line);
                                }
                            }

                            const fallbackText = fallbackParts.join(", ").trim();

                            if (fallbackText) {
                                names = [fallbackText];
                            }
                        }

                        for (const name of names) {
                            credits.push({
                                role,
                                name
                            });
                        }
                    }

                    return credits;
                }
                """,
            )
        )
    except Exception:
        return []


def normalize_credit_list(value):
    if not value:
        return []

    credits = []
    seen = set()

    for item in value:
        if not isinstance(item, dict):
            continue

        role = normalize_credit_role(item.get("role"))
        names = split_credit_names(item.get("name"))

        if not role or not names:
            continue

        for name in names:
            key = (role.casefold(), name.casefold())

            if key in seen:
                continue

            seen.add(key)
            credits.append(
                {
                    "role": role,
                    "name": name,
                }
            )

    return credits


def normalize_credit_role(value):
    value = clean_text(value)
    value = value.replace("_", " ")
    value = value.replace("-", " ")
    value = re.sub(r"\s+", " ", value).strip(" :;,.")
    value = re.sub(r"\s*\([^)]*\)\s*", " ", value).strip()
    key = value.casefold()

    role_aliases = {
        "writer": "Writer",
        "writers": "Writer",
        "artist": "Artist",
        "artists": "Artist",
        "penciler": "Penciller",
        "pencilers": "Penciller",
        "penciller": "Penciller",
        "pencillers": "Penciller",
        "inker": "Inker",
        "inkers": "Inker",
        "colorist": "Colorist",
        "colorists": "Colorist",
        "colourist": "Colorist",
        "colourists": "Colorist",
        "letterer": "Letterer",
        "letterers": "Letterer",
        "cover": "Cover Artist",
        "cover artist": "Cover Artist",
        "cover artists": "Cover Artist",
        "editor": "Editor",
        "editors": "Editor",
    }

    if key in role_aliases:
        return role_aliases[key]

    return value.title()


def split_credit_names(value):
    value = clean_text(value)

    if not value:
        return []

    value = value.replace("\n", ", ")
    value = insert_glued_credit_name_separators(value)
    value = re.sub(r"\s+and\s+", ", ", value, flags=re.IGNORECASE)
    value = re.sub(r"\s*&\s*", ", ", value)
    pieces = re.split(r"\s*,\s*|\s*;\s*", value)
    names = []

    for piece in pieces:
        name = clean_credit_name(piece)

        if not name:
            continue

        names.append(name)

    return names


def clean_credit_name(value):
    value = clean_text(value)
    value = re.sub(r"^by\s+", "", value, flags=re.IGNORECASE)
    value = re.sub(r"^[•\-*]+", "", value)
    value = value.strip(" :;,.")
    value = re.sub(r"\s+", " ", value)

    if not value:
        return ""

    skip_values = {
        "none",
        "n/a",
        "unknown",
        "writer",
        "writers",
        "artist",
        "artists",
        "penciller",
        "pencillers",
        "inker",
        "inkers",
        "colorist",
        "colorists",
        "letterer",
        "letterers",
        "cover artist",
        "cover artists",
        "editor",
        "editors",
    }

    if value.casefold() in skip_values:
        return ""

    return value


def insert_glued_credit_name_separators(value):
    value = clean_text(value)

    if not value:
        return ""

    result = []

    for index, character in enumerate(value):
        if index > 0 and should_insert_credit_name_separator(value, index):
            result.append(", ")

        result.append(character)

    return "".join(result)


def should_insert_credit_name_separator(value, index):
    previous_character = value[index - 1]
    current_character = value[index]
    next_character = value[index + 1] if index + 1 < len(value) else ""

    if not previous_character.islower():
        return False

    if not current_character.isupper():
        return False

    if next_character and not next_character.islower():
        return False

    current_word_start = index - 1

    while current_word_start >= 0 and value[current_word_start].isalpha():
        current_word_start -= 1

    current_word = value[current_word_start + 1:index]

    if len(current_word) < 2:
        return False

    next_word_end = index + 1

    while next_word_end < len(value) and value[next_word_end].isalpha():
        next_word_end += 1

    next_word = value[index:next_word_end]

    if len(next_word) < 2:
        return False

    return True


def looks_like_concatenated_credit_name(value):
    value = clean_text(value)

    if not value:
        return False

    if "," in value or ";" in value or "&" in value:
        return False

    return bool(re.search(r"[a-z][A-Z][a-z]", value))