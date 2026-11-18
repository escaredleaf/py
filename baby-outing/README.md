# 👶 16개월 아기와 서울·근교 나들이 가이드

16개월 아기와 가기 좋은 서울·경기 나들이 장소 31곳을 모은 한 페이지 웹사이트예요.
아기 요금, 할인, 주차, 운영시간, 편의시설, 반나절 추천 코스를 담았어요.

- 정보 확인일: **2026년 11월 18일**
- 단일 파일(`index.html`)이라 빌드할 필요가 없어요.

## 기능
- 카테고리 필터 5종: 박물관 · 키즈카페 · 아쿠아리움·동물원 · 야외 · 쇼핑몰
- 조건 필터: 실내 / 야외 / 아기 무료 / 모두 무료 / 겨울 추천 / 예약 필요 / 서울 / 경기 / 새로 추가
- 검색 (장소, 지역, 키워드)
- 카드마다 네이버 지도 링크와 공식 누리집 링크
- 반나절 추천 코스 6개, 방문 팁, 원본 대비 바뀐 점

## GitHub Pages 배포
1. GitHub에서 새 저장소를 만들어요. (예: `baby-outing`)
2. 이 가이드는 `escaredleaf/py` 저장소의 `baby-outing/` 폴더에 있어요.
   ```bash
   git init
   git add index.html README.md
   git commit -m "16개월 나들이 가이드"
   git branch -M main
   git remote add origin https://github.com/<아이디>/baby-outing.git
   git push -u origin main
   ```
3. 저장소에서 **Settings → Pages → Build and deployment**로 가요.
   Source는 `Deploy from a branch`, Branch는 `main` / `/ (root)`로 정하고 저장해요.
4. 1~2분 뒤 `https://<아이디>.github.io/baby-outing/` 주소로 열려요.

## 정보 수정하는 법
`index.html` 안의 `const PLACES = [...]` 배열만 고치면 화면에 바로 반영돼요.

| 필드 | 뜻 |
|---|---|
| `cat` | `museum`, `kids`, `aqua`, `outdoor`, `mall` 중 하나 |
| `indoor` | `true`(실내), `false`(야외), `"mix"`(실내+야외) |
| `babyFree` / `allFree` | 16개월 아기 무료 / 어른까지 무료 |
| `reserve` / `winter` | 예약 필요 / 겨울 추천 |
| `isNew` / `verified` | 새로 추가 / 2026.11 웹에서 확인함 |
| `adult`, `baby`, `discount`, `parking`, `hours`, `facility` | 카드에 보이는 정보 |
| `feature`, `warn`, `change` | 특징, 주의사항(주황), 원본 대비 변경(파랑) |
| `links` | `[{t:"이름", u:"주소"}]` (지도 링크는 자동 생성) |

## 주의
요금과 운영 정보는 자주 바뀌어요. `✔ 2026.11 확인` 표시가 없는 곳은 원본 정보를 유지한 것이니, 가기 전에 공식 안내를 꼭 확인하세요.
