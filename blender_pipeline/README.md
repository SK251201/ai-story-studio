# Local 3D production renderer

This is a local companion to the Streamlit app. Blender renders require a desktop or dedicated render machine; Streamlit Community Cloud is not suitable for running Blender.

## Current capabilities
- Imports original user-owned GLB/glTF character models into Blender.
- Reuses the same model across shots to maintain visual identity.
- Creates a 3-point-lit studio stage and cinematic camera.
- Adds simple root and camera movement between keyframes.
- Creates English, Tamil or Hindi narration with gTTS.
- Renders 1080p MP4 in 16:9 or 9:16 with Blender and FFmpeg.

This is the first 3D pipeline milestone, not a finished animation system. GLB models should include a rig and preferably embedded animation actions. This build does not yet generate 3D models from text, retarget animation packs, create custom facial expressions, or lip-sync dialogue.

## Requirements
- Windows 10/11, macOS or Linux
- Blender 4.2+ (Blender 5.x recommended)
- FFmpeg available on PATH
- Python 3.10+ and gTTS installed with: python -m pip install gTTS

## Steps
1. Create a story in AI Story Studio.
2. Add original characters and upload a rigged .glb model for each in the Characters tab.
3. Open Production Export and download the production ZIP.
4. Extract the ZIP on your computer.
5. Open a terminal in the extracted folder.
6. Run: python render_project.py --language Tamil --ratio 16:9
7. For Shorts, use: python render_project.py --language Tamil --ratio 9:16

If Blender or FFmpeg is not on PATH, pass --blender and --ffmpeg with their full executable paths. Use only models and audio you have rights to use commercially.
