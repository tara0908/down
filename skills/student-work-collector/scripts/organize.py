#!/usr/bin/env python3
"""학생 결과물 정리 스크립트.

manifest.json(수집한 결과물 목록)을 읽어
  - 학생 번호/이름을 찾고 (명렬표가 있으면 맞춰 보고)
  - 번호순 → 이름 가나다순 → 이름 미확인 순으로 정렬해
  - 과제별 폴더에 `번호_이름.txt` / `번호_이름.png`로 저장하고
  - 원문, 교정내역, 제출목록.csv, 미제출자 요약을 만든다.

사용법:
  python3 organize.py manifest.json --out 결과폴더 [--roster 명렬표.xlsx] [--zip] [--no-original]
"""
import argparse
import csv
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request

MARKER = ".student-work-collector"
HANGUL_TOKEN = re.compile(r"[가-힣]+")
NOT_NAMES = {
    "익명", "학생", "과제", "제출", "학년", "번", "반", "선생님", "작품", "결과물",
    "포스터", "활동지", "사진", "그림", "글쓰기", "발표", "모둠", "조", "팀",
}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".pdf"}


# ---------------------------------------------------------------- 명렬표
def load_roster(path):
    """[(번호, 이름), ...] 반환. '번호'/'이름' 열을 찾고, 없으면 첫 두 열을 쓴다."""
    rows = []
    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xlsm"):
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb.active
        rows = [[("" if c is None else str(c)).strip() for c in r] for r in ws.iter_rows(values_only=True)]
    elif ext == ".csv":
        for enc in ("utf-8-sig", "cp949"):
            try:
                with open(path, encoding=enc, newline="") as f:
                    rows = [[c.strip() for c in r] for r in csv.reader(f)]
                break
            except UnicodeDecodeError:
                continue
    else:
        for enc in ("utf-8-sig", "cp949"):
            try:
                with open(path, encoding=enc) as f:
                    rows = [re.split(r"[\t,]+|\s+", line.strip()) for line in f if line.strip()]
                break
            except UnicodeDecodeError:
                continue

    num_col, name_col, start = None, None, 0
    for i, r in enumerate(rows[:5]):
        for j, c in enumerate(r):
            if num_col is None and c.replace(" ", "") in ("번호", "번", "출석번호", "No", "no"):
                num_col = j
            if name_col is None and c.replace(" ", "") in ("이름", "성명", "학생", "학생이름"):
                name_col = j
        if num_col is not None or name_col is not None:
            start = i + 1
            break

    roster = []
    for r in rows[start:]:
        if not r:
            continue
        if num_col is not None and name_col is not None:
            num_s = r[num_col] if num_col < len(r) else ""
            name = r[name_col] if name_col < len(r) else ""
        else:  # 열 이름이 없으면 숫자 칸 = 번호, 한글 칸 = 이름
            num_s = next((c for c in r if re.fullmatch(r"\d+(\.0)?", c)), "")
            name = next((c for c in r if HANGUL_TOKEN.fullmatch(c.replace(" ", ""))), "")
        name = name.replace(" ", "")
        m = re.match(r"\d+", num_s or "")
        if name:
            roster.append((int(m.group()) if m else None, name))
    return roster


# ---------------------------------------------------------------- 번호·이름 찾기
def parse_number(text):
    t = text
    m = re.search(r"(\d+)\s*-\s*(\d+)\s*-\s*(\d+)", t)          # 3-2-15
    if m:
        return int(m.group(3))
    m = re.search(r"(\d+)\s*번", t)                               # 15번
    if m:
        return int(m.group(1))
    m = re.search(r"(?<!\d)(\d{4,5})(?!\d)", t)                    # 학번 20315 / 3215
    if m:
        return int(m.group(1)[-2:])
    m = re.search(r"[(\[](\d{1,2})[)\]]", t)                       # (15)
    if m:
        return int(m.group(1))
    m = re.search(r"(?i)no\.?\s*(\d{1,2})", t)                     # No.15
    if m:
        return int(m.group(1))
    m = re.search(r"(?<![\d.])(\d{1,2})(?![\d.])", t)              # 15 김민수
    if m and int(m.group(1)) > 0:
        return int(m.group(1))
    return None


def parse_name(text, roster_names):
    tokens = [tk for tk in HANGUL_TOKEN.findall(text)]
    # '번', '학년' 같은 꼬리 제거 (예: '15번김민수' → '김민수'는 정규식에서 이미 분리됨)
    cleaned = []
    for tk in tokens:
        tk = re.sub(r"^(학년|반|번)+", "", tk)
        tk = re.sub(r"(학년|반|번)+$", "", tk)
        if tk:
            cleaned.append(tk)
    if roster_names:
        for tk in cleaned:
            if tk in roster_names:
                return tk
        for tk in cleaned:  # '김민수의포스터'처럼 붙은 경우
            for rn in sorted(roster_names, key=len, reverse=True):
                if rn in tk:
                    return rn
    for tk in cleaned:
        if 2 <= len(tk) <= 4 and tk not in NOT_NAMES:
            return tk
    return None


def resolve_student(item, roster):
    """(번호 또는 None, 이름 또는 None, 확인메모) 반환."""
    author = str(item.get("author") or "")
    number = item.get("number")
    name = (item.get("name") or "").replace(" ", "") or None
    if isinstance(number, str):
        m = re.search(r"\d+", number)
        number = int(m.group()) if m else None
    roster_names = {n for _, n in roster}

    if item.get("unknown"):  # 별명·익명이라 누군지 알 수 없다고 표시한 항목
        return None, None, ""
    if name is None and author:
        name = parse_name(author, roster_names)
    if number is None and author:
        number = parse_number(author)

    note = ""
    if roster:
        by_name = {}
        for n_, nm in roster:
            by_name.setdefault(nm, []).append(n_)
        by_num = {n_: nm for n_, nm in roster if n_ is not None}
        if name and name in by_name:
            if len(by_name[name]) == 1 and by_name[name][0] is not None:
                if number is not None and number != by_name[name][0]:
                    note = f"표시 번호 {number}번 ≠ 명렬표 {by_name[name][0]}번(명렬표 기준)"
                number = by_name[name][0]
        elif name:
            # 성 없이 이름만 쓴 경우: '민수' → '김민수'
            cands = [nm for nm in roster_names if len(nm) >= 3 and nm[1:] == name]
            if len(cands) == 1:
                note = f"'{name}' → 명렬표 '{cands[0]}'로 맞춤"
                name = cands[0]
                ns = by_name[name]
                if len(ns) == 1 and ns[0] is not None:
                    number = ns[0]
            elif number in by_num:
                note = f"'{name}'은 명렬표에 없음, {number}번 {by_num[number]}(으)로 추정 – 확인 필요"
                name = by_num[number]
            else:
                note = f"'{name}'은 명렬표에 없음"
                name = None  # 별명·오타일 수 있으니 이름확인필요로 둔다
        elif number in by_num:
            name = by_num[number]
            note = "이름 없이 번호로 맞춤 – 확인 필요"
    return number, name, note


# ---------------------------------------------------------------- 파일 처리
def safe(s):
    s = re.sub(r'[\\/:*?"<>|\n\r\t]+', "_", str(s)).strip(" ._")
    return s[:60] or "이름없음"


def fetch(src, workdir):
    """로컬 경로면 그대로, URL이면 내려받아 경로 반환."""
    if re.match(r"https?://", src):
        ext = os.path.splitext(src.split("?")[0])[1].lower()
        if ext not in IMAGE_EXTS:
            ext = ".img"
        dst = os.path.join(workdir, f"dl_{abs(hash(src))}{ext}")
        req = urllib.request.Request(src, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as r, open(dst, "wb") as f:
            shutil.copyfileobj(r, f)
        return dst
    if not os.path.exists(src):
        raise FileNotFoundError(src)
    return src


def to_png_list(src, workdir):
    """이미지/PDF를 PNG 파일 경로 목록으로 변환 (PDF는 쪽마다 하나)."""
    from PIL import Image, ImageOps
    with open(src, "rb") as f:
        head = f.read(5)
    if head.startswith(b"%PDF"):
        prefix = os.path.join(workdir, f"pdf_{abs(hash(src))}")
        subprocess.run(["pdftoppm", "-png", "-r", "150", src, prefix], check=True)
        d = os.path.dirname(prefix)
        base = os.path.basename(prefix)
        return sorted(
            (os.path.join(d, f) for f in os.listdir(d) if f.startswith(base + "-") and f.endswith(".png")),
            key=lambda p: int(re.search(r"-(\d+)\.png$", p).group(1)),
        )
    out = []
    with Image.open(src) as im:
        im.seek(0)
        im = ImageOps.exif_transpose(im)  # 휴대폰 사진 회전 바로잡기
        if im.mode not in ("RGB", "RGBA", "L", "LA"):
            im = im.convert("RGBA" if "A" in im.getbands() or "transparency" in im.info else "RGB")
        dst = os.path.join(workdir, f"img_{abs(hash(src))}.png")
        im.save(dst, "PNG", optimize=True)
        out.append(dst)
    return out


# ---------------------------------------------------------------- 메인
def main():
    ap = argparse.ArgumentParser(description="학생 결과물 번호순 정리")
    ap.add_argument("manifest")
    ap.add_argument("--out", default=f"학생결과물_{dt.date.today().isoformat()}")
    ap.add_argument("--roster")
    ap.add_argument("--zip", action="store_true")
    ap.add_argument("--no-original", action="store_true")
    a = ap.parse_args()

    with open(a.manifest, encoding="utf-8") as f:
        data = json.load(f)
    items = data["items"] if isinstance(data, dict) else data
    roster = load_roster(a.roster) if a.roster else []

    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, MARKER), "w") as f:
        f.write("이 폴더는 학생 결과물 정리 스크립트가 만들었습니다.\n")
    workdir = tempfile.mkdtemp(prefix="swc_")

    # 학생 정보 붙이기
    enriched = []
    for idx, it in enumerate(items):
        number, name, note = resolve_student(it, roster)
        platform = it.get("platform") or "기타"
        assignment = it.get("assignment") or "과제"
        kind = it.get("type") or ("text" if "text" in it else "image")
        enriched.append(dict(it, _idx=idx, _num=number, _name=name, _note=note,
                             _group=f"{safe(platform)}_{safe(assignment)}", _kind=kind))

    def sort_key(e):
        if e["_name"] is None:
            return (2, 0, str(e.get("author") or ""), e["_idx"])
        if e["_num"] is not None:
            return (0, e["_num"], e["_name"], e["_idx"])
        return (1, 0, e["_name"], e["_idx"])

    groups = {}
    for e in enriched:
        groups.setdefault(e["_group"], []).append(e)

    rows, problems, errors = [], [], []
    summary = []
    for gname in sorted(groups):
        gdir = os.path.join(a.out, gname)
        if os.path.isdir(gdir) and os.path.exists(os.path.join(a.out, MARKER)):
            shutil.rmtree(gdir)  # 다시 실행하면 이 과제 폴더를 새로 만든다
        os.makedirs(gdir)
        counters, change_log = {}, []
        submitted = set()

        for e in sorted(groups[gname], key=sort_key):
            if e["_name"] is None:
                base = "이름확인필요_" + safe(e.get("author") or f"{e['_idx'] + 1}번째")
                problems.append(f"[{gname}] 원래 표시: '{e.get('author') or '(없음)'}'")
            else:
                base = (f"{e['_num']:02d}_" if e["_num"] is not None else "") + safe(e["_name"])
                submitted.add(e["_name"])
            if e["_note"]:
                problems.append(f"[{gname}] {base}: {e['_note']}")
            if e.get("label"):  # 예: 그림1(원래 그림), 그림2(3D) → 01_김민준_그림1.png
                base = f"{base}_{safe(e['label'])}"

            try:
                if e["_kind"] == "text":
                    original = (e.get("text") or "").strip()
                    corrected = (e.get("corrected") or original).strip()
                    changes = e.get("changes") or []
                    key = (base, ".txt")
                    counters[key] = counters.get(key, 0) + 1
                    fname = base + ("" if counters[key] == 1 else f"_{counters[key]}") + ".txt"
                    with open(os.path.join(gdir, fname), "w", encoding="utf-8") as f:
                        f.write(corrected + "\n")
                    if not a.no_original and original:
                        odir = os.path.join(gdir, "원문")
                        os.makedirs(odir, exist_ok=True)
                        with open(os.path.join(odir, fname), "w", encoding="utf-8") as f:
                            f.write(original + "\n")
                    change_log.append((fname, changes))
                    rows.append([e["_num"] or "", e["_name"] or "", e.get("platform", ""),
                                 e.get("assignment", ""), f"{gname}/{fname}", "글", sum(1 for c in changes if "(확인)" not in c), e["_note"]])
                else:
                    src = e.get("file") or e.get("url")
                    if not src:
                        raise ValueError("이미지 항목에 file 또는 url이 없음")
                    pngs = to_png_list(fetch(src, workdir), workdir)
                    for p in pngs:
                        key = (base, ".png")
                        counters[key] = counters.get(key, 0) + 1
                        fname = base + ("" if counters[key] == 1 else f"_{counters[key]}") + ".png"
                        shutil.copyfile(p, os.path.join(gdir, fname))
                        rows.append([e["_num"] or "", e["_name"] or "", e.get("platform", ""),
                                     e.get("assignment", ""), f"{gname}/{fname}", "그림", "", e["_note"]])
            except Exception as ex:  # 한 항목이 실패해도 나머지는 계속
                errors.append(f"[{gname}] {base}: {ex}")

        if change_log:
            with open(os.path.join(gdir, "교정내역.txt"), "w", encoding="utf-8") as f:
                f.write(f"{gname} 맞춤법·띄어쓰기 교정 내역\n")
                f.write("(원래 글은 '원문' 폴더에 있습니다)\n\n" if not a.no_original else "\n")
                for fname, changes in change_log:
                    f.write(f"■ {fname} – " + (f"{len(changes)}곳\n" if changes else "고친 곳 없음\n"))
                    for c in changes:
                        f.write(f"   · {c}\n")
                    f.write("\n")

        missing = [f"{n}번 {nm}" if n is not None else nm
                   for n, nm in sorted(roster, key=lambda x: (x[0] is None, x[0] or 0, x[1]))
                   if nm not in submitted] if roster else []
        summary.append((gname, len(submitted), sum(1 for _, cs in change_log for c in cs if "(확인)" not in c), missing))

    with open(os.path.join(a.out, "제출목록.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["번호", "이름", "플랫폼", "과제", "파일", "종류", "교정 수", "확인 메모"])
        w.writerows(rows)

    shutil.rmtree(workdir, ignore_errors=True)

    # 요약 출력
    print(f"저장 위치: {os.path.abspath(a.out)}")
    for gname, n, nchg, missing in summary:
        line = f"- {gname}: {n}명 제출"
        if nchg:
            line += f", 글 교정 {nchg}곳"
        if roster:
            line += f", 미제출 {len(missing)}명" + (f" ({', '.join(missing)})" if missing else "")
        print(line)
    if problems:
        print("\n확인이 필요한 항목:")
        for p in dict.fromkeys(problems):
            print("  " + p)
    if errors:
        print("\n저장하지 못한 항목:")
        for er in errors:
            print("  " + er)
    if a.zip:
        z = shutil.make_archive(os.path.abspath(a.out), "zip", root_dir=os.path.dirname(os.path.abspath(a.out)),
                                base_dir=os.path.basename(os.path.abspath(a.out)))
        print(f"\nzip: {z}")
    return 1 if errors and not rows else 0


if __name__ == "__main__":
    sys.exit(main())
