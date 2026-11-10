# AI Story Studio — Version 4 (3D production milestone)

AI Story Studio helps create original multi-genre stories and prepare reusable character assets for 3D video production.

## Creative formats
- Tamil and English nursery rhymes / children's songs
- Comedy, moral and bedtime stories
- Adventure, educational, fantasy and animal stories
- Family-friendly mystery, sci-fi and superhero stories

## Streamlit studio features
- Gemini story and shot-direction generation (API key and provider quotas apply)
- Free anonymous realistic per-scene image generation through AI Horde volunteer workers (no image API key or payment required)
- Generated or uploaded scene images are saved in project backups and used in narrated MP4 exports
- Character bible with type, appearance and personality
- Per-character GLB/FBX model upload
- Per-scene character casting and editable narration/dialogue/shot direction
- Project JSON backup including attached 3D character files and storyboard images
- Existing narrated slideshow MP4 export
- Optional manual YouTube upload as Unlisted

## Local Blender 3D production milestone
The 3D Production tab can package the story, character GLB files and Blender renderer into a ZIP. Rendering happens on a local computer because Streamlit Community Cloud is not a Blender render farm.

The current renderer:
- Imports original user-owned GLB/FBX models
- Reuses the same model across scenes
- Creates a simple lit 3D stage and camera
- Adds basic root/camera movement
- Generates English, Tamil or Hindi narration
- Renders 1080p MP4 in 16:9 or 9:16 using Blender and FFmpeg

**Current limitations:** this is an initial 3D pipeline, not a finished studio animation engine. It does not generate 3D characters from text, automatically create detailed body choreography, facial acting, lip-sync, scene-specific props, or custom music. The GLB/FBX model should be rigged and preferably include animation actions. Quality depends heavily on the model and its included animation. Review every rendered scene before publishing.

## Local rendering setup
1. Create a story in the web app.
2. Add each original character in Characters.
3. Upload a rigged .glb or .fbx model for each character.
4. Assign characters to scenes in Storyboard.
5. Open 3D Production and download the production ZIP.
6. Extract the ZIP on a Windows, macOS or Linux computer.
7. Install Blender 4.2+ (Blender 5.x recommended) and FFmpeg.
8. Install Python 3.10+ and run: python -m pip install gTTS
9. Open a terminal in the extracted folder and run:
   python render_project.py --language Tamil --ratio 16:9
10. For Shorts use:
    python render_project.py --language Tamil --ratio 9:16

If Blender or FFmpeg is not on PATH, use --blender and --ffmpeg with their full executable paths. Rendering time depends on the computer, number of scenes and model complexity.

## Run the Streamlit app locally
1. Install Python 3.10 or newer.
2. Clone this repository.
3. Install dependencies: pip install -r requirements.txt
4. Run: streamlit run app.py
5. Add GEMINI_API_KEY to Streamlit Secrets or environment variables. No image-generation API key or billing setup is required.

Never put API keys in source code or commit them to GitHub.

## Deploy on Streamlit Community Cloud
Select repository SK251201/ai-story-studio, branch main, main file app.py. Add this to app Secrets:

GEMINI_API_KEY = "your-own-api-key"

Then deploy or reboot the app. Never share your API key in chat.

## Important costs and licensing
- Gemini API has model-specific quotas and may require billing after free limits. This app cannot bypass those limits.
- AI Horde image generation is free to use anonymously through volunteer computers. Anonymous requests have lower priority and limits, so queue times and availability vary. Anonymous prompts and generated images may be shared with the community service; do not submit private photos or personal information.
- Blender is free and open source; local rendering uses your computer's resources. Adobe Mixamo provides free humanoid characters and animations; check its licence and download a rigged FBX for use in the app.
- gTTS requires internet access.
- Use only original stories, models, voices and music that you have rights to use commercially.
- YouTube monetisation is not guaranteed; repetitive or mass-produced content may not qualify.

## Optional YouTube upload
The app supports manual uploads only and uploads as Unlisted. It does not publish automatically. OAuth setup is required in Google Cloud Console; keep client secrets in Streamlit Secrets only.


## Version 4.8 — Built-in character library

The app now seeds a reusable original character cast locally (children, family, schoolteacher, comedy friends, animals, adventure and fantasy characters). When a story idea is submitted, a local keyword/category matcher selects up to four relevant cast members and passes only those profiles to the story writer. The story prompt requires exact names and consistent appearance across scenes. Character selection and character profiles do not call the free community image service. The community image service is used only when the user explicitly generates scene artwork in Storyboard. The built-in library is added to existing browser sessions without deleting existing user-created characters.
