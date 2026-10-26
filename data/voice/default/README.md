# 기본 낭독 목소리 (로컬만)

신규 회원이 **가입 직후** 들을 수 있는 **공용 기본 낭독**용 참조 음성입니다. git에는 wav를 올리지 않습니다.

## 배치 방법

1. `default-narration-source.wav` (약 24초, 24kHz mono PCM 권장)를 이 폴더에 넣습니다.
2. 서버가 처음 기본 낭독을 만들 때 `reference.wav` 로 복사하고, `reference.txt` 는 `content/record_script.txt` 와 동일한 받아쓰기로 생성합니다.
3. 생성된 이야기 오디오는 `data/audio/default/<story-id>.m4a` 에 저장됩니다 (회원별 `data/users/<id>/audio/` 와 별도).

기존 `data/voice/reference.*` · `data/audio/*.m4a` 는 삭제하지 않습니다. 운영자 레거시 데이터는 그대로 두고, 필요 시 관리자 계정으로 per-user 경로로 이전됩니다.
