from __future__ import annotations
from array import array
import asyncio
import datetime
import json
import os
import sys
import time
import traceback
from asyncio import Task
from typing import Optional
import dateutil.parser

from commons import get_danmaku_tool_file_path, get_file_dir

str = "  "
if str.strip() == "":
    print("empty")
else:
    print("not")