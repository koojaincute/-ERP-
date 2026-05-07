from __future__ import annotations

from io import BytesIO
from typing import Dict, Tuple

import pandas as pd
import yaml


REQUIRED_CANONICAL_COLUMNS = [
    "transaction_datetime",
    "user_name",
    "merchant_name",
    "merchant_category",
    "amount",
    "approval_no",
]

CANONICAL_COLUMN_ALIASES: Dict[str, list[str]] = {
    "transaction_datetime": [
        "거래일시",
        "결제일시",
        "사용일시",
        "거래시간",
        "승인일시",
        "승인일자",
        "거래일자",
        "transaction_datetime",
    ],
    "user_name": ["사용자", "사용자명", "사원명", "성명", "emp_name", "user_name", "이름", "직원명", "사용자(한글)"],
    "merchant_name": ["가맹점", "가맹점명", "거래처명", "사용처", "merchant_name", "상호", "매장명"],
    "merchant_category": ["업종", "가맹점업종", "업태", "merchant_category", "업종명", "가맹점분류"],
    "amount": ["금액", "결제금액", "사용금액", "승인금액", "amount"],
    "vat_amount": ["부가세", "vat_amount"],
    "card_no_masked": ["카드번호", "카드번호(마스킹)", "card_no_masked"],
    "approval_no": ["승인번호", "approval_no"],
}

EXTRACT_OUTPUT_COLUMNS = [
    "카드번호",
    "가맹점명",
    "승인일",
    "거래처",
    "적요",
    "비용 계정",
    "부가세",
    "카드사용자",
    "카드사용부서",
]


def _normalize_label(value: object) -> str:
    text = str(value or "").strip().replace("\n", "").replace("\r", "")
    return text


def _normalized_aliases() -> Dict[str, set[str]]:
    return {
        canonical: {_normalize_label(alias).lower() for alias in aliases}
        for canonical, aliases in CANONICAL_COLUMN_ALIASES.items()
    }


def read_excel_with_header_detection(file_obj) -> tuple[pd.DataFrame, int]:
    preview = pd.read_excel(file_obj, header=None, dtype=str)
    file_obj.seek(0)

    aliases = _normalized_aliases()
    best_row = 0
    best_score = -1
    scan_limit = min(25, len(preview))

    for idx in range(scan_limit):
        row_values = {_normalize_label(v).lower() for v in preview.iloc[idx].tolist() if pd.notna(v)}
        score = 0
        for required in REQUIRED_CANONICAL_COLUMNS:
            if row_values.intersection(aliases.get(required, set())):
                score += 1
        if score > best_score:
            best_score = score
            best_row = idx

    if best_score < 2:
        best_row = 0

    df = pd.read_excel(file_obj, header=best_row)
    file_obj.seek(0)
    return df, best_row


def load_yaml(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def normalize_card_dataframe(df: pd.DataFrame) -> Tuple[pd.DataFrame, list[str]]:
    df = df.copy()
    df.columns = [_normalize_label(col) for col in df.columns]

    mapped = {}
    for canonical, alias_list in CANONICAL_COLUMN_ALIASES.items():
        for col in df.columns:
            if _normalize_label(col).lower() in {_normalize_label(a).lower() for a in alias_list}:
                mapped[col] = canonical
                break
    normalized = df.rename(columns=mapped).copy()

    unnamed_cols = [c for c in normalized.columns if str(c).lower().startswith("unnamed:")]
    if unnamed_cols:
        normalized = normalized.drop(columns=unnamed_cols)

    if "transaction_datetime" in normalized.columns:
        normalized["transaction_datetime"] = pd.to_datetime(
            normalized["transaction_datetime"], errors="coerce"
        )
    if "amount" in normalized.columns:
        normalized["amount"] = (
            normalized["amount"]
            .astype(str)
            .str.replace(",", "", regex=False)
            .str.replace("원", "", regex=False)
        )
        normalized["amount"] = pd.to_numeric(normalized["amount"], errors="coerce").fillna(0)

    missing = [col for col in REQUIRED_CANONICAL_COLUMNS if col not in normalized.columns]
    default_values = {
        "transaction_datetime": pd.NaT,
        "user_name": "미상",
        "merchant_name": "미상",
        "merchant_category": "기타",
        "amount": 0,
        "approval_no": "",
    }
    for col in missing:
        normalized[col] = default_values.get(col, "")

    if "merchant_category" in normalized.columns:
        normalized["merchant_category"] = normalized["merchant_category"].fillna("기타").astype(str)
        normalized.loc[normalized["merchant_category"].str.strip() == "", "merchant_category"] = "기타"

    if "user_name" in normalized.columns:
        normalized["user_name"] = normalized["user_name"].fillna("미상").astype(str)
        normalized.loc[normalized["user_name"].str.strip() == "", "user_name"] = "미상"

    return normalized, missing


def _is_empty_value(value: object) -> bool:
    if pd.isna(value):
        return True
    text = str(value).strip().lower()
    return text in {"", "none", "nan", "null", "-"}


def _fill_only_empty(base: pd.Series, generated: pd.Series) -> pd.Series:
    result = base.copy()
    for idx in result.index:
        if _is_empty_value(result.loc[idx]):
            result.loc[idx] = generated.loc[idx]
    return result


def build_output_dataframe(
    original_df: pd.DataFrame, normalized_df: pd.DataFrame, enriched_df: pd.DataFrame
) -> pd.DataFrame:
    output = pd.DataFrame(index=original_df.index)
    for col in EXTRACT_OUTPUT_COLUMNS:
        output[col] = original_df[col] if col in original_df.columns else pd.NA

    generated = pd.DataFrame(index=original_df.index)
    generated["카드번호"] = normalized_df.get("card_no_masked", pd.Series([""] * len(original_df)))
    generated["가맹점명"] = normalized_df.get("merchant_name", pd.Series([""] * len(original_df)))
    generated["승인일"] = pd.to_datetime(
        normalized_df.get("transaction_datetime", pd.Series([pd.NaT] * len(original_df))), errors="coerce"
    ).dt.strftime("%Y-%m-%d")
    generated["거래처"] = normalized_df.get("merchant_name", pd.Series([""] * len(original_df)))
    generated["적요"] = enriched_df.get("summary_text", pd.Series([""] * len(original_df)))
    generated["비용 계정"] = enriched_df.get("account_subject", pd.Series([""] * len(original_df)))
    generated["부가세"] = enriched_df.get("vat_deduction", pd.Series([""] * len(original_df)))
    generated["카드사용자"] = normalized_df.get("user_name", pd.Series([""] * len(original_df)))
    generated["카드사용부서"] = enriched_df.get("department", pd.Series([""] * len(original_df)))

    for col in EXTRACT_OUTPUT_COLUMNS:
        if col == "부가세":
            # Source files can contain numeric VAT amounts; export must use 공제/불공제 labels.
            output[col] = generated[col]
        else:
            output[col] = _fill_only_empty(output[col], generated[col])

    return output


def dataframe_to_excel_bytes(df: pd.DataFrame, sheet_name: str = "ERP_UPLOAD") -> bytes:
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name)
    return buffer.getvalue()
