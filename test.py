from __future__ import annotations
import asyncio
import datetime
import json
import os
import sys
import time
import traceback
from asyncio import Task
from typing import Optional

class Cls:
    xx:int

datas:set = set()

cls = Cls()
cls.xx = 2
datas.add(cls)
datas.add(Cls())

if(Cls() in datas):
    print("cc is none")
