#!/usr/bin/env python3
"""
Parse Praharaj Odia Bhashakosha raw markup → structured pretty JSON.

Source options (set INPUT):
  - a directory of .txt files
  - a single .txt file
  - a .zip of .txt files

Each source record is typically one line:
  RomanKey,<entry>…</entry>

Reads files line-by-line. Entries sorted by explicit Odia dictionary order.

Gloss / sense rules:
  - Free <p> blocks without <nmb> are ONE continuous gloss (Odia paragraphs
    joined; English joined) — not separate senses.
  - <nmb> → separate senses; number on or as ୧. ୨. …
  - Unnumbered paragraphs after a numbered sense attach to it (notes/continuations).
  - syn collects ALL be / d / or values.

    pip install beautifulsoup4 lxml
"""

from __future__ import annotations
import json, re, zipfile
from pathlib import Path
from bs4 import BeautifulSoup, Tag, NavigableString

INPUT = Path("./src")  # dir, .txt, or .zip
OUT_JSON = Path("./dist/praharaj_structured.json")
OUT_LOG = Path("./tmp/praharaj_parse_log.txt")

# ── Odia dictionary order ─────────────────────────────────────────────────────
_ODIA_ORDER: list[str] = [
    "ଅ", "ଆ", "ଇ", "ଈ", "ଉ", "ଊ",
    "ଋ", "ୠ", "ଌ", "ୡ",
    "ଏ", "ଐ", "ଓ", "ଔ",
    "କ", "ଖ", "ଗ", "ଘ", "ଙ",
    "ଚ", "ଛ", "ଜ", "ଝ", "ଞ",
    "ଟ", "ଠ", "ଡ", "ଢ", "ଣ",
    "ତ", "ଥ", "ଦ", "ଧ", "ନ",
    "ପ", "ଫ", "ବ", "ଭ", "ମ",
    "ଯ", "ୟ", "ର", "ଲ", "ଳ", "ୱ", "ଵ",
    "ଶ", "ଷ", "ସ", "ହ",
    "କ୍ଷ", "ଜ୍ଞ",
    "ା", "ି", "ୀ", "ୁ", "ୂ", "ୃ", "ୄ", "େ", "ୈ", "ୋ", "ୌ",
    "ଂ", "ଃ", "ଁ", "଼", "ଽ", "୍",
    "୦", "୧", "୨", "୩", "୪", "୫", "୬", "୭", "୮", "୯",
    "0", "1", "2", "3", "4", "5", "6", "7", "8", "9",
]
_CHAR_RANK: dict[str, int] = {ch: i + 1 for i, ch in enumerate(_ODIA_ORDER)}
_IGNORE = set(" \t\n\r\u200c\u200d\u00a0—–-.,;:!?\"'()[]{}<>/\\|@#$%^&*+=~`")
_UNKNOWN_BASE = len(_ODIA_ORDER) + 10
_ODIA_DIGITS = "୦୧୨୩୪୫୬୭୮୯"


def to_odia_num(n: int) -> str:
    if n < 0:
        return str(n)
    if n == 0:
        return "୦"
    s = ""
    while n:
        s = _ODIA_DIGITS[n % 10] + s
        n //= 10
    return s


def odia_sort_key(word: str) -> tuple:
    if not word:
        return (0,)
    key: list[int] = []
    i, n = 0, len(word)
    while i < n:
        if i + 3 <= n and word[i : i + 3] in ("କ୍ଷ", "ଜ୍ଞ"):
            key.append(_CHAR_RANK[word[i : i + 3]])
            i += 3
            continue
        ch = word[i]
        if ch in _IGNORE:
            i += 1
            continue
        if ch in _CHAR_RANK:
            key.append(_CHAR_RANK[ch])
        elif "\u0B00" <= ch <= "\u0B7F":
            key.append(_UNKNOWN_BASE + ord(ch))
        elif ch.isascii() and ch.isalpha():
            key.append(_UNKNOWN_BASE + 1000 + ord(ch.lower()))
        else:
            key.append(_UNKNOWN_BASE + 5000 + ord(ch))
        i += 1
    return tuple(key) if key else (0,)


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
    s = s.replace('","', ",")
    s = s.replace(',"', ",")
    s = s.replace('",', ",")
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


def _join_parts(parts: list[str]) -> str:
    return " ".join(p for p in parts if p)


def _append_field(item: dict, key: str, value: str) -> None:
    """Append text to an existing field (space-separated)."""
    if not value:
        return
    prev = item.get(key, "")
    item[key] = f"{prev} {value}".strip() if prev else value


def parse_sense(sense_tag) -> list[dict]:
    """
    - <nmb> → new sense; number prefixed on or as ୧. ୨. …
    - Unnumbered paragraphs AFTER a numbered sense attach to that sense
      (notes [ଦ୍ର—…], continuations of or/en) — not new sense items.
    - Unnumbered paragraphs BEFORE any nmb merge into one item.
    """
    senses: list[dict] = []
    current: dict | None = None
    pre_or: list[str] = []
    pre_en: list[str] = []
    pre_note: list[str] = []

    def flush_pre():
        nonlocal pre_or, pre_en, pre_note, current
        if not pre_or and not pre_en and not pre_note:
            return
        item: dict = {}
        or_t = _join_parts(pre_or)
        en_t = _join_parts(pre_en)
        note_t = _join_parts(pre_note)
        if or_t:
            item["or"] = or_t
        if en_t:
            item["en"] = en_t
        if note_t:
            item["note"] = note_t
        if item:
            senses.append(item)
            current = item
        pre_or, pre_en, pre_note = [], [], []

    for child in sense_tag.children:
        if not isinstance(child, Tag):
            continue
        if child.name.lower() == "verse":
            continue
        nmb = extract_nmb(child)
        or_t, en_t, note = split_or_en(child)
        if not or_t and not en_t and not note:
            continue

        if nmb is not None:
            flush_pre()
            if or_t:
                or_t = f"{to_odia_num(nmb)}. {or_t}"
            else:
                or_t = f"{to_odia_num(nmb)}."
            item = {}
            if or_t:
                item["or"] = or_t
            if en_t:
                item["en"] = en_t
            if note:
                item["note"] = note
            senses.append(item)
            current = item
        else:
            # After a numbered sense: attach; else accumulate pre-nmb prose
            if current is not None and not pre_or and not pre_en and not pre_note:
                if note and not or_t and not en_t:
                    _append_field(current, "note", note)
                elif note and not or_t:
                    _append_field(current, "note", note)
                    _append_field(current, "en", en_t)
                elif or_t.startswith("[") and or_t.endswith("]") and not en_t:
                    _append_field(current, "note", or_t.strip("[]"))
                else:
                    _append_field(current, "or", or_t)
                    _append_field(current, "en", en_t)
                    if note:
                        _append_field(current, "note", note)
            else:
                if or_t:
                    pre_or.append(or_t)
                if en_t:
                    pre_en.append(en_t)
                if note:
                    pre_note.append(note)

    flush_pre()
    return senses


def parse_gramgrp(gg: Tag) -> dict:
    out: dict = {}
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
        for v in sense.find_all("verse"):
            t = clean(text_of(v))
            if t:
                verses.append(t)
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


def collect_free_gloss(entry_tag: Tag) -> dict | None:
    """
    Free <p> without <nmb> → ONE continuous gloss.
    Multiple Odia paragraphs joined; English joined.
    """
    or_parts: list[str] = []
    en_parts: list[str] = []
    note_parts: list[str] = []

    for child in entry_tag.children:
        if not isinstance(child, Tag):
            continue
        name = child.name.lower()
        if name in ("hw", "tr", "syn", "gender", "gramgrp", "page", "sense", "verse"):
            continue
        if child.find("hw"):
            continue
        if child.find("nmb"):
            continue
        if name in ("p", "or"):
            or_t, en_t, note = split_or_en(child)
            if or_t:
                or_parts.append(or_t)
            if en_t:
                en_parts.append(en_t)
            if note:
                note_parts.append(note)

    or_t = _join_parts(or_parts)
    en_t = _join_parts(en_parts)
    note_t = _join_parts(note_parts)
    if not or_t and not en_t and not note_t:
        return None
    gloss: dict = {}
    if or_t:
        gloss["or"] = or_t
    if en_t:
        gloss["en"] = en_t
    if note_t:
        gloss["note"] = note_t
    return gloss


def parse_entry(entry_tag: Tag, index: int, roman: str = "") -> dict | None:
    hw_or = ""
    hw = entry_tag.find("hw")
    if hw:
        b = hw.find("b")
        hw_or = clean(text_of(b)) if b else first_or_text(hw)
    if not hw_or:
        b = entry_tag.find("b")
        if b:
            hw_or = clean(text_of(b))

    entry: dict = {"or": hw_or or ""}

    if roman:
        entry["roman"] = roman

    tr = entry_tag.find("tr")
    if tr:
        t = clean(text_of(tr))
        if t:
            entry["tr"] = t

    syn = entry_tag.find("syn")
    if syn:
        syn_obj: dict = {}
        # collect ALL be / d / or (source can interleave multiple groups)
        bes = [clean(text_of(x)) for x in syn.find_all("be") if clean(text_of(x))]
        ds = [clean(text_of(x)) for x in syn.find_all("d") if clean(text_of(x))]
        ors = [clean(text_of(o)) for o in syn.find_all("or") if clean(text_of(o))]
        if len(bes) == 1:
            syn_obj["be"] = bes[0]
        elif bes:
            syn_obj["be"] = bes
        if len(ds) == 1:
            syn_obj["d"] = ds[0]
        elif ds:
            syn_obj["d"] = ds
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

    alts = []
    for o in entry_tag.find_all("or"):
        parents = {p.name.lower() for p in o.parents if isinstance(p, Tag)}
        if parents & {"hw", "syn", "gender", "gramgrp", "sense", "verse", "nmb"}:
            continue
        if "p" in parents and o.parent is not entry_tag:
            t = clean(text_of(o))
            if not t or t == hw_or:
                continue
            if "ଅନ୍ୟରୂପ" in t or "ବିପରୀତ" in t or len(t) < 40:
                curly = o.find("curly")
                if curly:
                    ct = clean(text_of(curly))
                    if ct:
                        t = f"{t} ({ct})"
                alts.append(t)
            continue
        t = clean(text_of(o))
        if t and t != hw_or and len(t) < 60:
            curly = o.find("curly")
            if curly:
                ct = clean(text_of(curly))
                if ct:
                    t = f"{t} ({ct})"
            alts.append(t)
    if alts:
        entry["or_alt"] = alts[0] if len(alts) == 1 else alts

    gloss = collect_free_gloss(entry_tag)
    if gloss:
        entry["gloss"] = gloss

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

    if (
        not hw_or
        and not entry.get("tr")
        and not entry.get("gramgrp")
        and not entry.get("sense")
        and not entry.get("gloss")
    ):
        return None

    entry["_index"] = index
    return entry


_LINE_ENTRY_RE = re.compile(
    r'^\s*"?([^"<\n]{0,120}?)"?\s*,\s*(<entry\s*>.*)$',
    re.IGNORECASE,
)
_ENTRY_ONLY_RE = re.compile(r"(<entry\s*>.*)", re.IGNORECASE)


def iter_source_lines(src: Path):
    if src.is_file() and src.suffix.lower() == ".zip":
        with zipfile.ZipFile(src, "r") as zf:
            names = sorted(
                n for n in zf.namelist()
                if n.lower().endswith(".txt") and not n.endswith("/")
            )
            for name in names:
                with zf.open(name) as fh:
                    for raw in fh:
                        yield Path(name).name, raw.decode("utf-8", errors="replace")
        return
    if src.is_file() and src.suffix.lower() == ".txt":
        with src.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                yield src.name, line
        return
    if src.is_dir():
        files = sorted(src.glob("**/*.txt"))
        if not files:
            raise FileNotFoundError(f"No .txt files found under {src}")
        for f in files:
            with f.open("r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    yield f.name, line
        return
    raise FileNotFoundError(f"Input not found: {src}")


def iter_entries_line_by_line(src: Path):
    buf_file = None
    buf_roman = ""
    buf_html: list[str] = []
    in_entry = False

    def flush():
        nonlocal buf_file, buf_roman, buf_html, in_entry
        if not buf_html:
            return None
        result = (buf_file or "", buf_roman, "".join(buf_html))
        buf_file, buf_roman, buf_html, in_entry = None, "", [], False
        return result

    for name, line in iter_source_lines(src):
        if not in_entry:
            m = _LINE_ENTRY_RE.match(line)
            if m:
                roman = m.group(1).strip().strip('"').strip()
                rest = m.group(2)
                if "</entry>" in rest.lower():
                    yield name, roman, rest
                else:
                    buf_file, buf_roman, buf_html, in_entry = name, roman, [rest], True
                continue
            m2 = _ENTRY_ONLY_RE.search(line)
            if m2:
                rest = m2.group(1)
                if "</entry>" in rest.lower():
                    yield name, "", rest
                else:
                    buf_file, buf_roman, buf_html, in_entry = name, "", [rest], True
            continue
        buf_html.append(line)
        if "</entry>" in line.lower():
            item = flush()
            if item:
                yield item
    item = flush()
    if item:
        yield item


def main():
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_LOG.parent.mkdir(parents=True, exist_ok=True)

    log = [f"Input: {INPUT}"]
    print(f"Reading from {INPUT} (line by line)…", flush=True)

    global_index = 0
    entries: list[dict] = []
    skipped: list[dict] = []
    file_counts: dict[str, int] = {}

    for name, roman, html in iter_entries_line_by_line(INPUT):
        file_counts[name] = file_counts.get(name, 0) + 1
        if (global_index + 1) % 5000 == 0:
            print(
                f"    {global_index + 1} processed, "
                f"written={len(entries)} skipped={len(skipped)}",
                flush=True,
            )
        try:
            soup = BeautifulSoup(html, "lxml")
            et = soup.find("entry")
            if et is None:
                skipped.append({
                    "file": name, "global_index": global_index,
                    "roman": roman, "reason": "no_entry_tag",
                })
                global_index += 1
                continue
            obj = parse_entry(et, global_index, roman=roman)
            if obj is None:
                skipped.append({
                    "file": name, "global_index": global_index,
                    "roman": roman, "reason": "empty",
                    "preview": clean(text_of(et))[:80],
                })
                global_index += 1
                continue
            obj["_source"] = name
            entries.append(obj)
            global_index += 1
        except Exception as e:
            skipped.append({
                "file": name, "global_index": global_index,
                "roman": roman, "reason": f"{type(e).__name__}:{e}",
            })
            global_index += 1

    for fname, cnt in sorted(file_counts.items()):
        log.append(f"{fname}: entries={cnt}")
        print(f"  {fname}: {cnt} entries", flush=True)

    print("Sorting by Odia dictionary order…", flush=True)
    entries.sort(key=lambda e: odia_sort_key(e.get("or") or ""))
    for i, e in enumerate(entries):
        e["_index"] = i

    print("Writing pretty JSON…", flush=True)
    with OUT_JSON.open("w", encoding="utf-8") as jf:
        json.dump(entries, jf, ensure_ascii=False, indent=2)

    log += [
        "", "=== SUMMARY ===",
        f"Files processed: {len(file_counts)}",
        f"Written: {len(entries)}",
        f"Skipped: {len(skipped)}",
        "", "=== SKIPPED (first 40) ===",
    ]
    for s in skipped[:40]:
        log.append(json.dumps(s, ensure_ascii=False))
    if len(skipped) > 40:
        log.append(f"... +{len(skipped) - 40} more")

    OUT_LOG.write_text("\n".join(log), encoding="utf-8")
    print(f"Done written={len(entries)} skipped={len(skipped)}", flush=True)
    print(f"JSON={OUT_JSON}\nLOG={OUT_LOG}", flush=True)


if __name__ == "__main__":
    main()
