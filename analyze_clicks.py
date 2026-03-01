import json
import sys
import io

out = open(r"d:\Telegram_agent\click_analysis.txt", "w", encoding="utf-8")

with open(r"d:\Telegram_agent\click_log.jsonl", "r", encoding="utf-8") as f:
    entries = [json.loads(line) for line in f if line.strip()]

def p(s=""):
    out.write(s + "\n")

p(f"Total clicks: {len(entries)}")
in_panel = sum(1 for e in entries if e.get("panelContext") == "inside_chat_panel")
p(f"Inside chat panel: {in_panel}")
p(f"Outside chat panel: {len(entries) - in_panel}")
p()

for i, entry in enumerate(entries):
    t = entry.get("target", {})
    tag = t.get("tag", "?")
    cls = ".".join(t.get("classes", [])[:3]) or "(none)"
    text = (t.get("text", "") or "")[:70].replace("\n", " ").strip()
    ctx = entry.get("panelContext", "?")
    icon = "G" if ctx == "inside_chat_panel" else "R"

    ancestors = entry.get("ancestors", [])
    meaningful = []
    for a in ancestors[:8]:
        acls = a.get("classes", [])
        if acls and not all(c.startswith("[") for c in acls):
            short_cls = [c for c in acls if not c.startswith("[")][:2]
            if short_cls:
                meaningful.append(f"{a['tag']}.{'.'.join(short_cls)}")
    
    p(f"[{icon}] #{i+1}: <{tag}> .{cls}")
    p(f"    text: \"{text[:60]}\"")
    if meaningful:
        p(f"    path: {' > '.join(meaningful[:5])}")
    
    sibs = entry.get("siblingContext", {})
    if sibs:
        total = sibs.get("totalSiblings", 0)
        stags = [s.get("tag", "?") for s in sibs.get("siblingTags", [])]
        p(f"    siblings: {total} [{', '.join(stags[:5])}]")
    p()

out.close()
print("Done - wrote click_analysis.txt")
