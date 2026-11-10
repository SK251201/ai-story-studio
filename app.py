import base64
import json
import os
import subprocess
import tempfile
import time
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


def get_pollinations_key():
    try:
        return st.secrets.get("POLLINATIONS_API_KEY", "") or os.getenv("POLLINATIONS_API_KEY", "")
    except Exception:
        return os.getenv("POLLINATIONS_API_KEY", "")

def generate_scene_image(api_key, scene, characters, visual_style, ratio):
    """Generate one cinematic storyboard image. The provider may charge Pollen per image."""
    from urllib.parse import quote

    cast = scene.get("characters", [])
    character_notes = []
    for character in characters:
        if character.get("name") in cast:
            character_notes.append(
                f"{character['name']}: {character.get('description', '')}"
            )
    cast_text = "; ".join(character_notes) or "Use the character details stated in the shot direction."
    prompt = (
        "Create one polished, high-detail cinematic 3D animated film frame for an original YouTube story. "
        "Realistic appealing character anatomy, expressive natural faces, detailed clothing and materials, "
        "beautiful professional 3D environment, physically based textures, soft cinematic global illumination, "
        "professional film lighting, rich but natural colors, clear composition, crisp focus, premium family-film quality. "
        "Do not make a flat vector drawing, stick figure, simple cartoon, collage, storyboard sheet, text, logo or watermark. "
        f"Visual style: {visual_style}. Character continuity bible: {cast_text}. "
        f"Scene: {scene.get('heading', '')}. Shot direction: {scene.get('visual_prompt', '')}. "
        "Show one coherent moment with all named characters looking consistent with their descriptions. "
        "Keep faces and full bodies visible where framing allows. No captions or written words."
    )
    url = "https://gen.pollinations.ai/image/" + quote(prompt, safe="")
    response = requests.get(
        url,
        params={
            "model": "black-forest-labs/flux.1-schnell",
            "width": 1024,
            "height": 1024,
            "safe": "privacy",
        },
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=(20, 180),
    )
    if response.status_code == 402:
        raise RuntimeError("Your Pollinations Pollen balance is insufficient. No further image was generated.")
    if response.status_code == 429:
        raise RuntimeError("Image service rate limit reached. Wait before trying again.")
    if response.status_code in (401, 403):
        raise RuntimeError("Pollinations rejected the API key. Check that it is a valid secret key with image permission.")
    response.raise_for_status()
    content_type = response.headers.get("Content-Type", "")
    if not content_type.startswith("image/"):
        raise RuntimeError("The image provider returned a non-image response.")
    image_bytes = response.content
    try:
        with Image.open(BytesIO(image_bytes)) as image:
            image.verify()
    except Exception as error:
        raise RuntimeError("The image provider returned an invalid image file.") from error
    return image_bytes


def generate_story(key, idea, genre, style, count, characters):
    prompt = f"""
Create an original {genre} story based on this idea: {idea}
Visual direction: {style}
Character bible: {characters or "Create suitable original characters."}
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

if "story" not in st.session_state:
    st.session_state.story = None
if "characters" not in st.session_state:
    st.session_state.characters = []
if "artwork" not in st.session_state:
    st.session_state.artwork = {}

with st.sidebar:
    st.header("Project settings")
    api_key = st.text_input("Gemini API key", value=get_secret_key(), type="password")
    st.caption("Use Streamlit Secrets for deployment. Never commit your key to GitHub.")
    pollinations_key = st.text_input(
        "Optional image-generation key", value=get_pollinations_key(), type="password",
        help="Pollinations secret key. Image generation uses your Pollinations Pollen balance."
    )
    st.caption("Image generation is optional. It is not unlimited-free: use only free/earned Pollen or set a strict zero/low budget on your provider key. No images are generated automatically.")
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

story_tab, character_tab, storyboard_tab, production_tab, export_tab, project_tab = st.tabs(
    ["Story Writer", "Characters", "Storyboard", "3D Production", "Voice & Export", "Save / Load"]
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
            character_bible = "; ".join(
                f"{character['name']}: {character['description']}"
                for character in st.session_state.characters
            )
            try:
                with st.spinner("Writing your original story..."):
                    st.session_state.story = generate_story(
                        api_key.strip(), idea, genre, visual_style, scene_count, character_bible
                    )
                st.session_state.artwork = {}
                st.success("Story generated. Review and edit it in Storyboard.")
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
    st.subheader("Character library")
    with st.form("add_character", clear_on_submit=True):
        character_name = st.text_input("Character name")
        character_description = st.text_area("Appearance, personality and defining details",
                placeholder="Age, face, hairstyle, skin tone, outfit, body shape, personality and signature details")
        character_type = st.selectbox("Character type", ["Human", "Animal", "Fantasy", "Other"])
        add_character = st.form_submit_button("Add character")
    if add_character:
        if character_name.strip() and character_description.strip():
            st.session_state.characters.append({
                "name": character_name.strip(),
                "description": character_description.strip(),
                "type": character_type,
                "asset_file": "",
                "model_bytes": None,
            })
            st.success("Character added.")
        else:
            st.warning("Enter both a name and description.")
    for index, character in enumerate(st.session_state.characters):
        st.markdown(f"**{character['name']}** ({character.get('type', 'Character')}) — {character['description']}")
        model_upload = st.file_uploader("Upload rigged 3D character model (.glb or .fbx)", type=["glb", "fbx"], key=f"character_model_{index}")
        if model_upload:
            safe_name = "".join(ch.lower() if ch.isalnum() else "_" for ch in character["name"]).strip("_")
            character["asset_file"] = (safe_name or f"character_{index}") + Path(model_upload.name).suffix.lower()
            character["model_bytes"] = model_upload.getvalue()
            st.success(f"3D model attached: {character['asset_file']}")
        elif character.get("model_bytes"):
            st.caption(f"3D model attached: {character.get('asset_file')}")
        if st.button("Remove", key=f"remove_character_{index}"):
            st.session_state.characters.pop(index)
            st.rerun()

with storyboard_tab:
    if not st.session_state.story:
        st.info("Generate or load a project to edit its storyboard.")
    else:
        st.info("Generate realistic 3D storyboard images scene by scene. Generated images are saved into your project and included in narrated MP4 exports.")
        if not pollinations_key.strip():
            st.warning("AI image generation needs a Pollinations secret key. On mobile, tap » at the top-left to open the sidebar and enter it under Optional image-generation key.")
            st.markdown("Create/manage a key at https://enter.pollinations.ai/. Generation requires an available free/earned Pollen balance; do not add payment details if you do not want to spend.")
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
                    if st.button("Generate realistic image", key=f"generate_image_{index}"):
                        if not pollinations_key.strip():
                            st.warning(
                                "Image generation is not connected yet. Open the sidebar (»), "
                                "add a Pollinations secret key in 'Optional image-generation key', "
                                "then click this button again. The key must have image permission "
                                "and an available free/earned Pollen balance."
                            )
                        else:
                            try:
                                with st.spinner(f"Generating image for scene {index + 1}..."):
                                    st.session_state.artwork[index] = generate_scene_image(
                                        pollinations_key.strip(), scene, st.session_state.characters,
                                        visual_style, video_ratio
                                    )
                                st.success("Scene image generated and saved.")
                            except Exception as error:
                                st.error(f"Image generation failed: {error}")
                with col2:
                    if st.button("Remove generated image", key=f"remove_image_{index}",
                                 disabled=index not in st.session_state.artwork):
                        st.session_state.artwork.pop(index, None)
                        st.rerun()
                uploaded = st.file_uploader("Or upload your own image (free)", type=["png", "jpg", "jpeg"], key=f"art_{index}")
                if uploaded:
                    st.session_state.artwork[index] = uploaded.getvalue()
                if index in st.session_state.artwork:
                    st.image(st.session_state.artwork[index], use_container_width=True)
        st.caption("Images are stored in the project JSON and used as scene backgrounds in narrated MP4 exports. Character descriptions guide consistency, but an image model may still vary faces/outfits between scenes.")

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

st.divider()
st.caption("Version 4 · Multi-genre story development, reusable 3D character assets and local Blender production pipeline. Use original stories and properly licensed assets.")
