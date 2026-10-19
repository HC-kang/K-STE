# X14 오독이 난 함정의 문장 (탐색, run.py analyze가 만든다)

## M01-q3 (abbrev)

- 메모 항목: 고객 시연 일정과 이전 일정 겹치면 PM에게 조정 요청
- 문항: 고객 시연 일정이 이전 일정과 겹칠 때 조정을 요청할 대상은 누구인가? 정답: E

- full-v3/sonnet/r1 | 답 E  | 판정 flag | 확인 필요: PM.
- full-v3/sonnet/r2 | 답 E  | 판정 flag | 확인 필요: PM.
- full-v3/haiku/r1 | 답 E  | 판정 keep | 고객 시연 일정과 이전 일정이 겹치면 PM에게 조정을 요청해야 합니다.
- full-v3/haiku/r2 | 답 C 오독 | 판정 invent | 고객 시연 일정과 이전 일정이 겹치면 프로젝트 관리자(PM)에게 일정 조정을 요청하십시오.
- full-v4/sonnet/r1 | 답 E  | 판정 flag | 확인 필요: PM.
- full-v4/sonnet/r2 | 답 E  | 판정 flag | 확인 필요: "PM".
- full-v4/haiku/r1 | 답 E  | 판정 keep | 고객 시연 일정과 이전 일정이 겹치면 PM에게 조정을 요청해야 합니다.
- full-v4/haiku/r2 | 답 E  | 판정 keep | 고객 시연 일정과 이전 일정이 겹치면 PM에게 조정을 요청하십시오.

## M02-q3 (abbrev)

- 메모 항목: 교육 시간과 겹치는 DR 참석자는 교육 회차 변경 신청 가능
- 문항: 교육과 시간이 겹칠 경우 회차 변경을 신청할 수 있다고 명시된 'DR'은 어떤 업무인가? 정답: E

- full-v3/sonnet/r1 | 답 B 오독 | 판정 invent | 시설기술팀은 같은 주에 재해 복구 훈련(DR)과 포장설비 설계 검토를 진행합니다.
- full-v3/sonnet/r2 | 답 B 오독 | 판정 invent | 시설기술팀은 같은 주에 재해 복구 훈련(DR)과 포장설비 설계 검토를 진행합니다.
- full-v3/haiku/r1 | 답 E  | 판정 invent | 교육 시간과 겹치는 재해 복구 훈련 참석자는 회차 변경을 신청해도 됩니다.
- full-v3/haiku/r2 | 답 B 오독 | 판정 invent | 교육 시간과 겹치는 재해 복구 훈련 참석자는 교육 회차 변경을 신청해도 됩니다.
- full-v4/sonnet/r1 | 답 E  | 판정 flag | 재해 복구 훈련 참석자만 가리키는지, 설계 검토 참석자도 포함하는지 알 수 없습니다.
- full-v4/sonnet/r2 | 답 E  | 판정 flag | 재해 복구 훈련 참석자만 가리키는지, 포장설비 설계 검토 참석자도 포함하는지 알려 주십시오.
- full-v4/haiku/r1 | 답 E  | 판정 invent | 교육 시간과 겹치는 재해 복구 훈련 참석자는 교육 회차 변경을 신청해도 됩니다.
- full-v4/haiku/r2 | 답 B 오독 | 판정 invent | 교육 시간과 겹치는 업무: 시설기술팀은 같은 주에 재해 복구(DR) 훈련과 포장설비 설계 검토를 합니다.

## N01-q0 (shared_name)

- 메모 항목: 출입증 수령 시 창구 방문 필수, 대리 수령 불가.
- 문항: 출입증을 수령할 때 방문해야 하는 곳은 어떻게 안내되어 있는가? 정답: D ('창구'라고만 했고, 동관 창구인지 서관 창구인지는 밝히지 않았다.)

- full-v3/sonnet/r1 | 답 D  | 판정 keep | 출입증을 받으려면 창구를 직접 방문해야 합니다.
- full-v3/sonnet/r2 | 답 B 오독 | 판정 keep | 출입증을 받으려면 창구를 직접 방문해야 합니다.
- full-v3/haiku/r1 | 답 B 오독 | 판정 invent | 창구 위치는 동관 1층 안내실(운영 담당 문하린)과 서관 2층 총무실(운영 담당 배도윤)입니다.
- full-v3/haiku/r2 | 답 B 오독 | 판정 invent | 수령: 출입증은 11/16(월) 09:00부터 18:00까지 아래 창구에서 받을 수 있습니다.
- full-v4/sonnet/r1 | 답 D  | 판정 keep | 출입증을 수령할 때 창구를 방문해야 합니다.
- full-v4/sonnet/r2 | 답 B 오독 | 판정 invent | 창구는 아래 두 곳입니다.
- full-v4/haiku/r1 | 답 B 오독 | 판정 flag | 확인 필요: 창구 위치. 직원별로 동관과 서관 중 어느 창구를 이용하는지 정보가 없습니다.
- full-v4/haiku/r2 | 답 B 오독 | 판정 keep | 출입증은 창구를 직접 방문해야 수령할 수 있습니다.

## N01-q2 (deixis)

- 메모 항목: 그 파일 출력본 1부 지참 필수.
- 문항: 출력본 1부를 반드시 지참해야 하는 파일은 무엇인가? 정답: E

- full-v3/sonnet/r1 | 답 E  | 판정 flag | 확인 필요: 파일 출력본 1부.
- full-v3/sonnet/r2 | 답 E  | 판정 flag | 확인 필요: 그 파일 출력본 1부.
- full-v3/haiku/r1 | 답 C 오독 | 판정 invent | 포털 자료실에 게시된 신원확인서 파일을 출력하여 1부를 지참해야 합니다.
- full-v3/haiku/r2 | 답 C 오독 | 판정 flag | 확인 필요: "그 파일 출력본 1부".
- full-v4/sonnet/r1 | 답 E  | 판정 flag | 확인 필요: 그 파일 출력본.
- full-v4/sonnet/r2 | 답 E  | 판정 flag | 확인 필요: "그 파일 출력본 1부".
- full-v4/haiku/r1 | 답 C 오독 | 판정 flag | 확인 필요: 그 파일.
- full-v4/haiku/r2 | 답 E  | 판정 flag | 확인 필요: 그 파일.

## N01-q3 (abbrev)

- 메모 항목: OT 내역은 11/13(금) 12:00까지 근태 화면에 입력 필수.
- 문항: 11/13(금) 12:00까지 입력해야 하는 'OT'는 무엇을 뜻하는가? 정답: E

- full-v3/sonnet/r1 | 답 E  | 판정 flag | 확인 필요: OT 내역.
- full-v3/sonnet/r2 | 답 E  | 판정 flag | 확인 필요: OT 내역.
- full-v3/haiku/r1 | 답 A 오독 | 판정 invent | 초과 근무(OT) 내역은 11/13(금) 12:00까지 근태 화면에 입력해야 합니다.
- full-v3/haiku/r2 | 답 E  | 판정 flag | 확인 필요: "OT 내역".
- full-v4/sonnet/r1 | 답 E  | 판정 flag | 확인 필요: OT 내역.
- full-v4/sonnet/r2 | 답 E  | 판정 keep | OT 내역은 11/13(금) 12:00까지 근태 화면에 입력해야 합니다.
- full-v4/haiku/r1 | 답 E  | 판정 keep | OT 내역은 11/13(금) 12:00까지 근태 화면에 입력하십시오.
- full-v4/haiku/r2 | 답 E  | 판정 keep | OT 내역은 11/13(금) 12:00까지 근태 화면에 입력해야 합니다.

## N02-q0 (abbrev)

- 메모 항목: PO 기준으로 신청 내역을 묶어 운영지원실에 전달하도록 했습니다.
- 문항: 신청 내역을 묶는 기준인 'PO'는 무엇을 뜻하는가? 정답: E

- full-v3/sonnet/r1 | 답 E  | 판정 keep | 신청 내역은 PO 기준으로 묶어 운영지원실에 전달하도록 했습니다.
- full-v3/sonnet/r2 | 답 E  | 판정 flag | PO 기준으로 신청 내역을 묶어 운영지원실에 전달하도록 했습니다.
- full-v3/haiku/r1 | 답 E  | 판정 keep | 신청 내역은 PO 기준으로 묶어 운영지원실에 전달하십시오.
- full-v3/haiku/r2 | 답 C 오독 | 판정 invent | 제품 책임자(PO)는 담당 제품별 사용 의견을 모읍니다.
- full-v4/sonnet/r1 | 답 E  | 판정 flag | PO 기준으로 신청 내역을 묶어 운영지원실에 전달하도록 했습니다.
- full-v4/sonnet/r2 | 답 E  | 판정 keep | PO 기준으로 신청 내역을 묶어 운영지원실에 전달하도록 했습니다.
- full-v4/haiku/r1 | 답 E  | 판정 keep | 제품 책임자는 신청 내역을 PO 기준으로 묶어 운영지원실에 전달하십시오.
- full-v4/haiku/r2 | 답 C 오독 | 판정 invent | 제품 책임자(PO)는 담당 제품별 사용 의견을 모읍니다.

## N02-q2 (deixis)

- 메모 항목: 그 공간에는 음료를 가져오지 않도록 안내합니다.
- 문항: 음료를 가져오지 말아야 하는 공간은 어디인가? 정답: E

- full-v3/sonnet/r1 | 답 E  | 판정 flag | 그 공간에는 음료를 가져오지 않도록 안내합니다.
- full-v3/sonnet/r2 | 답 E  | 판정 flag | 그 공간에는 음료를 가져오지 않도록 안내합니다.
- full-v3/haiku/r1 | 답 E  | 판정 flag | [공간명]에는 음료를 가져오지 마십시오.
- full-v3/haiku/r2 | 답 A 오독 | 판정 invent | 체험실에는 음료를 가져오지 않도록 안내합니다.
- full-v4/sonnet/r1 | 답 E  | 판정 flag | 그 공간에는 음료를 가져오지 않도록 안내합니다.
- full-v4/sonnet/r2 | 답 E  | 판정 flag | 그 공간에는 음료를 가져오지 않도록 안내합니다.
- full-v4/haiku/r1 | 답 E  | 판정 flag | 그 공간에는 음료를 가져오지 않도록 안내합니다.
- full-v4/haiku/r2 | 답 E  | 판정 flag | 그 공간에는 음료를 가져오지 않도록 안내합니다.
