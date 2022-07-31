import argparse
import asyncio
import os
from shutil import copyfile
import sys
import re

from commons import get_danmaku_tool_file_path, get_file_dir

parser = argparse.ArgumentParser(description='gen danmaku summary files')
parser.add_argument('video_file', type=str, nargs='+', help='path to the video file')

global Video_path
Video_path:str = None

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

global Base_path
Base_path:str = None
def output_base_path()->str:
    global Base_path
    if Base_path is None:
        dir = os.path.dirname(Video_path) + '/danmaku/'
        filename = os.path.basename(Video_path)
        
        os.makedirs(dir, mode=0o777, exist_ok=True)
        Base_path = dir + filename.split(".")[-2] + ".all"
    return Base_path

def output_path():
    return {
        "xml": output_base_path() + ".xml",
        "clean_xml": output_base_path() + ".clean.xml",
        "ass": output_base_path() + ".ass",
        "early_video": output_base_path() + ".flv",
        "danmaku_video": output_base_path() + ".bar.mp4",
        "concat_file": output_base_path() + ".concat.txt",
        "thumbnail": output_base_path() + ".thumb.png",
        "he_graph": output_base_path() + ".he.png",
        "he_file": output_base_path() + ".he.txt",
        "he_range": output_base_path() + ".he_range.txt",
        "sc_file": output_base_path() + ".sc.txt",
        "sc_srt": output_base_path() + ".sc.srt",
        "he_pos": output_base_path() + ".he_pos.txt",
        "extras_log": output_base_path() + ".extras.log",
        "video_log": output_base_path() + ".video.log"}

async def clean_xml():
    tool_path = get_danmaku_tool_file_path("clean_danmaku.py")
    danmaku_clean_command = \
        f"python \"{tool_path}\" " \
        f"\"{output_path()['xml']}\" " \
        f"--output \"{output_path()['clean_xml']}\" " \
        f">> \"{output_path()['extras_log']}\" 2>&1"
    await async_wait_output(danmaku_clean_command)

async def process_xml():
    tool_path = get_danmaku_tool_file_path("danmaku_energy_map.py")
    danmaku_extras_command = \
        f"python \"{tool_path}\" " \
        f"--graph \"{output_path()['he_graph']}\" " \
        f"--he_map \"{output_path()['he_file']}\" " \
        f"--sc_list \"{output_path()['sc_file']}\" " \
        f"--he_time \"{output_path()['he_pos']}\" " \
        f"--sc_srt \"{output_path()['sc_srt']}\" " \
        f"--he_range \"{output_path()['he_range']}\" " + \
        f"\"{output_path()['clean_xml']}\" " \
        f">> \"{output_path()['extras_log']}\" 2>&1"
    await async_wait_output(danmaku_extras_command)

async def do_gen_files(video_path:str):
    print(video_path)
    print(output_base_path())
    copyfile(video_path.split(".")[-2] + ".xml", output_path()['xml'])
    await clean_xml()
    await process_xml()

if __name__ == '__main__':
    args = parser.parse_args()

    if len(args.video_file) == 0:
        print("video file path have to be passed as input.")

    Video_path = args.video_file[0].replace('\\', '/')
    asyncio.run(do_gen_files(Video_path))