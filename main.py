import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests


# =========================================================
# 기본 설정
# =========================================================

BRANCH_CODE = "0028"       # 대전신세계아트앤사이언스
THEATER_CODE = "DBC"       # Dolby Cinema

STATE_FILE = Path("state.json")

BOOKING_PAGE = (
    "https://www.megabox.co.kr/on/oh/ohb/"
    "SimpleBooking/simpleBookingPage.do"
)

API_URL = (
    "https://www.megabox.co.kr/on/oh/ohb/"
    "SimpleBooking/selectBokdList.do"
)

BOOKING_URL = "https://www.megabox.co.kr/booking"


# =========================================================
# Discord 알림
# =========================================================

def send_discord(message):
    webhook_url = os.environ.get("WEBHOOK")

    if not webhook_url:
        raise RuntimeError(
            "WEBHOOK 환경변수가 없습니다. GitHub Secret 설정을 확인하세요."
        )

    response = requests.post(
        webhook_url,
        json={"content": message},
        timeout=20,
    )

    response.raise_for_status()


# =========================================================
# 메가박스 조회
# =========================================================

def get_dolby_dates():
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    today = now.strftime("%Y%m%d")

    session = requests.Session()

    user_agent = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    )

    # 먼저 메가박스 페이지에 접속하여 세션/쿠키 생성
    session.get(
        BOOKING_PAGE,
        params={
            "rpstMovieNo": "",
            "theabKindCode1": THEATER_CODE,
            "brchNo1": BRANCH_CODE,
            "sellChnlCd": "",
            "playDe": today,
            "naverPlaySchdlNo": "",
        },
        headers={
            "User-Agent": user_agent,
            "Accept-Language": "ko-KR,ko;q=0.9",
        },
        timeout=20,
    )

    payload = {
        "arrMovieNo": "",
        "playDe": today,

        "brchNoListCnt": 1,

        "brchNo1": BRANCH_CODE,
        "brchNo2": "",
        "brchNo3": "",

        "areaCd1": THEATER_CODE,
        "areaCd2": "",
        "areaCd3": "",

        "spclbYn1": "Y",
        "spclbYn2": "",
        "spclbYn3": "",

        "theabKindCd1": THEATER_CODE,
        "theabKindCd2": "",
        "theabKindCd3": "",

        "brchAll": "",
        "brchSpcl": THEATER_CODE,

        "movieNo1": "",
        "movieNo2": "",
        "movieNo3": "",

        "sellChnlCd": "",
    }

    headers = {
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Content-Type": "application/json; charset=UTF-8",
        "Origin": "https://www.megabox.co.kr",
        "Referer": BOOKING_PAGE,
        "User-Agent": user_agent,
        "X-Requested-With": "XMLHttpRequest",
    }

    response = session.post(
        API_URL,
        json=payload,
        headers=headers,
        timeout=20,
    )

    response.raise_for_status()

    # 메가박스 응답이 BOM을 포함하는 경우까지 처리
    text = response.content.decode("utf-8-sig")
    data = json.loads(text)

    movie_dates = data.get("movieFormDeList") or []

    dates = sorted(
        {
            str(item.get("playDe"))
            for item in movie_dates
            if item.get("playDe")
            and str(item.get("playDe")) >= today
        }
    )

    print(f"메가박스 응답에서 발견된 미래 날짜: {dates}")

    if not dates:
        print(f"응답의 주요 항목: {list(data.keys())}")
        raise RuntimeError(
            "대전신세계 돌비 예매 날짜를 하나도 찾지 못했습니다."
        )

    return dates


# =========================================================
# 상태 저장 / 읽기
# =========================================================

def load_state():
    if not STATE_FILE.exists():
        return {
            "initialized": False,
            "seen_dates": [],
        }

    with STATE_FILE.open(
        "r",
        encoding="utf-8",
    ) as f:
        return json.load(f)


def save_state(state):
    with STATE_FILE.open(
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            state,
            f,
            ensure_ascii=False,
            indent=2,
        )


# =========================================================
# 날짜 표시
# =========================================================

def pretty_date(date_string):
    dt = datetime.strptime(
        date_string,
        "%Y%m%d",
    )

    return dt.strftime("%Y년 %m월 %d일")


# =========================================================
# 메인
# =========================================================

def main():

    # Discord 연결 테스트 모드
    test_mode = os.environ.get(
        "TEST_MODE",
        "false",
    ).lower()

    if test_mode == "true":
        send_discord(
            "✅ **대돌비 알리미 테스트 성공**\n"
            "GitHub Actions와 Discord Webhook이 정상적으로 연결되었습니다."
        )

        print("Discord 테스트 메시지를 전송했습니다.")
        return

    # 현재 대전신세계 Dolby 예매 날짜 조회
    current_dates = get_dolby_dates()

    state = load_state()

    # 최초 실행
    # 현재 열린 날짜를 기준값으로 저장하되 알림은 보내지 않음
    if not state.get("initialized", False):

        state = {
            "initialized": True,
            "seen_dates": current_dates,
        }

        save_state(state)

        print(
            "최초 실행입니다. "
            "현재 예매 날짜를 기준값으로 저장했습니다."
        )

        return

    seen_dates = set(
        state.get("seen_dates", [])
    )

    current_set = set(current_dates)

    # 이전에 없었던 새 날짜
    new_dates = sorted(
        current_set - seen_dates
    )

    if not new_dates:
        print("새로운 예매 날짜가 없습니다.")
        return

    pretty_dates = [
        pretty_date(date)
        for date in new_dates
    ]

    date_text = "\n".join(
        f"• {date}"
        for date in pretty_dates
    )

    message = (
        "🚨 **대전신세계 돌비 예매 오픈 감지**\n\n"
        f"{date_text}\n\n"
        "대전신세계아트앤사이언스 "
        "DOLBY CINEMA에 새로운 예매 날짜가 추가되었습니다.\n\n"
        f"🎟️ {BOOKING_URL}"
    )

    # Discord 전송
    send_discord(message)

    print(
        f"새 날짜 감지 및 Discord 알림 완료: {new_dates}"
    )

    # 알림 전송이 성공한 경우에만 기억
    seen_dates.update(new_dates)

    state = {
        "initialized": True,
        "seen_dates": sorted(seen_dates),
    }

    save_state(state)


if __name__ == "__main__":
    main()
