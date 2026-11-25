# -*- coding: utf-8 -*-
"""
희망 뉴스레터 생성기 (Good News Newsletter)
- 전 세계의 긍정적·진취적인 뉴스(의학 돌파구, 과학 난제 해결, 신기술 등)를 RSS로 수집
- 최근 N일(기본 180일 = 6개월) 이내 기사만 남김
- 긍정 키워드 점수화 + 부정 키워드 제외 + 중복 제거
- 카테고리별로 정리한 HTML 뉴스레터 생성

외부 라이브러리 없이 파이썬 표준 라이브러리만 사용합니다.

사용법:
    python good_news.py                # 기본: 최근 180일, 카테고리별 최대 12개
    python good_news.py --days 90      # 최근 90일
    python good_news.py --per-cat 20   # 카테고리별 최대 20개
    python good_news.py --no-open      # 생성 후 브라우저 자동 열기 안 함
"""
import argparse
import html
import re
import sys
import time
import urllib.parse
import urllib.request
import webbrowser
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) GoodNewsNewsletter/1.0"

# ---------------------------------------------------------------------------
# 1. 카테고리별 검색어 (Google News RSS 검색)
# ---------------------------------------------------------------------------
CATEGORIES = {
    "medical": {
        "name": "🩺 의학 · 생명과학",
        "en": [
            "medical breakthrough", "first successful transplant", "artificial heart transplant",
            "gene therapy cure", "cancer cure breakthrough", "new treatment approved FDA",
            "Down syndrome breakthrough", "Alzheimer's breakthrough", "HIV cure",
            "paralyzed patient walks again", "vaccine breakthrough", "CRISPR cure",
        ],
        "ko": ["의학 돌파구", "세계 최초 이식 성공", "완치 치료제 개발", "유전자 치료 성공", "신약 승인"],
    },
    "science": {
        "name": "🔬 과학 · 수학",
        "en": [
            "scientific breakthrough", "mathematicians prove conjecture", "Riemann hypothesis proof",
            "physicists discover", "long-standing problem solved", "major discovery scientists",
        ],
        "ko": ["난제 해결", "추측 증명", "과학 돌파구", "세계 최초 발견"],
    },
    "tech": {
        "name": "🚀 기술 · 우주",
        "en": [
            "technology breakthrough", "quantum computing breakthrough", "fusion energy record",
            "battery breakthrough", "space mission success", "robotics breakthrough",
        ],
        "ko": ["기술 혁신 세계 최초", "핵융합 신기록", "양자컴퓨터 돌파구", "우주 발사 성공"],
    },
    "planet": {
        "name": "🌱 환경 · 에너지",
        "en": [
            "renewable energy record", "species saved from extinction", "ocean cleanup success",
            "reforestation success", "emissions fall record", "clean energy milestone",
        ],
        "ko": ["재생에너지 신기록", "멸종위기종 복원", "탄소 감축 성과"],
    },
    "society": {
        "name": "🤝 사회 · 인류",
        "en": [
            "poverty falls record", "disease eradicated", "malaria eliminated", "literacy milestone",
            "good news humanity", "child mortality falls",
        ],
        "ko": ["퇴치 선언", "빈곤 감소", "희망 소식"],
    },
}

# 긍정 뉴스 전문 매체 RSS (카테고리는 키워드로 자동 분류)
EXTRA_FEEDS = [
    "https://www.goodnewsnetwork.org/feed/",
    "https://www.sciencedaily.com/rss/top/science.xml",
    "https://www.sciencedaily.com/rss/top/health.xml",
    "https://www.reasonstobecheerful.world/feed/",
]

# ---------------------------------------------------------------------------
# 2. 점수화 키워드
# ---------------------------------------------------------------------------
POSITIVE = {
    # 강한 신호 (3점)
    3: ["breakthrough", "world first", "world's first", "first-ever", "first ever", "cure", "cured",
        "proved", "proves", "proof", "solved", "eradicat", "eliminat", "approved", "restores",
        "record-breaking", "historic", "milestone",
        "세계 최초", "돌파구", "완치", "증명", "해결", "퇴치", "성공", "승인", "신기록", "최초"],
    # 보통 신호 (1점)
    1: ["discover", "new treatment", "promising", "hope", "success", "advance", "innovation",
        "record", "saved", "recover", "regenerat", "restore", "boost", "improve",
        "개발", "발견", "혁신", "희망", "회복", "복원", "기록"],
}
NEGATIVE = [
    "dies", "died", "death", "killed", "kill", "war", "attack", "shooting", "crash", "scandal",
    "fraud", "lawsuit", "sued", "arrest", "crisis", "collapse", "layoff", "outbreak", "fail",
    "fails", "failed", "warning", "threat", "fears", "disaster", "recall", "bankrupt", "hack",
    "lost", "loses", "opinion", "debate", "drawing board", "setback", "slop", "decline",
    "tired", "won't", "gatekeeping", "상실", "잃었", "잃어", "도마", "비판",
    "사망", "숨져", "전쟁", "공격", "사고", "논란", "사기", "소송", "체포", "위기", "붕괴",
    "해고", "실패", "경고", "위협", "우려", "참사", "재난", "의혹", "폭락", "피해",
]
# 광고·주식·클릭베이트성 기사 제외
SPAM = ["stock", "shares", "price target", "market size", "cagr", "forecast 20", "webinar",
        "sponsored", "earnings", "revenue", "slop", "bible", "jesus", "playoff", "championship",
        "주가", "특징주", "관련주", "급등", "목표가", "시장 규모", "사설", "칼럼", "실적", "영업이익",
        "매출", "수출", "수주", "경영권", "분쟁", "연승", "메달", "대표팀", "포스트시즌", "홈런",
        "혁신상", "수상", "출시", "신제품", "할인", "분양", "어떡하나", "충격", "인터뷰", "기고",
        "도전", "착수", "추진", "나선다", "손잡고", "협약", "mou"]
# 풍자·저품질 매체
BLOCKED_SOURCES = ["the onion", "babylon bee", "express.co.uk", "daily star"]

# 주요 언론·과학 매체 (하이라이트 가산점)
MAJOR_SOURCES = [
    "reuters", "associated press", "ap news", "apnews", "bbc", "new york times", "nytimes",
    "washington post", "the guardian", "guardian", "cnn", "bloomberg", "financial times",
    "wall street journal", "wsj", "npr", "the economist", "time", "cnbc", "abc news", "nbc news",
    "cbs news", "forbes", "wired", "mit technology review", "nature", "science", "new scientist",
    "scientific american", "statnews", "stat", "the verge", "axios", "al jazeera", "nikkei",
    "sciencedaily", "smithsonian", "national geographic", "le monde", "dw",
    "연합뉴스", "조선일보", "중앙일보", "동아일보", "한겨레", "경향신문", "한국일보", "서울신문",
    "한국경제", "매일경제", "kbs", "mbc", "sbs", "ytn", "jtbc", "동아사이언스", "뉴시스", "뉴스1",
]
STOPWORDS = {"the", "and", "for", "with", "has", "have", "how", "what", "why", "new", "from", "that",
             "this", "are", "was", "its", "into", "after", "could", "may", "just", "inside", "still"}

# 기사가 실제 과학·의학·사회 진보와 관련 있는지 확인하는 단어 (하나 이상 포함 필요)
RELEVANCE_EXTRA = ["research", "scientist", "researchers", "study", "university", "patients",
                   "연구", "연구팀", "연구진", "규명", "교수", "대학", "과학", "학회", "논문"]

CATEGORY_HINTS = {
    "medical": ["patient", "cancer", "therapy", "transplant", "disease", "drug", "vaccine", "gene",
                "heart", "brain", "medical", "health", "hospital", "환자", "암", "치료", "이식", "질환",
                "신약", "백신", "유전자", "의학", "병원"],
    "science": ["math", "physic", "chemist", "scientist", "theorem", "conjecture", "hypothesis",
                "fossil", "species discovered", "수학", "물리", "화학", "과학자", "정리", "추측", "가설"],
    "tech": ["quantum", "ai ", "robot", "battery", "chip", "fusion", "space", "rocket", "nasa",
             "satellite", "양자", "로봇", "배터리", "반도체", "핵융합", "우주", "로켓", "위성"],
    "planet": ["climate", "solar", "wind", "renewable", "forest", "ocean", "wildlife", "extinct",
               "emission", "기후", "태양광", "풍력", "재생에너지", "숲", "바다", "멸종", "탄소"],
    "society": ["poverty", "education", "community", "eradicat", "literacy", "빈곤", "교육", "공동체"],
}


# ---------------------------------------------------------------------------
# 3. 수집
# ---------------------------------------------------------------------------
SEARCH_WINDOW = "1y"  # main()에서 --days에 맞춰 조정


def google_news_url(query: str, lang: str) -> str:
    q = urllib.parse.quote(f"{query} when:{SEARCH_WINDOW}")  # 날짜는 이후 직접 한 번 더 필터
    if lang == "ko":
        return f"https://news.google.com/rss/search?q={q}&hl=ko&gl=KR&ceid=KR:ko"
    return f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"


def fetch(url: str, timeout: int = 15, retries: int = 3) -> bytes | None:
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:  # 일시적 차단(429/503)이면 잠시 쉬었다 재시도
            if attempt == retries - 1:
                print(f"  [skip] {url[:80]}... ({type(e).__name__})", file=sys.stderr)
                return None
            time.sleep(3 * (attempt + 1))


def parse_date(text: str | None) -> datetime | None:
    if not text:
        return None
    text = text.strip()
    try:
        d = parsedate_to_datetime(text)
    except Exception:
        try:
            d = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except Exception:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d


def strip_tags(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s or "")
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def parse_feed(data: bytes, cat_hint: str | None, lang: str) -> list[dict]:
    items = []
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return items
    atom = "{http://www.w3.org/2005/Atom}"
    nodes = root.findall(".//item") or root.findall(f".//{atom}entry")
    for rank, it in enumerate(nodes):
        def g(*tags):
            # 주의: ElementTree 요소는 자식이 없으면 False로 평가되므로 `or` 대신 None 비교
            for tag in tags:
                for t in (tag, atom + tag):
                    el = it.find(t)
                    if el is not None:
                        return el
            return None
        title_el = g("title")
        title = strip_tags(title_el.text if title_el is not None else "")
        link_el = g("link")
        link = ""
        if link_el is not None:
            link = (link_el.text or link_el.get("href") or "").strip()
        date_el = g("pubDate", "published", "updated")
        date = parse_date(date_el.text if date_el is not None else None)
        desc_el = g("description", "summary")
        desc = strip_tags(desc_el.text if desc_el is not None else "")
        src_el = it.find("source")
        source = strip_tags(src_el.text) if src_el is not None and src_el.text else ""
        # Google News 제목은 "제목 - 언론사" 형식
        if not source and " - " in title:
            title, source = title.rsplit(" - ", 1)
        elif source and title.endswith(" - " + source):
            title = title[: -len(" - " + source)]
        if not source:
            source = urllib.parse.urlparse(link).netloc.replace("www.", "")
        if title and link:
            items.append({"title": title.strip(), "link": link, "date": date, "desc": desc,
                          "source": source, "cat": cat_hint, "lang": lang, "rank": rank})
    return items


def collect() -> list[dict]:
    jobs = []  # (url, cat_hint, lang)
    for cat, conf in CATEGORIES.items():
        for q in conf["en"]:
            jobs.append((google_news_url(q, "en"), cat, "en"))
        for q in conf["ko"]:
            jobs.append((google_news_url(q, "ko"), cat, "ko"))
    for url in EXTRA_FEEDS:
        jobs.append((url, None, "en"))

    print(f"📡 {len(jobs)}개 피드에서 수집 중...")
    results = []
    with ThreadPoolExecutor(max_workers=3) as ex:
        futs = {ex.submit(fetch, u): (u, c, l) for u, c, l in jobs}
        for f in as_completed(futs):
            u, c, l = futs[f]
            data = f.result()
            if data:
                results.extend(parse_feed(data, c, l))
    print(f"   원본 기사 {len(results)}건")
    return results


# ---------------------------------------------------------------------------
# 4. 필터링 · 점수화 · 분류
# ---------------------------------------------------------------------------
def has_word(text: str, kw: str) -> bool:
    if re.search(r"[가-힣]", kw):
        return kw in text
    return re.search(r"\b" + re.escape(kw), text) is not None


def score(item: dict) -> int:
    text = (item["title"] + " " + item["title"] + " " + item["desc"]).lower()
    s = 0
    for pts, kws in POSITIVE.items():
        for kw in kws:
            if has_word(text, kw.lower()):
                s += pts
    return s


def is_bad(item: dict) -> bool:
    t = item["title"].lower()
    src = (item["source"] + " " + item["link"]).lower()
    return (any(has_word(t, k) for k in NEGATIVE) or any(k in t for k in SPAM)
            or any(b in src for b in BLOCKED_SOURCES))


RELEVANCE = [k for kws in CATEGORY_HINTS.values() for k in kws] + RELEVANCE_EXTRA


def is_relevant(item: dict) -> bool:
    text = (" " + item["title"] + " " + item["desc"] + " ").lower()
    return any(k in text for k in RELEVANCE)


def classify(item: dict) -> str:
    if item["cat"]:
        return item["cat"]
    text = (item["title"] + " " + item["desc"]).lower()
    best, best_n = "society", 0
    for cat, kws in CATEGORY_HINTS.items():
        n = sum(1 for k in kws if k in text)
        if n > best_n:
            best, best_n = cat, n
    return best


def norm_title(t: str) -> str:
    t = re.sub(r"[^\w가-힣]+", " ", t.lower())
    return " ".join(w for w in t.split() if len(w) > 2)[:80]


def same_story(a: str, b: str) -> bool:
    """제목 핵심 단어가 충분히 겹치면 같은 사건을 다룬 기사로 봄"""
    sa = set(a.split()) - STOPWORDS
    sb = set(b.split()) - STOPWORDS
    if not sa or not sb:
        return False
    common = len(sa & sb)
    return common >= 3 and common / min(len(sa), len(sb)) >= 0.5 or common / min(len(sa), len(sb)) >= 0.8


def is_major(source: str) -> bool:
    s = source.lower().strip()
    for m in MAJOR_SOURCES:
        if re.search(r"[가-힣]", m):
            if m in s:
                return True
        elif len(m) <= 5:  # time, stat, dw 등 짧은 이름은 정확히 일치할 때만
            if s in (m, "the " + m):
                return True
        elif re.search(r"\b" + re.escape(m) + r"\b", s):
            return True
    return False


def highlight_score(it: dict, now: datetime) -> float:
    """
    하이라이트 종합 점수
      - 언급량: 같은 소식을 보도한 매체 수 (많을수록 화제성 ↑)
      - 주요 언론: 메이저 언론·과학 매체 보도 여부와 수
      - 검색 순위: 구글 뉴스 검색 결과 상위 노출 (관련도·인기 반영)
      - 긍정도: 돌파구·최초·완치 등 키워드 점수
      - 최신성: 최근일수록 가산
    """
    mention = 6 * (len(it["sources"]) - 1) ** 0.5           # 2곳 6점, 5곳 12점, 10곳 18점
    major = (5 + 2 * min(len(it["majors"]) - 1, 3)) if it["majors"] else 0
    rank = max(0, 4 - it["best_rank"] * 0.4)  # 상위 10위 이내 가산
    positive = min(it["score"], 12) * 0.6
    age_days = (now - it["date"]).days
    recency = max(0, 3 - age_days / 30)
    return round(mention + major + rank + positive + recency, 1)


def process(items: list[dict], days: int, per_cat: int, min_score: int, n_highlight: int):
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    kept = []
    for it in items:
        if not it["date"] or it["date"] < cutoff or it["date"] > datetime.now(timezone.utc) + timedelta(days=1):
            continue
        if is_bad(it) or not is_relevant(it):
            continue
        it["score"] = score(it)
        if it["score"] < min_score:
            continue
        it["cat"] = classify(it)
        kept.append(it)

    # 같은 사건을 다룬 기사끼리 묶기 (언급량 집계)
    kept.sort(key=lambda x: (x["score"], x["date"]), reverse=True)
    clusters: list[list[dict]] = []
    keys: list[str] = []
    seen_links = set()
    for it in kept:
        if it["link"] in seen_links:
            continue
        seen_links.add(it["link"])
        nt = norm_title(it["title"])
        for i, k in enumerate(keys):
            if same_story(nt, k):
                clusters[i].append(it)
                break
        else:
            clusters.append([it])
            keys.append(nt)

    # 2차 병합: 드문 핵심어(예: riemann + hypothesis)를 2개 이상 공유하면 같은 사건으로 봄
    import math
    toks = [set(k.split()) - STOPWORDS for k in keys]
    df: dict[str, int] = {}
    for ts in toks:
        for w in ts:
            df[w] = df.get(w, 0) + 1
    N = len(toks)
    idf = {w: math.log(N / c) for w, c in df.items()}
    merged: list[list[dict]] = []
    merged_toks: list[set] = []
    for cl, ts in zip(clusters, toks):
        for i, mt in enumerate(merged_toks):
            shared = ts & mt
            if len(shared) >= 2 and sum(idf[w] for w in shared) >= 7.0:
                merged[i].extend(cl)
                break
        else:
            merged.append(list(cl))
            merged_toks.append(ts)
    clusters = merged

    now = datetime.now(timezone.utc)
    uniq = []
    for cl in clusters:
        majors = sorted({a["source"] for a in cl if is_major(a["source"])})
        # 대표 기사: 주요 언론 기사 우선, 없으면 긍정 점수 최고
        rep = next((a for a in cl if is_major(a["source"])), cl[0])
        rep = dict(rep)
        rep["score"] = max(a["score"] for a in cl)
        rep["sources"] = sorted({a["source"] for a in cl})
        rep["majors"] = majors
        rep["best_rank"] = min(a["rank"] for a in cl)
        rep["date"] = max(a["date"] for a in cl)
        rep["hscore"] = highlight_score(rep, now)
        uniq.append(rep)

    # 하이라이트: 종합 점수 순, 같은 주제(드문 핵심어 공유)는 1개만
    highlights, used = [], []
    for it in sorted(uniq, key=lambda x: x["hscore"], reverse=True):
        ts = set(norm_title(it["title"]).split()) - STOPWORDS
        if any(len(ts & u) >= 2 and sum(idf.get(w, 0) for w in ts & u) >= 5.0 for u in used):
            continue
        highlights.append(it)
        used.append(ts)
        if len(highlights) >= n_highlight:
            break

    out = {c: [] for c in CATEGORIES}
    for it in sorted(uniq, key=lambda x: x["hscore"], reverse=True):
        if len(out[it["cat"]]) < per_cat:
            out[it["cat"]].append(it)
    for c in out:
        out[c].sort(key=lambda x: x["date"], reverse=True)
    print(f"   필터 후 {len(kept)}건 → 사건 {len(uniq)}개로 묶음, 게재 {sum(len(v) for v in out.values())}건")
    return out, highlights


# ---------------------------------------------------------------------------
# 5. HTML 뉴스레터
# ---------------------------------------------------------------------------
CSS = """
:root{--bg:#f6f4ef;--card:#fff;--ink:#1d1d1f;--sub:#6b6b70;--line:#e6e2d8;--accent:#d96d1f;--chip:#fdf0e5;--nav:rgba(246,244,239,.92)}
@media (prefers-color-scheme:dark){:root{--bg:#141414;--card:#1e1e1f;--ink:#f1f1f1;--sub:#a0a0a6;--line:#2e2e30;--accent:#f39a55;--chip:#33261b;--nav:rgba(20,20,20,.92)}}
*{box-sizing:border-box}html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--ink);
font-family:"Pretendard","Apple SD Gothic Neo","Malgun Gothic",system-ui,sans-serif;line-height:1.55}
.wrap{max-width:1600px;margin:0 auto;padding:32px 24px 80px}
header{text-align:center;margin-bottom:20px}
header h1{font-size:2.2rem;margin:0 0 6px;letter-spacing:-.02em}
header p{color:var(--sub);margin:0}
nav.toc{position:sticky;top:0;z-index:10;background:var(--nav);backdrop-filter:blur(8px);
display:flex;flex-wrap:wrap;gap:8px;justify-content:center;padding:12px 0;margin:0 -24px 28px;border-bottom:1px solid var(--line)}
nav.toc a{background:var(--chip);color:var(--accent);text-decoration:none;padding:6px 14px;border-radius:999px;font-size:.9rem;font-weight:600;white-space:nowrap}
nav.toc a:hover{background:var(--accent);color:#fff}
section{margin-bottom:44px;scroll-margin-top:70px}
section h2{font-size:1.35rem;border-bottom:2px solid var(--accent);padding-bottom:8px;margin:0 0 14px}
.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
@media (max-width:760px){.grid{grid-template-columns:1fr}.wrap{padding:24px 16px 80px}nav.toc{margin:0 -16px 24px}}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 18px;display:flex;gap:14px;align-items:flex-start}
.card .body{min-width:0;flex:1}
.card a.t{color:var(--ink);text-decoration:none;font-weight:600;font-size:1.02rem}
.card a.t:hover{color:var(--accent)}
.rank{flex:none;width:34px;height:34px;border-radius:50%;background:var(--accent);color:#fff;font-weight:800;display:grid;place-items:center}
#highlight .card{background:linear-gradient(135deg,#ffb36b1f,#ffd86b14),var(--card)}
.meta{color:var(--sub);font-size:.82rem;margin-top:6px;display:flex;gap:6px 10px;flex-wrap:wrap;align-items:center}
.desc{color:var(--sub);font-size:.9rem;margin-top:6px}
.tag{background:var(--chip);color:var(--accent);border-radius:4px;padding:0 6px;font-weight:700;font-size:.78rem}
.crit{color:var(--sub);font-size:.85rem;margin:-6px 0 14px}
.empty{color:var(--sub);font-style:italic}
#top{position:fixed;right:22px;bottom:22px;width:48px;height:48px;border-radius:50%;border:none;cursor:pointer;
background:var(--accent);color:#fff;font-size:1.3rem;box-shadow:0 4px 14px #0003;opacity:0;pointer-events:none;transition:opacity .2s}
#top.show{opacity:1;pointer-events:auto}
.brief{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--accent);border-radius:10px;
padding:12px 16px;margin:0 0 16px;font-size:.92rem;line-height:1.9}
.brief .bl{font-weight:800;color:var(--accent);margin-right:6px}
.brief a{color:var(--ink);text-decoration:none}.brief a:hover{color:var(--accent)}
.brief b{color:var(--accent)}.brief small{color:var(--sub)}
.card{scroll-margin-top:80px}
.ko{font-weight:800;color:var(--accent);font-size:1.05rem;margin-bottom:2px}
footer a{color:var(--accent)}
footer{text-align:center;color:var(--sub);font-size:.8rem;margin-top:40px}
"""


# ---------------------------------------------------------------------------
# 5-1. Claude Code로 하이라이트 한국어 요약 (claude -p, API 키 불필요)
# ---------------------------------------------------------------------------
def find_claude() -> str | None:
    import shutil
    for cand in (shutil.which("claude"), str(Path.home() / ".local" / "bin" / "claude.exe"),
                 str(Path.home() / ".local" / "bin" / "claude")):
        if cand and Path(cand).exists():
            return cand
    return None


def summarize_ko(highlights: list[dict], model: str = "haiku") -> None:
    """각 하이라이트에 it['ko'] (한국어 핵심 요약 한 줄)을 채움. 실패하면 조용히 건너뜀."""
    import json
    import os
    import subprocess
    import tempfile
    exe = find_claude()
    if not exe or not highlights:
        print("   (Claude Code를 찾지 못해 한국어 요약 생략)")
        return
    lines = "\n".join(f"{i}. {it['title']} ({it['source']})" for i, it in enumerate(highlights, 1))
    prompt = (
        "아래는 뉴스 헤드라인 목록이다. 각 헤드라인을 한국어 핵심 단어 위주의 짧은 요약(8~18자)으로 바꿔라.\n"
        "규칙: 앞 항목과 같은 사건·주제(예: 같은 수학 증명, 같은 신약)를 다룬 항목은 빈 문자열 \"\"로 둘 것. "
        "제목에 없는 사실을 지어내지 말 것. '~했다' 같은 서술 대신 명사형으로(예: '클로드, 리만 가설 증명', "
        "'췌장암 신약 FDA 승인', '흑색종 백신 재발 억제'). 고유명사는 한국어 표기.\n"
        f"출력은 문자열 {len(highlights)}개짜리 JSON 배열 하나만. 다른 말은 절대 쓰지 말 것.\n\n{lines}"
    )
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    try:
        r = subprocess.run([exe, "-p", "--model", model], input=prompt, capture_output=True,
                           text=True, encoding="utf-8", timeout=180, env=env, cwd=tempfile.gettempdir())
        m = re.search(r"\[.*\]", r.stdout, re.S)
        arr = json.loads(m.group(0)) if m else []
        if len(arr) != len(highlights):
            raise ValueError(f"요약 개수 불일치 ({len(arr)})")
        for it, s in zip(highlights, arr):
            it["ko"] = str(s).strip()
            it["dup"] = not it["ko"]
        print("   🤖 하이라이트 한국어 요약 완료")
    except Exception as e:
        print(f"   (한국어 요약 실패, 원문 제목 사용: {type(e).__name__} {e})", file=sys.stderr)


def card(it: dict, rank: int | None = None) -> str:
    lang = "KR" if it["lang"] == "ko" else "EN"
    desc = it["desc"]
    if desc and norm_title(desc).startswith(norm_title(it["title"])[:30]):
        desc = ""  # Google News 설명은 제목 반복이라 생략
    desc_html = f'<div class="desc">{html.escape(desc[:200])}{"…" if len(desc) > 200 else ""}</div>' if desc else ""
    tags = f'<span class="tag">{lang}</span>'
    n = len(it["sources"])
    if n > 1:
        tags += f'<span class="tag">📣 {n}개 매체 보도</span>'
    if it["majors"]:
        tags += f'<span class="tag" title="{html.escape(", ".join(it["majors"]))}">🏛 주요 언론</span>'
    num = f'<div class="rank">{rank}</div>' if rank else ""
    cid = f' id="h{rank}"' if rank else ""
    ko = f'<div class="ko">{html.escape(it["ko"])}</div>' if rank and it.get("ko") else ""
    return (f'<div class="card"{cid}>{num}<div class="body">{ko}<a class="t" href="{html.escape(it["link"])}" target="_blank" rel="noopener">'
            f'{html.escape(it["title"])}</a>{desc_html}<div class="meta">{tags}'
            f'<span>{html.escape(it["source"])}</span><span>{it["date"].astimezone().strftime("%Y-%m-%d")}</span></div></div></div>')


def render(groups: dict[str, list[dict]], highlights: list[dict], days: int, archive_href: str = "") -> str:
    now = datetime.now()
    since = (now - timedelta(days=days)).strftime("%Y.%m.%d")
    total = sum(len(v) for v in groups.values())

    def short(title: str, n: int = 60) -> str:
        title = re.split(r" \| | - | — | – ", title)[0].strip(" '\"‘’“”")
        return title if len(title) <= n else title[:n].rstrip() + "…"
    parts = []
    for i, it in enumerate(highlights, 1):
        n = len(it["sources"])
        cnt = f" <small>({n}개 매체)</small>" if n > 1 else ""
        label = it.get("ko") or short(it["title"])
        parts.append(f'<a href="#h{i}"><b>{i}</b> {html.escape(label)}{cnt}</a>')
    brief = " · ".join(parts)
    toc = '<a href="#highlight">⭐ 하이라이트</a>' + "".join(
        f'<a href="#{c}">{CATEGORIES[c]["name"]} {len(v)}</a>' for c, v in groups.items())
    hl = "".join(card(it, i + 1) for i, it in enumerate(highlights))
    secs = (f'<section id="highlight"><h2>⭐ 이번 호 하이라이트 TOP {len(highlights)}</h2>'
            f'<p class="crit">선정 기준: 보도 매체 수(언급량) · 주요 언론 보도 · 구글 뉴스 검색 상위 노출 · 긍정 키워드 · 최신성을 합산한 종합 점수</p>'
            f'<div class="grid">{hl}</div></section>')
    for c, v in groups.items():
        body = (f'<div class="grid">{"".join(card(i) for i in v)}</div>' if v
                else '<p class="empty">이번 기간에는 소식이 없어요.</p>')
        secs += f'<section id="{c}"><h2>{CATEGORIES[c]["name"]}</h2>{body}</section>'

    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>희망 뉴스레터 {now:%Y.%m.%d}</title>
<style>{CSS}</style></head><body><div class="wrap">
<header><h1>☀️ 희망 뉴스레터</h1><p>{since} ~ {now:%Y.%m.%d} · 세계의 진보와 돌파구 소식 {total}건</p></header>
<div class="brief"><span class="bl">📌 이번 호 TOP {len(highlights)}</span> {brief}</div>
<nav class="toc">{toc}</nav>
{secs}
<footer>자동 수집된 헤드라인입니다. 자세한 내용과 사실 여부는 원문 기사에서 확인하세요.<br>
생성: {now:%Y-%m-%d %H:%M}{f' · <a href="{archive_href}">📚 지난 호 보기</a>' if archive_href else ""}</footer></div>
<button id="top" title="맨 위로" aria-label="맨 위로">↑</button>
<script>
const b=document.getElementById('top');
addEventListener('scroll',()=>b.classList.toggle('show',scrollY>400));
b.onclick=()=>scrollTo({{top:0,behavior:'smooth'}});
</script></body></html>"""

def write_archive_index(arch: Path) -> None:
    files = sorted((p for p in arch.glob("????-??-??.html")), reverse=True)
    rows = "".join(f'<a class="card" href="{p.name}">☀️ {p.stem} 호</a>' for p in files)
    (arch / "index.html").write_text(f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>지난 호 모음</title>
<style>{CSS} a.card{{color:var(--ink);text-decoration:none;font-weight:600;margin:8px 0}}</style></head>
<body><div class="wrap" style="max-width:720px"><header><h1>📚 지난 호 모음</h1>
<p><a href="../" style="color:var(--accent)">← 최신 호로</a></p></header>{rows}</div></body></html>""", encoding="utf-8")


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="긍정적·진취적인 세계 뉴스 뉴스레터 생성기")
    ap.add_argument("--days", type=int, default=7, help="최근 며칠 이내 기사만 (기본 7일)")
    ap.add_argument("--per-cat", type=int, default=12, help="카테고리별 최대 기사 수")
    ap.add_argument("--min-score", type=int, default=3, help="긍정 점수 최소값 (높을수록 엄격)")
    ap.add_argument("--highlights", type=int, default=10, help="하이라이트 개수")
    ap.add_argument("--out", default=None, help="출력 HTML 경로")
    ap.add_argument("--no-open", action="store_true", help="브라우저 자동 열기 끄기")
    ap.add_argument("--no-ai", action="store_true", help="Claude Code 한국어 요약 끄기")
    ap.add_argument("--site", default=None, help="웹 게시용 폴더 (index.html + archive/ 생성)")
    a = ap.parse_args()

    global SEARCH_WINDOW
    SEARCH_WINDOW = f"{a.days + 1}d" if a.days <= 30 else "1y"
    t0 = time.time()
    groups, highlights = process(collect(), a.days, a.per_cat, a.min_score, a.highlights + 5)  # 중복 대비 여유분
    if not a.no_ai:
        summarize_ko(highlights)
    highlights = [h for h in highlights if not h.get("dup")][: a.highlights]

    if a.site:
        site = Path(a.site)
        arch = site / "archive"
        arch.mkdir(parents=True, exist_ok=True)
        (arch / f"{datetime.now():%Y-%m-%d}.html").write_text(
            render(groups, highlights, a.days, archive_href="./"), encoding="utf-8")
        out = site / "index.html"
        out.write_text(render(groups, highlights, a.days, archive_href="archive/"), encoding="utf-8")
        write_archive_index(arch)
    else:
        out_dir = Path(__file__).parent / "newsletters"
        out_dir.mkdir(exist_ok=True)
        out = Path(a.out) if a.out else out_dir / f"newsletter_{datetime.now():%Y%m%d}.html"
        out.write_text(render(groups, highlights, a.days), encoding="utf-8")
    print(f"✅ 완료 ({time.time() - t0:.1f}초): {out.resolve()}")
    if not a.no_open:
        webbrowser.open(out.resolve().as_uri())


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    main()
