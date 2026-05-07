from __future__ import annotations

import json
import os
from dataclasses import dataclass

from openai import OpenAI
import yaml

from utils.rule_engine import infer_summary_by_rules, infer_vat_by_rules


@dataclass
class InferenceResult:
    summary_text: str
    vat_deduction: str
    confidence: float
    reason: str


def _load_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _safe_json_parse(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise


def _llm_infer(
    merchant_name: str,
    merchant_category: str,
    transaction_hour: int,
    amount: float,
    policy_text: str,
    summary_hint: str,
    vat_hint: str,
) -> InferenceResult:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set.")

    client = OpenAI(api_key=api_key)
    prompt = {
        "merchant_name": merchant_name,
        "merchant_category": merchant_category,
        "transaction_hour": transaction_hour,
        "amount": amount,
        "policy_text": policy_text,
        "summary_hint": summary_hint,
        "vat_hint": vat_hint,
        "output_schema": {
            "summary_text": "string",
            "vat_deduction": "공제|불공제",
            "confidence": "0.0~1.0",
            "reason": "string",
        },
    }

    resp = client.responses.create(
        model="gpt-4o-mini",
        input=[
            {
                "role": "system",
                "content": "당신은 한국 ERP 전표 보조 에이전트입니다. 반드시 JSON만 반환하세요.",
            },
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ],
    )
    text = (resp.output_text or "").strip()
    data = _safe_json_parse(text)
    return InferenceResult(
        summary_text=data.get("summary_text", summary_hint),
        vat_deduction=data.get("vat_deduction", vat_hint),
        confidence=float(data.get("confidence", 0.7)),
        reason=data.get("reason", "LLM 판단"),
    )


def infer_summary_and_vat(
    merchant_name: str,
    merchant_category: str,
    transaction_hour: int,
    amount: float,
    policy_text: str,
    user_name: str = "",
    use_llm: bool = True,
) -> InferenceResult:
    summary_hint, summary_reason = infer_summary_by_rules(
        merchant=merchant_name,
        category=merchant_category,
        hour=transaction_hour,
        user_name=user_name,
        policy_text=policy_text,
    )
    vat_hint, vat_reason = infer_vat_by_rules(
        merchant=merchant_name,
        category=merchant_category,
        policy_text=policy_text,
        amount=amount,
    )
    fallback = InferenceResult(
        summary_text=summary_hint,
        vat_deduction=vat_hint,
        confidence=0.6,
        reason=f"{summary_reason}; {vat_reason}",
    )

    if not use_llm:
        return fallback

    try:
        llm_result = _llm_infer(
            merchant_name=merchant_name,
            merchant_category=merchant_category,
            transaction_hour=transaction_hour,
            amount=amount,
            policy_text=policy_text,
            summary_hint=summary_hint,
            vat_hint=vat_hint,
        )
        return llm_result
    except Exception:
        return fallback


def load_policy_text(policy_path: str) -> str:
    raw = _load_text(policy_path).strip()
    try:
        data = yaml.safe_load(raw) or {}
        if isinstance(data, dict):
            notices = data.get("공지사항", [])
            if isinstance(notices, list):
                return "\n".join(f"- {item}" for item in notices)
            return str(data)
        if isinstance(data, list):
            return "\n".join(str(item) for item in data)
    except Exception:
        pass
    return raw
