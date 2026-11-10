#!/usr/bin/env python3
"""Local Blender + FFmpeg renderer for an AI Story Studio production package."""
import argparse, json, shutil, subprocess, tempfile
from pathlib import Path
from gtts import gTTS

HERE = Path(__file__).resolve().parent
def executable(value, default):
    found = shutil.which(value or default)
    if not found and value and Path(value).is_file():
        found = value
    if not found:
        raise SystemExit("Cannot find " + (value or default) + ". Install it or pass its path.")
    return str(found)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--blender")
    parser.add_argument("--ffmpeg")
    parser.add_argument("--language", choices=["English", "Tamil", "Hindi"], default="Tamil")
    parser.add_argument("--ratio", choices=["16:9", "9:16"], default="16:9")
    parser.add_argument("--fps", type=int, default=24)
    parser.add_argument("--seconds-per-scene", type=float, default=5)
    parser.add_argument("--output", default="ai-story-studio-3d.mp4")
    args = parser.parse_args()
    blender, ffmpeg = executable(args.blender, "blender"), executable(args.ffmpeg, "ffmpeg")
    project = json.loads((HERE / "project.json").read_text(encoding="utf-8"))
    scenes, characters = project.get("story", {}).get("scenes", []), project.get("characters", [])
    if not scenes:
        raise SystemExit("This project contains no scenes.")
    assets = {}
    for char in characters:
        filename = char.get("asset_file")
        if filename and (HERE / "assets" / filename).is_file():
            assets[char["name"]] = str((HERE / "assets" / filename).resolve())
    if not assets:
        raise SystemExit("Upload at least one rigged GLB character in the app before exporting this package.")
    lang = {"English":"en", "Tamil":"ta", "Hindi":"hi"}[args.language]
    width, height = (1080,1920) if args.ratio == "9:16" else (1920,1080)
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ai_story_") as temp:
        work = Path(temp)
        clips = []
        frames = max(24, int(args.fps * args.seconds_per_scene))
        for index, item in enumerate(scenes):
            names = item.get("characters") or list(assets.keys())
            names = [name for name in names if name in assets] or list(assets.keys())[:1]
            narration = " ".join(x for x in (item.get("narration",""),item.get("dialogue","")) if x).strip()
            narration = narration or item.get("heading","Scene")
            audio = work / f"voice_{index:03d}.mp3"
            gTTS(text=narration, lang=lang).save(str(audio))
            # Estimate narration duration so the animation does not cut off long dialogue.
            probe = subprocess.run([ffmpeg, "-i", str(audio), "-f", "null", "-"],
                                   capture_output=True, text=True)
            import re
            match = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", probe.stderr)
            audio_seconds = (int(match.group(1))*3600 + int(match.group(2))*60 + float(match.group(3))) if match else args.seconds_per_scene
            frames = max(frames, int((audio_seconds + 0.8) * args.fps))
            shot = {"assets":assets, "character_names":names, "heading":item.get("heading",""),
                    "visual_prompt":item.get("visual_prompt",""), "frame_end":frames,
                    "width":width, "height":height, "fps":args.fps}
            shot_json = work / f"shot_{index:03d}.json"
            shot_json.write_text(json.dumps(shot, ensure_ascii=False), encoding="utf-8")
            prefix = work / f"frame_{index:03d}_"
            run = subprocess.run([blender,"--background","--python",str(HERE/"render_scene.py"),
                                  "--",str(shot_json),str(prefix)],capture_output=True,text=True)
            if run.returncode:
                raise SystemExit(f"Blender failed on scene {index+1}:\\n{run.stderr[-5000:]}")
            clip = work / f"clip_{index:03d}.mp4"
            encode = [ffmpeg,"-y","-framerate",str(args.fps),"-i",str(prefix)+"%04d.png",
                      "-i",str(audio),"-vf",f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
                      "-c:v","libx264","-preset","medium","-pix_fmt","yuv420p","-c:a","aac",
                      "-b:a","192k","-shortest","-movflags","+faststart",str(clip)]
            result = subprocess.run(encode,capture_output=True,text=True)
            if result.returncode:
                raise SystemExit(f"FFmpeg failed on scene {index+1}:\n{result.stderr[-3000:]}")
            clips.append(clip)
        concat = work / "concat.txt"
        concat.write_text("".join("file '"+p.as_posix()+"'\n" for p in clips),encoding="utf-8")
        result = subprocess.run([ffmpeg,"-y","-f","concat","-safe","0","-i",str(concat),
                                 "-c","copy","-movflags","+faststart",str(output)],capture_output=True,text=True)
        if result.returncode:
            raise SystemExit("Final MP4 assembly failed:\n"+result.stderr[-3000:])
    print("Finished:", output)

if __name__ == "__main__":
    main()
