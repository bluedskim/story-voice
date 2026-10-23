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

녹음 대본: [`content/record_script.txt`](content/record_script.txt). 자세한 팁은 [`content/recording_guide.md`](content/recording_guide.md).

웹 **목소리** 탭: 녹음/업로드 → **받아쓰기 확인**(서버가 Qwen3-ASR로 인식) → 받아쓰기를 고친 뒤 **이 목소리로 저장**. 확인 전에는 기존 목소리가 바뀌지 않습니다. 저장 시 `reference.wav`(24kHz mono)와 **확인한** `reference.txt`가 함께 들어가고, 이전 참조는 `data/voice/history/`에 백업됩니다. 녹음 **5–40초**, 업로드 **8MB** 이하. 받아쓰기 길이는 녹음 시간과 맞아야 합니다(대략 **2–11자/초**). 이야기 **생성 중**에는 받아쓰기 확인이 잠시 거절됩니다(ASR는 별도 프로세스, TTS와 동시에 MLX를 쓰지 않음).

CLI로 직접 넣을 때:

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

한 편 (검증된 CLI — wav 출력):

```bash
source .venv/bin/activate
scripts/clone_story.sh data/voice/reference.wav data/voice/reference.txt \
  content/stories/ui-joeun-hyeongje.txt out/story.wav
```

카탈로그 단축 (기본 출력 `data/audio/<id>.m4a`):

```bash
scripts/clone_story.sh content/stories/ui-joeun-hyeongje.txt
```

전체 (모델은 한 번만 로드):

```bash
python scripts/generate_all.py
```

쉼·청크 (검증 기본: `--max-chars 120`, `--pause 0.35`):

```bash
python scripts/clone_story.py content/stories/ui-joeun-hyeongje.txt \
  --sentence-pause 0.35 --paragraph-pause 0.75 --max-chars 120
```

생성 파일: `data/audio/<id>.m4a` (역시 git 제외).

#### 대사(따옴표) 스타일 — EQ

동화 원문에서 `"…"` / `‘…’` 안의 **대사**는 별도 TTS 청크로 읽고, 기본적으로 **airy** EQ 프리셋을 씁니다 (피치·볼륨 보정은 0, 사용자가 env로만 조정).

| 환경 변수 | 설명 |
|-----------|------|
| `STORY_VOICE_DIALOGUE_EQ_PRESET` | `airy` (기본), `bright`, `warm` — `off`면 EQ 없음 |
| `STORY_VOICE_DIALOGUE_EQ` | ffmpeg `-af` 체인 전체를 직접 지정 (프리셋보다 우선) |
| `STORY_VOICE_DIALOGUE_STYLE=0` | 대사 후처리 끔 (`clone_story.py --no-dialogue-style` 동일) |
| `STORY_VOICE_DIALOGUE_PITCH_ST` / `STORY_VOICE_DIALOGUE_GAIN_DB` | 기본 0 (선택) |

대사 청크 처리 순서: 페이드 인 → (선택) 피치/게인 → EQ → **입력 평균 음량에 맞춤** → 피크 리미터 (`alimiter`, 약 -1 dBFS) → 페이드 아웃.

### 5. 웹 플레이어 + 다시 만들기

```bash
source .venv/bin/activate
python scripts/serve.py
# 기본: http://127.0.0.1:8765/ — Cloudflare Tunnel은 localhost:8765 로 프록시
# 집 Wi‑Fi에서 포트 직접 열기: python scripts/serve.py --host 0.0.0.0
```

- **이야기** 탭: 재생, **다시 만들기**, **전체 다시 만들기** (다시 만들기는 **운영자**만)
- **목소리** 탭: 녹음/업로드, 받아쓰기, 저장 (**운영자**만; 회원은 듣기만)
- 헤더: **로그인** / **회원가입** (가족용 한국어 UI). 세션은 HttpOnly 쿠키 `sv_session`.
- 생성은 서버 안 **단일 워커**(MLX 모델 1회 로드, 작업 1개씩, 대기열 최대 2). 새 `.m4a`는 임시 파일에 만든 뒤 `rename`으로 교체해 재생 중 끊김을 줄입니다. 완료 후 카탈로그·오디오 화이트리스트를 **재시작 없이** 갱신합니다.
- IP당 요청 제한·업로드/대기열 상한 (`CF-Connecting-IP` 지원). 공개 URL은 운영자 선택입니다.

#### 계정·권한

| 구분 | 설명 |
|------|------|
| **회원** | 이야기 재생·다운로드 |
| **운영자** | 목소리 저장, 이야기 다시 만들기 (`STORY_VOICE_ADMIN_EMAILS`에 있는 이메일만; 로그인·`/api/auth/me`마다 목록과 대조) |

SQLite: `data/story_voice.db` (git 제외). 비밀번호는 scrypt.

**API (JSON, 쿠키 세션 + CSRF)**

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/api/config` | `csrfToken`, `authEmailDevMode`, 정적 `assetVersions` |
| GET | `/api/users/nickname-available?nickname=` | 닉네임 중복 (`^[a-zA-Z0-9_가-힣]{2,12}$`) |
| POST | `/api/users/signup/send-verification` | 이메일 인증코드 (Resend, 60초 재전송 쿨다운) |
| POST | `/api/users/signup` | 가입 (`loginId`, `nickname`, `password`, `verificationCode`) |
| POST | `/api/auth/login` | 로그인 → 세션 쿠키 |
| POST | `/api/auth/logout` | 로그아웃 |
| GET | `/api/auth/me` | 현재 사용자 (`user` 또는 `null`) |

쓰기 API(목소리·생성)는 운영자 세션 + `X-CSRF-Token` 필요. 미로그인 401, 회원 403.

**환경 변수 (메일·세션)**

```bash
# 필수 (프로덕션): STORY_VOICE_PRODUCTION=1 이면 반드시 설정
export STORY_VOICE_SESSION_SECRET="$(openssl rand -base64 48)"

# Resend (baem.app 도메인 인증됨). 키 없으면 서버 로그에 코드만 출력
export RESEND_API_KEY="re_..."
export STORY_VOICE_MAIL_FROM='Story Voice <noreply@baem.app>'   # 기본값 동일
export STORY_VOICE_MAIL_MODE=resend   # resend | log

# 운영자 이메일 (쉼표 구분, 대소문자 무시). 비어 있으면 운영자 없음(서버 시작 시 경고)
export STORY_VOICE_ADMIN_EMAILS="you@example.com"
```

개발만: `STORY_VOICE_SESSION_SECRET` 없으면 `data/.session_secret`에 자동 생성 (gitignore).

Linux/CI에서 HTTP·대기열·ffmpeg·인증 검증:

```bash
python scripts/test_auth_flow.py
python scripts/test_generation_flow.py   # STORY_VOICE_GENERATOR=fake
python scripts/test_voice_upload_flow.py
```

### 6. Mac mini 배포 (launchd + Tunnel)

저장소 경로 `~/story-voice`, 에이전트 예: `app.baem.story-voice` (ProgramArguments는 `.venv`의 Python으로 `scripts/serve.py`).

```bash
cd ~/story-voice
git pull
source .venv/bin/activate
uv pip install -r requirements-mlx.txt
# launchd 재시작 (사용 중인 방법에 맞게)
launchctl kickstart -k gui/$(id -u)/app.baem.story-voice
```

Tunnel은 `http://127.0.0.1:8765` 를 `https://story-voice.baem.app` 등으로 노출합니다. `serve.py`는 기본 `127.0.0.1`에만 바인드합니다.

`serve.py`는 `web/catalog.json`을 갱신한 뒤, 페이지·API·카탈로그에 있는 `data/audio/<id>.m4a`만 제공합니다 (디렉터리 목록 없음, Safari용 HTTP Range).

## 프로젝트 구조

| 경로 | 설명 |
|------|------|
| `content/stories/` | 동화 원문 + 제목 메타데이터 |
| `content/recording_guide.md` | 목소리 녹음 가이드 |
| `data/voice/` | `reference.wav`, `reference.txt` (로컬만) |
| `data/audio/` | 생성된 `.m4a` (로컬만) |
| `scripts/clone_story.py` | 한 편 TTS (~120자 청크, mlx-audio `generate`, ffmpeg concat) |
| `scripts/generate_all.py` | 모든 편 일괄 생성 |
| `scripts/story_catalog.py` | `web/catalog.json` 빌드 |
| `scripts/serve.py` | 웹 UI, 목소리 API, 생성 대기열, 오디오 서빙 |
| `scripts/voice_service.py` | 참조 음성 저장·백업·ffmpeg 변환 |
| `scripts/generation_service.py` | 단일 워커 생성 큐 |
| `content/record_script.txt` | 웹에 표시되는 녹음 대본 |
| `web/` | 다크 테마 UI (한국어) |

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

계정(가족 로그인)은 웹에 들어갔다. 결제·학습 콘텐츠는 그 뒤에 둔다.
