"""Разчита текстовете на решенията на КЗЗ и прави регистъра.

-> data/register.csv         цялата страна: по един ред за всеки имот във всяка точка на решение
-> data/register_sofia.csv   само Столична община
-> data/decisions.csv        по един ред на решение (номер, дата, брой точки, линк)
-> out/report.json           статистика и точки, които не са разчетени

Не извлича собствениците (нито имена, нито инициали).
"""
import csv
import json
import os
import re
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(ROOT, "out")

MONTHS = {m: i + 1 for i, m in enumerate(
    ["януари", "февруари", "март", "април", "май", "юни", "юли", "август", "септември", "октомври", "ноември", "декември"])}
CATEGORIES = ["първа", "втора", "трета", "четвърта", "пета", "шеста", "седма", "осма", "девета", "десета"]

ID_RE = re.compile(r"(?<![\d.])(\d{5})\s*\.\s*(\d{1,5})\s*\.\s*(\d{1,5})(?:\s*\.\s*(\d{1,5}))?(?![\d])")
ROMAN_LINE = re.compile(r"^\s*([IVXІХ]{1,6})\s*\.\s+(.*)$")
ITEM_LINE = re.compile(r"^\s*(\d{1,3})\s*\.\s+(.*)$")


def norm(s):
    s = s.replace(" ", " ").replace("\t", " ")
    return re.sub(r"[ ]{2,}", " ", s).strip()


# ---------------------------------------------------------------- decision header
def parse_header(text, fname):
    head = text[:3000]
    num = None
    m = re.search(r"№\s*КЗЗ\s*[–—-]?\s*(\d{1,3})", head) or re.search(r"Протокол\s*№\s*(\d{1,3})", head)
    if m:
        num = int(m.group(1))
    date = None
    m = re.search(r"от\s+(\d{1,2})\s+(" + "|".join(MONTHS) + r")\s+(\d{4})", head, re.I)
    if m:
        date = f"{m.group(3)}-{MONTHS[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"
    else:
        m = re.search(r"от\s+(\d{1,2})\.(\d{1,2})\.(\d{4})", head)
        if m:
            date = f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    if num is None:  # от името на файла: reshenie__kzz-11_ot_..., reshenie-19-2012-up.doc
        m = re.search(r"kzz-?_?(\d{1,3})", fname) or re.search(r"reshenie-(\d{1,3})-\d{4}", fname)
        if m:
            num = int(m.group(1))
    if date is None:
        m = re.search(r"(\d{4})", re.sub(r"filer_public/\d{4}", "", fname))
        date = m.group(1) if m else None
    return num, date


# ---------------------------------------------------------------- items
def split_items(text):
    """-> [(section_roman, section_text, item_no, item_text)]"""
    lines = [norm(l) for l in text.replace("\r", "").split("\n")]
    out, sec, sec_txt, cur = [], None, "", None
    started = False
    for l in lines:
        if not l:
            continue
        if re.match(r"^Р\s*Е\s*Ш\s*И\s*:?$", l) or "Р Е Ш И" in l:
            started = True
            continue
        rm = ROMAN_LINE.match(l)
        if rm and (started or "основание" in l or "Променя" in l):
            if cur:
                out.append(cur)
                cur = None
            sec, sec_txt, started = rm.group(1), rm.group(2), True
            continue
        im = ITEM_LINE.match(l)
        if im and started:
            if cur:
                out.append(cur)
            cur = [sec, sec_txt, int(im.group(1)), im.group(2)]
            continue
        if cur:
            if re.match(r"^(Решението подлежи на обжалване|ПРЕДСЕДАТЕЛ|СЕКРЕТАР|Председател)", l):
                out.append(cur)
                cur = None
                continue
            cur[3] += "\n" + l
    if cur:
        out.append(cur)
    return [tuple(x) for x in out]


ACTIONS = [
    (r"^Не\s+(?:разрешава|утвърждава|променя|дава)|^Отказва", "отказ"),
    (r"^Утвърждава\s+площадка\s+и\s+трасе", "утвърждаване на площадка и трасе"),
    (r"^Утвърждава\s+площадк", "утвърждаване на площадка"),
    (r"^Утвърждава\s+трасе", "утвърждаване на трасе"),
    (r"^(?:Променя\s+предназначението|На\s+[\d\s.,]+\s*кв\.?\s*м)", "промяна на предназначението"),
    (r"^Разрешава\s+временно\s+ползване", "временно ползване"),
    (r"^Изменя", "изменение на решение"),
    (r"^Отменя", "отмяна на решение"),
    (r"^Потвърждава", "потвърждаване на решение"),
    (r"^Отлага|ще се произнесе", "отлагане"),
    (r"^Включва", "включване в урбанизирана територия"),
    (r"^Прекратява", "прекратяване"),
]


def action_of(item, section_text):
    first = item.split("\n", 1)[0]
    for pat, name in ACTIONS:
        if re.search(pat, first, re.I):
            if name == "промяна на предназначението" and re.match(r"^На\s", first):
                # точка само с площ: действието е в заглавието на раздела
                for p2, n2 in ACTIONS:
                    if n2 != "промяна на предназначението" and re.search(p2.lstrip("^"), section_text, re.I):
                        return n2
            return name
    for pat, name in ACTIONS:
        if re.search(pat.lstrip("^"), section_text, re.I):
            return name
    if re.search(r"променя предназначението", section_text, re.I):
        return "промяна на предназначението"
    return "друго"


def first_area(t):
    m = re.search(r"(\d{1,3}(?:[  ]\d{3})+|\d+)(?:[.,](\d+))?\s*кв\.?\s*м", t)
    if not m:
        return None
    whole = m.group(1).replace(" ", "").replace(" ", "")
    return float(whole + ("." + m.group(2) if m.group(2) else ""))


def field(pat, t, flags=re.I):
    m = re.search(pat, t, flags)
    return norm(m.group(1)).strip(" ,.;") if m else ""


OBJ_STOP = re.compile(
    r"(?:,\s*(?:в\s+)?част(?:и)?\s+от\s+поземлен|,\s*поземлен[и]?\s+имот|,\s*(?:в\s+)?землище|,\s*с\s+кое?то\s+се\s+засяга"
    r"|,\s*с\s+която\s+се\s+засяга|,\s*както\s+следва|,\s*при\s+граници|,\s*местност|\s+по\s+КККР|,\s*имот\s*№"
    r"|,\s*с\s+площ|,\s*собственост|\n)", re.I)


def parse_object(t):
    m = re.search(r"(?:обект|нуждите на обект)\s*:?\s*", t, re.I)
    if not m:
        return ""
    rest = t[m.end():]
    stop = OBJ_STOP.search(rest)
    s = norm(rest[:stop.start()] if stop else rest[:300])
    s = s.strip(" ,")
    s = re.sub(r'^[„"“]\s*', "", s)
    s = re.sub(r'\s*[“"”]+$', "", s)
    return s


PLAN_CODES = r"(?:Ч?И?ПРЗ|Ч?И?ПЗ|ПП|Ч?И?ПР|И?ПУР|ПЗР|ПРП|ЧЗРП|ЧЗРКП)"
PUP_RE = re.compile(r"\b(С?ПУП)\s*[–—-]?\s*(" + PLAN_CODES + r"(?:\s*(?:и|,)\s*(?:С?ПУП\s*[–—-]?\s*)?" + PLAN_CODES + r")*)\b")


def parse_pup(t):
    """'влязъл в сила ПУП – ПРЗ и ПП' -> 'ПУП-ПРЗ, ПУП-ПП'; 'СПУП – ПЗ' -> 'СПУП-ПЗ'."""
    out = []
    for m in PUP_RE.finditer(t):
        kind = m.group(1)
        for code in re.findall(PLAN_CODES, m.group(2)):
            v = f"{kind}-{code}"
            if v not in out:
                out.append(v)
    return ", ".join(out)


def project_ids(t):
    out = []
    for m in re.finditer(r"проект(?:ен|ни)\s+идентификатор[и]?\s*([^)/]*)", t, re.I):
        out += [i for i in find_ids(m.group(1))]
    return list(dict.fromkeys(out))


def find_ids(t):
    out = []
    for m in ID_RE.finditer(t or ""):
        cid = ".".join(g for g in m.groups() if g)
        if cid not in out:
            out.append(cid)
    return out


def parse_item(item, section_text):
    t = norm(item.replace("\n", " "))
    proj = project_ids(t)
    ids = [i for i in find_ids(t) if i not in proj]
    # махни идентификатори от препратки към други обекти в името на обекта ("... в поземлен имот с идентификатор X по КККР")
    obj = parse_object(t)
    obj_ids = set(find_ids(obj))
    main_ids = [i for i in ids if i not in obj_ids] or ids
    cat = ""
    m = re.search(r"\b(" + "|".join(CATEGORIES) + r")\s+категория", t, re.I)
    if m:
        cat = m.group(1).lower()
    irr = ""
    if re.search(r"\bнеполивна\b", t, re.I):
        irr = "неполивна"
    elif re.search(r"\bполивна\b", t, re.I):
        irr = "поливна"
    settle = field(r"по\s+(?:КККР|КВС|ПНИ|кадастрална(?:та)?\s+карта|плана)\s+(?:на|за)\s+((?:гр|с)\.\s*[^,;(]+)", t) or \
        field(r"землище(?:то)?\s+на\s+((?:гр|с)\.\s*[^,;(]+)", t)
    municipality = "Столична" if re.search(r"Столична\s+община|община\s+Столична|община\s+София\b", t, re.I) else \
        field(r"\bобщина\s+([А-Я][^,;.()]+)", t, 0)
    return {
        "action": action_of(item, section_text),
        "area_m2": first_area(t),
        "category": cat,
        "irrigation": irr,
        "object": obj[:400],
        "ids": main_ids,
        "project_ids": proj,
        "part_of": bool(re.search(r"част\s+от\s+поземлен", t, re.I)),
        "built": bool(re.search(r"извършено\s+строителство", t, re.I)),
        "settlement": settle,
        "locality": field(r"местност\s+[„\"“]?([^„“”\",;]+)", t),
        "district": field(r"\b[Рр]айон\s+[„\"“]?([А-Я][а-я]+(?:\s+[А-Яа-я][а-я]+)?)", t, 0),
        "municipality": municipality,
        "province": field(r"\bобласт\s+([А-Я][^,;.()]+)", t, 0),
        "upi": field(r"\(\s*(УПИ[^)]*)\)", t),
        "pup": parse_pup(t),
        "refs": ["КЗЗ-%s/%s" % (a, b) for a, b in re.findall(r"Решение\s*№\s*КЗЗ\s*[–—-]?\s*(\d+)\s*/\s*(\d{1,2}\.\d{1,2}\.\d{4})", t)],
    }


SOFIA_DISTRICTS = ["Средец", "Красно село", "Възраждане", "Оборище", "Сердика", "Подуяне", "Слатина", "Изгрев",
                   "Лозенец", "Триадица", "Красна поляна", "Илинден", "Надежда", "Искър", "Младост", "Студентски",
                   "Витоша", "Овча купел", "Люлин", "Връбница", "Нови Искър", "Кремиковци", "Панчарево", "Банкя"]


def norm_district(d):
    """'Овча Купел' -> 'Овча купел', 'Панчерево' -> 'Панчарево', 'Връбница за' -> 'Връбница'."""
    import difflib
    if not d:
        return ""
    d = re.sub(r"\s+(?:за|област|Столична|община).*$", "", d.strip(), flags=re.I)
    low = {x.lower(): x for x in SOFIA_DISTRICTS}
    if d.lower() in low:
        return low[d.lower()]
    m = difflib.get_close_matches(d.lower(), list(low), n=1, cutoff=0.8)
    return low[m[0]] if m else d


COLS = ["decision", "date", "item", "action", "identifier", "ekatte", "project_ids", "part_of", "built",
        "area_m2", "category", "irrigation", "object", "settlement", "locality", "district", "municipality",
        "province", "upi", "pup", "refs", "url"]


def main():
    files = json.load(open(os.path.join(DATA, "files.json"), encoding="utf-8"))
    rows, decisions, unparsed, stats = [], [], [], Counter()
    for fname, meta in sorted(files.items()):
        if not meta.get("ok"):
            continue
        text = open(os.path.join(DATA, "text", fname + ".txt"), encoding="utf-8").read()
        num, date = parse_header(text, fname)
        items = split_items(text)
        decisions.append({"decision": f"КЗЗ-{num}" if num else "", "date": date, "items": len(items),
                          "file": fname, "url": meta["url"]})
        if not items:
            unparsed.append({"file": fname, "reason": "няма разпознати точки"})
        for sec, sec_txt, no, item in items:
            p = parse_item(item, sec_txt)
            stats[p["action"]] += 1
            ids = p["ids"] or [""]
            for cid in ids:
                rows.append({
                    "decision": f"КЗЗ-{num}" if num else fname, "date": date, "item": no, "action": p["action"],
                    "identifier": cid, "ekatte": cid.split(".")[0] if cid else "",
                    "project_ids": " ".join(p["project_ids"]), "part_of": "да" if p["part_of"] else "",
                    "built": "да" if p["built"] else "", "area_m2": p["area_m2"] or "", "category": p["category"],
                    "irrigation": p["irrigation"], "object": p["object"], "settlement": p["settlement"],
                    "locality": p["locality"], "district": p["district"], "municipality": p["municipality"],
                    "province": p["province"], "upi": p["upi"], "pup": p["pup"], "refs": " ".join(p["refs"]), "url": meta["url"],
                })
    rows.sort(key=lambda r: (r["date"] or "", r["decision"], int(r["item"])), reverse=True)
    # землищата в Столична община = ЕКАТТЕ, срещнати в точки, които изрично казват „Столична община“
    sofia_ekatte = {r["ekatte"] for r in rows if r["municipality"] == "Столична" and r["ekatte"]}
    sofia_ekatte.add("68134")
    sofia = [r for r in rows if r["municipality"] == "Столична" or r["ekatte"] in sofia_ekatte]
    # районите: нормализирани; за селата (едно землище = един район) – попълнени по землището
    for r in sofia:
        r["district"] = norm_district(r["district"]) if r["district"] else ""
    by_ek = {}
    for r in sofia:
        if r["district"] in SOFIA_DISTRICTS and r["ekatte"] and r["ekatte"] != "68134":
            by_ek.setdefault(r["ekatte"], Counter())[r["district"]] += 1
    for r in sofia:
        if not r["district"] and r["ekatte"] in by_ek:
            r["district"] = by_ek[r["ekatte"]].most_common(1)[0][0]
    for name, data in (("register.csv", rows), ("register_sofia.csv", sofia)):
        with open(os.path.join(DATA, name), "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLS, delimiter=";")
            w.writeheader()
            w.writerows(data)
    with open(os.path.join(DATA, "decisions.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["decision", "date", "items", "file", "url"], delimiter=";")
        w.writeheader()
        w.writerows(sorted(decisions, key=lambda d: d["date"] or "", reverse=True))
    os.makedirs(OUT, exist_ok=True)
    report = {
        "decisions": len(decisions), "rows": len(rows), "rows_without_identifier": sum(1 for r in rows if not r["identifier"]),
        "actions": dict(stats.most_common()), "sofia_rows": len(sofia), "sofia_ekatte": sorted(sofia_ekatte),
        "unparsed_files": unparsed,
    }
    json.dump(report, open(os.path.join(OUT, "report.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps({k: v for k, v in report.items() if k != "unparsed_files"}, ensure_ascii=False, indent=1))
    print("unparsed files:", len(unparsed))


if __name__ == "__main__":
    main()
