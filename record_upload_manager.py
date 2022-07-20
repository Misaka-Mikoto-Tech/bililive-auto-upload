import asyncio
import os.path
import sys
import threading
import time
import traceback
import toml
from queue import Queue
from string import Template

import dateutil.parser
import yaml
from bilibili_api import video

from comment_task import CommentTask
from blrec_event import BlrecEvent
from recorder_config import RecorderConfig, UploaderAccount
from room_sessions import RoomSessions
#from recorder_manager import RecorderManager
from session import Session, Video
from session_manager import SessionManager
from subtitle_task import SubtitleTask
from task_save import TaskSave
from upload_task import UploadTask

CONTINUE_SESSION_MINUTES = 5
WAIT_SESSION_MINUTES = 6
WAIT_BEFORE_SESSION_MINUTES = 1

class RecordUploadManager:
    def __init__(self, config_path, save_path):
        self.config_path = config_path
        self.save_path = save_path
        with open(config_path, 'r') as file:
            self.config = RecorderConfig(yaml.load(file, Loader=yaml.FullLoader))
        if os.path.isfile(save_path):
            with open(save_path, 'r') as file:
                self.save = TaskSave.from_dict(yaml.load(file, Loader=yaml.FullLoader))
        else:
            print("Creating save file")
            self.save = TaskSave()
            self.save_progress()
        
        # 改为接收 blrec 的数据，BililiveRecorder 会漏录数据
        #self.recorder_manager = RecorderManager([room.id for room in self.config.rooms])
        self.session_manager: SessionManager = SessionManager()
        self.video_upload_queue: Queue[UploadTask] = Queue()
        self.comment_post_queue: Queue[CommentTask] = Queue()
        self.subtitle_post_queue: Queue[SubtitleTask] = Queue()
        self.save_lock = threading.Lock()
        self.video_upload_thread = threading.Thread(target=self.video_uploader)
        self.comment_post_thread = threading.Thread(target=self.comment_poster)
        self.subtitle_post_thread = threading.Thread(target=self.subtitle_poster)
        self.video_processing_loop = asyncio.new_event_loop()
        self.video_uploading_loop = asyncio.new_event_loop()
        self.subtitle_posting_loop = asyncio.new_event_loop()
        self.video_upload_thread.start()
        self.comment_post_thread.start()
        self.subtitle_post_thread.start()
        self.video_uploading_thread = threading.Thread(target=lambda: self.video_processing_loop.run_forever())
        self.video_uploading_thread.start()

    def save_progress(self):
        with open(self.save_path, 'w') as file:
            yaml.dump(self.save.to_dict(), file, Dumper=yaml.Dumper)

    def video_uploader(self):
        asyncio.set_event_loop(self.video_uploading_loop)
        while True:
            upload_task = self.video_upload_queue.get()
            try:
                # TODO session_id 貌似最好还是要处理一下的，否则无法区分同个room_id的多个已上传但未通过审核的任务
                first_video_comment = upload_task.session_id not in self.save.session_id_map
                bv_id = upload_task.upload(self.save.session_id_map)
                sys.stdout.flush()
                with self.save_lock:
                    self.save.session_id_map[upload_task.session_id] = bv_id
                    self.save_progress()
                if first_video_comment:
                    self.comment_post_queue.put(
                        CommentTask.from_upload_task(upload_task)
                    )
                v_info = video.get_video_info(bvid=bv_id, is_simple=False, is_member=True, verify=upload_task.verify)
                cid = v_info['videos'][0]['cid']
                print("adding subtitle task to queue")
                self.subtitle_post_queue.put(
                    SubtitleTask.from_upload_task(upload_task, bv_id, cid)
                )
            except Exception:
                if upload_task.trial < 5:
                    upload_task.trial += 1
                    self.video_upload_queue.put(upload_task)
                    print(f"Upload failed: {upload_task.title}, retrying")
                else:
                    print(f"Upload failed too many times: {upload_task.title}")
                print(traceback.format_exc())

    def comment_poster(self):
        asyncio.set_event_loop(self.video_uploading_loop)
        while True:
            with self.save_lock:
                while not self.comment_post_queue.empty():
                    self.save.active_comment_tasks += [self.comment_post_queue.get()]
                    self.save_progress()
            try:
                if len(self.save.active_comment_tasks) != 0:
                    task_to_remove = []
                    for idx, task in enumerate(self.save.active_comment_tasks):
                        task: CommentTask
                        if task.post_comment(self.save.session_id_map):
                            task_to_remove += [idx]
                    if task_to_remove != 0:
                        with self.save_lock:
                            self.save.active_comment_tasks = [
                                comment_task
                                for idx, comment_task in enumerate(self.save.active_comment_tasks)
                                if idx not in task_to_remove
                            ]
                            self.save_progress()
            except Exception as err:
                print(f"Unknown posting exception: {err}")
                print(traceback.format_exc())
            finally:
                time.sleep(60)

    def subtitle_poster(self):
        asyncio.set_event_loop(self.subtitle_posting_loop)
        while True:
            with self.save_lock:
                while not self.subtitle_post_queue.empty():
                    self.save.active_subtitle_tasks += [self.subtitle_post_queue.get()]
                    self.save_progress()
            try:
                if len(self.save.active_subtitle_tasks) != 0:
                    task_to_remove = []
                    for idx, task in enumerate(self.save.active_subtitle_tasks):
                        task: SubtitleTask
                        print("try posting subtitle")
                        if task.post_subtitle():
                            task_to_remove += [idx]
                    if task_to_remove != 0:
                        with self.save_lock:
                            new_subtitle_tasks = []
                            for idx, subtitle_task in enumerate(self.save.active_subtitle_tasks):
                                subtitle_task: SubtitleTask
                                append = True
                                if idx in task_to_remove:
                                    append = False
                                else:
                                    for j in task_to_remove:
                                        removing_task = self.save.active_subtitle_tasks[j]
                                        if subtitle_task.is_earlier_task_of(removing_task):
                                            append = False
                                            break
                                if append:
                                    new_subtitle_tasks += [subtitle_task]
                            self.save.active_subtitle_tasks = new_subtitle_tasks
                            self.save_progress()
            except Exception as err:
                print(f"Unknown posting exception: {err}")
                print(traceback.format_exc())
            finally:
                time.sleep(60)

    # 接收到录播结束事件后的回调函数
    async def upload_video(self, session: Session):
        await asyncio.sleep(WAIT_BEFORE_SESSION_MINUTES * 60)
        if len(session.videos) == 0:
            print(f"No video in session: {session.room_id}@{session.session_id}")
            return
        room_config = session.room_config
        if room_config.uploader is None:
            print(f"No need to upload for {room_config.id}")
            await session.gen_early_video()
            await asyncio.sleep(WAIT_SESSION_MINUTES * 60)
            await session.gen_danmaku_video()
            return
        uploader: UploaderAccount = self.config.accounts[room_config.uploader]
        substitute_dict = {
            "name": session.room_name,
            "title": session.room_title,
            "uploader_name": uploader.name,
            "y": session.start_time.year,
            "m": session.start_time.month,
            "d": session.start_time.day,
            "yy": f"{session.start_time.year:04d}",
            "mm": f"{session.start_time.month:02d}",
            "dd": f"{session.start_time.day:02d}",
            "flv_path": session.videos[0].flv_file_path()
        }
        title = Template(room_config.title).substitute(substitute_dict)
        # blrec 无法区分不同session_id，因此历史title没有意义
        # temp_title = title
        # i = 1
        # other_video_titles = [
        #     name for room_id, name in self.save.video_name_history.items()
        #     if room_id != session.room_id
        # ]
        # while temp_title in other_video_titles:
        #     i += 1
        #     temp_title = f"{temp_title}{i}"
        # title = temp_title
        # with self.save_lock:
        #     self.save.video_name_history[session.room_id] = title
        description = Template(room_config.description).substitute(substitute_dict)
        await session.gen_early_video()
        early_upload_task = None # 无字幕版视频上传
        if session.early_video_path is not None: # 可能是原始文件(录制文件未分段)或xx.all.flv, 多个分段且分辨率不同时会出现无原始文件的情况
            early_upload_task = UploadTask(
                #session_id=session.session_id,
                video_path=session.early_video_path,
                thumbnail_path=session.output_path()['thumbnail'],
                sc_path=session.output_path()['sc_file'],
                he_path=session.output_path()['he_file'],
                subtitle_path=session.output_path()['sc_srt'],
                title=title,
                source=room_config.source,
                description=description,
                tag=room_config.tags,
                channel_id=room_config.channel_id,
                danmaku=False,
                account=uploader
            )
            self.video_upload_queue.put(early_upload_task)
        await asyncio.sleep(WAIT_SESSION_MINUTES * 60)
        if self.config.gen_he_video or session.early_video_path is None: # 未能快速生成early_video时强制生成弹幕高能版
            await session.gen_danmaku_video()
            danmaku_upload_task = UploadTask(
                #session_id=session.session_id,
                video_path=session.output_path()['danmaku_video'],
                thumbnail_path=session.output_path()['thumbnail'],
                sc_path=session.output_path()['sc_file'],
                he_path=session.output_path()['he_file'],
                subtitle_path=session.output_path()['sc_srt'],
                title=title,
                source=room_config.source,
                description=description,
                tag=room_config.tags,
                channel_id=room_config.channel_id,
                danmaku=True,
                account=uploader
            )
            self.video_upload_queue.put(
                danmaku_upload_task
            )
        if early_upload_task is None: # TODO 无原始文件时直接创建评论任务
            self.comment_post_queue.put(
                CommentTask.from_upload_task(danmaku_upload_task)
            )

    # web处理函数改为接收 blrec 请求
    async def handle_update_blrec(self, update_json: dict):
        id = update_json["id"] #guid
        room_id = BlrecEvent.get_room_id(update_json)
        event_timestamp = dateutil.parser.isoparse(update_json["date"])
        event_type = update_json["type"]

        room_config = None
        for room in self.config.rooms:
            if room.id == room_id:
                room_config = room
        
        if room_config is None:
            #print(f"Cannot find room config for {room_id}!")
            return
        else:
            print(f"Received blrec event:{event_type} of room:{room_id}")
        
        if event_type in ["LiveBeganEvent", "RecordingStartedEvent"]: # 允许从中间开始录制
            for sessions in self.sessions.values():
                if sessions.room_id == room_id:
                    last_session = sessions[-1]
                    # 5分钟内重新开播(开始录制)的视为同一场直播
                    # 两个事件均收到时忽略第二个事件（开播前就已运行会收到两个事件）
                    if (event_timestamp - last_session.end_time).total_seconds() / 60 < CONTINUE_SESSION_MINUTES or \
                        (event_timestamp - last_session.start_time).total_seconds() < 10:
                        if last_session.upload_task is not None:
                            last_session.upload_task.cancel()
                        return
            self.session_manager.add_session(Session(update_json, room_config=room_config))
        else:
            current_session: Session = self.session_manager.get_recording_session(room_id)
            if current_session is None:
                return

            if not current_session.process_update(update_json):
                return
            
            # blrec 支持转封装flv为mp4，录制结束后可能还会收到VideoPostprocessingCompletedEvent事件，
            # 此事件可能会在录制结束事件之后发送，当前无法得知是否会被转封装，临时解决方案是关闭转封装功能
            if event_type == "VideoFileCompletedEvent":
                new_video = Video(update_json, current_session)
                await current_session.add_video(new_video)
            elif event_type in ["RecordingFinishedEvent", "RecordingCancelledEvent"]: # 录制结束和取消都视为录制完成
                current_session.upload_task = \
                    asyncio.run_coroutine_threadsafe(self.upload_video(current_session), self.video_processing_loop)


    # async def handle_update(self, update_json: dict):
    #     room_id = update_json["EventData"]["RoomId"]
    #     session_id = update_json["EventData"]["SessionId"]
    #     event_timestamp = dateutil.parser.isoparse(update_json["EventTimestamp"])
    #     room_config = None
    #     for room in self.config.rooms:
    #         if room.id == room_id:
    #             room_config = room
    #     if room_config is None:
    #         print(f"Cannot find room config for {room_id}!")
    #         return
    #     if update_json["EventType"] == "SessionStarted":
    #         for session in self.sessions.values():
    #             if session.room_id == room_id and \
    #                     (event_timestamp - session.end_time).total_seconds() / 60 < CONTINUE_SESSION_MINUTES:
    #                 self.sessions[session_id] = session
    #                 if session.upload_task is not None:
    #                     session.upload_task.cancel()
    #                 return
    #         self.sessions[session_id] = Session(update_json, room_config=room_config)
    #     else:
    #         if session_id not in self.sessions:
    #             print(f"Cannot find {room_id}/{session_id} for: {update_json}")
    #             return
    #         current_session: Session = self.sessions[session_id]
    #         current_session.process_update(update_json)
    #         if update_json["EventType"] == "FileClosed":
    #             new_video = Video(update_json)
    #             await current_session.add_video(new_video)
    #         elif update_json["EventType"] == "SessionEnded":
    #             current_session.upload_task = \
    #                 asyncio.run_coroutine_threadsafe(self.upload_video(current_session), self.video_processing_loop)
