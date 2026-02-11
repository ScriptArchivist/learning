import json
import subprocess
from pathlib import Path
import subprocess
from pathlib import Path

def ffprobe_metadata(full_path: str) -> dict:
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-show_entries", "format=duration",
        "-of", "json",
        full_path,
    ]
    out = subprocess.check_output(cmd)
    data = json.loads(out.decode("utf-8"))
    duration = float(data.get("format", {}).get("duration") or 0) or None
    stream = (data.get("streams") or [{}])[0]
    width = stream.get("width")
    height = stream.get("height")
    return {"duration": duration, "width": width, "height": height}

def make_thumbnail(full_path: str, out_path: str, at_seconds: float = 1.0) -> None:
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(at_seconds),
        "-i", full_path,
        "-frames:v", "1",
        "-q:v", "3",
        out_path,
    ]
    subprocess.check_call(cmd)



def make_hls(full_path: str, out_dir: str) -> str:
    """
    Делает HLS (index.m3u8 + ts-сегменты) из локального файла.
    out_dir создаётся автоматически.
    Возвращает абсолютный путь к index.m3u8 (внутри контейнера).
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    playlist = out / "index.m3u8"
    segments = out / "seg_%05d.ts"

    # 1) Пробуем без перекодирования (минимальная нагрузка)
    cmd_copy = [
        "ffmpeg", "-y",
        "-hide_banner", "-loglevel", "info",
        "-i", full_path,
        "-an",
        "-c:v", "copy",
        "-f", "hls",
        "-hls_time", "2",
        "-hls_list_size", "6",
        "-hls_flags", "delete_segments+append_list+independent_segments+temp_file",
        "-hls_segment_type", "mpegts",
        "-hls_segment_filename", str(segments),
        str(playlist),
    ]

    p = subprocess.run(cmd_copy, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if p.returncode == 0 and playlist.exists():
        return str(playlist)

    # 2) Fallback: перекодируем в H.264 (если copy не подошёл)
    cmd_x264 = [
        "ffmpeg", "-y",
        "-hide_banner", "-loglevel", "info",
        "-i", full_path,
        "-an",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-profile:v", "main",
        "-pix_fmt", "yuv420p",
        "-g", "48",
        "-keyint_min", "48",
        "-sc_threshold", "0",
        "-f", "hls",
        "-hls_time", "2",
        "-hls_list_size", "6",
        "-hls_flags", "delete_segments+append_list+independent_segments+temp_file",
        "-hls_segment_type", "mpegts",
        "-hls_segment_filename", str(segments),
        str(playlist),
    ]

    p2 = subprocess.run(cmd_x264, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if p2.returncode != 0 or not playlist.exists():
        raise RuntimeError(
            "ffmpeg hls failed.\n"
            f"copy attempt output:\n{p.stdout}\n\n"
            f"x264 attempt output:\n{p2.stdout}\n"
        )

    return str(playlist)

