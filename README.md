# story-voice

* 슬로건: Your voice. Their stories.
* 한줄: 부모의 목소리로 듣는 동화·학습 라이브러리
* 영문: A story library that reads in a parent’s voice
* 방식: voice cloning. 부모 목소리 샘플로 동화 전체를 읽게 한다.
* 실행: 로컬 모델. Mac Mini M2에서 MLX로 돌린다.
* 모델: Qwen3-TTS 12Hz Base. 한국어와 짧은 샘플 클로닝을 지원하고, 라이선스는 Apache 2.0이다.

## 지금 단계

검증을 통과했어요. 이제 **얇은 제품** — 목소리 하나, 동화 몇 편, 재생 버튼 — 을 Mac mini에서 돌립니다. 계정·결제·학습 콘텐츠는 그다음입니다.

## 빠른 시작 (Mac mini)

아래는 **한 번만** 하는 설정과, **이야기마다** 하는 생성, **재생할 때마다** 켜는 서버 순서입니다.

### 1. 도구 설치

```bash
# Homebrew
brew install ffmpeg uv

cd story-voice
uv venv --python 3.12
source .venv/bin/activate
uv pip install -r requirements-mlx.txt
```

### 2. 부모 목소리 준비

녹음 방법은 [`content/recording_guide.md`](content/recording_guide.md)를 보세요.

```bash
mkdir -p data/voice
ffmpeg -i ~/Downloads/parent_sample.m4a -ar 24000 -ac 1 data/voice/reference.wav
# reference.txt 에 녹음과 똑같은 받아쓰기 저장
```

`data/voice/` 안의 wav·txt는 **git에 올리지 마세요** (실제 목소리).

### 3. 동화 글

- 카탈로그: `content/stories/*.txt` (YAML 머리말에 `title`, `id`, `order`)
- 새 이야기를 추가한 뒤 오디오를 다시 생성하면 됩니다.

### 4. 오디오 생성 (MLX)

한 편:

```bash
source .venv/bin/activate
chmod +x scripts/clone_story.sh
./scripts/clone_story.sh content/stories/ui-joeun-hyeongje.txt
```

전체 (모델은 한 번만 로드):

```bash
python scripts/generate_all.py
```

문장·문단 쉼 (초):

```bash
python scripts/clone_story.py content/stories/ui-joeun-hyeongje.txt \
  --sentence-pause 0.35 \
  --paragraph-pause 0.75
```

생성 파일: `data/audio/<id>.m4a` (역시 git 제외).

### 5. 웹 플레이어

```bash
python scripts/serve.py
# 브라우저: http://localhost:8765/
# 같은 Wi‑Fi 폰: http://<맥미니-IP>:8765/
```

`serve.py`는 `web/catalog.json`을 갱신하고, `data/audio/`를 `web/audio/`로 연결합니다.

## 프로젝트 구조

| 경로 | 설명 |
|------|------|
| `content/stories/` | 동화 원문 + 제목 메타데이터 |
| `content/recording_guide.md` | 목소리 녹음 가이드 |
| `data/voice/` | `reference.wav`, `reference.txt` (로컬만) |
| `data/audio/` | 생성된 `.m4a` (로컬만) |
| `scripts/clone_story.py` | 한 편 TTS (문장 단위 + ffmpeg 이어붙이기) |
| `scripts/generate_all.py` | 모든 편 일괄 생성 |
| `scripts/story_catalog.py` | `web/catalog.json` 빌드 |
| `scripts/serve.py` | 정적 웹 + 오디오 서빙 |
| `web/` | 다크 테마 재생 UI (한국어) |

## 검증 (완료)

Mac mini M2 (16GB), `Qwen3-TTS-12Hz-1.7B-Base-8bit`, mlx-audio 0.6.0, Python 3.12 — 약 23초 샘플+받아쓰기로 「의좋은 형제」 전편(약 1분 41초) 낭독이 잠자리용으로 통과했습니다.

## 로컬 모델

Qwen3-TTS 12Hz Base를 쓴다. Apple Silicon용 MLX로 로컬에서 돌린다.

| 메모리 | 모델 | 이유 |
|---|---|---|
| 16GB 이상 | `Qwen3-TTS-12Hz-1.7B-Base` 8-bit | 샘플과 받아쓰기를 함께 쓰는 클로닝. 동화 읽기 품질은 이쪽이 낫다. |
| 8GB | `Qwen3-TTS-12Hz-0.6B-Base` | 메모리에 들어간다. 복제 유사도는 1.7B보다 낮다. |

같은 샘플로 들어보고 한국어 낭독이 밋밋하면, 비교 대상은 MLX로 돌아가는 CosyVoice 3 0.5B다. CUDA 전용 모델은 이 머신에서 빼는 편이 낫다.

## 통과한 다음

얇은 제품으로 간다. 목소리 하나, 이야기 몇 편, 재생 버튼만 있는 웹 화면이면 충분하다. 계정, 결제, 학습 콘텐츠는 그 뒤에 둔다.
