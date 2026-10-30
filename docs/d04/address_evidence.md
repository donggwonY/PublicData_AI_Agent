# 행정동 후보의 보존 주소 대조

2026-10-30. 확인한 로컬폴더에서 대상4업종 원본CSV를 찾지 못해 stores의 road_addr_raw/jibun_addr_raw만 대조했다. 독립 원본파일 검증이 아니다.

{'exact_address_support': 2518}

| 업종 | 구분 | 건수 |
| --- | --- | ---: |
| 담배소매업 | exact_address_support | 1596 |
| 병원 | exact_address_support | 28 |
| 약국 | exact_address_support | 487 |
| 의원 | exact_address_support | 407 |

exact_address_support: 같은 주소 문자열 안에 구군과 후보행정동이 토큰 단위로 일치하고 다른 현재행정동 토큰은 없음. conflicting_admin_names: 동일 구군의 다른현재행정동토큰도있어검토필요. no_exact_address_support: 정확문자열근거부족. 이 검사는 철자·표기차이/과거행정구역을 해결하지 않는다.

행정동표기와법정동입력혼입 가능성을 확인하는 자료이며,현재경계소속·과거소속·대표행정동매핑의정확성을 증명하지 않는다. 자동연결/삭제/운영DB수정없음. 다음은 근거충분후보의현재맥락조회용보정정책과충돌/불일치별주소점검이다. 역사적모델입력은별도검증해야한다.

입력해시/키유일성/다대일연결/행수/후보2518재현/집계합계/부분문자열오탐방지검사통과. 재현:`python scripts/audit_d04_address_evidence.py`. [결과](address_evidence.json).
