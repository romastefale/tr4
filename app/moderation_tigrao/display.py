from __future__ import annotations


def group_display_name(title: str | None, fallback: str = "grupo selecionado") -> str:
    clean = str(title or "").strip()
    if not clean:
        return fallback
    if clean.lstrip("-").isdigit():
        return fallback
    return clean


def disambiguate_group_labels(groups: list[dict]) -> list[dict]:
    counts: dict[str, int] = {}
    result: list[dict] = []
    for group in groups:
        base = group_display_name(group.get("title"), "Grupo")
        counts[base] = counts.get(base, 0) + 1
        label = base if counts[base] == 1 else f"{base} #{counts[base]}"
        row = dict(group)
        row["display_label"] = label
        result.append(row)
    return result
