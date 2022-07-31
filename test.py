from __future__ import annotations
from array import array
import asyncio
import datetime
from fileinput import filename
from importlib.resources import path
import json
import os
import sys
import time
import traceback
from asyncio import Task
from typing import Optional
import dateutil.parser
import re

from commons import get_danmaku_tool_file_path, get_file_dir

str = r"W:\B站直播录制\blrec\rec\23501664 - 莉奥拉Liala\blive_23501664_2022-07-31-090227-呃呃睡过头了.mp4".replace('\\', '/')
dir = os.path.dirname(str)
filename = os.path.basename(str)
matchObj = re.match(r'blive_\d+_(\d+\-\d+)\-\d+\-.*\.mp4', filename)
if matchObj:
    dir = dir + f"/{matchObj.group(1)}/"
else:
    print("not match")

os.makedirs(dir, mode=0o777, exist_ok=True)

fullname = dir + '/' + filename
print(dir)
print(filename)
print(fullname)