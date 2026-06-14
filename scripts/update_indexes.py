from pathlib import Path
import re

ROOT = Path(".")
SEASONS = ROOT / "seasons"

def read_meta(readme):
    text = readme.read_text(encoding="utf-8")
    title = re.search(r"^#\s+HTB\s+(.+)$", text, re.M)

    meta = {
        "name": title.group(1).strip() if title else readme.parent.name.title(),
        "difficulty": "TBD",
        "os": "TBD",
        "initial": "TBD",
        "privesc": "TBD",
    }

    fields = {
        "Difficulty": "difficulty",
        "OS": "os",
        "Initial Access": "initial",
        "Privilege Escalation": "privesc",
    }

    for label, key in fields.items():
        m = re.search(rf"^-\s+{re.escape(label)}:\s*(.+)$", text, re.M)
        if m:
            meta[key] = m.group(1).strip()

    return meta

def update_season(season_dir):
    rows = []

    for machine_dir in sorted(p for p in season_dir.iterdir() if p.is_dir()):
        readme = machine_dir / "README.md"
        if not readme.exists():
            continue

        meta = read_meta(readme)
        rows.append(
            f"| {meta['name']} | {meta['difficulty']} | {meta['os']} | "
            f"{meta['initial']} | {meta['privesc']} | [Read]({machine_dir.name}/) |"
        )

    if not rows:
        return 0

    season_name = season_dir.name.replace("-", " ").title()

    content = f"""# Hack The Box {season_name}

| Machine | Difficulty | OS | Initial Access | Privilege Escalation | Write-up |
|---|:---:|---|---|---|---|
{chr(10).join(rows)}
"""

    (season_dir / "README.md").write_text(content, encoding="utf-8")
    return len(rows)

def update_root(counts):
    readme = ROOT / "README.md"
    text = readme.read_text(encoding="utf-8") if readme.exists() else "# HTB Lab\n\n"

    table = [
        "| Season | Machines | Status |",
        "|---|---:|---|",
    ]

    for season_dir in sorted(counts):
        number = season_dir.name.split("-")[-1]
        table.append(
            f"| [Season {number}](seasons/{season_dir.name}/) | {counts[season_dir]} | In progress |"
        )

    replacement = "## Seasons\n\n" + "\n".join(table)

    if re.search(r"## Seasons\n\n(?:\|.*\n?)+", text):
        text = re.sub(r"## Seasons\n\n(?:\|.*\n?)+", replacement, text)
    else:
        text = text.rstrip() + "\n\n" + replacement + "\n"

    readme.write_text(text, encoding="utf-8")

def main():
    counts = {}

    for season_dir in sorted(p for p in SEASONS.iterdir() if p.is_dir()):
        count = update_season(season_dir)
        if count:
            counts[season_dir] = count

    update_root(counts)

if __name__ == "__main__":
    main()