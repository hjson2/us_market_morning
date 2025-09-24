import os
import sys
import json
import math
import time
from datetime import datetime, timedelta, timezone
from dateutil import tz
import pandas as pd
import yfinance as yf
import feedparser
import yaml
from jinja2 import Template

# --- 설정 ---
OUTPUT_DIR = "site"
REPORT_TITLE = "미국 증시 마감 요약 & 주요 뉴스"
TIMEZONE_KST = tz.gettz("Asia/Seoul")
NOW_KST = datetime.now(TIMEZONE_KST)
RUN_AT = NOW_KST.strftime("%Y-%m-%d %H:%M KST")

# 추적 지수/지표(전일 대비 %)
# ^TNX는 10배 스케일(예: 42.5 = 4.25%), 표시 시 /10
TICKERS = {
    "^GSPC": "S&P 500",
    "^IXIC": "NASDAQ",
    "^DJI": "Dow Jones",
    "^VIX":  "VIX",
    "^TNX":  "US 10Y"
}

NEWS_LIMIT = 12  # 보여줄 뉴스 항목 수
NEWS_PER_SOURCE = 5  # 각 피드에서 최대 n개까지

DISCLAIMER = "본 자료는 교육/정보 제공 목적이며 투자권유가 아닙니다."

# --- 유틸 ---
def pct(a, b):
    try:
        return (a/b - 1.0) * 100.0
    except Exception:
        return float("nan")

def safe_first_sentence(text: str, max_chars=220):
    if not text:
        return ""
    s = text.strip().replace("\n", " ").replace("  ", " ")
    # 간단 요약: 첫 문장 또는 최대 글자수
    dot = s.find(". ")
    if 0 < dot < max_chars:
        s = s[:dot+1]
    return s[:max_chars]

def fetch_prices():
    # 최근 10일 일봉 로드 → 전일/당일 종가 계산에 안정적
    data = yf.download(list(TICKERS.keys()), period="10d", interval="1d", group_by='ticker', progress=False)
    rows = []
    for tk, label in TICKERS.items():
        try:
            df = data[tk] if isinstance(data.columns, pd.MultiIndex) else data
            df = df.dropna()
            if len(df) < 2:
                continue
            last_two = df["Close"].tail(2).tolist()
            prev_close, last_close = last_two[-2], last_two[-1]
            change = pct(last_close, prev_close)
            # 10년물 표시 조정
            display_last = last_close/10.0 if tk == "^TNX" else last_close
            rows.append({
                "ticker": tk,
                "name": label,
                "last": round(display_last, 2),
                "chgpct": round(change, 2),
            })
        except Exception as e:
            print(f"[WARN] fetch {tk}: {e}", file=sys.stderr)
    return rows

def fetch_news():
    # RSS 목록 읽기
    yaml_path = os.path.join(os.path.dirname(__file__), "rss_sources.yaml")
    with open(yaml_path, "r", encoding="utf-8") as f:
        feeds = yaml.safe_load(f)["feeds"]

    items = []
    for feed in feeds:
        try:
            parsed = feedparser.parse(feed["url"])
            count = 0
            for e in parsed.entries:
                if count >= NEWS_PER_SOURCE:
                    break
                title = e.get("title", "")
                link = e.get("link", "")
                summary = e.get("summary", "") or e.get("description", "")
                source = feed["name"]
                if not title or not link:
                    continue
                items.append({
                    "title": title.strip(),
                    "link": link.strip(),
                    "source": source,
                    "summary": safe_first_sentence(summary),
                })
                count += 1
        except Exception as e:
            print(f"[WARN] rss {feed['name']}: {e}", file=sys.stderr)

    # 간단 중복 제거(제목 기준)
    seen = set()
    dedup = []
    for it in items:
        key = it["title"].lower()
        if key in seen:
            continue
        seen.add(key)
        dedup.append(it)
    return dedup[:NEWS_LIMIT]

def render_html(title, when_kst, indices, news):
    template = Template("""
<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>{{ title }}</title>
  <style>
    body{font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, "Apple Color Emoji","Segoe UI Emoji"; margin: 24px; line-height:1.45}
    h1{font-size: 1.6rem; margin-bottom: 4px;}
    .meta{color:#666; margin-bottom: 20px;}
    table{border-collapse: collapse; width: 100%; margin: 10px 0 24px}
    th, td{border:1px solid #ddd; padding:8px; text-align:left}
    th{background:#fafafa}
    .chp{font-variant-numeric: tabular-nums;}
    .up{color:#0a7b00;font-weight:600}
    .dn{color:#b00020;font-weight:600}
    .badge{display:inline-block; padding:2px 8px; border-radius:12px; background:#f1f1f1; font-size:12px; margin-left:6px}
    .news-item{margin:10px 0 14px}
    .footer{margin-top: 28px; color:#666; font-size: 12px;}
    a{color:#0645ad; text-decoration:none}
    a:hover{text-decoration:underline}
  </style>
</head>
<body>
  <h1>{{ title }}</h1>
  <div class="meta">생성 시각: {{ when_kst }}</div>

  <h2>지수/지표 요약</h2>
  <table>
    <thead>
      <tr><th>지수</th><th>종가</th><th>등락률</th></tr>
    </thead>
    <tbody>
      {% for r in indices %}
      <tr>
        <td>{{ r.name }}</td>
        <td class="chp">{{ r.last }}</td>
        <td class="chp {% if r.chgpct>=0 %}up{% else %}dn{% endif %}">{{ "%+.2f"|format(r.chgpct) }}%</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>

  <h2>핵심 뉴스 (자동 큐레이션)</h2>
  {% for n in news %}
    <div class="news-item">
      <a href="{{ n.link }}" target="_blank" rel="noopener">{{ n.title }}</a>
      <span class="badge">{{ n.source }}</span>
      {% if n.summary %}<div>{{ n.summary }}</div>{% endif %}
    </div>
  {% endfor %}

  <div class="footer">
    <hr/>
    <div>면책: {{ disclaimer }}</div>
    <div>ⓒ 자동 생성 리포트</div>
  </div>
</body>
</html>
    """)
    return template.render(
        title=title,
        when_kst=when_kst,
        indices=indices,
        news=news,
        disclaimer=DISCLAIMER
    )

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    indices = fetch_prices()
    news = fetch_news()

    html = render_html(
        title=REPORT_TITLE,
        when_kst=RUN_AT,
        indices=indices,
        news=news
    )

    # index.html로 저장(매일 덮어씀) + 날짜별 보관 파일도 생성
    out_index = os.path.join(OUTPUT_DIR, "index.html")
    with open(out_index, "w", encoding="utf-8") as f:
        f.write(html)

    dated = NOW_KST.strftime("%Y-%m-%d")
    out_archive = os.path.join(OUTPUT_DIR, f"{dated}.html")
    with open(out_archive, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"[OK] Wrote {out_index} and {out_archive}")

if __name__ == "__main__":
    main()
