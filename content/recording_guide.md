# 목소리 샘플 녹음 가이드

## 녹음 팁
- **조용한 방**에서 녹음해요. TV, 에어컨, 선풍기는 끄고, 이불이나 커튼이 있는 방이 울림이 적어 좋아요.
- 휴대폰은 입에서 **약 20cm** 떨어뜨리고, 마이크(휴대폰 아래쪽)가 입을 향하게 해요. 너무 가까우면 숨소리가 커져요.
- 아이에게 잠자리 동화를 읽어 주듯 **천천히, 부드럽게** 읽어요. 약 20초 정도 걸리면 딱 좋아요.
- 앞뒤로 1초쯤 조용히 있다가 시작하고 끝내요.
- 파일 형식은 휴대폰 기본 녹음(**m4a**)이든 **wav**든 다 괜찮아요.
- 대본은 `content/record_script.txt`예요. 웹 **목소리** 탭에도 같은 글이 미리 채워져 있어요. 저장하면 `data/voice/reference.txt`가 됩니다.

- 읽다가 단어를 바꾸거나 빠뜨렸다면, 다시 녹음하거나 **받아쓰기를 실제로 읽은 대로 똑같이 고쳐** 주세요. 녹음과 글이 정확히 일치해야 목소리가 잘 복제돼요.
- 녹음 원본은 `data/voice/` 에 `my_voice.m4a` 같은 이름으로 넣어 주세요.

## 1. 휴대폰 녹음 → 24kHz 모노 wav 변환
```bash
cd ~/story-voice
ffmpeg -y -i data/voice/my_voice.m4a -ar 24000 -ac 1 data/voice/reference.wav
```

## 2. 웹에서 녹음 (권장)

`python scripts/serve.py` 실행 후 브라우저에서 **목소리** 탭 → 녹음 또는 파일 업로드 → 받아쓰기 확인 → **목소리 저장**.  
이전 `reference.wav` / `reference.txt`는 `data/voice/history/<타임스탬프>/`에 자동 백업됩니다.

## 3. 내 목소리로 동화 만들기 (CLI)
```bash
cd ~/story-voice
scripts/clone_story.sh data/voice/reference.wav data/voice/reference.txt \
  content/stories/ui-joeun-hyeongje.txt data/audio/ui-joeun-hyeongje.m4a
```
또는 카탈로그 단축:
```bash
scripts/clone_story.sh content/stories/ui-joeun-hyeongje.txt
```

결과: `data/audio/ui-joeun-hyeongje.m4a` (또는 `--out`으로 지정한 경로)
