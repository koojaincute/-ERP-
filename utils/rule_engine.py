from __future__ import annotations

import re


VEHICLE_TOLL_KEYWORDS = ["후불하이패스", "한국도로공사"]
VEHICLE_FUEL_KEYWORDS = ["주유소", "에너지", "oil", "gas", "주유"]
VEHICLE_PARKING_KEYWORDS = ["주차", "하이파킹", "시설관리공단", "parking"]
TRAIN_RENT_KEYWORDS = ["에스알", "srt", "한국철도공사", "ktx", "쏘카", "socar", "렌트", "렌터카"]
TAXI_KEYWORDS = ["택시", "카카오t", "티머니택시"]
STAY_KEYWORDS = ["호텔", "숙박", "여기어때", "xym", "motel"]
MEAL_KEYWORDS = ["식당", "음식점", "한식", "중식", "일식", "레스토랑", "meal", "restaurant"]
CAFE_KEYWORDS = ["스타벅스", "투썸", "커피", "파스쿠찌", "베이커리", "카페", "coffee"]
MEAL_MERCHANT_HINTS = ["국밥", "칼국수", "김밥", "치킨", "피자", "버거", "족발", "보쌈", "횟집", "식당"]
ENTERTAINMENT_KEYWORDS = ["골프", "유흥", "클럽", "bar", "룸", "접대"]
TAX_EXEMPT_KEYWORDS = ["면세", "의료", "병원", "약국", "교육기관", "간이과세"]
POST_OFFICE_TAXABLE_KEYWORDS = ["택배", "운반", "parcel"]
POST_OFFICE_EXEMPT_KEYWORDS = ["우편", "등기", "ems", "소포", "stamp", "우표"]
TRANSPORT_NON_DEDUCTIBLE = ["항공", "비행", "ktx", "srt", "고속버스", "택시"]
TRANSPORT_DEDUCTIBLE = ["전세버스"]
FOREIGN_USE_KEYWORDS = ["overseas", "해외", "국외"]
LIGHT_VEHICLE_KEYWORDS = ["경차", "1000cc", "125cc", "9인승", "화물차", "라보", "다마스"]
PASSENGER_CAR_KEYWORDS = ["승용차", "8인승", "개별소비세"]
SAAS_KEYWORDS = ["openai", "chatgpt", "scribd", "dgmarket", "microsoft"]
LAND_RELATED_KEYWORDS = ["토지", "형질", "자본적", "취득", "조성"]


def _extract_keywords_in_section(policy_text: str, section_header: str) -> list[str]:
    if not policy_text:
        return []
    lines = policy_text.splitlines()
    in_section = False
    collected: list[str] = []
    for line in lines:
        s = line.strip()
        if s.startswith("### "):
            in_section = section_header in s
            continue
        if in_section and ("키워드" in s or "->" in s):
            collected.extend(re.findall(r"'([^']+)'", s))
    return [k.strip().lower() for k in collected if k.strip()]


def _build_dynamic_keywords(policy_text: str) -> dict[str, list[str]]:
    return {
        "vehicle": _extract_keywords_in_section(policy_text, "A. 차량유지비"),
        "travel": _extract_keywords_in_section(policy_text, "B. 여비교통비"),
        "meal": _extract_keywords_in_section(policy_text, "C. 복리후생비"),
        "supply_fee": _extract_keywords_in_section(policy_text, "D. 지급수수료"),
    }


def infer_summary_by_rules(
    merchant: str,
    category: str,
    hour: int,
    user_name: str = "",
    policy_text: str = "",
) -> tuple[str, str]:
    merchant_l = (merchant or "").lower()
    category_l = (category or "").lower()
    merged = f"{merchant_l} {category_l}"
    dynamic = _build_dynamic_keywords(policy_text)
    dynamic_vehicle = dynamic.get("vehicle", [])
    dynamic_travel = dynamic.get("travel", [])
    dynamic_meal = dynamic.get("meal", [])
    dynamic_saas = dynamic.get("supply_fee", [])

    if any(k in merged for k in (VEHICLE_TOLL_KEYWORDS + dynamic_vehicle)):
        return "법인차량 통행료", "규칙: 차량 통행료 키워드"
    if any(k in merged for k in VEHICLE_FUEL_KEYWORDS):
        return "법인차량 주유", "규칙: 차량 주유 키워드"
    if any(k in merged for k in (VEHICLE_PARKING_KEYWORDS + ["아이파킹"])):
        return "법인차량 주차대", "규칙: 차량 주차 키워드"

    if any(k in merged for k in (TRAIN_RENT_KEYWORDS + dynamic_travel)):
        name = user_name.strip() or "사용자"
        return f"{name} 출장 기차료/렌트카 이용료", "규칙: 출장 기차/렌트 키워드"
    if any(k in merged for k in TAXI_KEYWORDS):
        return "시내 출장 택시비", "규칙: 택시 키워드"
    if any(k in merged for k in STAY_KEYWORDS):
        return "출장 숙박비", "규칙: 숙박 키워드"

    if any(k in merged for k in CAFE_KEYWORDS):
        return "간식대(차대)", "규칙: 카페/베이커리 키워드"
    meal_detected = any(k in merged for k in (MEAL_KEYWORDS + MEAL_MERCHANT_HINTS + dynamic_meal))
    if 11 <= hour <= 13 and meal_detected:
        return "중식대", "규칙: 11:30~13:30 식대 시간대"
    if hour >= 18 and meal_detected:
        return "야근 식대", "규칙: 18:30 이후 식대 시간대"
    if meal_detected:
        return "식대", "규칙: 식음료 키워드"

    if any(k in merged for k in (SAAS_KEYWORDS + dynamic_saas)):
        return "SaaS/유료자료 정기구독료", "규칙: SaaS/구독 키워드"

    return "업무 관련 비용", "규칙: 기본값"


def infer_vat_by_rules(
    merchant: str,
    category: str,
    policy_text: str,
    amount: float = 0,
) -> tuple[str, str]:
    # NOTE:
    # policy_text contains the full rule document and must NOT be mixed into
    # keyword matching. Otherwise every row can match unrelated keywords from
    # the document and become over-classified as 불공제.
    merged = f"{merchant} {category}".lower()
    dynamic = _build_dynamic_keywords(policy_text)
    dynamic_vehicle = dynamic.get("vehicle", [])
    dynamic_travel = dynamic.get("travel", [])
    dynamic_meal = dynamic.get("meal", [])
    dynamic_saas = dynamic.get("supply_fee", [])

    has_post_office = ("우체국" in merged) or ("우정사업본부" in merged)
    has_transport = any(k in merged for k in (TRANSPORT_NON_DEDUCTIBLE + dynamic_travel))
    has_charter_bus = any(k in merged for k in TRANSPORT_DEDUCTIBLE)
    has_stay = any(k in merged for k in STAY_KEYWORDS)
    has_meal_or_snack = any(k in merged for k in (MEAL_KEYWORDS + CAFE_KEYWORDS + MEAL_MERCHANT_HINTS + dynamic_meal))
    has_vehicle_maintenance = any(
        k in merged for k in (VEHICLE_TOLL_KEYWORDS + VEHICLE_FUEL_KEYWORDS + VEHICLE_PARKING_KEYWORDS + dynamic_vehicle)
    )
    has_light_vehicle = any(k in merged for k in LIGHT_VEHICLE_KEYWORDS)
    has_passenger_car = any(k in merged for k in PASSENGER_CAR_KEYWORDS)
    has_tax_exempt_merchant = any(k in merged for k in TAX_EXEMPT_KEYWORDS)

    # [불공제 우선] YES/규칙 67~74
    if has_post_office and any(k in merged for k in POST_OFFICE_EXEMPT_KEYWORDS):
        return "불공제", "규칙: 우체국 우편요금(면세) 불공제"
    if any(k in merged for k in FOREIGN_USE_KEYWORDS):
        return "불공제", "규칙: 국외 사용액 불공제"
    if has_transport and not has_charter_bus:
        return "불공제", "규칙: 여객운송(항공/KTX/SRT/고속버스/택시) 불공제"
    if has_passenger_car or (has_vehicle_maintenance and not has_light_vehicle):
        return "불공제", "규칙: 일반 승용차 관련 유지비 불공제"
    if any(k in merged for k in ENTERTAINMENT_KEYWORDS):
        return "불공제", "규칙: 접대비/유흥성 불공제"
    if amount >= 100000 and has_meal_or_snack:
        return "불공제", "규칙: 10만원 이상 식대(접대성) 불공제"
    if has_tax_exempt_merchant:
        return "불공제", "규칙: 면세/간이과세자 거래 불공제"
    if any(k in merged for k in LAND_RELATED_KEYWORDS):
        return "불공제", "규칙: 토지 관련 자본적 지출 불공제"
    if any(k in merged for k in (SAAS_KEYWORDS + dynamic_saas)):
        return "불공제", "규칙: 해외/구독형 SaaS 사용 불공제"

    # [공제] YES/규칙 60~65
    if has_post_office and any(k in merged for k in POST_OFFICE_TAXABLE_KEYWORDS):
        # 개인카드 여부를 직접 식별할 필드가 없으므로, 관련 키워드가 있으면 보수적으로 불공제 처리
        if "개인카드" in merged or "개인" in merged:
            return "불공제", "규칙: 우체국 택배비(개인카드) 불공제"
        return "공제", "규칙: 우체국 택배비(운반비) 공제"
    if has_light_vehicle:
        return "공제", "규칙: 경차/특수차 유지비 공제"
    if has_stay:
        return "공제", "규칙: 숙박비 공제"
    if has_charter_bus:
        return "공제", "규칙: 전세버스 이용료 공제"
    if has_meal_or_snack:
        return "공제", "규칙: 종업원 복리후생비(식대/간식) 공제"

    return "공제", "규칙: 기타 일반 과세 매입 공제"
