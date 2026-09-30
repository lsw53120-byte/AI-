import os
import sys
import time
import threading
import urllib.request
import webbrowser

import streamlit.web.cli as stcli


APP_URL = "http://127.0.0.1:8501"


def resolve_path(path):
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, path)
    return os.path.join(os.path.abspath("."), path)


def server_is_ready():
    try:
        with urllib.request.urlopen(APP_URL, timeout=0.6) as response:
            return response.status == 200
    except Exception:
        return False


def open_browser_when_ready():
    for _ in range(80):
        if server_is_ready():
            try:
                os.startfile(APP_URL)
                return
            except Exception:
                webbrowser.open(APP_URL)
                return
        time.sleep(0.25)


if __name__ == "__main__":
    if hasattr(sys, "frozen"):
        os.chdir(os.path.dirname(sys.executable))

    # 이미 실행 중이면 중복 서버 대신 기존 화면만 엽니다.
    if server_is_ready():
        os.startfile(APP_URL)
        raise SystemExit(0)

    threading.Thread(target=open_browser_when_ready, daemon=True).start()
    sys.argv = [
        "streamlit",
        "run",
        resolve_path("app.py"),
        "--global.developmentMode=false",
        "--server.headless=true",
        "--server.address=127.0.0.1",
        "--server.port=8501",
        "--server.enableCORS=false",
        "--server.enableXsrfProtection=false",
        "--server.maxUploadSize=500",
        "--browser.gatherUsageStats=false",
    ]
    raise SystemExit(stcli.main())
