import os


BINARY_PATH = "/"

def get_file_dir(path:str)->str:
    return os.path.dirname(os.path.abspath(path))

def get_danmaku_tool_file_path(path:str)->str:
    return get_file_dir(__file__) + "/danmaku_tools/" + path