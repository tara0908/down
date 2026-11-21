# 학생 결과물 정리 스킬 (student-work-collector)

캔바·패들렛·클래스팅AI·하이클래스 등에 학생들이 올린 결과물을 Claude가 한꺼번에 받아
**번호순**(번호가 없으면 이름 가나다순)으로 정리하는 Claude 스킬입니다.

- 글 결과물: 맞춤법·띄어쓰기만 고쳐 `txt`로 저장 (원문·교정 내역 함께)
- 그림·디자인 결과물: `png`로 저장
- 명렬표를 주면 번호 자동 채우기 + 미제출자 확인

다운로드 페이지: https://tara0908.github.io/down/

## 설치

### claude.ai
1. [`student-work-collector.skill`](student-work-collector.skill)을 내려받습니다.
2. claude.ai → 설정 → 기능 → 스킬 → **스킬 업로드**에서 올립니다.

### Claude Code
```
/plugin marketplace add tara0908/down
/plugin install student-work-collector@teacher-skills
```

## 사용 예
- "이 패들렛 글이랑 그림 다 받아서 번호순으로 정리해줘 https://padlet.com/…"
- "캔바 '독서포스터' 과제 학생 디자인 png로 모아줘"
- "하이클래스에서 받은 zip이야. 명렬표도 줄게, 미제출자도 알려줘"

자세한 내용은 [사용설명서.pdf](사용설명서.pdf)를 보세요.

## 파일 구조
```
.claude-plugin/          Claude Code 플러그인·마켓 설정
skills/student-work-collector/
  SKILL.md               스킬 지시문
  references/platforms.md 플랫폼별 수집 요령
  scripts/organize.py    정리·정렬·PNG 변환·목록 작성
  scripts/padlet_to_manifest.js 패들렛 보드 자동 수집
student-work-collector.skill  claude.ai 업로드용 파일
학생결과물정리_스킬.zip        전체 묶음
index.html               다운로드 페이지 (GitHub Pages)
```

## 라이선스
MIT. 캔바, 패들렛, 클래스팅, 하이클래스는 각 회사의 상표이며 이 스킬은 해당 회사와 관계가 없습니다.
