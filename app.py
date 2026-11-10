import base64
import json
import os
import subprocess
import tempfile
import time
import uuid
from datetime import datetime, timezone
import zipfile
from io import BytesIO
from pathlib import Path

import imageio_ffmpeg
import requests
import streamlit as st
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from gtts import gTTS
from PIL import Image, ImageDraw

st.set_page_config(page_title="AI Story Studio", page_icon="🎬", layout="wide")
st.title("🎬 AI Story Studio")
st.caption("Turn an original idea into a narrated YouTube-ready story video.")

def get_secret_key():
    try:
        return st.secrets.get("GEMINI_API_KEY", "")
    except Exception:
        return os.getenv("GEMINI_API_KEY", "")


def generate_scene_image(scene, characters, visual_style, ratio, progress_callback=None):
    """Free AI Horde generation with lower-work settings and rate-limit-safe polling."""
    cast = scene.get("characters", [])
    character_notes = [
        f"{item.get('name')}: {item.get('description', '')}"
        for item in characters if item.get("name") in cast
    ]
    cast_text = "; ".join(character_notes) or "Follow the original character descriptions in the scene."
    style_name = str(visual_style).lower()
    if "photoreal" in style_name or "live-action" in style_name:
        render_direction = (
            "Photorealistic live-action cinematic still photograph, real human skin texture and pores, "
            "natural facial proportions, realistic eyes, individual hair strands, authentic fabric texture, "
            "professional full-frame cinema camera, physically accurate lighting, natural depth of field, "
            "high-end film colour grading. It must look like a real photographed scene, not an illustration."
        )
    elif "animal" in style_name and "realistic" in style_name:
        render_direction = (
            "Ultra-detailed realistic 3D animal film still, lifelike anatomy, individually rendered fur or feathers, "
            "natural eyes, physically based materials, cinematic natural lighting and believable environment."
        )
    elif "stylized" in style_name:
        render_direction = (
            "Premium studio-quality stylized 3D animated feature film still, appealing expressive character design, "
            "detailed 3D materials, polished animation-movie lighting and cinematic composition."
        )
    else:
        render_direction = (
            "Premium cinematic realistic 3D animated family film still, believable human or animal anatomy, "
            "expressive natural faces, detailed hair and clothing, realistic skin and fur textures, "
            "physically based materials, soft global illumination and professional cinematography."
        )
    prompt = (
        render_direction + " "
        f"Visual direction: {visual_style}. Character continuity: {cast_text}. "
        f"Scene: {scene.get('heading', '')}. Action and camera: {scene.get('visual_prompt', '')}. "
        "One single coherent cinematic frame, original characters only, keep each saved character's "
        "face, hairstyle, body proportions, outfit and signature colours consistent, clear readable action, "
        "no text, logo, watermark or collage."
    )
    negative = (
        "flat vector, stick figure, crude cartoon, blurry, pixelated, bad anatomy, extra fingers, "
        "extra limbs, duplicated people, distorted face, text, subtitles, logo, watermark"
    )
    # Smaller images and fewer steps use far less volunteer GPU time.
    if ratio.startswith("9:16"):
        width, height = 512, 768
    else:
        width, height = 768, 432
    headers = {
        "apikey": "0000000000",
        "Client-Agent": "AI-Story-Studio:4.3:free",
        "Content-Type": "application/json",
    }
    payload = {
        "prompt": prompt + " ### " + negative,
        "params": {
            "sampler_name": "k_euler_a",
            "cfg_scale": 6.5,
            "steps": 14,
            "width": width,
            "height": height,
            "n": 1,
        },
        # No single-model restriction: any compatible volunteer worker may accept it.
        "nsfw": False,
        "censor_nsfw": True,
        "r2": True,
        "shared": True,
        "allow_downgrade": True,
    }
    base = "https://aihorde.net/api/v2"
    try:
        submitted = requests.post(
            base + "/generate/async", headers=headers, json=payload, timeout=(15, 45)
        )
        if submitted.status_code == 429:
            retry = submitted.headers.get("Retry-After", "a short while")
            raise RuntimeError(f"Free image service is receiving too many requests. Retry after {retry} seconds.")
        submitted.raise_for_status()
        request_id = submitted.json().get("id")
        if not request_id:
            raise RuntimeError("The free image service did not return a job ID.")

        # /check is designed for frequent progress checks; /status is reserved for final image retrieval.
        deadline = time.time() + 1800
        last_queue = None
        while time.time() < deadline:
            try:
                check_response = requests.get(
                    base + f"/generate/check/{request_id}", headers=headers, timeout=(10, 25)
                )
                if check_response.status_code == 429:
                    retry_after = check_response.headers.get("Retry-After")
                    delay = min(max(int(retry_after), 5), 60) if retry_after and retry_after.isdigit() else 15
                    if progress_callback:
                        progress_callback("rate-limited", f"retrying in {delay}s")
                    time.sleep(delay)
                    continue
                check_response.raise_for_status()
                check_data = check_response.json()
            except requests.exceptions.Timeout:
                time.sleep(10)
                continue

            queue = check_data.get("queue_position", "?")
            wait = check_data.get("wait_time", 0)
            if progress_callback and (queue, wait) != last_queue:
                progress_callback(queue, wait)
                last_queue = (queue, wait)

            if check_data.get("faulted"):
                raise RuntimeError("The volunteer worker could not complete this image. Please retry.")
            if check_data.get("done"):
                result_response = requests.get(
                    base + f"/generate/status/{request_id}", headers=headers, timeout=(15, 45)
                )
                if result_response.status_code == 429:
                    time.sleep(15)
                    result_response = requests.get(
                        base + f"/generate/status/{request_id}", headers=headers, timeout=(15, 45)
                    )
                result_response.raise_for_status()
                result_data = result_response.json()
                generations = result_data.get("generations") or []
                if not generations:
                    raise RuntimeError("The image job finished without returning an image.")
                image_value = generations[0].get("img", "")
                if image_value.startswith("http://") or image_value.startswith("https://"):
                    image_response = requests.get(image_value, timeout=(15, 90))
                    image_response.raise_for_status()
                    image_bytes = image_response.content
                else:
                    image_bytes = base64.b64decode(image_value)
                try:
                    with Image.open(BytesIO(image_bytes)) as image:
                        image.verify()
                except Exception as error:
                    raise RuntimeError("The free image service returned an invalid image.") from error
                return image_bytes

            # The Horde status cache is 1 second; 8-second checks reduce 429s without slowing completion.
            time.sleep(8)
        raise TimeoutError("The volunteer queue is still busy after 30 minutes. Your story is safe; retry later.")
    except requests.exceptions.Timeout as error:
        raise RuntimeError("The free image service timed out. Please retry.") from error
    except requests.exceptions.ConnectionError as error:
        raise RuntimeError("Could not connect to the free image service. Check the app connection and retry.") from error



def analyze_uploaded_characters(key, image_bytes, mime_type):
    """Use the user's Gemini key to extract reusable character descriptions from an uploaded image."""
    prompt = """
Analyze this uploaded image for distinct visible characters suitable for an original animated video.
Return JSON only, in this exact structure:
{"characters":[
 {"name":"short original name","type":"Human or Animal or Fantasy or Other",
  "description":"Detailed visible appearance: approximate age range if clearly adult/child, face shape, skin/fur colour, hair, eyes, clothing, body shape, accessories, distinctive visual details and personality only if visually suggested",
  "visual_prompt":"A full-body cinematic character reference portrait prompt, neutral simple background, same visible outfit and features",
  "bounding_box":[ymin,xmin,ymax,xmax]}
]}
Bounding box coordinates must be integers from 0 to 1000, relative to the full image. Include the whole visible character with a little surrounding space. If an accurate box cannot be determined, use [0,0,0,0].
Rules:
- Identify each clearly distinct character, up to 6. Do not invent hidden people.
- Do not identify real people or guess names, identity, ethnicity, exact age, or private traits.
- If the image is a real person, describe only visible non-sensitive appearance and create a fictionalized character description; do not claim the generated result will be an exact likeness.
- Preserve visible clothing, colours, hairstyle and accessories.
- If there are no discernible characters, return {"characters":[]}.
"""
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent"
    payload = {
        "contents": [{"parts": [
            {"text": prompt},
            {"inline_data": {"mime_type": mime_type, "data": base64.b64encode(image_bytes).decode("ascii")}}
        ]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2}
    }
    response = requests.post(url, params={"key": key}, json=payload, timeout=(15, 120))
    if response.status_code in (429, 500, 502, 503, 504):
        raise RuntimeError(f"Character image analysis is temporarily unavailable (HTTP {response.status_code}). Try again later.")
    response.raise_for_status()
    candidates = response.json().get("candidates", [])
    if not candidates:
        raise ValueError("The image analyser could not identify characters in this picture.")
    raw = candidates[0]["content"]["parts"][0]["text"].strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
    data = json.loads(raw)
    items = data.get("characters", []) if isinstance(data, dict) else []
    if not isinstance(items, list):
        raise ValueError("The image analyser returned an unexpected result.")
    cleaned = []
    for item in items[:6]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()[:60]
        description = str(item.get("description", "")).strip()[:1200]
        if not name or not description:
            continue
        kind = str(item.get("type", "Other")).title()
        if kind not in ("Human", "Animal", "Fantasy", "Other"):
            kind = "Other"
        crop_base64 = ""
        box = item.get("bounding_box", [])
        if isinstance(box, list) and len(box) == 4:
            try:
                ymin, xmin, ymax, xmax = [max(0, min(1000, int(value))) for value in box]
                if ymax > ymin and xmax > xmin:
                    with Image.open(BytesIO(image_bytes)) as source_image:
                        source_image = source_image.convert("RGB")
                        image_width, image_height = source_image.size
                        # Gemini coordinates are normalized to 0..1000; add a small margin.
                        left = int(xmin / 1000 * image_width)
                        top = int(ymin / 1000 * image_height)
                        right = int(xmax / 1000 * image_width)
                        bottom = int(ymax / 1000 * image_height)
                        margin_x = max(8, int((right - left) * 0.08))
                        margin_y = max(8, int((bottom - top) * 0.08))
                        crop = source_image.crop((
                            max(0, left - margin_x), max(0, top - margin_y),
                            min(image_width, right + margin_x), min(image_height, bottom + margin_y)
                        ))
                        buffer = BytesIO()
                        crop.save(buffer, format="JPEG", quality=90)
                        crop_base64 = base64.b64encode(buffer.getvalue()).decode("ascii")
            except Exception:
                crop_base64 = ""
        cleaned.append({
            "name": name,
            "type": kind,
            "description": description,
            "visual_prompt": str(item.get("visual_prompt", "")).strip()[:1200],
            "asset_file": "",
            "model_bytes": None,
            "portrait_base64": "",
            "source_reference_base64": crop_base64,
        })
    return cleaned


def generate_character_portrait(character, visual_style, ratio):
    """Create a single reusable character reference image using free AI Horde workers."""
    scene = {
        "heading": f"Character reference portrait: {character.get('name', 'Original character')}",
        "visual_prompt": (
            "Create a premium professional character reference portrait. "
            "Show one character only, full body, front three-quarter view, standing naturally, "
            "complete head-to-toe body and outfit visible, clean neutral studio background, "
            "sharp detailed face and eyes, natural anatomy, realistic hands, cinematic soft studio lighting. "
            "Keep the same facial features, hairstyle, skin tone, body proportions, clothing and accessories "
            "described below. Do not add other people, text, logos or watermarks. "
            f"Character details: {character.get('description', '')}. "
            f"Additional visual direction: {character.get('visual_prompt', '')}"
        ),
        "characters": [character.get("name", "")],
    }
    return generate_scene_image(scene, [character], visual_style, ratio)



def generate_story(key, idea, genre, style, count, characters):
    prompt = f"""
Create an original {genre} story based on this idea: {idea}
Visual direction: {style}
Character bible (use ONLY these reusable characters; do not invent replacements): {characters or "Create suitable original characters."}
Select the most relevant characters for the topic and use their exact names. Assign only suitable characters to each scene in the characters array. Keep their face, age range, hairstyle, body shape, clothing, colours and accessories identical across every scene. Do not rename or redesign them.
Create a production-ready script for a 3D animated video. Every visual_prompt must specify camera framing,
camera movement, character action, facial expression, body language, environment, lighting, time of day and mood.
Use original characters only. Return exactly {count} scenes as valid JSON with this structure:
{{
  "title": "story title",
  "logline": "one sentence",
  "scenes": [
    {{"heading":"scene heading","narration":"voiceover text","dialogue":"spoken dialogue","visual_prompt":"detailed 3D shot direction","characters":["character names appearing in this shot"]}}
  ]
}}
Keep character appearance and names consistent in every scene. Return JSON only.
Do not use copyrighted characters, existing franchises, or celebrity likenesses.
"""
    # Try the primary model, then a lighter fallback if Google is overloaded.
    models = ["gemini-3.8-flash", "gemini-3.5-flash-lite"]
    last_error = None
    for model in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        for attempt in range(2):
            try:
                response = requests.post(
                    url,
                    params={"key": key},
                    json={
                        "contents": [{"parts": [{"text": prompt}]}],
                        "generationConfig": {"responseMimeType": "application/json"},
                    },
                    timeout=(15, 180),
                )
                if response.status_code in (429, 500, 502, 503, 504):
                    last_error = requests.HTTPError(
                        f"Gemini model {model} is temporarily unavailable "
                        f"(HTTP {response.status_code}): {response.text[:500]}",
                        response=response,
                    )
                    if attempt == 0:
                        time.sleep(2)
                        continue
                    break
                response.raise_for_status()
                candidates = response.json().get("candidates", [])
                if not candidates:
                    raise ValueError("Gemini returned no story. Try again or check your API key.")
                raw = candidates[0]["content"]["parts"][0]["text"].strip()
                if raw.startswith("```"):
                    raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
                data = json.loads(raw)
                # Some model responses return each scene as a list instead of an object.
                # Normalize every item so downstream editors always receive dictionaries.
                if isinstance(data, list):
                    data = {"title": "Untitled story", "logline": "", "scenes": data}
                if not isinstance(data, dict):
                    raise ValueError("Gemini returned an invalid story structure. Please try again.")
                scenes = data.get("scenes")
                if not isinstance(scenes, list) or not scenes:
                    raise ValueError("The generated response did not contain any scenes.")
                normalized_scenes = []
                fields = ("heading", "narration", "dialogue", "visual_prompt", "characters")
                for scene_index, scene in enumerate(scenes):
                    if isinstance(scene, dict):
                        normalized = scene.copy()
                    elif isinstance(scene, list):
                        # Support positional scene data as a fallback.
                        if len(scene) == 1 and isinstance(scene[0], dict):
                            normalized = scene[0].copy()
                        else:
                            normalized = {
                                field: scene[pos] if pos < len(scene) else ""
                                for pos, field in enumerate(fields)
                            }
                    elif isinstance(scene, str):
                        normalized = {"heading": f"Scene {scene_index + 1}", "narration": scene}
                    else:
                        normalized = {"heading": f"Scene {scene_index + 1}", "narration": str(scene)}
                    for field in ("heading", "narration", "dialogue", "visual_prompt"):
                        value = normalized.get(field, "")
                        normalized[field] = value if isinstance(value, str) else str(value or "")
                    names = normalized.get("characters", [])
                    if isinstance(names, str):
                        names = [names] if names.strip() else []
                    elif not isinstance(names, list):
                        names = []
                    normalized["characters"] = [str(name) for name in names if name]
                    normalized_scenes.append(normalized)
                data["scenes"] = normalized_scenes
                data.setdefault("title", "Untitled story")
                data.setdefault("logline", "")
                return data
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as error:
                last_error = error
                if attempt == 0:
                    time.sleep(3)
                    continue
                break
            except requests.HTTPError as error:
                status = error.response.status_code if error.response is not None else None
                if status in (429, 500, 502, 503, 504):
                    last_error = error
                    if attempt == 0:
                        time.sleep(2)
                        continue
                    break
                raise
    if last_error:
        raise last_error
    raise RuntimeError("Gemini could not generate a story. Please try again shortly.")


YOUTUBE_SCOPE = ["https://www.googleapis.com/auth/youtube.upload"]
YOUTUBE_REDIRECT_PATH = "/oauth2callback"


def youtube_oauth_config():
    cfg = st.secrets.get("youtube", {})
    client_id = cfg.get("client_id", "")
    client_secret = cfg.get("client_secret", "")
    if not client_id or not client_secret:
        return None
    return {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [st.secrets.get("youtube_redirect_uri", "")],
        }
    }


def youtube_flow(state=None):
    config = youtube_oauth_config()
    if not config:
        raise RuntimeError("Add [youtube].client_id, [youtube].client_secret and youtube_redirect_uri in Streamlit Secrets.")
    redirect_uri = st.secrets.get("youtube_redirect_uri", "")
    if not redirect_uri:
        raise RuntimeError("Set youtube_redirect_uri in Streamlit Secrets.")
    flow = Flow.from_client_config(config, scopes=YOUTUBE_SCOPE, state=state)
    flow.redirect_uri = redirect_uri
    return flow


def youtube_credentials_from_session():
    token = st.session_state.get("youtube_token")
    if not token:
        return None
    return Credentials.from_authorized_user_info(token, YOUTUBE_SCOPE)


def handle_youtube_oauth_callback():
    params = st.query_params
    code = params.get("code")
    state = params.get("state")
    if not code:
        return
    expected_state = st.session_state.get("youtube_oauth_state")
    if not expected_state or state != expected_state:
        st.error("YouTube authorization state did not match. Please connect again.")
        st.query_params.clear()
        return
    try:
        flow = youtube_flow(state=expected_state)
        flow.fetch_token(code=code)
        st.session_state.youtube_token = json.loads(flow.credentials.to_json())
        st.session_state.youtube_oauth_state = None
        st.query_params.clear()
        st.success("YouTube channel connected. You can now upload manually.")
    except Exception as error:
        st.error(f"YouTube authorization failed: {error}")
        st.query_params.clear()


def upload_video_to_youtube(video_bytes, title, description, tags):
    credentials = youtube_credentials_from_session()
    if not credentials:
        raise RuntimeError("Connect your YouTube channel first.")
    youtube = build("youtube", "v3", credentials=credentials, cache_discovery=False)
    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "tags": [tag.strip() for tag in tags.split(",") if tag.strip()][:500],
            "categoryId": "22",
        },
        "status": {"privacyStatus": "unlisted", "selfDeclaredMadeForKids": False},
    }
    media = MediaIoBaseUpload(BytesIO(video_bytes), mimetype="video/mp4", chunksize=1024 * 1024, resumable=True)
    response = youtube.videos().insert(part="snippet,status", body=body, media_body=media).execute()
    return response.get("id")

def render_scene_card(scene, artwork_bytes, width, height, index, total):
    if artwork_bytes:
        image = Image.open(BytesIO(artwork_bytes)).convert("RGB")
        scale = max(width / image.width, height / image.height)
        image = image.resize((int(image.width * scale), int(image.height * scale)))
        left = (image.width - width) // 2
        top = (image.height - height) // 2
        image = image.crop((left, top, left + width, top + height))
    else:
        image = Image.new("RGB", (width, height), (29, 39, 68))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, int(height * 0.70), width, height), fill=(0, 0, 0))
    draw.text((int(width * 0.05), int(height * 0.74)),
              f"{index + 1}/{total}  {scene.get('heading', 'Scene')[:90]}", fill="white")
    narration = scene.get("narration", "").replace("\n", " ")
    draw.text((int(width * 0.05), int(height * 0.82)), narration[:220], fill=(225, 230, 245))
    return image

def export_video(scenes, artwork, ratio, language):
    if not scenes:
        raise ValueError("There are no scenes to export.")
    width, height = (720, 1280) if ratio.startswith("9:16") else (1280, 720)
    language_code = {"English": "en", "Tamil": "ta", "Hindi": "hi"}[language]
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        clips = []
        for index, scene in enumerate(scenes):
            narration = " ".join(
                part for part in (scene.get("narration", ""), scene.get("dialogue", "")) if part
            ).strip() or scene.get("heading", "Scene")
            audio_path = root / f"audio_{index}.mp3"
            image_path = root / f"scene_{index}.jpg"
            clip_path = root / f"clip_{index}.mp4"

            gTTS(text=narration, lang=language_code).save(str(audio_path))
            render_scene_card(scene, artwork.get(index), width, height, index, len(scenes)).save(
                image_path, quality=90
            )
            command = [
                ffmpeg, "-y", "-loop", "1", "-framerate", "24", "-i", str(image_path),
                "-i", str(audio_path), "-map", "0:v:0", "-map", "1:a:0",
                "-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage",
                "-r", "24", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
                "-shortest", "-movflags", "+faststart", str(clip_path),
            ]
            result = subprocess.run(command, capture_output=True, text=True)
            if result.returncode:
                raise RuntimeError(f"Could not render scene {index + 1}: {result.stderr[-1000:]}")
            clips.append(clip_path)

        concat_file = root / "concat.txt"
        concat_file.write_text(
            "".join("file '" + str(path).replace("'", "'\\''") + "'\n" for path in clips),
            encoding="utf-8",
        )
        output_path = root / "ai-story-studio.mp4"
        command = [
            ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file),
            "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(output_path),
        ]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(f"Could not combine scenes: {result.stderr[-1000:]}")
        return output_path.read_bytes()

def make_project_json(story, characters, artwork):
    safe_characters = []
    for character in characters:
        item = {key: value for key, value in character.items() if key != "model_bytes"}
        if character.get("model_bytes"):
            item["model_base64"] = base64.b64encode(character["model_bytes"]).decode("ascii")
        safe_characters.append(item)
    return json.dumps({
        "format_version": 3, "story": story, "characters": safe_characters,
        "artwork": {str(index): base64.b64encode(data).decode("ascii") for index, data in artwork.items()},
    }, ensure_ascii=False, indent=2).encode("utf-8")

def load_project_json(file_bytes):
    project = json.loads(file_bytes.decode("utf-8"))
    if not isinstance(project, dict) or not isinstance(project.get("story"), dict):
        raise ValueError("This file is not a valid AI Story Studio project.")
    scenes = project["story"].get("scenes")
    if not isinstance(scenes, list) or not scenes or len(scenes) > 20:
        raise ValueError("Project must contain between 1 and 20 scenes.")
    artwork = {int(index): base64.b64decode(value) for index, value in project.get("artwork", {}).items()}
    characters = project.get("characters", [])
    for character in characters:
        encoded = character.pop("model_base64", None)
        character["model_bytes"] = base64.b64decode(encoded) if encoded else None
    return project["story"], characters, artwork

def make_production_package(story, characters, artwork, ratio, language):
    package = BytesIO()
    with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("project.json", make_project_json(story, characters, artwork))
        for source, target in [
            ("blender_pipeline/render_project.py", "render_project.py"),
            ("blender_pipeline/render_scene.py", "render_scene.py"),
            ("blender_pipeline/README.md", "README.md"),
        ]:
            archive.writestr(target, Path(source).read_text(encoding="utf-8"))
        for character in characters:
            if character.get("model_bytes") and character.get("asset_file"):
                archive.writestr("assets/" + character["asset_file"], character["model_bytes"])
        archive.writestr("render-settings.txt", "Suggested language: " + language + "\nSuggested ratio: " + ratio + "\n")
    return package.getvalue()

BUILTIN_CHARACTER_LIBRARY = [
 {"name":"Aru","type":"Human","category":"kids","tags":["child","boy","school","friendship","rhyme","kids"],"description":"A cheerful 7-year-old Indian schoolboy with warm medium-brown skin, short neatly side-parted black hair, expressive dark-brown eyes, a sky-blue school shirt, navy shorts, white socks and black school shoes. Curious, brave and energetic.","visual_prompt":"Photoreal live-action child, sky-blue school shirt and navy shorts."},
 {"name":"Maya","type":"Human","category":"kids","tags":["child","girl","school","friendship","rhyme","kids"],"description":"A cheerful 7-year-old Indian schoolgirl with warm medium-brown skin, large brown eyes, long black hair in two braids with yellow ribbons, teal pinafore over a white shirt and white shoes. Kind and confident.","visual_prompt":"Photoreal live-action child, teal pinafore, white shirt and twin braids."},
 {"name":"Paati","type":"Human","category":"family","tags":["grandmother","family","kids","rhyme","village","home"],"description":"A kind Indian grandmother in her late 60s with silver hair in a low bun, gentle eyes, round glasses, lavender cotton saree and sandals. Warm, wise and playful.","visual_prompt":"Photoreal live-action elderly Indian woman in lavender saree."},
 {"name":"Kutti","type":"Animal","category":"animals","tags":["puppy","dog","pet","animal","kids","rhyme","friendship"],"description":"A small golden Indian-spitz puppy with fluffy cream-gold fur, floppy-tipped ears, round dark eyes and a green collar. Playful and loyal.","visual_prompt":"Photoreal realistic fluffy golden puppy with green collar."},
 {"name":"Mittu","type":"Animal","category":"animals","tags":["parrot","bird","animal","kids","rhyme","comedy"],"description":"A bright green parrot with yellow chest, curved red beak, subtle blue wing feathers and lively intelligent eyes. Curious and mischievous.","visual_prompt":"Photoreal realistic green parrot, yellow chest and red beak."},
 {"name":"Karthik","type":"Human","category":"comedy","tags":["comedy","funny","friends","office","adult","man"],"description":"A slim 25-year-old Indian man with medium-brown skin, short curly black hair, expressive eyebrows, red-and-black checked shirt, dark jeans and sneakers. Overconfident, talkative and lovable.","visual_prompt":"Photoreal live-action young Indian man in red-black checked shirt."},
 {"name":"Bala","type":"Human","category":"comedy","tags":["comedy","funny","friends","office","adult","man"],"description":"A cheerful stocky 27-year-old Indian man with medium-brown skin, round face, short black hair, orange polo shirt, dark trousers and sandals. Good-hearted and easily confused.","visual_prompt":"Photoreal live-action young Indian man in orange polo shirt."},
 {"name":"Boss Kumar","type":"Human","category":"comedy","tags":["comedy","office","boss","work","adult"],"description":"A middle-aged Indian office manager with neatly combed black hair, trimmed moustache, rectangular glasses, pale-blue formal shirt and charcoal trousers. Stern but comical.","visual_prompt":"Photoreal middle-aged Indian office manager in pale-blue shirt and glasses."},
 {"name":"Raja","type":"Animal","category":"animals","tags":["lion","wildlife","jungle","animal","adventure","kids"],"description":"A young Asiatic lion with tawny-gold fur, soft developing mane, amber eyes and a small notch in the left ear. Gentle but courageous.","visual_prompt":"Photoreal cinematic young Asiatic lion."},
 {"name":"Mimi","type":"Animal","category":"animals","tags":["rabbit","bunny","forest","animal","kids","adventure"],"description":"A small white rabbit with soft fur, pink inner ears, bright dark eyes and a sky-blue neck scarf. Quick and friendly.","visual_prompt":"Photoreal white rabbit with sky-blue scarf."},
 {"name":"Aadi","type":"Human","category":"adventure","tags":["adventure","treasure","explore","journey","hero"],"description":"A brave 16-year-old Indian adventurer with medium-brown skin, tousled black hair, alert brown eyes, forest-green utility jacket, tan cargo trousers, hiking boots and canvas shoulder bag.","visual_prompt":"Photoreal teenage Indian adventurer in green jacket and tan cargo trousers."},
 {"name":"Luna","type":"Fantasy","category":"fantasy","tags":["fantasy","magic","princess","space","moon","adventure"],"description":"An original moon guardian with silver-blue hair, luminous pale-blue eyes, midnight-blue cloak embroidered with tiny stars and a silver pendant. Calm and brave.","visual_prompt":"Cinematic realistic fantasy character with silver-blue hair and star cloak."},
 {"name":"Ember","type":"Fantasy","category":"fantasy","tags":["fantasy","dragon","magic","fire","adventure","kids"],"description":"A small friendly dragon with ruby-red scales, golden eyes, two short curved horns and softly glowing orange wing membranes. Playful.","visual_prompt":"Detailed realistic fantasy dragon with ruby scales."},
 {"name":"Arun","type":"Human","category":"family","tags":["family","father","husband","city","work","human","drama"],"description":"A 30-year-old Indian man with medium-brown skin, short black hair, close-trimmed beard, navy casual shirt, dark trousers and wristwatch. Thoughtful and dependable.","visual_prompt":"Photoreal Indian adult man in navy shirt."},
 {"name":"Priya","type":"Human","category":"family","tags":["family","mother","wife","city","work","human","drama"],"description":"A 28-year-old Indian woman with medium-brown skin, expressive brown eyes, long dark hair, simple teal kurta and small earrings. Warm and confident.","visual_prompt":"Photoreal Indian adult woman in teal kurta."},
 {"name":"Teacher Meena","type":"Human","category":"kids","tags":["teacher","school","classroom","child","education","kids"],"description":"A friendly Indian schoolteacher in her early 30s with medium-brown skin, dark hair tied back, rectangular glasses and neat pastel salwar suit. Patient and encouraging.","visual_prompt":"Photoreal Indian female teacher in pastel salwar suit."},
 {"name":"Pechu","type":"Animal","category":"comedy","tags":["monkey","jungle","comedy","funny","animal","kids"],"description":"A mischievous bonnet macaque with realistic brown fur, expressive eyes and a tiny red scarf. Clever and cheeky.","visual_prompt":"Photoreal bonnet macaque monkey with red scarf."}
]


def select_characters_for_story(idea, genre, characters, limit=4):
    """Choose matching built-in cast locally; no image service is called."""
    text = f"{idea} {genre}".casefold()
    scores = []
    for order, character in enumerate(characters):
        tags = character.get("tags", [])
        score = sum(2 for tag in tags if str(tag).casefold() in text)
        category = character.get("category", "")
        if category == "comedy" and any(word in text for word in ["comedy","funny","joke","office"]):
            score += 5
        if category == "kids" and any(word in text for word in ["rhyme","nursery","kids","children","school"]):
            score += 4
        if category == "animals" and any(word in text for word in ["animal","jungle","forest","pet","puppy","lion","rabbit","parrot"]):
            score += 4
        if category == "fantasy" and any(word in text for word in ["magic","dragon","fantasy","kingdom","princess","wizard","space"]):
            score += 5
        if category == "family" and any(word in text for word in ["family","mother","father","grandmother","home","village"]):
            score += 4
        if category == "adventure" and any(word in text for word in ["adventure","treasure","journey","explore","hero"]):
            score += 4
        scores.append((score, order, character))
    scores.sort(key=lambda row: (-row[0], row[1]))
    chosen = [row[2] for row in scores if row[0] > 0][:limit]
    return chosen or [row[2] for row in scores[:2]]

if "story" not in st.session_state:
    st.session_state.story = None
if "characters" not in st.session_state:
    st.session_state.characters = [dict(item, asset_file="", model_bytes=None, portrait_base64="", source_reference_base64="") for item in BUILTIN_CHARACTER_LIBRARY]
else:
    existing_character_names = {item.get("name", "").casefold() for item in st.session_state.characters}
    for default_character in BUILTIN_CHARACTER_LIBRARY:
        if default_character["name"].casefold() not in existing_character_names:
            st.session_state.characters.append(dict(default_character, asset_file="", model_bytes=None, portrait_base64="", source_reference_base64=""))
if "artwork" not in st.session_state:
    st.session_state.artwork = {}
if "creation_history" not in st.session_state:
    st.session_state.creation_history = []
if "current_history_id" not in st.session_state:
    st.session_state.current_history_id = None

def save_history_snapshot():
    """Keep a restorable, bounded history of stories and their generated images."""
    if not st.session_state.story:
        return
    entry_id = st.session_state.current_history_id or str(uuid.uuid4())
    st.session_state.current_history_id = entry_id
    safe_images = {
        str(index): base64.b64encode(data).decode("ascii")
        for index, data in st.session_state.artwork.items()
    }
    snapshot = {
        "id": entry_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "title": st.session_state.story.get("title", "Untitled story"),
        "genre": st.session_state.get("active_genre", ""),
        "style": st.session_state.get("active_style", ""),
        "ratio": st.session_state.get("active_ratio", ""),
        "story": st.session_state.story,
        "characters": [
            {key: value for key, value in item.items() if key != "model_bytes"}
            for item in st.session_state.characters
        ],
        "artwork": safe_images,
    }
    previous = [
        item for item in st.session_state.creation_history
        if item.get("id") != entry_id
    ]
    st.session_state.creation_history = [snapshot] + previous
    st.session_state.creation_history = st.session_state.creation_history[:20]

def restore_history_entry(entry):
    st.session_state.story = entry.get("story")
    st.session_state.characters = entry.get("characters", [])
    st.session_state.artwork = {
        int(index): base64.b64decode(value)
        for index, value in entry.get("artwork", {}).items()
    }
    st.session_state.current_history_id = entry.get("id")

with st.sidebar:
    st.header("Project settings")
    api_key = st.text_input("Gemini API key", value=get_secret_key(), type="password")
    st.caption("Use Streamlit Secrets for deployment. Never commit your key to GitHub.")
    st.success("Character library: built in and automatically matched to story topics. Scene artwork: free community generation.")
    st.caption("Images are created by volunteer AI Horde computers. Anonymous requests may wait in a queue; availability is not guaranteed.")
    genre = st.selectbox("Content type", ["Tamil nursery rhyme / kids song", "Comedy", "Moral story",
                                   "Bedtime story", "Adventure", "Educational", "Fantasy",
                                   "Animal story", "Family story", "Mystery", "Sci-fi",
                                   "Action / superhero", "Romance (family-friendly)"])
    visual_style = st.selectbox("Character and visual style", ["High-quality realistic 3D humans",
        "Stylized 3D animated humans", "Realistic 3D animals", "Stylized 3D animated animals",
        "3D fantasy characters", "Photoreal live-action look"])
    scene_count = st.slider("Number of scenes", 3, 8, 5)
    narration_language = st.selectbox("Narration language", ["English", "Tamil", "Hindi"])
    video_ratio = st.selectbox("Video format", ["9:16 Vertical Shorts", "16:9 YouTube widescreen"])

story_tab, character_tab, storyboard_tab, production_tab, export_tab, project_tab, history_tab = st.tabs(
    ["Story Writer", "Characters", "Storyboard", "3D Production", "Voice & Export", "Save / Load", "My History"]
)

with story_tab:
    idea = st.text_area("Your story idea",
                        placeholder="A young inventor finds a lost robot and helps it return home.")
    if st.button("Generate story", type="primary"):
        if not idea.strip():
            st.warning("Enter a story idea first.")
        elif not api_key.strip():
            st.warning("Add your Gemini API key in the sidebar or Streamlit Secrets.")
        else:
            selected_characters = select_characters_for_story(
                idea, genre, st.session_state.characters, limit=4
            )
            st.session_state.selected_story_characters = [item["name"] for item in selected_characters]
            character_bible = "; ".join(
                f"{character['name']} ({character.get('type', 'Character')}): {character['description']}"
                for character in selected_characters
            )
            try:
                with st.spinner("Choosing characters from your built-in library and writing your story..."):
                    st.session_state.story = generate_story(
                        api_key.strip(), idea, genre, visual_style, scene_count, character_bible
                    )
                st.session_state.artwork = {}
                st.session_state.current_history_id = str(uuid.uuid4())
                st.session_state.active_genre = genre
                st.session_state.active_style = visual_style
                st.session_state.active_ratio = video_ratio
                save_history_snapshot()
                st.success("Story generated and saved to My History. Auto-selected characters: " + ", ".join(st.session_state.selected_story_characters) + ". Review it in Storyboard.")
            except requests.HTTPError as error:
                detail = error.response.text[:1000] if error.response is not None else str(error)
                st.error(f"Gemini request failed: {detail}")
            except Exception as error:
                st.error(f"Story generation failed: {error}")

    if st.session_state.story:
        st.subheader(st.session_state.story.get("title", "Your story"))
        st.write(st.session_state.story.get("logline", ""))
        st.write(f"**Scenes:** {len(st.session_state.story.get('scenes', []))}")

with character_tab:
    st.subheader("Character Studio")
    st.caption("Build a reusable cast for nursery rhymes, comedy, stories, animals, fantasy and realistic human videos.")

    st.markdown("#### Create characters from an uploaded picture")
    reference_image = st.file_uploader(
        "Upload a picture containing one or more characters",
        type=["png", "jpg", "jpeg", "webp"], key="character_reference_upload"
    )
    st.caption("The picture is analysed with Gemini 3.8 Flash using your API key. Visible characters are identified, their descriptions are extracted, and approximate image crops are saved into your library. The uploaded picture is sent to Google's Gemini API for analysis; only use images you have permission to use.")
    if st.button("Automatically extract characters", type="primary",
                 disabled=(reference_image is None or not bool(api_key.strip()))):
        try:
            with st.spinner("Analysing the picture and identifying visible characters..."):
                mime_type = reference_image.type or "image/jpeg"
                extracted = analyze_uploaded_characters(
                    api_key.strip(), reference_image.getvalue(), mime_type
                )
            existing = {item.get("name", "").casefold() for item in st.session_state.characters}
            added = 0
            for item in extracted:
                if item["name"].casefold() not in existing:
                    st.session_state.characters.append(item)
                    existing.add(item["name"].casefold())
                    added += 1
            st.success(f"Extracted {len(extracted)} character(s); added {added} new character(s) to your library.")
            if not extracted:
                st.info("No clear characters were detected. Try a picture where the people or characters are visible.")
        except Exception as error:
            st.error(f"Character extraction failed: {error}")
    if reference_image is not None and not api_key.strip():
        st.warning("Add your Gemini API key in the sidebar to enable automatic character extraction.")

    st.divider()
    st.markdown("#### Quick character packs")
    pack_choice = st.selectbox(
        "Choose a starter cast",
        ["Nursery rhyme family", "Comedy friends", "Animal adventures", "Fantasy adventure", "Everyday human stories"],
        key="character_pack_choice"
    )
    packs = {
        "Nursery rhyme family": [
            ("Aru", "Human", "A cheerful 6-year-old boy with warm brown skin, round expressive face, short wavy black hair, bright blue shirt, mustard shorts and red sneakers. Friendly, curious and energetic."),
            ("Maya", "Human", "A cheerful 6-year-old girl with warm brown skin, large expressive brown eyes, two neat black braids with yellow ribbons, teal dress and white shoes. Kind and adventurous."),
            ("Paati", "Human", "A kind grandmother in her late 60s, silver hair in a low bun, gentle face, round glasses, lavender cotton saree and a warm smile."),
            ("Kutti", "Animal", "A small fluffy golden puppy with floppy ears, round dark eyes, a green collar and a playful friendly expression."),
            ("Mittu", "Animal", "A bright green parrot with a yellow chest, red curved beak and expressive eyes, curious and funny.")
        ],
        "Comedy friends": [
            ("Karthik", "Human", "A slim young adult man with medium brown skin, expressive eyebrows, short curly black hair, checked shirt, dark jeans and comic overconfident expressions."),
            ("Bala", "Human", "A cheerful stocky young adult man with medium brown skin, round face, short black hair, orange polo shirt and playful confused expressions."),
            ("Boss Kumar", "Human", "A middle-aged office manager with neatly combed black hair, rectangular glasses, moustache, pale blue formal shirt and stern but funny expressions."),
            ("Pechu", "Animal", "A mischievous small grey monkey with expressive eyes, a tiny red scarf and clever comic body language.")
        ],
        "Animal adventures": [
            ("Raja", "Animal", "A friendly young golden lion with soft detailed golden fur, expressive amber eyes and a gentle brave personality."),
            ("Mimi", "Animal", "A small white rabbit with soft fur, pink inner ears, bright eyes and a sky-blue scarf."),
            ("Koko", "Animal", "A colourful tropical parrot with emerald green feathers, yellow chest and red beak."),
            ("Toby", "Animal", "A playful brown bear cub with detailed soft fur, round ears and a red neckerchief.")
        ],
        "Fantasy adventure": [
            ("Aadi", "Human", "A brave teenage adventurer with medium brown skin, tousled black hair, navy tunic, leather shoulder strap and a determined expression."),
            ("Luna", "Fantasy", "A young moon guardian with silver-blue hair, luminous pale-blue eyes, flowing midnight-blue cloak and subtle magical star details."),
            ("Ember", "Fantasy", "A small friendly fire dragon with deep red scales, golden eyes, tiny horns and softly glowing orange wing membranes."),
            ("Moss", "Fantasy", "A gentle forest spirit with leaf-textured green hair, warm amber eyes and natural moss-green clothing.")
        ],
        "Everyday human stories": [
            ("Arun", "Human", "A young adult man with medium brown skin, short black hair, navy casual shirt, dark trousers and a thoughtful expression."),
            ("Priya", "Human", "A young adult woman with medium brown skin, long dark hair, expressive brown eyes, simple teal kurta and a confident warm expression."),
            ("Amma", "Human", "A middle-aged mother with medium brown skin, dark hair tied back, simple cotton saree and a caring expression."),
            ("Teacher Meena", "Human", "A friendly female teacher in her 30s with medium brown skin, dark hair tied back, rectangular glasses and a neat pastel salwar suit.")
        ],
    }
    if st.button("Add this character pack", key="add_character_pack"):
        existing = {item.get("name", "").casefold() for item in st.session_state.characters}
        added = 0
        for name, kind, description in packs[pack_choice]:
            if name.casefold() not in existing:
                st.session_state.characters.append({
                    "name": name, "type": kind, "description": description,
                    "asset_file": "", "model_bytes": None, "portrait_base64": "",
                    "visual_prompt": ""
                })
                existing.add(name.casefold())
                added += 1
        st.success(f"Added {added} original characters. Generate portraits below when needed.")

    st.divider()
    st.markdown("#### Add a character manually")
    with st.form("add_character", clear_on_submit=True):
        character_name = st.text_input("Character name")
        character_description = st.text_area("Appearance, personality and defining details",
                placeholder="Age range, face, hairstyle, skin tone, outfit, body shape, personality and signature details")
        character_type = st.selectbox("Character type", ["Human", "Animal", "Fantasy", "Other"])
        add_character = st.form_submit_button("Add character")
    if add_character:
        if character_name.strip() and character_description.strip():
            st.session_state.characters.append({
                "name": character_name.strip(), "description": character_description.strip(),
                "type": character_type, "asset_file": "", "model_bytes": None,
                "portrait_base64": "", "visual_prompt": ""
            })
            st.success("Character added.")
        else:
            st.warning("Enter both a name and description.")

    st.divider()
    st.markdown("#### Save or move your character library")
    library_data = {
        "format": "ai-story-studio-character-library",
        "version": 1,
        "characters": [
            {key: value for key, value in item.items() if key != "model_bytes"}
            for item in st.session_state.characters
        ],
    }
    st.download_button(
        "Download character library",
        json.dumps(library_data, ensure_ascii=False, indent=2).encode("utf-8"),
        file_name="ai_story_studio_characters.json",
        mime="application/json"
    )
    library_upload = st.file_uploader(
        "Import a saved character library", type=["json"], key="character_library_import"
    )
    if st.button("Import characters", disabled=(library_upload is None), key="import_character_library"):
        try:
            imported = json.loads(library_upload.getvalue().decode("utf-8"))
            incoming = imported.get("characters", [])
            if not isinstance(incoming, list):
                raise ValueError("This file does not contain a character list.")
            existing = {item.get("name", "").casefold() for item in st.session_state.characters}
            count = 0
            for item in incoming[:50]:
                if not isinstance(item, dict) or not item.get("name") or not item.get("description"):
                    continue
                if item["name"].casefold() in existing:
                    continue
                item["model_bytes"] = None
                item.setdefault("portrait_base64", "")
                item.setdefault("asset_file", "")
                st.session_state.characters.append(item)
                existing.add(item["name"].casefold())
                count += 1
            st.success(f"Imported {count} character(s).")
            st.rerun()
        except Exception as error:
            st.error(f"Could not import character library: {error}")

    st.divider()
    st.markdown(f"#### Your reusable cast ({len(st.session_state.characters)} characters)")
    for index, character in enumerate(st.session_state.characters):
        with st.expander(f"{character.get('name', 'Character')} · {character.get('type', 'Character')}", expanded=(index == 0)):
            if character.get("source_reference_base64"):
                try:
                    st.image(base64.b64decode(character["source_reference_base64"]), caption="Character crop extracted from your uploaded image", width=260)
                except Exception:
                    pass
            elif character.get("portrait_base64"):
                try:
                    st.image(base64.b64decode(character["portrait_base64"]), caption="Saved character reference portrait", width=260)
                except Exception:
                    pass
            if character.get("portrait_base64") and character.get("source_reference_base64"):
                try:
                    st.image(base64.b64decode(character["portrait_base64"]), caption="Generated reusable character portrait", width=260)
                except Exception:
                    pass
            st.write(character.get("description", ""))
            st.caption("Built-in reusable character profile. Automatically selected for matching story topics; no image-generation request or community-worker queue.")
            model_col = st.container()
            with model_col:
                model_upload = st.file_uploader(
                    "Attach rigged 3D model (.glb or .fbx)", type=["glb", "fbx"],
                    key=f"character_model_{index}"
                )
                if model_upload:
                    safe_name = "".join(ch.lower() if ch.isalnum() else "_" for ch in character["name"]).strip("_")
                    character["asset_file"] = (safe_name or f"character_{index}") + Path(model_upload.name).suffix.lower()
                    character["model_bytes"] = model_upload.getvalue()
                    st.success(f"3D model attached: {character['asset_file']}")
                elif character.get("model_bytes"):
                    st.caption(f"3D model attached: {character.get('asset_file')}")
            if st.button("Remove character", key=f"remove_character_{index}"):
                st.session_state.characters.pop(index)
                st.rerun()

with storyboard_tab:
    if not st.session_state.story:
        st.info("Generate or load a project to edit its storyboard.")
    else:
        st.info("Generate realistic 3D storyboard images scene by scene. Generated images are saved into your project and included in narrated MP4 exports.")
        st.success("Free AI image generation is built in. No API key or payment is needed.")
        character_names = [item["name"] for item in st.session_state.characters]
        for index, scene in enumerate(st.session_state.story["scenes"]):
            with st.expander(f"Scene {index + 1} — {scene.get('heading', 'Scene')}", expanded=(index == 0)):
                scene["heading"] = st.text_input("Scene heading", scene.get("heading", ""), key=f"heading_{index}")
                scene["narration"] = st.text_area("Narration", scene.get("narration", ""), key=f"narration_{index}")
                scene["dialogue"] = st.text_area("Dialogue", scene.get("dialogue", ""), key=f"dialogue_{index}")
                scene["visual_prompt"] = st.text_area("3D shot direction", scene.get("visual_prompt", ""), key=f"prompt_{index}")
                scene["characters"] = st.multiselect(
                    "Characters in this scene", character_names,
                    default=[name for name in scene.get("characters", []) if name in character_names],
                    key=f"scene_characters_{index}"
                )
                col1, col2 = st.columns([1, 1])
                with col1:
                    if st.button("Generate realistic image", key=f"generate_image_{index}", type="primary"):
                        try:
                            status_box = st.status("Connecting to free community image workers...", expanded=True)
                            progress_line = status_box.empty()
                            def update_image_progress(queue, wait):
                                progress_line.write(f"Free worker queue position: {queue} · Estimated wait: {wait} seconds")
                            with status_box:
                                st.session_state.artwork[index] = generate_scene_image(
                                    scene, st.session_state.characters, visual_style, video_ratio,
                                    progress_callback=update_image_progress
                                )
                                save_history_snapshot()
                                status_box.update(label="Image generated and saved to this project and My History.", state="complete")
                            st.rerun()
                        except Exception as error:
                            st.error(f"Free image generation failed: {error}")
                with col2:
                    if st.button("Remove generated image", key=f"remove_image_{index}",
                                 disabled=index not in st.session_state.artwork):
                        st.session_state.artwork.pop(index, None)
                        st.rerun()
                uploaded = st.file_uploader("Or upload your own image (free)", type=["png", "jpg", "jpeg"], key=f"art_{index}")
                if uploaded:
                    st.session_state.artwork[index] = uploaded.getvalue()
                    save_history_snapshot()
                if index in st.session_state.artwork:
                    st.image(st.session_state.artwork[index], use_container_width=True)
        st.caption("Generated images are saved in your project and used in MP4 exports. Free volunteer workers can be busy, so generation may take several minutes. Anonymous requests are shared with the community service; do not submit private photos or personal information. Character likeness consistency is best-effort.")

with production_tab:
    st.subheader("3D animated production package")
    st.write("Package your story and reusable 3D character models for local Blender rendering.")
    st.warning("Blender rendering runs on your computer, not Streamlit Cloud. You need Blender, FFmpeg and at least one rigged GLB character model.")
    attached = [item for item in st.session_state.characters if item.get("model_bytes")]
    st.metric("3D character models attached", len(attached))
    for item in st.session_state.characters:
        st.write(f"- {item['name']}: {'3D model ready' if item.get('model_bytes') else 'No GLB model attached'}")
    st.caption("Use original GLB models you own or have permission to use. Rigged models with embedded animation actions are recommended.")
    if st.session_state.story:
        if st.button("Build downloadable 3D production package", type="primary", disabled=(len(attached) == 0)):
            try:
                with st.spinner("Packaging story, character models and Blender renderer..."):
                    bundle = make_production_package(
                        st.session_state.story, st.session_state.characters,
                        st.session_state.artwork, video_ratio.split()[0], narration_language
                    )
                st.download_button("Download 3D production ZIP", bundle,
                    file_name="ai-story-studio-3d-production.zip",
                    mime="application/zip", type="primary")
                st.success("Production package is ready. Extract it and follow the included README.")
            except Exception as error:
                st.error(f"Could not build production package: {error}")
    else:
        st.info("Create or load a story first.")
    st.markdown("**Local render command**")
    st.code("python render_project.py --language Tamil --ratio 16:9", language="bash")
    st.caption("This first 3D milestone reuses imported models, adds simple camera and root movement, and renders narration. Text-to-3D generation, facial acting, lip-sync and detailed choreography are future milestones.")

with export_tab:
    if not st.session_state.story:
        st.info("Generate or load a project first.")
    else:
        st.write(f"**Output:** {video_ratio}  ·  **Narration:** {narration_language}")
        st.caption("Narration uses Google Text-to-Speech. Internet access is required during export.")
        if st.button("Build narrated MP4", type="primary"):
            try:
                with st.spinner("Creating voice tracks and rendering your video..."):
                    video_bytes = export_video(
                        st.session_state.story["scenes"], st.session_state.artwork,
                        video_ratio, narration_language
                    )
                st.session_state.generated_video = video_bytes
                st.success("Your MP4 is ready.")
            except Exception as error:
                st.error(f"Video export failed: {error}")
        if st.session_state.get("generated_video"):
            video_bytes = st.session_state.generated_video
            st.video(video_bytes)
            st.download_button(
                "Download MP4", video_bytes, file_name="ai-story-studio.mp4",
                mime="video/mp4", type="primary", key="download_generated_mp4"
            )
            st.divider()
            st.subheader("Upload to YouTube")
            st.caption("Manual upload only. The app always uploads as Unlisted; review it in YouTube Studio before sharing.")
            handle_youtube_oauth_callback()
            credentials = youtube_credentials_from_session()
            if credentials:
                st.success("YouTube channel is connected.")
                if st.button("Disconnect YouTube", key="disconnect_youtube"):
                    st.session_state.youtube_token = None
                    st.rerun()
            else:
                st.info("Connect your YouTube channel once to enable manual uploads.")
                if st.button("Connect YouTube channel", key="connect_youtube"):
                    try:
                        flow = youtube_flow()
                        auth_url, state = flow.authorization_url(
                            access_type="offline",
                            include_granted_scopes="true",
                            prompt="consent",
                        )
                        st.session_state.youtube_oauth_state = state
                        st.link_button("Continue with Google", auth_url)
                    except Exception as error:
                        st.error(str(error))
            upload_title = st.text_input(
                "YouTube title", value=st.session_state.story.get("title", "My AI Story")[:100],
                max_chars=100, key="youtube_upload_title"
            )
            upload_description = st.text_area(
                "Description", value=st.session_state.story.get("logline", ""),
                max_chars=5000, key="youtube_upload_description"
            )
            upload_tags = st.text_input("Tags (comma-separated)", key="youtube_upload_tags")
            st.warning("Manual approval required: clicking below uploads this video as UNLISTED to your connected channel. It will not be made public.")
            if st.button("Upload this video as Unlisted", type="primary", disabled=(credentials is None)):
                try:
                    with st.spinner("Uploading video to YouTube..."):
                        video_id = upload_video_to_youtube(
                            video_bytes, upload_title, upload_description, upload_tags
                        )
                    st.success("Upload complete. Your video is Unlisted.")
                    st.markdown(f"[Open your YouTube video](https://www.youtube.com/watch?v={video_id})")
                except Exception as error:
                    st.error(f"YouTube upload failed: {error}")

with project_tab:
    st.subheader("Save your project")
    if st.session_state.story:
        project_bytes = make_project_json(
            st.session_state.story, st.session_state.characters, st.session_state.artwork
        )
        safe_title = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in
                             st.session_state.story.get("title", "story"))[:50]
        st.download_button(
            "Download project backup (.json)", project_bytes,
            file_name=f"{safe_title or 'story'}_project.json",
            mime="application/json",
        )
        script_text = st.session_state.story.get("title", "Untitled story") + "\n"
        script_text += st.session_state.story.get("logline", "") + "\n\n"
        for index, scene in enumerate(st.session_state.story["scenes"], start=1):
            script_text += f"SCENE {index}: {scene.get('heading', '')}\n"
            script_text += f"NARRATION: {scene.get('narration', '')}\n"
            script_text += f"DIALOGUE: {scene.get('dialogue', '')}\n"
            script_text += f"IMAGE PROMPT: {scene.get('visual_prompt', '')}\n\n"
        st.download_button(
            "Download story script (.txt)", script_text.encode("utf-8"),
            file_name=f"{safe_title or 'story'}_script.txt", mime="text/plain",
        )
    else:
        st.info("Create a story to download a project backup or script.")
    st.divider()
    st.write("**Load a previous project**")
    project_upload = st.file_uploader("Choose an AI Story Studio project JSON", type=["json"],
                                      key="project_import")
    if st.button("Load project", disabled=(project_upload is None)):
        try:
            loaded_story, loaded_characters, loaded_artwork = load_project_json(
                project_upload.getvalue()
            )
            st.session_state.story = loaded_story
            st.session_state.characters = loaded_characters
            st.session_state.artwork = loaded_artwork
            st.success("Project loaded. Open Storyboard to continue editing.")
            st.rerun()
        except Exception as error:
            st.error(f"Could not load project: {error}")

with history_tab:
    st.subheader("My History")
    st.caption("Your latest 20 story creations are kept in this browser session. Save a History Backup JSON if you want to keep them after closing or refreshing the app.")
    if st.session_state.creation_history:
        history_export = json.dumps(
            {"format_version": 1, "creations": st.session_state.creation_history},
            ensure_ascii=False, indent=2
        ).encode("utf-8")
        st.download_button(
            "Download my history backup", history_export,
            file_name="ai_story_studio_history.json", mime="application/json"
        )
        for number, entry in enumerate(st.session_state.creation_history):
            created = entry.get("created_at", "")[:19].replace("T", " ")
            image_count = len(entry.get("artwork", {}))
            with st.expander(f"{entry.get('title', 'Untitled')} · {created} · {image_count} images", expanded=(number == 0)):
                st.write(f"**Type:** {entry.get('genre', 'Story')}  |  **Style:** {entry.get('style', '')}")
                st.write(entry.get("story", {}).get("logline", ""))
                if st.button("Open this creation", key=f"history_open_{entry.get('id', number)}"):
                    restore_history_entry(entry)
                    st.success("Creation restored. Open Storyboard or Voice & Export.")
                    st.rerun()
                for scene_key, encoded_image in entry.get("artwork", {}).items():
                    try:
                        st.image(base64.b64decode(encoded_image), caption=f"Scene {int(scene_key) + 1}", width=220)
                    except Exception:
                        pass
        if st.button("Clear history", type="secondary"):
            st.session_state.creation_history = []
            st.session_state.current_history_id = None
            st.rerun()
    else:
        st.info("Your creations will appear here automatically after you generate a story.")

    st.divider()
    st.write("**Restore a previous history backup**")
    history_upload = st.file_uploader("Choose history backup JSON", type=["json"], key="history_import")
    if st.button("Restore history backup", disabled=(history_upload is None)):
        try:
            backup = json.loads(history_upload.getvalue().decode("utf-8"))
            entries = backup.get("creations", [])
            if not isinstance(entries, list):
                raise ValueError("History backup does not contain a creations list.")
            valid_entries = [
                item for item in entries[:20]
                if isinstance(item, dict) and isinstance(item.get("story"), dict)
            ]
            st.session_state.creation_history = valid_entries
            st.success(f"Restored {len(valid_entries)} creations.")
            st.rerun()
        except Exception as error:
            st.error(f"Could not restore history: {error}")

st.divider()
st.caption("Version 4.8 · Built-in reusable character library with automatic story-topic casting; no community image queue for character selection, reusable characters, 3D production tools and YouTube-ready exports.")
