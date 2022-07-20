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
import dateutil.parser

class Cls:
    x:int

    def __init__(self, x:int) -> None:
        self.x = x

dic:dict = dict()
dic[1] = Cls(10)
dic[3] = Cls(30)

print(dic.pop(100, None))