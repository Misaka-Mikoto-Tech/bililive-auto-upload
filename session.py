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
from blrec_event import BlrecEvent
#from gpuinfo import GPUInfo

from commons import BINARY_PATH, get_danmaku_tool_file_path
from commons import get_room_id
from recorder_config import RecoderRoom
from session_manager import SessionManager


async def async_wait_output(command):
    print(f"running: {command}")
    sys.stdout.flush()
    process = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    return_value = await process.communicate()
    sys.stdout.flush()
    sys.stderr.flush()
    return return_value


class Video:
    base_path: str
    base_dir: str
    room_id: int
    session:Session
    date:datetime
    video_resolution: str
    video_resolution_x: int
    video_resolution_y: int
    video_length_flv: float

    def __init__(self, file_closed_event_json:str, session:Session):
        flv_name = file_closed_event_json['data']['path']
        self.base_path = os.path.abspath(flv_name.rpartition('.')[0])
        self.base_dir = os.path.dirname(self.base_path)
        self.room_id = file_closed_event_json["data"]["room_id"]
        self.date = file_closed_event_json["date"]
        self.session = session

    def flv_file_path(self):
        return self.base_path + ".flv"

    def mp4_file_path(self):
        return self.base_path + ".mp4"

    def xml_file_path(self):
        return self.base_path + ".xml"

    async def gen_thumbnail(self, he_time, png_file_path, video_log_path):
        ffmpeg_command_img = f"ffmpeg -y -ss {he_time} -i \"{self.flv_file_path()}\" -vframes 1 \"{png_file_path}\"" \
                             f" >> \"{video_log_path}\" 2>&1"
        await async_wait_output(ffmpeg_command_img)

    async def query_meta(self):
        video_length_str = await async_wait_output(
            f'ffprobe -v error -show_entries format=duration '
            f'-of default=noprint_wrappers=1:nokey=1 "{self.flv_file_path()}"'
        )
        video_resolution_str = await async_wait_output(
            f'ffprobe -v error -select_streams v:0 -show_entries stream=width,height '
            f'-of csv=s=x:p=0 "{self.flv_file_path()}"'
        )
        self.video_length_flv = float(video_length_str[0].decode('utf-8').strip())
        self.video_resolution = str(video_resolution_str[0].decode('utf-8').strip())
        video_resolutions = self.video_resolution.split("x")
        self.video_resolution_x, self.video_resolution_y = int(video_resolutions[0]), int(video_resolutions[1])


class Session:
    session_id:int
    session_manager:SessionManager
    events:set[str] # 已处理过的事件，防止重复处理（blrec可能会重复发送）
    live_start_time: datetime.datetime # 开播时间
    start_time: datetime.datetime # 开始录制事件
    end_time: Optional[datetime.datetime]
    uid: int
    room_id: int
    videos: list[Video]
    total_length: float
    notify_length: int # 暂时不知道是啥
    length_alert: bool
    he_time: Optional[float] # high energy
    early_video_path: Optional[str] # 将碎片文件合并起来的文件 xxx.all.flv
    room_name: str # 如果开播以后点开始录播，此数据会获取不到
    room_title: str
    room_config: RecoderRoom

    def __init__(self, session_start_event_json, notify_length=60, room_config=None):
        if room_config is None:
            self.room_config = RecoderRoom({})
        else:
            self.room_config = room_config
        self.live_start_time = time.ctime(session_start_event_json["data"]["live_start_time"])
        self.start_time = dateutil.parser.isoparse(session_start_event_json["date"])
        self.room_id = session_start_event_json["data"]["room_id"]
        self.end_time = None
        self.notify_length = notify_length
        self.length_alert = False
        self.total_length = 0
        self.videos = []
        self.he_time = None
        self.early_video_path = None
        self.process_update(session_start_event_json)
        self.upload_task: Optional[Task] = None
        self.events = set()

    def process_update(self, update_json:str) -> bool:
        if update_json["id"] in self.events:
            return False
        self.events.add(update_json["id"])
        BlrecEvent.update_room_info(json, self)
        if update_json["type"] in ["RecordingFinishedEvent", "RecordingCancelledEvent"]: # 录制结束
            self.end_time = dateutil.parser.isoparse(update_json["date"])
        return True

    async def add_video(self, video):
        try:
            await video.query_meta()
        except ValueError:
            print(traceback.format_exc())
            print(f"video corrupted, skipping: {video.flv_file_path()}")
            return
        self.videos += [video]
        new_length = self.total_length + video.video_length_flv
        if (new_length // self.notify_length) != (self.total_length // self.notify_length):
            self.length_alert = True
        self.total_length += new_length

    def output_base_path(self):
        process_dir = self.videos[0].base_dir + "/postprocess/" + self.start_time.strftime("%Y-%m-%d")
        if(not os.path.isdir(process_dir)):
            os.makedirs(process_dir, exist_ok=True)
        return process_dir + ".all"

    def output_path(self):
        return {
            "xml": self.output_base_path() + ".xml",
            "clean_xml": self.output_base_path() + ".clean.xml",
            "ass": self.output_base_path() + ".ass",
            "early_video": self.output_base_path() + ".flv",
            "danmaku_video": self.output_base_path() + ".bar.mp4",
            "concat_file": self.output_base_path() + ".concat.txt",
            "thumbnail": self.output_base_path() + ".thumb.png",
            "he_graph": self.output_base_path() + ".he.png",
            "he_file": self.output_base_path() + ".he.txt",
            "he_range": self.output_base_path() + ".he_range.txt",
            "sc_file": self.output_base_path() + ".sc.txt",
            "sc_srt": self.output_base_path() + ".sc.srt",
            "he_pos": self.output_base_path() + ".he_pos.txt",
            "extras_log": self.output_base_path() + ".extras.log",
            "video_log": self.output_base_path() + ".video.log",
        }

    async def merge_xml(self): # 官方仓库说支持blrec格式的弹幕文件，因此无需重写
        xmls = ' '.join(['"' + video.xml_file_path() + '"' for video in self.videos])
        tool_path = get_danmaku_tool_file_path("merge_danmaku.py")
        danmaku_merge_command = \
            f"python3 -m \"{tool_path}\" " \
            f"{xmls} " \
            f"--video_time \".flv\" " \
            f"--output \"{self.output_path()['xml']}\" " \
            f">> \"{self.output_path()['extras_log']}\" 2>&1"
        await async_wait_output(danmaku_merge_command)

    async def clean_xml(self):
        tool_path = get_danmaku_tool_file_path("clean_danmaku.py")
        danmaku_clean_command = \
            f"python3 -m \"{tool_path}\" " \
            f"{self.output_path()['xml']} " \
            f"--output \"{self.output_path()['clean_xml']}\" " \
            f">> \"{self.output_path()['extras_log']}\" 2>&1"
        await async_wait_output(danmaku_clean_command)

    async def process_xml(self):
        tool_path = get_danmaku_tool_file_path("danmaku_energy_map.py")
        danmaku_extras_command = \
            f"python3 -m \"{tool_path}\" " \
            f"--graph \"{self.output_path()['he_graph']}\" " \
            f"--he_map \"{self.output_path()['he_file']}\" " \
            f"--sc_list \"{self.output_path()['sc_file']}\" " \
            f"--he_time \"{self.output_path()['he_pos']}\" " \
            f"--sc_srt \"{self.output_path()['sc_srt']}\" " \
            f"--he_range \"{self.output_path()['he_range']}\" " + \
            (
                f"--user_dict \"{self.room_config.he_user_dict}\" "
                if self.room_config.he_user_dict is not None else ""
            ) + \
            (
                f"--regex_rules \"{self.room_config.he_regex_rules}\" "
                if self.room_config.he_regex_rules is not None else ""
            ) + \
            f"\"{self.output_path()['clean_xml']}\" " \
            f">> \"{self.output_path()['extras_log']}\" 2>&1"
        await async_wait_output(danmaku_extras_command)
        with open(self.output_path()['he_pos'], 'r') as file:
            he_time_str = file.readline()
            self.he_time = float(he_time_str)

    def generate_concat(self):
        concat_text = "\n".join([f"file '{video.flv_file_path()}'" for video in self.videos])
        with open(self.output_path()['concat_file'], 'w') as concat_file:
            concat_file.write(concat_text)

    async def process_thumbnail(self):
        local_he_time = self.he_time
        thumbnail_generated = False
        for video in self.videos:
            if local_he_time < video.video_length_flv:
                await video.gen_thumbnail(local_he_time, self.output_path()['thumbnail'],
                                          self.output_path()['video_log'])
                thumbnail_generated = True
                break
            local_he_time -= video.video_length_flv
        if not thumbnail_generated:  # Rare case where he_pos is after the last video
            print(f"{self.output_path()['video']}: thumbnail at {local_he_time} cannot be found")
            await self.videos[-1].gen_thumbnail(
                self.videos[-1].video_length_flv / 2,
                self.output_path()['thumbnail'],
                self.output_path()['video_log']
            )

    def get_resolution(self):
        video_res_sorted = list(reversed([
            (video.video_resolution_x / video.video_resolution_y,
             video.video_resolution_x,
             video.video_resolution_y)
            for video in self.videos
        ]))  # prioritize wider, higher-res format
        video_res_x = video_res_sorted[0][1]
        video_res_y = video_res_sorted[0][2]
        return video_res_x, video_res_y

    async def process_danmaku(self):
        video_res_x, video_res_y = self.get_resolution()
        font_size = max(video_res_x, video_res_y) * 55 // 1920
        print(f"font_size: {font_size}")
        danmaku_conversion_command = \
            f"{BINARY_PATH}DanmakuFactory/DanmakuFactory " \
            f"-x {video_res_x} " \
            f"-y {video_res_y} " \
            f"--ignore-warnings " \
            f"-o \"{self.output_path()['ass']}\" " \
            f"-i \"{self.output_path()['clean_xml']}\" " \
            f"--fontname \"Noto Sans CJK SC\" -S {font_size} -O 255 -L 1 -D 1 --showusernames true --showmsgbox false" \
            f">> \"{self.output_path()['extras_log']}\" 2>&1"
        await async_wait_output(danmaku_conversion_command)

    async def process_early_video(self):
        if len(self.videos) == 1:
            self.early_video_path = self.videos[0].flv_file_path
            return
        
        format_check = True
        ref_video_res = self.videos[0].video_resolution
        for video in self.videos:
            if video.video_resolution != ref_video_res: # TODO 分辨率不一致就不再Copy? 只有一个文件也Copy?
                format_check = False
                break
        if not format_check:
            return
        ffmpeg_command = f'''ffmpeg -y \
        -f concat \
        -safe 0 \
        -i "{self.output_path()['concat_file']}" \
        -c copy "{self.output_path()['early_video']}" >> "{self.output_path()["video_log"]}" 2>&1'''
        await async_wait_output(ffmpeg_command)
        self.early_video_path = self.output_path()['early_video']

    # 生成第一遍的无弹幕版的视频
    async def gen_early_video(self):
        if len(self.videos) == 0:
            print(f"No video in session for {self.room_id}@{self.start_time}, skip!")
            return
        await self.merge_xml()
        await self.clean_xml()
        await self.process_xml()
        await self.process_danmaku()
        await self.process_thumbnail()
        self.generate_concat()
        await self.process_early_video()

    # 生成第二遍的带弹幕高能进度条的视频
    # TODO 1.改成多P上传
    # 2.考虑将ffmpeg参数都改成配置文件
    async def gen_danmaku_video(self):
        if len(self.videos) == 0:
            print(f"No video in session for {self.room_id}@{self.start_time}, skip!")
            return
        
        total_time = sum([video.video_length_flv for video in self.videos])
        max_size = 8000_000 * 8  # Kb
        audio_bitrate = 320
        video_bitrate = (max_size / total_time - audio_bitrate) - 500  # just to be safe
        max_video_bitrate = float(8000)  # BiliBili now re-encode every video anyways
        video_bitrate = int(min(max_video_bitrate, video_bitrate))
        video_res_x, video_res_y = self.get_resolution()
        ffmpeg_command = f'''ffmpeg -y -loop 1 -t {total_time} \
        -i "{self.output_path()['he_graph']}" \
        -f concat \
        -safe 0 \
        -i "{self.output_path()['concat_file']}" \
        -t {total_time} \
        -filter_complex "
        [1:v]scale={video_res_x}:{video_res_y}:force_original_aspect_ratio=decrease,pad={video_res_x}:{video_res_y}:-1:-1:color=black[v_fixed];
        [0:v][v_fixed]scale2ref=iw:iw*(main_h/main_w)[color][ref];
        [color]split[color1][color2];
        [color1]hue=s=0[gray];
        [color2]negate=negate_alpha=1[color_neg];
        [gray]negate=negate_alpha=1[gray_neg];
        color=black:d={total_time}[black];
        [black][ref]scale2ref[blackref][ref2];
        [blackref]split[blackref1][blackref2];
        [color_neg][blackref1]overlay=x=t/{total_time}*W-W[color_crop_neg];
        [gray_neg][blackref2]overlay=x=t/{total_time}*W[gray_crop_neg];
        [color_crop_neg]negate=negate_alpha=1[color_crop];
        [gray_crop_neg]negate=negate_alpha=1[gray_crop];
        [ref2][color_crop]overlay=y=main_h-overlay_h[out_color];
        [out_color][gray_crop]overlay=y=main_h-overlay_h[out];
        [out]ass='{self.output_path()['ass']}'[out_sub]" \
        -map "[out_sub]" -map 1:a ''' + \
                         " -c:v libx264 -preset faster " + \
                         f'-b:v {video_bitrate}K' + f''' -b:a 320K -ar 44100  "{self.output_path()['danmaku_video']}" \
                    ''' + f'>> "{self.output_path()["video_log"]}" 2>&1'
        await async_wait_output(ffmpeg_command)


if __name__ == '__main__':
    BINARY_PATH = "../exes/"
    session_json = {'EventType': 'SessionStarted', 'EventTimestamp': '2021-04-09T22:50:15.301987-07:00',
                    'EventId': '6379acb5-0dfd-465e-bb03-58d9867e7591',
                    'EventData': {'SessionId': 'e3807981-3104-402a-ad71-8d42023c787d', 'RoomId': 128308, 'ShortId': 0,
                                  'Name': '隐染啊', 'Title': '不要自闭挑战', 'AreaNameParent': '娱乐', 'AreaNameChild': '户外'}}
    filenames = ["128308-20210530-014105.flv", "128308-20210530-020536.flv", "128308-20210530-032330.flv"]
    video_json_list = [
        {'EventType': 'FileClosed', 'EventTimestamp': '2021-04-09T23:44:37.128312-07:00',
         'EventId': '114c0b8d-80a3-4d2e-81f5-9d1ba17f4acd',
         'EventData': {'RelativePath': f'128308/{filename}', 'FileSize': 128308,
                       'Duration': 63.646, 'FileOpenTime': '2021-04-09T23:43:32.456413-07:00',
                       'FileCloseTime': '2021-04-09T23:44:37.128288-07:00',
                       'SessionId': '22fa4a41-6e75-4ed6-8352-2a2449eeb252', 'RoomId': 128308, 'ShortId': 0,
                       'Name': '隐染啊', 'Title': '不要自闭挑战', 'AreaNameParent': '娱乐', 'AreaNameChild': '户外'}} for filename in filenames
    ]
    session = Session(session_json)
    video_tasks = []
    for video_json in video_json_list:
        video = Video(video_json)
        asyncio.run(session.add_video(video))

    asyncio.run(session.gen_early_video())
    asyncio.run(session.gen_danmaku_video())
