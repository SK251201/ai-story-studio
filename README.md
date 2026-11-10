# AI Story Studio — Version 3

A Streamlit application for drafting original stories, building scene storyboards, adding text-to-speech narration and exporting MP4 slideshow videos for YouTube Shorts (9:16) or widescreen (16:9).

## Version 2 features
- Gemini-powered story and scene-prompt generation
- Character library for consistent story planning
- Editable scene headings, narration, dialogue and visual prompts
- Generate scene illustrations with Gemini image generation (requires supported model access and quota)
- Use the first generated scene image as a visual reference for later scenes
- Upload individual images for scenes
- English, Tamil and Hindi narration through gTTS
- FFmpeg MP4 export in vertical or widescreen format
- Download a complete JSON project backup, including uploaded artwork
- Reload a saved project later
- Download the story script as a text file
- Optional manual YouTube upload using Google OAuth; uploads are always Unlisted

## Important limitation
The app creates narrated slideshow videos from still images; it does not generate full moving animation. AI image generation requires Gemini image-model access and may consume quota or incur charges. Character consistency is guided by a reference image, not guaranteed.

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

## Optional YouTube upload setup
The app supports **manual uploads only** and sets every uploaded video's visibility to **Unlisted**. It never uploads automatically when an MP4 is rendered.

1. In Google Cloud Console, create or select a project and enable **YouTube Data API v3**.
2. Configure the OAuth consent screen. Add your Google account as a test user while the app is in Testing mode.
3. Create an OAuth Client ID with application type **Web application**.
4. Add your deployed Streamlit app URL (for example, `https://YOUR-APP.streamlit.app/`) as an authorized redirect URI. It must match exactly.
5. In Streamlit Community Cloud → App → Settings → Secrets, add:

```toml
[youtube]
client_id = "YOUR_GOOGLE_OAUTH_CLIENT_ID"
client_secret = "YOUR_GOOGLE_OAUTH_CLIENT_SECRET"

youtube_redirect_uri = "https://YOUR-APP.streamlit.app/"
```

6. Save secrets and reboot the app. Open **Voice & Export**, generate an MP4, click **Connect YouTube channel**, approve the Google permission request, then click **Upload this video as Unlisted** only when you are ready.

The app requests the `youtube.upload` OAuth scope. Keep OAuth client secrets in Streamlit Secrets only; never commit them to GitHub or share them in chat. Google may require OAuth app verification for broader public use. While the OAuth consent screen is in Testing mode, refresh-token behavior and test-user access are subject to Google's testing restrictions. Review the uploaded video in YouTube Studio before changing its visibility.
