from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MappingResult:
    department: str
    cost_group: str
    account_subject: str
    reason: str


MANUFACTURING_DEPARTMENTS = {
    "신성장사업본부",
    "솔루션사업본부",
    "전력인프라본부",
    "시스템사업본부",
    "YI ENG KFT",
    "생산팀",
    "해상풍력사업실",
    "사업개발실",
    "태양광사업실",
    "전력계통팀",
    "해외사업실",
}
SGA_DEPARTMENTS = {
    "임원실",
    "사업관리실",
    "기술연구소",
    "품질안전실",
    "전략기획실",
    "경영지원본부",
    "국책과제",
    "영업팀",
    "관리팀",
}
RND_DEPARTMENTS = {"기술연구소", "국책과제", "연구팀"}
RND_CARD_NUMBERS = {
    "4140031641394935",
    "4140031648533964",
    "4140031514183902",
}
FORCED_RND_USERS = {"김형래"}
FORCED_MANUFACTURING_USERS = {
    "김민선",
    "민병문",
    "이백석",
    "이영준",
    "이현호",
    "김종화",
    "김인재",
    "정종원",
    "남기헌",
}
MEAL_HINT_KEYWORDS = [
    "식당",
    "음식점",
    "한식",
    "중식",
    "일식",
    "국밥",
    "칼국수",
    "김밥",
    "치킨",
    "피자",
    "버거",
    "족발",
    "보쌈",
    "횟집",
]
CAFE_HINT_KEYWORDS = ["스타벅스", "투썸", "커피", "파스쿠찌", "베이커리", "카페", "디저트"]


def _normalize_card_number(card_no: str) -> str:
    return "".join(ch for ch in str(card_no or "") if ch.isdigit())


def _resolve_department(user_name: str, org_chart: dict) -> tuple[str, str]:
    users = org_chart.get("users", {})
    if user_name in users:
        dept = users[user_name].get("department", "미지정")
        return dept, "조직도 사용자 매핑"
    return "미지정", "조직도 미매핑(기본값)"


def _resolve_prefix(department: str) -> tuple[str, str]:
    if department in MANUFACTURING_DEPARTMENTS:
        return "제조", "제조 부문 접두어"
    if department in SGA_DEPARTMENTS:
        return "판관", "판관 부문 접두어"
    return "판관", "미분류 부서 기본 접두어"


def _resolve_project_outsourcing(project_type: str) -> tuple[str | None, str]:
    p = (project_type or "").lower()
    if "제품" in p:
        return "(제조)외주가공비(제품PJT)", "제품 프로젝트 외주비 규칙"
    if "용역" in p:
        return "(제조)외주용역비(용역PJT)", "용역 프로젝트 외주비 규칙"
    if "공사" in p:
        return "(제조)외주공사비(공사PJT)", "공사 프로젝트 외주비 규칙"
    return None, ""


def _resolve_keyword_subject(merchant_name: str, merchant_category: str) -> tuple[str | None, str]:
    merchant_l = (merchant_name or "").lower()
    category_l = (merchant_category or "").lower()
    merged = f"{merchant_l} {category_l}"

    # 주차/파킹은 규칙 B(여비교통비)로 우선 분류한다.
    if any(k in merged for k in ["주차", "하이파킹", "아이파킹", "parking"]):
        return "여비교통비", "주차/파킹 키워드 규칙(여비교통비)"
    if any(k in merged for k in ["후불하이패스", "한국도로공사", "주유소", "에너지", "시설관리공단"]):
        return "차량유지비", "차량유지비 키워드 규칙"
    if any(
        k in merged
        for k in [
            "에스알",
            "srt",
            "한국철도공사",
            "ktx",
            "아이파킹",
            "쏘카",
            "socar",
            "택시",
            "카카오t",
            "티머니택시",
            "호텔",
            "xym",
            "숙박",
            "여기어때",
        ]
    ):
        return "여비교통비", "출장/교통 키워드 규칙"
    if any(k in merged for k in (MEAL_HINT_KEYWORDS + CAFE_HINT_KEYWORDS)):
        return "복리후생비", "식대/간식 키워드 규칙"
    if any(k in merged for k in ["openai", "chatgpt", "scribd", "dgmarket", "microsoft"]):
        return "지급수수료", "SaaS/구독 키워드 규칙"
    if "우체국" in merged or "우정사업본부" in merged:
        if "택배" in merged:
            return "운반비", "우체국 택배비 규칙"
        return "통신비", "우체국 우편요금 규칙"
    if any(k in merged for k in ["시청", "군청", "지자체세입금"]):
        return "세금과공과", "지자체 세금 키워드 규칙"
    if any(k in merged for k in ["인쇄", "현수막", "교보문고"]):
        return "도서인쇄비", "인쇄/도서 키워드 규칙"
    return None, ""


def classify_account(
    user_name: str,
    merchant_name: str,
    merchant_category: str,
    org_chart: dict,
    account_rules: dict,
    project_type: str = "",
    card_no: str = "",
) -> MappingResult:
    department, dept_reason = _resolve_department(user_name, org_chart)
    dept_rules = account_rules.get("department_rules", {})
    default_rule = account_rules.get("default", {})
    category_overrides = account_rules.get("category_overrides", {})

    matched_override = None
    for keyword, rule in category_overrides.items():
        if keyword.lower() in (merchant_category or "").lower():
            matched_override = rule
            break

    normalized_card = _normalize_card_number(card_no)
    keyword_subject, keyword_reason = _resolve_keyword_subject(merchant_name, merchant_category)

    if user_name in FORCED_RND_USERS or normalized_card in RND_CARD_NUMBERS:
        subject = keyword_subject or "경상연구개발비"
        if not subject.startswith("(판관)경상연구개발비"):
            subject = f"(판관)경상연구개발비_{subject}"
        return MappingResult(
            department=department,
            cost_group="판매비와관리비",
            account_subject=subject,
            reason=f"{dept_reason} + 연구소 전용 우선순위(카드/사용자) + {keyword_reason or '기본 연구개발비'}",
        )

    if user_name in FORCED_MANUFACTURING_USERS:
        prefix, prefix_reason = "제조", "우선순위 사용자별 제조원가 경비 규칙"
    else:
        prefix, prefix_reason = _resolve_prefix(department)
    project_account, project_reason = _resolve_project_outsourcing(project_type)

    if project_account and "외주" in f"{merchant_name} {merchant_category}":
        return MappingResult(
            department=department,
            cost_group="제조원가",
            account_subject=project_account,
            reason=f"{dept_reason} + {project_reason}",
        )

    if matched_override:
        subject = matched_override.get("account_subject", default_rule.get("account_subject", "복리후생비"))
        return MappingResult(
            department=department,
            cost_group=matched_override.get("cost_group", default_rule.get("cost_group", "판매비와관리비")),
            account_subject=f"({prefix}){subject}" if not str(subject).startswith("(") else str(subject),
            reason=f"{dept_reason} + 업종 예외룰 + {prefix_reason}",
        )

    if keyword_subject:
        return MappingResult(
            department=department,
            cost_group="제조원가" if prefix == "제조" else "판매비와관리비",
            account_subject=f"({prefix}){keyword_subject}",
            reason=f"{dept_reason} + {keyword_reason} + {prefix_reason}",
        )

    rule = dept_rules.get(department, default_rule)
    subject = rule.get("account_subject", "복리후생비")
    if department in RND_DEPARTMENTS:
        subject = f"(판관)경상연구개발비_{subject}"
        rnd_reason = "연구소/국책과제 전용 계정 규칙"
    else:
        subject = f"({prefix}){subject}" if not str(subject).startswith("(") else str(subject)
        rnd_reason = prefix_reason

    return MappingResult(
        department=department,
        cost_group=rule.get("cost_group", "판매비와관리비"),
        account_subject=subject,
        reason=f"{dept_reason} + 부서 기본룰 + {rnd_reason}",
    )
