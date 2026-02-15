# service/ffmpeg_utils.py
import json
import shutil
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

    duration_raw = (data.get("format") or {}).get("duration")
    duration = float(duration_raw) if duration_raw else None

    stream = (data.get("streams") or [{}])[0] or {}
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
    """Generate multi-variant HLS (360p/720p/1080p) with audio + master playlist.

    Output layout:
      {out_dir}/master.m3u8
      {out_dir}/360p/index.m3u8 + segments
      {out_dir}/720p/index.m3u8 + segments
      {out_dir}/1080p/index.m3u8 + segments
    """
    out = Path(out_dir)
    tmp = out.parent / (out.name + "__tmp")

    if tmp.exists():
        shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True, exist_ok=True)

    master = tmp / "master.m3u8"
    variant_pattern = str(tmp / "%v" / "index.m3u8")
    seg_pattern = str(tmp / "%v" / "seg_%05d.ts")

    # scale with aspect ratio preserved + pad to exact frame size (x264-friendly)
    filter_complex = (
        "[0:v]split=3[v1][v2][v3];"
        "[v1]scale=w=640:h=360:force_original_aspect_ratio=decrease,"
        "pad=640:360:(ow-iw)/2:(oh-ih)/2,setsar=1[v360];"
        "[v2]scale=w=1280:h=720:force_original_aspect_ratio=decrease,"
        "pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1[v720];"
        "[v3]scale=w=1920:h=1080:force_original_aspect_ratio=decrease,"
        "pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1[v1080]"
    )

    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "info",
        "-i", full_path,

        "-filter_complex", filter_complex,

        # map video variants + (optional) audio
        "-map", "[v360]",  "-map", "0:a:0?",
        "-map", "[v720]",  "-map", "0:a:0?",
        "-map", "[v1080]", "-map", "0:a:0?",

        # video encoding (all variants)
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-profile:v", "main",
        "-pix_fmt", "yuv420p",
        "-g", "48",
        "-keyint_min", "48",
        "-sc_threshold", "0",

        # bitrate ladder (defaults)
        "-b:v:0", "800k",  "-maxrate:v:0", "856k",  "-bufsize:v:0", "1200k",
        "-b:v:1", "2800k", "-maxrate:v:1", "2996k", "-bufsize:v:1", "4200k",
        "-b:v:2", "5000k", "-maxrate:v:2", "5350k", "-bufsize:v:2", "7500k",

        # audio encoding
        "-c:a", "aac",
        "-ac", "2",
        "-b:a:0", "96k",
        "-b:a:1", "128k",
        "-b:a:2", "192k",

        # HLS output
        "-f", "hls",
        "-hls_time", "2",
        "-hls_list_size", "0",
        "-hls_playlist_type", "vod",
        "-hls_flags", "independent_segments+temp_file",
        "-hls_segment_type", "mpegts",
        "-start_number", "0",
        "-hls_segment_filename", seg_pattern,
        "-master_pl_name", "master.m3u8",

        # name each variant folder
        "-var_stream_map",
        "v:0,a:0,name:360p v:1,a:1,name:720p v:2,a:2,name:1080p",

        variant_pattern,
    ]

    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if p.returncode != 0 or not master.exists():
        raise RuntimeError("ffmpeg multi-variant hls failed.\n" + p.stdout)

    if out.exists():
        shutil.rmtree(out, ignore_errors=True)
    tmp.rename(out)

    return str(out / "master.m3u8")
