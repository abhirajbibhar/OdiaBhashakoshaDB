#!/usr/bin/env python3
"""
Parse Praharaj Odia Bhashakosha raw markup → structured JSONL + SQLite.

Skips presentation tags: p, b
Skips noise: nm, ramgrp, image_p.7893, br, div, td, table, sub, sup, c, letter, v, img, image

Hierarchy:
  entry
    hw.or, tr, syn{be,d,or}, gender, or_alt
    gramgrp[] { or (POS), sense[] {nmb, or, en, note}, verse }
    
    pip install beautifulsoup4 lxml
"""

from __future__ import annotations
import json, re, sqlite3, shutil
from pathlib import Path
from bs4 import BeautifulSoup, Tag, NavigableString

INPUT = Path("./praharaj_app_content_selected.txt")
OUT_JSONL = Path("./dist/praharaj_structured.json")
OUT_DB = Path("./tmp/praharaj_structured.db")          # /tmp avoids some FS issues
OUT_DB_FINAL = Path("./dist/praharaj_structured.db")
OUT_LOG = Path("./tmp/praharaj_parse_log.txt")

SKIP = {
    "p", "b", "br", "div", "td", "table", "sub", "sup",
    "c", "letter", "v", "nm", "ramgrp", "image_p.7893", "image", "img",
}

def text_of(node) -> str:
    if node is None:
        return ""
    if isinstance(node, NavigableString):
        return str(node)
    if not isinstance(node, Tag):
        return ""
    return "".join(text_of(c) for c in node.children)

def clean(s: str) -> str:
    if not s:
        return ""
    s = s.replace("\xa0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n+", "\n", s)
    return s.strip(" \t\n—–-")

def first_or_text(node) -> str:
    if node is None:
        return ""
    for o in node.find_all("or"):
        t = clean(text_of(o))
        t = re.sub(r"^\d+\s*[।.]\s*", "", t)
        if t:
            return t
    return clean(text_of(node))

def extract_nmb(node):
    n = node.find("nmb")
    if not n:
        return None
    try:
        return int(clean(text_of(n)))
    except ValueError:
        return None

def split_or_en(block) -> tuple[str, str, str]:
    """Split a sense block into (odia, english, note)."""
    or_el = block.find("or")
    or_text = ""
    if or_el:
        or_text = clean(text_of(or_el))
        or_text = re.sub(r"^\d+\s*[।.]\s*", "", or_text)
    full = clean(text_of(block))
    en = full
    if or_text and or_text in full:
        en = full.replace(or_text, "", 1)
    en = clean(en)
    en = re.sub(r"^[—–\-–\s]*\d+\s*[।.)]\s*", "", en)
    en = clean(en)
    note = ""
    m = re.search(r"\[(ଦ୍ର[^\]]*)\]", or_text)
    if m:
        note = m.group(1)
        or_text = clean(or_text.replace(m.group(0), ""))
    if not note:
        m2 = re.search(r"\[(ଦ୍ର[^\]]*)\]", en)
        if m2:
            note = m2.group(1)
            en = clean(en.replace(m2.group(0), ""))
    return or_text, en, note

def parse_sense(sense_tag) -> list[dict]:
    senses = []
    for child in sense_tag.children:
        if not isinstance(child, Tag):
            continue
        if child.name.lower() == "verse":
            continue
        nmb = extract_nmb(child)
        or_t, en_t, note = split_or_en(child)
        if not or_t and not en_t:
            continue
        item = {}
        if nmb is not None:
            item["nmb"] = nmb
        if or_t:
            item["or"] = or_t
        if en_t:
            item["en"] = en_t
        if note:
            item["note"] = note
        senses.append(item)
    return senses

def parse_verse(parent) -> str | None:
    v = parent.find("verse")
    if not v:
        return None
    t = clean(text_of(v))
    return t or None

def parse_gramgrp(gg: Tag) -> dict:
    out = {}
    pos_or = ""
    for child in gg.children:
        if not isinstance(child, Tag):
            continue
        if child.name.lower() == "sense":
            break
        if child.name.lower() in ("p", "or"):
            t = first_or_text(child)
            if t:
                pos_or = t
                break
    if pos_or:
        out["or"] = pos_or

    senses, verses = [], []
    for sense in gg.find_all("sense", recursive=False):
        senses.extend(parse_sense(sense))
        vs = parse_verse(sense)
        if vs:
            verses.append(vs)
    for v in gg.find_all("verse", recursive=False):
        t = clean(text_of(v))
        if t:
            verses.append(t)

    if senses:
        out["sense"] = senses
    if len(verses) == 1:
        out["verse"] = verses[0]
    elif verses:
        out["verse"] = verses
    return out

def parse_entry(entry_tag: Tag, index: int) -> dict | None:
    hw_or = ""
    hw = entry_tag.find("hw")
    if hw:
        b = hw.find("b")
        hw_or = clean(text_of(b)) if b else first_or_text(hw)
    if not hw_or:
        b = entry_tag.find("b")
        if b:
            hw_or = clean(text_of(b))
    if not hw_or:
        return None  # skip – no headword

    entry: dict = {"hw": {"or": hw_or}}

    tr = entry_tag.find("tr")
    if tr:
        t = clean(text_of(tr))
        if t:
            entry["tr"] = t

    syn = entry_tag.find("syn")
    if syn:
        syn_obj = {}
        be, d = syn.find("be"), syn.find("d")
        if be:
            syn_obj["be"] = clean(text_of(be))
        if d:
            syn_obj["d"] = clean(text_of(d))
        ors = [clean(text_of(o)) for o in syn.find_all("or") if clean(text_of(o))]
        if len(ors) == 1:
            syn_obj["or"] = ors[0]
        elif ors:
            syn_obj["or"] = ors
        if syn_obj:
            entry["syn"] = syn_obj

    gender = entry_tag.find("gender")
    if gender:
        g = first_or_text(gender)
        if g:
            entry["gender"] = g

    # alternate forms (sibling <or> not under hw/syn/gramgrp/…)
    alts = []
    for o in entry_tag.find_all("or"):
        parents = {p.name.lower() for p in o.parents if isinstance(p, Tag)}
        if parents & {"hw", "syn", "gender", "gramgrp", "sense", "verse", "nmb"}:
            continue
        t = clean(text_of(o))
        if t and t != hw_or and len(t) < 100:
            curly = o.find("curly")
            if curly:
                ct = clean(text_of(curly))
                if ct:
                    t = f"{t} ({ct})"
            alts.append(t)
    if alts:
        entry["or_alt"] = alts[0] if len(alts) == 1 else alts

    gramgrps = entry_tag.find_all("gramgrp")
    if gramgrps:
        parsed = [g for g in (parse_gramgrp(x) for x in gramgrps) if g]
        if parsed:
            entry["gramgrp"] = parsed[0]
            for i, g in enumerate(parsed[1:], start=2):
                entry[f"gramgrp{i}"] = g
    else:
        bare = []
        for sense in entry_tag.find_all("sense"):
            bare.extend(parse_sense(sense))
        if bare:
            entry["sense"] = bare

    page = entry_tag.find("page")
    if page:
        entry["page"] = clean(text_of(page)) or True

    entry["_index"] = index
    return entry

def main():
    log = [f"Input: {INPUT} size={INPUT.stat().st_size}"]
    print("Reading…", flush=True)
    content = INPUT.read_text(encoding="utf-8", errors="replace")
    print("Splitting…", flush=True)
    raw = re.findall(r"<entry\s*>.*?</entry>", content, re.DOTALL | re.IGNORECASE)
    total = len(raw)
    log.append(f"entries={total}")
    print(f"Found {total}", flush=True)
    del content

    if OUT_DB.exists():
        OUT_DB.unlink()
    conn = sqlite3.connect(str(OUT_DB))
    cur = conn.cursor()
    cur.executescript("""
    CREATE TABLE entries (
      id INTEGER PRIMARY KEY, src_index INTEGER, hw_or TEXT NOT NULL,
      tr TEXT, gender TEXT, or_alt TEXT, syn_be TEXT, syn_d TEXT, syn_or TEXT,
      page TEXT, raw_json TEXT NOT NULL);
    CREATE TABLE gramgrps (
      id INTEGER PRIMARY KEY, entry_id INTEGER, seq INTEGER,
      pos_or TEXT, verse TEXT);
    CREATE TABLE senses (
      id INTEGER PRIMARY KEY, gramgrp_id INTEGER, entry_id INTEGER,
      nmb INTEGER, or_text TEXT, en_text TEXT, note TEXT);
    CREATE INDEX idx_hw ON entries(hw_or);
    CREATE INDEX idx_tr ON entries(tr);
    """)

    skipped, written = [], 0
    with OUT_JSONL.open("w", encoding="utf-8", buffering=1) as jf:
        for i, html in enumerate(raw):
            if (i + 1) % 5000 == 0:
                print(f"  {i+1}/{total} written={written} skipped={len(skipped)}", flush=True)
                conn.commit()
            try:
                soup = BeautifulSoup(html, "lxml")
                et = soup.find("entry")
                if et is None:
                    skipped.append({"index": i, "reason": "no_entry_tag"})
                    continue
                obj = parse_entry(et, i)
                if obj is None:
                    skipped.append({
                        "index": i, "reason": "no_headword",
                        "preview": clean(text_of(et))[:80],
                    })
                    continue

                jf.write(json.dumps(obj, ensure_ascii=False) + "\n")

                syn = obj.get("syn") or {}
                or_alt = obj.get("or_alt")
                if isinstance(or_alt, list):
                    or_alt = " | ".join(or_alt)
                syn_or = syn.get("or")
                if isinstance(syn_or, list):
                    syn_or = " | ".join(syn_or)

                cur.execute(
                    """INSERT INTO entries
                       (src_index,hw_or,tr,gender,or_alt,syn_be,syn_d,syn_or,page,raw_json)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (
                        obj["_index"], obj["hw"]["or"], obj.get("tr"),
                        obj.get("gender"), or_alt,
                        syn.get("be"), syn.get("d"), syn_or,
                        str(obj["page"]) if "page" in obj else None,
                        json.dumps(obj, ensure_ascii=False),
                    ),
                )
                eid = cur.lastrowid

                ggs = []
                if "gramgrp" in obj:
                    ggs.append(obj["gramgrp"])
                k = 2
                while f"gramgrp{k}" in obj:
                    ggs.append(obj[f"gramgrp{k}"])
                    k += 1

                if ggs:
                    for seq, gg in enumerate(ggs):
                        verse = gg.get("verse")
                        if isinstance(verse, list):
                            verse = "\n".join(verse)
                        cur.execute(
                            "INSERT INTO gramgrps (entry_id,seq,pos_or,verse) VALUES (?,?,?,?)",
                            (eid, seq, gg.get("or"), verse),
                        )
                        gid = cur.lastrowid
                        for s in gg.get("sense") or []:
                            cur.execute(
                                """INSERT INTO senses
                                   (gramgrp_id,entry_id,nmb,or_text,en_text,note)
                                   VALUES (?,?,?,?,?,?)""",
                                (gid, eid, s.get("nmb"), s.get("or"),
                                 s.get("en"), s.get("note")),
                            )
                elif "sense" in obj:
                    for s in obj["sense"]:
                        cur.execute(
                            """INSERT INTO senses
                               (gramgrp_id,entry_id,nmb,or_text,en_text,note)
                               VALUES (NULL,?,?,?,?,?)""",
                            (eid, s.get("nmb"), s.get("or"),
                             s.get("en"), s.get("note")),
                        )
                written += 1
            except Exception as e:
                skipped.append({"index": i, "reason": f"{type(e).__name__}:{e}"})

    conn.commit()
    conn.close()

    try:
        shutil.copy2(OUT_DB, OUT_DB_FINAL)
        log.append(f"DB copied → {OUT_DB_FINAL}")
    except Exception as e:
        log.append(f"DB copy failed ({e}); kept at {OUT_DB}")

    log += [
        "", "=== SUMMARY ===",
        f"Written: {written}", f"Skipped: {len(skipped)}",
        "", "=== SKIPPED (first 40) ===",
    ]
    for s in skipped[:40]:
        log.append(json.dumps(s, ensure_ascii=False))
    if len(skipped) > 40:
        log.append(f"... +{len(skipped)-40} more")
    OUT_LOG.write_text("\n".join(log), encoding="utf-8")

    print(f"Done written={written} skipped={len(skipped)}", flush=True)
    print(f"JSONL={OUT_JSONL}\nDB={OUT_DB_FINAL}\nLOG={OUT_LOG}", flush=True)

if __name__ == "__main__":
    main()