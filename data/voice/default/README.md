# 기본 낭독 목소리

신규 회원이 **가입 직후** 들을 수 있는 **공용 기본 낭독**용 참조 음성입니다.

이야기마다 `content/stories/*.txt` front matter의 `defaultVoice: harry|dana` 로 목소리가 정해집니다.

## git에 포함되는 파일

| 파일 | 설명 |
|------|------|
| `default-narration-source.wav` | **Harry** 참조 원본 (레거시 경로, `harry/`와 동일) |
| `harry/default-narration-source.wav` | Harry 기본 낭독 참조 |
| `dana/default-narration-source.wav` | Dana 기본 낭독 참조 |
| `README.md` | 이 안내 |

## 로컬만 (커밋하지 않음)

| 파일 | 설명 |
|------|------|
| `harry/reference.wav`, `dana/reference.wav` | 서버가 첫 기본 낭독 생성 시 각 `default-narration-source.wav`에서 복사 |
| `harry/reference.txt`, `dana/reference.txt` | 없으면 `content/record_script.txt` 받아쓰기로 자동 생성 |

생성된 이야기 오디오는 `data/audio/default/<story-id>.m4a`에 저장됩니다 (회원별 `data/users/<id>/audio/`와 별도).

회원·운영자 **개인** 녹음(`data/users/…`, 레거시 `data/voice/reference.*`)은 git에 올리지 마세요.

기존 `data/voice/reference.*` · `data/audio/*.m4a`는 삭제하지 않습니다.
