from __future__ import annotations

import re


TRANSLATION_MAP = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u2022": "-",
    }
)


def normalize_text(text: str) -> str:
    value = text.translate(TRANSLATION_MAP)
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    value = "\n".join(line.strip() for line in value.split("\n"))
    return value.strip()
