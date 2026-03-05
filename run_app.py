import streamlit.web.cli as stcli
import os, sys

# 파일의 실제 경로를 찾는 함수
def resolve_path(path):
    return os.path.abspath(os.path.join(os.getcwd(), path))

if __name__ == "__main__":
    # 실행할 메인 파일 이름 (실제 파일명으로 확인하세요)
    target_file = resolve_path("trackman_api_video.py")
    
    sys.argv = [
        "streamlit",
        "run",
        target_file,
        "--global.developmentMode=false",
    ]
    sys.exit(stcli.main())