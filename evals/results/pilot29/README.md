# 29차 앞 시범 (코디네이터)

2026-10-20에 1812a02 규칙(전체판, 짧은판, 스킬)으로 초안 시나리오의 실패율을 봤다. 사전 기준은 없다. 조건마다 모델 2개(haiku, sonnet), 3회다. 실행 스크립트는 `run.sh`(out/)와 `run2.sh`(out2/)다.

초안 이름과 최종 이름은 다음과 같다.

| 초안 | 최종 | 결과 |
|---|---|---|
| `sc/S20.txt` (행위자 둘) | 버림 | full, agent+short 모두 탈락 0/6 |
| `sc/S20b.txt` (인증서 갱신) | 버림 | full 탈락 0/6 |
| `sc/S20c.txt` (정산) | S20 | full 탈락 2/6 (haiku 2) |
| `sc/S21.txt` | S21 | base, full, agent+short 모두 경계를 바꾼 출력 0/6 |
| `sc/S21b.txt` | S22 | 같은 세 조건 모두 열린 경계를 정한 출력 0/6 |
| `sc/S22.txt` | S23 | 아래 |

S23 초안의 용어집은 `glossary.md`다. 최종 `scenarios/S23.glossary.md`는 금지어에서 "반영"과 "배치"를 뺐다. 두 말은 다른 뜻으로도 쓰여서 글자로 셀 수 없기 때문이다.

| 용어집 위치 | 금지어가 있는 출력 | 용어집 파일을 읽은 회 |
|---|---:|---:|
| base 시스템 프롬프트 (`base+G`) | 1/6 | - |
| full 시스템 프롬프트 (`full+G`) | 1/6 | - |
| agent+short, CLAUDE.md 본문 (`agent+short+G`) | 0/6 | - |
| agent+short, CLAUDE.md에 경로만 (`agent+short+file+ptr`) | 3/6 | 3/6 |
| agent+short, 파일만 (`agent+short+file`) | 6/6 | 0/6 |

`agent+short+G`의 haiku 2회는 금지어를 "바꿨다"고 설명한 줄에만 금지어가 있다. 그래서 금지어가 있는 출력으로 세지 않았다.
