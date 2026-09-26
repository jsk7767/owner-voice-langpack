# 반복 검사 개선에 참고한 공개 프로젝트

2026-09-26에 공식 GitHub README와 저장소 메타데이터를 확인했습니다. 아래는 도입 후보와 설계 참고이며, 이 저장소가 모두 설치하거나 실행했다는 뜻은 아닙니다.

| 프로젝트 | 우리 작업에 도움이 되는 기능 | 범위와 도입 판단 |
|---|---|---|
| [Kiwi / kiwipiepy](https://github.com/bab2min/kiwipiepy) | 한국어 형태소의 형태·품사·원문 위치, 문장 분리, 사용자 단어 등록 | 조사·어미가 달라진 단어를 비교할 때 유용한 후보. 기본 표면형 검사와 구분해 한국어 사례로 정확도를 검증해야 함. 모델 데이터 의존성이 있음 |
| [RapidFuzz](https://github.com/rapidfuzz/RapidFuzz) | 문자열 거리와 유사도, 어순·표현이 조금 달라진 문장 후보 비교 | 문자 기반 유사도이지 의미 판단이 아님. 반복 횟수 검사를 대신하면 안 됨 |
| [Sentence Transformers](https://github.com/huggingface/sentence-transformers) | 임베딩·문장 의미 유사도·유사 문장 검색 | 단어가 달라도 같은 이야기를 하는 후보를 찾는 확장안. 한국어 모델과 판정 기준을 별도로 검증해야 하며 PyTorch·모델 실행 환경이 필요 |
| [Promptfoo](https://github.com/promptfoo/promptfoo) | 같은 사례로 프롬프트·모델 변경 전후 평가 반복 | 글 내부/과거 글 반복, 원문 보존, 자료 부재, 정당한 반복을 분리한 평가 사례 설계에 참고. 설치만으로 작성 지시 준수가 보장되지는 않음 |

## 지금 검사에 반영할 원칙

1. **발생 횟수를 지우지 않는다.** RapidFuzz 공식 README의 `token_set_ratio("fuzzy was a bear", "fuzzy fuzzy was a bear")`는 100점이다. 집합 기반 유사도는 같은 단어를 더 쓴 횟수를 놓칠 수 있으므로 내부 반복은 원문 위치와 발생 횟수를 별도로 센다.
2. **표면 반복과 의미 반복을 분리한다.** 같은 문자열 탐지 결과로 “같은 이야기인지”까지 판정하지 않는다. 핵심 주장·사례·결말은 원고 근거를 보며 수동 검토한다.
3. **원문 근거를 남긴다.** Kiwi가 토큰 위치와 문장 위치를 제공하는 것처럼, 반복 검토에서도 어떤 표현이 어느 줄에서 몇 번 나왔는지 보여준다. 규칙 설명만 제시하고 문제 구간을 생략하지 않는다.
4. **정상 사례도 검증한다.** 반복 문장뿐 아니라 필요한 매장명·메뉴명, 서로 다른 사실, 수정 범위 보존, 이력 없는 글, 읽지 못한 파일을 함께 검사한다.
5. **같은 사례로 수정 전후를 비교한다.** 점수나 경고 개수만 낮추지 않고 실제 중복이 줄었는지, 원래 사실과 보존 구간을 손상하지 않았는지 확인한다.

기본 도구는 추가 라이브러리 없는 검사를 우선한다. 형태소나 임베딩을 도입하면 그 결과를 기본 검사와 구분하고, 모델·버전·비교한 자료·미검증 범위를 기록한다. 단순히 라이브러리를 붙였다는 이유로 완성된 자동 편집자로 설명하지 않는다.

## 라이선스와 공식 근거

확인 당시 저장소 라이선스: kiwipiepy Apache-2.0, RapidFuzz MIT, Sentence Transformers Apache-2.0, Promptfoo MIT. 별도로 사용하는 모델·의존성의 라이선스는 각각 확인해야 한다. 이번 참고 작업에서는 이들 프로젝트의 코드를 복사하지 않았다.

- [kiwipiepy README](https://github.com/bab2min/kiwipiepy/blob/main/README.md): `tokenize`, 토큰 위치, `split_into_sents`, `add_user_word`, 모델 패키지 설명
- [RapidFuzz README](https://github.com/rapidfuzz/RapidFuzz/blob/main/README.md): Token Set Ratio 예제와 기본 전처리 미적용 설명
- [Sentence Transformers README](https://github.com/huggingface/sentence-transformers/blob/main/README.md): 의미 유사도·검색과 실행 의존성
- [Promptfoo README](https://github.com/promptfoo/promptfoo/blob/main/README.md): 프롬프트·모델 평가 CLI와 실행 설정
