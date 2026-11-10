import json, os, subprocess, tempfile
from pathlib import Path
from io import BytesIO
import requests, streamlit as st, imageio_ffmpeg
from gtts import gTTS
from PIL import Image, ImageDraw

st.set_page_config(page_title='AI Story Studio', page_icon='🎬', layout='wide')
st.title('🎬 AI Story Studio')
st.write('Create original stories, plan scenes, add narration and export YouTube-ready MP4 videos.')

def api_key():
    try: return st.secrets.get('GEMINI_API_KEY', '')
    except Exception: return ''

def create_story(key, idea, genre, style, count, cast):
    prompt = 'Create an original ' + genre + ' story. Idea: ' + idea + '. Visual style: ' + style + '. Characters: ' + cast + '. Create exactly ' + str(count) + ' scenes. Return only JSON with title, logline, and scenes. Each scene must have heading, narration, dialogue, and visual_prompt. Keep characters consistent. Do not use copyrighted characters or celebrity likenesses.'
    url = 'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent'
    r = requests.post(url, params={'key':key}, json={'contents':[{'parts':[{'text':prompt}]}], 'generationConfig':{'responseMimeType':'application/json'}}, timeout=90)
    r.raise_for_status()
    raw = r.json()['candidates'][0]['content']['parts'][0]['text'].strip()
    if raw.startswith('```'): raw = raw.split('\n',1)[1].rsplit('```',1)[0]
    data = json.loads(raw)
    if not data.get('scenes'): raise ValueError('No scenes were returned')
    return data

def make_card(scene, artwork, w, h, i, total):
    if artwork:
        image = Image.open(BytesIO(artwork)).convert('RGB')
        scale = max(w/image.width, h/image.height)
        image = image.resize((int(image.width*scale),int(image.height*scale)))
        x,y=(image.width-w)//2,(image.height-h)//2
        image=image.crop((x,y,x+w,y+h))
    else:
        image=Image.new('RGB',(w,h),(29,39,68))
    draw=ImageDraw.Draw(image)
    draw.rectangle((0,int(h*.72),w,h),fill=(0,0,0))
    draw.text((int(w*.05),int(h*.76)),str(i+1)+' / '+str(total)+'  '+scene.get('heading','Scene'),fill='white')
    draw.text((int(w*.05),int(h*.82)),scene.get('narration','')[:400],fill=(225,230,245))
    return image

def export_video(scenes, artwork, ratio, language):
    w,h=(720,1280) if ratio.startswith('9:16') else (1280,720)
    lang={'English':'en','Tamil':'ta','Hindi':'hi'}[language]
    ffmpeg=imageio_ffmpeg.get_ffmpeg_exe()
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp); clips=[]
        for i,scene in enumerate(scenes):
            speech=' '.join([scene.get('narration',''),scene.get('dialogue','')]).strip() or scene.get('heading','Scene')
            audio=root/('a'+str(i)+'.mp3'); still=root/('s'+str(i)+'.jpg'); clip=root/('c'+str(i)+'.mp4')
            gTTS(speech,lang=lang).save(str(audio))
            make_card(scene,artwork.get(i),w,h,i,len(scenes)).save(still)
            cmd=[ffmpeg,'-y','-loop','1','-framerate','24','-i',str(still),'-i',str(audio),'-c:v','libx264','-tune','stillimage','-c:a','aac','-b:a','128k','-pix_fmt','yuv420p','-shortest',str(clip)]
            p=subprocess.run(cmd,capture_output=True,text=True)
            if p.returncode: raise RuntimeError(p.stderr[-800:])
            clips.append(clip)
        listing=root/'files.txt'
        listing.write_text(''.join("file '"+str(p)+"'\n" for p in clips))
        output=root/'story.mp4'
        p=subprocess.run([ffmpeg,'-y','-f','concat','-safe','0','-i',str(listing),'-c','copy',str(output)],capture_output=True,text=True)
        if p.returncode: raise RuntimeError(p.stderr[-800:])
        return output.read_bytes()

with st.sidebar:
    st.header('Project settings')
    key=st.text_input('Gemini API key',value=api_key(),type='password')
    st.caption('Create a private key in Google AI Studio. Never commit it to GitHub.')
    genre=st.selectbox('Genre',['Adventure','Fantasy','Comedy','Mystery','Educational','Inspirational','Sci-fi','Bedtime'])
    style=st.selectbox('Visual style',['3D animation','Anime','Cartoon','Storybook illustration','Realistic cinematic'])
    count=st.slider('Scenes',3,8,5)
    language=st.selectbox('Narration language',['English','Tamil','Hindi'])
    ratio=st.selectbox('Video format',['9:16 Vertical Shorts','16:9 YouTube widescreen'])

if 'story' not in st.session_state: st.session_state.story=None
if 'cast' not in st.session_state: st.session_state.cast=[]
if 'art' not in st.session_state: st.session_state.art={}
t1,t2,t3,t4=st.tabs(['Story Writer','Characters','Storyboard','Voice and Export'])
with t1:
    idea=st.text_area('Story idea',placeholder='A young inventor finds a lost robot and helps it return home.')
    if st.button('Generate story',type='primary'):
        if not idea.strip(): st.warning('Enter a story idea first.')
        elif not key.strip(): st.warning('Add your Gemini API key in the sidebar.')
        else:
            try:
                cast='; '.join([c['name']+': '+c['description'] for c in st.session_state.cast])
                with st.spinner('Writing your story...'): st.session_state.story=create_story(key.strip(),idea,genre,style,count,cast)
                st.session_state.art={}; st.success('Story created. Review it in Storyboard.')
            except Exception as e: st.error(str(e))
    if st.session_state.story:
        st.subheader(st.session_state.story.get('title','Your story')); st.write(st.session_state.story.get('logline',''))
with t2:
    st.subheader('Character library')
    with st.form('character',clear_on_submit=True):
        name=st.text_input('Character name'); desc=st.text_area('Appearance and personality'); add=st.form_submit_button('Add character')
    if add and name.strip() and desc.strip(): st.session_state.cast.append({'name':name.strip(),'description':desc.strip()}); st.success('Character added')
    for c in st.session_state.cast: st.write('**'+c['name']+'** — '+c['description'])
with t3:
    if not st.session_state.story: st.info('Generate a story first.')
    else:
        for i,s in enumerate(st.session_state.story['scenes']):
            with st.expander('Scene '+str(i+1)+' — '+s.get('heading','Scene'),expanded=(i==0)):
                s['heading']=st.text_input('Heading',s.get('heading',''),key='h'+str(i))
                s['narration']=st.text_area('Narration',s.get('narration',''),key='n'+str(i))
                s['dialogue']=st.text_area('Dialogue',s.get('dialogue',''),key='d'+str(i))
                s['visual_prompt']=st.text_area('Artwork prompt',s.get('visual_prompt',''),key='p'+str(i))
                up=st.file_uploader('Upload scene image',type=['png','jpg','jpeg'],key='u'+str(i))
                if up: st.session_state.art[i]=up.getvalue()
                if i in st.session_state.art: st.image(st.session_state.art[i],use_container_width=True)
        st.caption('Without uploaded artwork, export uses clean storyboard cards. This MVP does not generate moving AI animation.')
with t4:
    if not st.session_state.story: st.info('Generate a story first.')
    else:
        st.write('Format: '+ratio+' | Voice: '+language)
        if st.button('Build narrated MP4',type='primary'):
            try:
                with st.spinner('Generating narration and rendering video...'): video=export_video(st.session_state.story['scenes'],st.session_state.art,ratio,language)
                st.video(video); st.download_button('Download MP4',video,file_name='ai-story-studio.mp4',mime='video/mp4')
            except Exception as e: st.error('Export failed: '+str(e))

st.divider()
st.caption('Early MVP: use original stories, characters and licensed assets. Review all content before publishing or monetising.')