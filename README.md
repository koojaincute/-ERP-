# 법인카드 ERP 전표 자동화 (Streamlit)

법인카드 사용내역 엑셀을 업로드하면 다음을 자동 처리합니다.
- `pandas`로 데이터 로딩/정규화
- 조직도 + 부서별 계정기준 기반 분류(`제조원가`/`판매비와관리비`, 계정과목)
- 결제시간/가맹점/업종 규칙 + OpenAI LLM으로 `적요`, `부가세 공제여부` 판단
- ERP 업로드용 엑셀 결과 파일 생성

## 실행 파일
- `main.py`

## 디렉토리 구조
- `main.py`: Streamlit UI 및 전체 파이프라인
- `mapping_logic.py`: 부서/계정 분류
- `inference_engine.py`: 적요/부가세 추론(규칙 + LLM)
- `utils/io_utils.py`: 엑셀 I/O, 컬럼 정규화, 출력 스키마
- `utils/rule_engine.py`: 시간/가맹점 키워드 규칙
- `config/*.yaml`: 조직도/계정기준/정책 텍스트

## Poetry 가상환경 세팅
```bash
poetry install
poetry shell
```

## 앱 실행
```bash
streamlit run main.py
```

## 필수 입력 컬럼(원본 엑셀)
아래 별칭을 자동 인식합니다.
- 거래일시/결제일시/사용일시 -> `transaction_datetime`
- 사용자/사용자명/사원명 -> `user_name`
- 가맹점/가맹점명/거래처명 -> `merchant_name`
- 업종/가맹점업종 -> `merchant_category`
- 금액/결제금액/사용금액 -> `amount`
- 승인번호 -> `approval_no`

## 출력 컬럼(ERP 업로드용)
- 전표일자, 사용자명, 부서, 가맹점명, 업종, 금액
- 비용대분류, 계정과목, 적요, 부가세구분, 증빙유형, 판정근거, 원천승인번호

## OpenAI API 키
- 프로젝트 루트의 `.env` 파일에 키를 입력합니다.
```bash
OPENAI_API_KEY=YOUR_KEY
```
- 앱은 시작 시 `.env`를 자동 로드합니다.

## 샘플 판정 시나리오
- 20시 이후 + 식당 업종 -> `야간 식대`
- 가맹점명에 `KTX`, `호텔`, `주유` 포함 -> 출장/여비교통 성격
- 접대비/면세 키워드 거래 -> 부가세 `불공제`
- 일반 식대/비품 구입 -> 부가세 `공제`(정책 전제)

## 사용 모델
- LLM 모델은 `gpt-4o-mini`로 설정되어 있습니다.
