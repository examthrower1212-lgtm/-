import json
import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests


# =========================================================
# 설정
# =========================================================

BRANCH_CODE = "0028"       # 대전신세계아트앤사이언스
THEATER_CODE = "DBC"       # Dolby Cinema

# ""이면 돌비 전체 영화 감시
# "오디세이"라고 쓰면 영화명에 '오디세이'가 들어간 회차만 알림
TARGET_KEYWORD = ""

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
# 기본 도구
# =========================================================

def send_discord(message):
    webhook_url = os.environ.get("WEBHOOK")

    if not webhook_url:
        raise RuntimeError(
            "WEBHOOK 환경변수가 없습니다. GitHub Secret을 확인하세요."
        )

    response = requests.post(
        webhook_url,
        json={"content": message},
        timeout=20,
    )

    response.raise_for_status()


def make_session():
    session = requests.Session()

    user_agent = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    )

    session.headers.update({
        "User-Agent": user_agent,
        "Accept-Language": "ko-KR,ko;q=0.9",
    })

    # 메가박스 세션/쿠키 생성
    session.get(
        BOOKING_PAGE,
        timeout=20,
    )

    return session


def request_megabox(session, play_date):
    payload = {
        "arrMovieNo": "",
        "playDe": play_date,

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
        "Content-Type": "application/json; charset=UTF-8",
        "Origin": "https://www.megabox.co.kr",
        "Referer": BOOKING_PAGE,
        "X-Requested-With": "XMLHttpRequest",
    }

    response = session.post(
        API_URL,
        json=payload,
        headers=headers,
        timeout=20,
    )

    response.raise_for_status()

    text = response.content.decode("utf-8-sig")

    return json.loads(text)


def get_list(data, key):
    """
    메가박스 응답 구조가 약간 달라져도
    top-level / megaMap 양쪽을 모두 확인합니다.
    """

    if key in data:
        return data.get(key) or []

    mega_map = data.get("megaMap") or {}

    return mega_map.get(key) or []


# =========================================================
# 상영 날짜 조회
# =========================================================

def get_available_dates(session):
    today = datetime.now(
        ZoneInfo("Asia/Seoul")
    ).strftime("%Y%m%d")

    data = request_megabox(
        session,
        today,
    )

    date_items = get_list(
        data,
        "movieFormDeList",
    )

    dates = sorted({
        str(item.get("playDe"))
        for item in date_items
        if item.get("playDe")
        and str(item.get("playDe")) >= today
    })

    if not dates:
        raise RuntimeError(
            "대전신세계 돌비 상영 날짜를 찾지 못했습니다."
        )

    print(
        f"조회 가능한 날짜: {dates}"
    )

    return dates


# =========================================================
# 상영회차 조회
# =========================================================

def normalize_time(value):
    value = str(value or "").strip()

    # 1030 → 10:30
    if len(value) == 4 and value.isdigit():
        return f"{value[:2]}:{value[2:]}"

    # 이미 10:30 형태라면 그대로 사용
    return value


def get_all_sessions():
    session = make_session()

    dates = get_available_dates(session)

    sessions = []

    for date in dates:
        data = request_megabox(
            session,
            date,
        )

        movie_list = get_list(
            data,
            "movieFormList",
        )

        print(
            f"{date}: {len(movie_list)}개 회차 발견"
        )

        for item in movie_list:

            play_schedule_no = str(
                item.get("playSchdlNo") or ""
            ).strip()

            movie_name = str(
                item.get("movieNm")
                or item.get("rpstMovieNm")
                or "영화명 없음"
            ).strip()

            play_date = str(
                item.get("playDe")
                or date
            ).strip()

            start_time = normalize_time(
                item.get("playStartTime")
            )

            end_time = normalize_time(
                item.get("playEndTime")
            )

            theater_name = str(
                item.get("theabExpoNm")
                or ""
            ).strip()

            # 필요하다면 특정 영화만 필터링 가능
            if (
                TARGET_KEYWORD
                and TARGET_KEYWORD.lower()
                not in movie_name.lower()
            ):
                continue

            # 정상적으로는 playSchdlNo가 존재함.
            # 혹시 없을 때를 대비한 fallback ID.
            if play_schedule_no:
                session_id = play_schedule_no
            else:
                session_id = (
                    f"{play_date}|"
                    f"{movie_name}|"
                    f"{start_time}|"
                    f"{theater_name}"
                )

            sessions.append({
                "id": session_id,
                "playSchdlNo": play_schedule_no,
                "date": play_date,
                "movie": movie_name,
                "start": start_time,
                "end": end_time,
                "theater": theater_name,
            })

    if not sessions:
        raise RuntimeError(
            "돌비 상영회차를 하나도 찾지 못했습니다."
        )

    # 혹시 같은 회차가 중복으로 들어올 경우 제거
    unique_sessions = {
        item["id"]: item
        for item in sessions
    }

    sessions = list(
        unique_sessions.values()
    )

    sessions.sort(
        key=lambda x: (
            x["date"],
            x["start"],
            x["movie"],
        )
    )

    print(
        f"총 {len(sessions)}개 돌비 회차 확인"
    )

    return sessions


# =========================================================
# state.json
# =========================================================

def load_state():
    if not STATE_FILE.exists():
        return {
            "initialized": False,
            "seen_sessions": [],
        }

    with STATE_FILE.open(
        "r",
        encoding="utf-8",
    ) as f:
        state = json.load(f)

    # 기존 날짜 기반 state.json 자동 변환
    if "seen_sessions" not in state:
        print(
            "기존 날짜 기반 state.json을 "
            "회차 기반 방식으로 전환합니다."
        )

        return {
            "initialized": False,
            "seen_sessions": [],
        }

    return state


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
# 표시용 함수
# =========================================================

def pretty_date(date_string):
    try:
        dt = datetime.strptime(
            date_string,
            "%Y%m%d",
        )

        weekday = [
            "월", "화", "수", "목",
            "금", "토", "일"
        ][dt.weekday()]

        return (
            f"{dt.year}년 "
            f"{dt.month}월 "
            f"{dt.day}일 ({weekday})"
        )

    except ValueError:
        return date_string


# =========================================================
# Discord 신규회차 알림
# =========================================================

def notify_new_sessions(new_sessions):

    # 날짜 + 영화별로 묶음
    groups = defaultdict(list)

    for session in new_sessions:
        key = (
            session["date"],
            session["movie"],
        )

        groups[key].append(session)

    for (date, movie), group in sorted(
        groups.items()
    ):

        group.sort(
            key=lambda x: x["start"]
        )

        times = " / ".join(
            item["start"]
            for item in group
        )

        theater_names = {
            item["theater"]
            for item in group
            if item["theater"]
        }

        theater_text = ""

        if theater_names:
            theater_text = (
                "\n🎦 "
                + ", ".join(
                    sorted(theater_names)
                )
            )

        message = (
            "🚨 **대전신세계 돌비 신규 회차 오픈**\n\n"
            f"📅 **{pretty_date(date)}**\n"
            f"🎬 **{movie}**\n"
            f"🕒 **{times}**"
            f"{theater_text}\n\n"
            f"🎟️ {BOOKING_URL}"
        )

        send_discord(message)

        print(
            f"알림 전송: "
            f"{date} / {movie} / {times}"
        )


# =========================================================
# 메인
# =========================================================

def main():

    test_mode = os.environ.get(
        "TEST_MODE",
        "false",
    ).lower()

    if test_mode == "true":
        send_discord(
            "✅ **대돌비 알리미 테스트 성공**\n"
            "GitHub Actions와 Discord Webhook이 "
            "정상적으로 연결되었습니다."
        )

        print("Discord 테스트 성공")
        return

    current_sessions = get_all_sessions()

    state = load_state()

    current_ids = {
        item["id"]
        for item in current_sessions
    }

    # 회차 기반 감시를 처음 시작하는 경우
    # 현재 존재하는 모든 회차를 기준값으로 저장
    if not state.get("initialized", False):

        save_state({
            "initialized": True,
            "seen_sessions": sorted(
                current_ids
            ),
        })

        print(
            "회차 단위 감시를 처음 시작합니다."
        )

        print(
            f"현재 {len(current_ids)}개 회차를 "
            "기준값으로 저장했습니다."
        )

        print(
            "최초 실행이므로 Discord 알림은 보내지 않습니다."
        )

        return

    seen_ids = set(
        state.get(
            "seen_sessions",
            [],
        )
    )

    new_ids = (
        current_ids - seen_ids
    )

    new_sessions = [
        item
        for item in current_sessions
        if item["id"] in new_ids
    ]

    if not new_sessions:
        print(
            "새로운 돌비 상영회차가 없습니다."
        )

        return

    print(
        f"신규 회차 {len(new_sessions)}개 발견!"
    )

    # Discord 전송
    notify_new_sessions(
        new_sessions
    )

    # Discord 전송 성공 후에만 기록
    seen_ids.update(
        new_ids
    )

    save_state({
        "initialized": True,
        "seen_sessions": sorted(
            seen_ids
        ),
    })


if __name__ == "__main__":
    main()
