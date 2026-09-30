# AI 블로그 오토 스튜디오

사진을 분석해 네이버 블로그와 Blogger용 글 작성을 돕는 Windows용 Streamlit 앱입니다.

## 실행 방법

Windows PowerShell에서 다음 순서로 실행합니다.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python run.py
```

실행 후 앱 화면에서 Gemini API 키를 입력해 사용합니다.

## 모델 모드

- 기본 모드: 분석은 Gemini 3.5 Flash-Lite, 글쓰기는 Gemini 3.8 Flash
- Pro 모드: 분석은 Gemini 3.8 Flash, 최종 글쓰기는 Gemini 3.1 Pro Preview
- 절약 모드: 분석과 글쓰기 모두 Gemini 3.5 Flash-Lite
- 선택한 모델이 사용할 수 없으면 자동으로 대체 모델을 시도합니다.

## Blogger 연결

Blogger 업로드 기능을 쓰려면 Google Cloud에서 받은 `client_secret.json`이 필요합니다. 로그인 후 생성되는 `token.json`도 로컬에만 보관하세요.

다음 파일에는 인증 정보가 들어갈 수 있으므로 GitHub에 올리면 안 됩니다.

- `app_config.json`
- `client_secret*.json`
- `token*.json`
- `.env*`

이 저장소의 `.gitignore`에 위 파일들이 이미 제외되어 있습니다.

## EXE 빌드

```powershell
pip install -r requirements-dev.txt
python -m PyInstaller --noconfirm --clean BloggerAutoStudio.spec
```

빌드 결과물은 `dist` 폴더에 생성됩니다. `dist`와 EXE는 소스 저장소에 커밋하지 말고, 배포가 필요하면 GitHub Releases에 별도로 첨부하세요.
[Windows용 AI 블로그 오토 스튜디오 다운로드](https://github.com/사용자명/저장소명/releases/download/태그명/AI.exe)

