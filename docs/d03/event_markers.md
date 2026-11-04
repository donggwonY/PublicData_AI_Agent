# 전체 일반음식점 행사 표기 점검

폐업 상태/날짜/기간을 읽지 않고 주소·상호로만 후보를 분류했다. 법적 한시허가 여부나 과거 정보 가용성을 확정하지 않는다.

전체 97,438건.

| 분류 | 건수 |
| --- | ---: |
| no_marker | 96729 |
| review_keyword | 391 |
| unmatched | 249 |
| explicit_address | 69 |

explicit_address는 주소의 행사장/축제장 직접 표기, review_keyword는 넓은 키워드 후보다. no_marker는 행사 여부 미확인이며 상설점포 확정이 아니다. 원본 미연결은 unmatched로 보존한다.

## 연도별 분포

| 개업연도 | 분류 | 건수 |
| --- | --- | ---: |
| 1998 | review_keyword | 3 |
| 1999 | review_keyword | 3 |
| 2000 | review_keyword | 4 |
| 2003 | review_keyword | 3 |
| 2004 | review_keyword | 1 |
| 2005 | review_keyword | 1 |
| 2006 | review_keyword | 1 |
| 2007 | review_keyword | 2 |
| 2009 | review_keyword | 1 |
| 2013 | review_keyword | 1 |
| 2018 | explicit_address | 50 |
| 2018 | review_keyword | 2 |
| 2019 | explicit_address | 9 |
| 2019 | review_keyword | 52 |
| 2022 | explicit_address | 10 |
| 2022 | review_keyword | 48 |
| 2023 | review_keyword | 60 |
| 2024 | review_keyword | 58 |
| 2025 | review_keyword | 100 |
| 2026 | review_keyword | 51 |

규칙은 전체 연도 동일 적용. 원본 해시·키 유일성·합계 검사 통과. 후보 키와 근거 주소는 JSON에 보존. 이 결과로 행을 삭제하거나 성능 개선을 주장하지 않는다. 새 모델 평가 전 분류 오탐 확인과 별도 평가계획이 필요하다.
