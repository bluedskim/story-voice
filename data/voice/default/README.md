# 기본 낭독 목소리

신규 회원이 **가입 직후** 들을 수 있는 **공용 기본 낭독**용 참조 음성입니다.

이야기마다 `content/stories/*.txt` front matter의 `defaultVoice: harry|dana` 로 목소리가 정해집니다.

## Dana (git + Mac mini 레거시)

| 경로 | 설명 |
|------|------|
| `default-narration-source.wav` | **Dana** 참조 원본 — **git에 포함** |
| `reference.wav` / `reference.txt` | 서버가 첫 Dana 기본 낭독 생성 시 만들어 쓰는 로컬 파일 (git 제외). txt 없으면 `content/record_script.txt` |

`data/voice/default/` 루트 전체가 **Dana** 참조 디렉터리입니다 (`defaultVoice: dana` 이야기).

## Harry (로컬만, git 제외)

Harry 기본 낭독은 **Dana로 대체하지 않습니다**. 참조 wav가 없으면 해당 이야기 기본 낭독 생성을 **건너뛰고** 서버 로그에 경고를 남깁니다.

탐색 순서:

1. `data/voice/default/harry/reference.wav` (있으면 우선)
2. `data/voice/harry/harry_script_reference.wav` (Mac mini 등 로컬 배포)

받아쓰기(txt): wav와 같은 폴더의 같은 이름 `.txt`, 또는 `reference.txt`, 없으면 `content/record_script.txt` (Dana와 동일 스크립트).

## 생성 오디오

`data/audio/default/<story-id>.m4a` (회원별 `data/users/<id>/audio/`와 별도).

회원·운영자 **개인** 녹음은 git에 올리지 마세요. 기존 `data/voice/reference.*` · `data/audio/*.m4a`는 삭제하지 않습니다.
