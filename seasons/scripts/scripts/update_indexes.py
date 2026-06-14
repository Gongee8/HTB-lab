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
        m = re.search(rf"^- {re.escape(label)}:\s*(.+)$", text, re.M)
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

    season_title = season_dir.name.replace("-", " ").title()
    content = f"# Hack The Box {season_title}\n\n"
    content += "| Machine | Difficulty | OS | Initial Access | Privilege Escalation | Write-up |\n"
    content += "|---|---:|---|---|---|---|\n"
    content += "\n".join(rows) + "\n"

    (season_dir / "README.md").write_text(content, encoding="utf-8")
    return len(rows)

def update_root(season_counts):
    root_readme = ROOT / "README.md"
    text = root_readme.read_text(encoding="utf-8")

    table = "## Seasons\n\n"
    table += "| Season | Machines | Status |\n"
    table += "|---|---:|---|\n"

    for season, count in sorted(season_counts.items()):
        name = season.replace("-", " ").title()
        table += f"| [{name}](seasons/{season}/) | {count} | In progress |\n"

    if "## Seasons" in text:
        text = re.sub(
            r"## Seasons\n\n\| Season \| Machines \| Status \|[\s\S]*?(?=\n## |\Z)",
            table.rstrip(),
            text,
        )
    else:
        text = text.rstrip() + "\n\n" + table

    root_readme.write_text(text.rstrip() + "\n", encoding="utf-8")

def main():
    season_counts = {}

    for season_dir in sorted(p for p in SEASONS.iterdir() if p.is_dir()):
        season_counts[season_dir.name] = update_season(season_dir)

    update_root(season_counts)

if __name__ == "__main__":
    main()