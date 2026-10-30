# 동 추출 누락·생략 후보 대조

2026-10-30. 보존된주소/현재대표매핑기반의추가후보분류. 원본CSV/지리경계확인이아니며 검토표나운영데이터에연결추가하지않았다.

| 대상 | 근거 구분 | n |
| --- | --- | ---: |
| missing_dong | no_known_address_target | 94 |
| missing_dong | unique_address_target_candidate | 167 |
| omitted_dong | normalization_only_no_address_support | 28 |
| omitted_dong | normalized_name_address_supported | 26 |

## 193후보 위치/대표성 점검

[{'position_supported': True, 'mapping_share_below_one': False, 'n': 136}, {'position_supported': True, 'mapping_share_below_one': True, 'n': 57}]

position_supported는구군다음주소성분또는괄호첫성분에일치동명이있는지검사한다. 이것도현재/과거경계확인은아니다. share<1은상가표본에서동일법정동의행정동표기가여럿이었다는뜻이며,share=1도전체경계일치를보장하지않는다.

unique_address_target_candidate는주소내구군과알려진동토큰으로가능한대표행정동이하나인경우다. 행정동과법정동동명충돌은양쪽후보를검토했다. 대표매핑은상가정보에서구한대표값이므로한법정동이여러행정동에걸치는경계정확성을보장하지않는다.

normalized_name_address_supported는노원3가→노원동3가같이보완한이름이보존주소에도있고대상행정동이일치하는경우다. normalization_only는보완형이연결표에는있으나주소에그이름이없어추가확인이필요하다. 누락동의0후보는주소없음과다르다.

현재2,518직접행정동후보와근거수준이다르므로합쳐서확정복구로발표하지않는다. 다음은단일대상후보도지번/도로명위치에서추출된값인지확인하고다대행정동법정동의경계불확실성을따로표시하는것이다. 과거동명소속은별도검증.

315/261/54표본·합계·복합키·해시검증통과. 재현:`python scripts/audit_d04_recovery_candidates.py`. [집계](recovery_candidates.json).
