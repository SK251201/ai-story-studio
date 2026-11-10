# AI Story Studio

A free-first Streamlit MVP for creating original stories, planning scenes, adding text-to-speech narration and exporting MP4 slideshow videos for YouTube Shorts (9:16) or widescreen videos (16:9).

## Features
- Gemini-powered original story and scene-prompt generation
- Character descriptions to help maintain visual consistency
- Editable scene headings, narration, dialogue and visual prompts
- Upload your own artwork for each scene
- English, Tamil and Hindi narration using gTTS
- MP4 export with FFmpeg for vertical and widescreen formats

## Important MVP limitation
This first version creates a narrated slideshow from uploaded still images or storyboard cards. It does not create moving AI animation or generate images itself. The style selector guides the written image prompts; it does not render 3D, anime, cartoon or realistic images automatically.

## Run locally
1. Install Python 3.10 or newer.
2. Clone this repository.
3. Install dependencies: `pip install -r requirements.txt`
4. Run: `streamlit run app.py`
5. Add your Gemini API key in the app sidebar.

Get a Gemini API key from Google AI Studio: https://aistudio.google.com/app/apikey

## Deploy free on Streamlit Community Cloud
1. Sign in at https://share.streamlit.io/ with the GitHub account that can access this repository.
2. Choose **Create app** and select `SK251201/ai-story-studio`.
3. Select branch `main` and main file path `app.py`.
4. In app settings, add this secret:

```toml
GEMINI_API_KEY = "paste-your-own-key-here"
```

5. Deploy. Never put your API key in source code or commit it to GitHub.

## Notes
- gTTS needs an internet connection while generating narration.
- Video rendering uses FFmpeg through imageio-ffmpeg and may take a few minutes.
- Streamlit Community Cloud has resource and usage limits. Large videos may exceed them.
- Generated stories should be reviewed. Use original or properly licensed images, music and other assets. YouTube monetisation is not guaranteed; repetitive or mass-produced content may not qualify.
