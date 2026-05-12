from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from inference_engine import infer_summary_and_vat, load_policy_text
from mapping_logic import classify_account
from utils.io_utils import (
    build_output_dataframe,
    dataframe_to_excel_bytes,
    EXTRACT_OUTPUT_COLUMNS,
    load_yaml,
    normalize_card_dataframe,
    read_excel_with_header_detection,
)


BASE_DIR = Path(__file__).parent
DEFAULT_ORG_PATH = BASE_DIR / "config" / "org_chart.yaml"
DEFAULT_ACCOUNT_PATH = BASE_DIR / "config" / "account_rules.yaml"
DEFAULT_POLICY_PATH = BASE_DIR / "config" / "policy_rules.yaml"
DEFAULT_ENV_PATH = BASE_DIR / ".env"
DEFAULT_YES_RULE_PATH = BASE_DIR / "YES" / "규칙"


def process_transactions(
    input_df: pd.DataFrame,
    org_chart: dict,
    account_rules: dict,
    policy_text: str,
    use_llm: bool,
    user_override: str = "",
    department_override: str = "",
) -> pd.DataFrame:
    rows = []
    forced_user = (user_override or "").strip()
    forced_department = (department_override or "").strip()
    for _, row in input_df.iterrows():
        effective_user_name = forced_user or str(row.get("user_name", ""))
        effective_org_chart = org_chart
        if forced_department:
            users = dict(org_chart.get("users", {}))
            users[effective_user_name] = {"department": forced_department}
            effective_org_chart = dict(org_chart)
            effective_org_chart["users"] = users
        merchant_name = str(row.get("merchant_name", ""))
        merchant_category = str(row.get("merchant_category", ""))
        detail_text = str(row.get("summary_text", ""))
        amount = float(row.get("amount", 0) or 0)
        cancel_flag = amount < 0 or any(
            k in f"{merchant_name} {merchant_category} {detail_text}" for k in ["취소", "cancel", "승인취소"]
        )

        mapping = classify_account(
            user_name=effective_user_name,
            merchant_name=merchant_name,
            merchant_category=merchant_category,
            org_chart=effective_org_chart,
            account_rules=account_rules,
            project_type=str(row.get("project_type", "")),
            card_no=str(row.get("card_no_masked", "")),
        )
        dt = row.get("transaction_datetime")
        hour = int(dt.hour) if pd.notna(dt) else 0
        if cancel_flag:
            summary_text = "승인취소"
            vat_deduction = "불공제"
            infer_reason = "취소 거래 예외 규칙 적용"
        else:
            try:
                infer = infer_summary_and_vat(
                    merchant_name=merchant_name,
                    merchant_category=merchant_category,
                    transaction_hour=hour,
                    amount=amount,
                    policy_text=policy_text,
                    user_name=effective_user_name,
                    detail_text=detail_text,
                    use_llm=use_llm,
                )
            except TypeError:
                # Compatibility fallback for older inference_engine signatures.
                infer = infer_summary_and_vat(
                    merchant_name=merchant_name,
                    merchant_category=merchant_category,
                    transaction_hour=hour,
                    amount=amount,
                    policy_text=policy_text,
                    user_name=effective_user_name,
                    use_llm=use_llm,
                )
            summary_text = infer.summary_text
            vat_deduction = infer.vat_deduction
            infer_reason = infer.reason
        new_row = row.copy()
        new_row["department"] = mapping.department
        new_row["cost_group"] = mapping.cost_group
        new_row["account_subject"] = "승인취소" if cancel_flag else mapping.account_subject
        new_row["summary_text"] = summary_text
        new_row["vat_deduction"] = vat_deduction
        new_row["reasoning"] = f"{mapping.reason}; {infer_reason}"
        new_row["evidence_type"] = "신용카드매출전표"
        new_row["user_name"] = effective_user_name
        new_row["is_cancelled"] = cancel_flag
        rows.append(new_row)

    return pd.DataFrame(rows)


def main() -> None:
    load_dotenv(dotenv_path=DEFAULT_ENV_PATH)
    st.set_page_config(page_title="법인카드 ERP 전표 자동화", layout="wide")
    st.markdown(
        """
        <style>
        [data-testid="stHeader"] {
            background: linear-gradient(90deg, #0a5ea8 0%, #0f8a9d 50%, #2bb673 100%);
            border-bottom: 1px solid rgba(255, 255, 255, 0.18);
        }
        [data-testid="stHeader"] * {
            color: #ffffff !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.title("법인카드 ERP 전표 자동화")
    st.caption("엑셀 업로드 -> 계정/적요/부가세 자동 판정 -> ERP 업로드용 엑셀 출력")

    with st.sidebar:
        logo_path = BASE_DIR / "logo.png"
        if logo_path.exists():
            st.image(str(logo_path), use_container_width=True)
        st.subheader("설정")
        use_llm = st.checkbox("LLM 추론 사용(OpenAI)", value=True)
        user_override = st.text_input(
            "사용자명 직접 입력(선택)",
            value="",
            help="입력하면 모든 거래에 해당 사용자명을 우선 적용합니다.",
        )
        department_override = st.text_input(
            "부서 직접 입력(선택)",
            value="",
            help="입력하면 위 사용자명(또는 원본 사용자명)의 부서를 우선 적용합니다.",
        )
        import os

        has_api_key = bool(os.getenv("OPENAI_API_KEY"))
        st.caption("API 키는 `.env` 파일에서 로드됩니다.")
        st.write(f"OPENAI_API_KEY 로드 상태: {'설정됨' if has_api_key else '미설정'}")
        st.write(f"적용 규칙 파일: {'YES/규칙' if DEFAULT_YES_RULE_PATH.exists() else 'config/policy_rules.yaml'}")

    policy_source = DEFAULT_YES_RULE_PATH if DEFAULT_YES_RULE_PATH.exists() else DEFAULT_POLICY_PATH
    policy_mtime = policy_source.stat().st_mtime if policy_source.exists() else 0
    prev_policy_mtime = st.session_state.get("policy_mtime")
    if prev_policy_mtime is None:
        st.session_state["policy_mtime"] = policy_mtime
    elif policy_mtime != prev_policy_mtime:
        st.session_state["policy_mtime"] = policy_mtime
        st.session_state.pop("preview_df", None)
        st.info("규칙 파일 변경 감지: 최신 규칙으로 자동 반영됩니다. 미리보기를 다시 생성해 주세요.")

    uploaded = st.file_uploader("법인카드 사용내역 엑셀 업로드", type=["xlsx", "xls"])
    preview_btn = st.button("추출 미리보기 생성", type="primary")

    if uploaded is None:
        st.info("엑셀 파일을 업로드해 주세요.")
        return

    if st.session_state.get("uploaded_name") != uploaded.name:
        st.session_state["uploaded_name"] = uploaded.name
        st.session_state.pop("preview_df", None)

    raw_df, detected_header_row = read_excel_with_header_detection(uploaded)
    st.caption(f"자동 감지된 헤더 행: {detected_header_row + 1}번째 행")
    with st.expander("원본 데이터 보기(참고용)", expanded=False):
        st.dataframe(raw_df.head(20), use_container_width=True)

    if preview_btn:
        normalized_df, missing = normalize_card_dataframe(raw_df)
        if missing:
            st.warning(f"누락 컬럼 자동 보정 적용: {', '.join(missing)}")

        org_chart = load_yaml(str(DEFAULT_ORG_PATH))
        account_rules = load_yaml(str(DEFAULT_ACCOUNT_PATH))
        policy_text = load_policy_text(str(policy_source))

        processed_df = process_transactions(
            input_df=normalized_df,
            org_chart=org_chart,
            account_rules=account_rules,
            policy_text=policy_text,
            use_llm=use_llm,
            user_override=user_override,
            department_override=department_override,
        )
        preview_df = build_output_dataframe(raw_df, normalized_df, processed_df)
        st.session_state["preview_df"] = preview_df
        st.session_state["cancelled_count"] = int(processed_df.get("is_cancelled", pd.Series(dtype=bool)).sum())
        st.session_state["user_override"] = user_override
        st.session_state["department_override"] = department_override
        st.success("추출 미리보기 생성 완료 (빈 값만 자동 기입)")

    preview_df = st.session_state.get("preview_df")
    if preview_df is not None:
        applied_user_override = str(st.session_state.get("user_override", "")).strip()
        if applied_user_override:
            st.info(f"사용자명 직접 입력 적용됨: {applied_user_override}")
        applied_department_override = str(st.session_state.get("department_override", "")).strip()
        if applied_department_override:
            st.info(f"부서 직접 입력 적용됨: {applied_department_override}")
        cancelled_count = int(st.session_state.get("cancelled_count", 0))
        if cancelled_count:
            st.warning(f"승인취소로 분류된 거래 {cancelled_count}건은 적요/계정이 '승인취소'로 표시됩니다.")
        st.write("추출 결과 미리보기 (지정 12개 컬럼)")
        st.dataframe(preview_df[EXTRACT_OUTPUT_COLUMNS].head(50), use_container_width=True)

        excel_bytes = dataframe_to_excel_bytes(preview_df[EXTRACT_OUTPUT_COLUMNS], sheet_name="EXTRACT_RESULT")
        st.download_button(
            label="추출 결과 XLSX 다운로드",
            data=excel_bytes,
            file_name="erp_extract_output.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )


if __name__ == "__main__":
    main()
