# AI Story Studio — Version 2

A Streamlit application for drafting original stories, building scene storyboards, adding text-to-speech narration and exporting MP4 slideshow videos for YouTube Shorts (9:16) or widescreen (16:9).

## Version 2 features
- Gemini-powered story and scene-prompt generation
- Character library for consistent story planning
- Editable scene headings, narration, dialogue and visual prompts
- Upload individual images for scenes
- English, Tamil and Hindi narration through gTTS
- FFmpeg MP4 export in vertical or widescreen format
- Download a complete JSON project backup, including uploaded artwork
- Reload a saved project later
- Download the story script as a text file

## Important limitation
This version creates narrated slideshow videos from uploaded still images or storyboard title cards. It does not generate AI images or moving animation. The visual-style selector guides the text prompts; it does not itself render 3D, anime, cartoon or realistic artwork.

## Run locally
1. Install Python 3.10 or newer.
2. Clone this repository.
3. Install dependencies: `pip install -r requirements.txt`.
4. Run: `streamlit run app.py`.
5. Enter a Gemini API key in the sidebar, or set `GEMINI_API_KEY` as an environment variable.

Create a key at https://aistudio.google.com/app/apikey.

## Deploy on Streamlit Community Cloud
1. Sign in at https://share.streamlit.io/.
2. Select **Create app**.
3. Choose repository `SK251201/ai-story-studio`, branch `main`, and main file `app.py`.
4. Add this under app settings → Secrets:

```toml
GEMINI_API_KEY = "your-own-api-key"
```

5. Deploy or reboot the app after updating the repository.

Never put your API key in source code or commit it to GitHub.

## Testing
A GitHub Actions workflow compiles the Python application on every push and pull request. This catches syntax errors; it does not replace a live Streamlit browser test or a real Gemini/FFmpeg export test.

## Notes
- Gemini API access may be subject to quotas, model availability and billing terms.
- gTTS requires internet access during narration generation.
- Video rendering can take several minutes and may hit Streamlit Cloud resource limits for large projects.
- Use original stories and properly licensed artwork/audio. YouTube monetisation is not guaranteed; repetitive or mass-produced content may not qualify.
