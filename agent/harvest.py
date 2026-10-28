"""Изтегля решенията на Комисията за земеделските земи (КЗЗ) от сайта на МЗХ и записва текста им.

Страница: https://www.mzh.government.bg/bg/uslugi/komisiya-za-zemedelskite-zemi/resheniya-komisiyata-zemedelskite-zemi/
Файлове: .docx (текстът се чете от word/document.xml) и стари .doc (чрез `catdoc`).
-> data/text/<име на файла>.txt     (текстът на решението)
-> data/files.json                 (кои файлове са обработени, адрес, дата на качване)

Usage: python agent/harvest.py [--all]   (без --all спира, щом стигне до вече известни файлове)
"""
import argparse
import html
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
TEXT = os.path.join(DATA, "text")
BASE = "https://www.mzh.government.bg"
INDEX = BASE + "/bg/uslugi/komisiya-za-zemedelskite-zemi/resheniya-komisiyata-zemedelskite-zemi/"
UA = "karta-promiana-prednaznachenie/1.0 (open data research)"


def get(url, delay=1.5, retries=4):
    for i in range(retries):
        time.sleep(delay)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            if i == retries - 1:
                raise
            print(f"  retry {i + 1} {url[:90]}: {e}", flush=True)
            time.sleep(5 * (i + 1))


def docx_text(path):
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"<w:tab/>", "\t", xml)
    xml = re.sub(r"<w:br/>", "\n", xml)
    return html.unescape(re.sub(r"<[^>]+>", "", xml))


def doc_text(path):
    out = subprocess.run(["catdoc", "-d", "utf-8", "-w", path], capture_output=True, timeout=120)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.decode("utf-8", "replace")[:300])
    return out.stdout.decode("utf-8", "replace")


def list_files(stop_known, known):
    files, page = [], 1
    while page < 100:
        url = INDEX + (f"?page={page}" if page > 1 else "")
        h = get(url).decode("utf-8", "replace")
        links = re.findall(r'href="(/media/[^"]+\.(?:docx?|pdf))"', h, re.I)
        fresh = [l for l in dict.fromkeys(links) if l not in files]
        if not fresh:
            break
        files.extend(fresh)
        new_here = [l for l in fresh if os.path.basename(l) not in known]
        print(f"page {page}: {len(fresh)} files, {len(new_here)} new", flush=True)
        if stop_known and not new_here:
            break
        page += 1
    return files


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    os.makedirs(TEXT, exist_ok=True)
    reg_path = os.path.join(DATA, "files.json")
    reg = json.load(open(reg_path, encoding="utf-8")) if os.path.exists(reg_path) else {}
    files = list_files(stop_known=not a.all and bool(reg), known=reg)
    new = errors = 0
    for link in files:
        name = os.path.basename(link)
        if name in reg and reg[name].get("ok"):
            continue
        url = BASE + urllib.parse.quote(link)
        up = re.search(r"/filer_public/(\d{4})/(\d{2})/(\d{2})/", link)
        entry = {"url": BASE + link, "uploaded": "-".join(up.groups()) if up else None}
        try:
            raw = get(url)
            with tempfile.NamedTemporaryFile(suffix=os.path.splitext(name)[1], delete=False) as tf:
                tf.write(raw)
                tmp = tf.name
            try:
                text = docx_text(tmp) if name.lower().endswith(".docx") else doc_text(tmp)
            finally:
                os.unlink(tmp)
            with open(os.path.join(TEXT, name + ".txt"), "w", encoding="utf-8") as f:
                f.write(text)
            entry["ok"] = True
            new += 1
        except Exception as e:  # noqa: BLE001
            entry["ok"] = False
            entry["error"] = f"{type(e).__name__}: {e}"[:300]
            errors += 1
            print(f"  ГРЕШКА {name}: {entry['error']}", flush=True)
        reg[name] = entry
        if new % 20 == 0:
            json.dump(reg, open(reg_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1, sort_keys=True)
    json.dump(reg, open(reg_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1, sort_keys=True)
    print(f"files listed {len(files)}, new {new}, errors {errors}, total {len(reg)}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
