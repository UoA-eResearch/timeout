#!/usr/bin/env python3

import base64
import pandas as pd
import os
pd.set_option("display.max_columns", None)
pd.set_option("display.max_colwidth", 100)
from pprint import pprint
import json
from glob import glob
from tqdm import tqdm
from openai import OpenAI
import argparse
from tqdm.contrib.concurrent import thread_map
import ffmpeg
import tempfile

# Parse command line arguments
parser = argparse.ArgumentParser(description='Process videos with LLM')
parser.add_argument('--dataset', type=str, choices=['timeout', 'supplements', 'distress'],
                    required=True, help='Dataset to process (timeout, supplements or distress)')
parser.add_argument('--max_workers', type=int, default=16, help='Maximum number of worker threads')
parser.add_argument('--think', action='store_true', default=False, help='Enable thinking steps')
args = parser.parse_args()

files = []
folder = f"{args.dataset}_videos"
result_folder = f"{args.dataset}_results"
if args.think:
    result_folder += "_think"
os.makedirs(result_folder, exist_ok=True)
for f in glob(f"{folder}/*.json"):
    output_filename = os.path.join(result_folder, os.path.basename(f.replace(
        ".info.json", ".result.json"
    )))
    if not os.path.isfile(output_filename):
        files.append(f)
print(len(files))

client = OpenAI(base_url="https://ai.cer-sandbox.cloud.edu.au/v1", api_key="not needed")

def has_audio(video_path):
    try:
        # Probe the video file specifically selecting audio streams
        probe = ffmpeg.probe(video_path, select_streams='a')
        # If the 'streams' list is not empty, an audio track exists
        return len(probe['streams']) > 0
    except ffmpeg.Error as e:
        print(f"Error checking file: {e}")
        return False

# Video codecs the vLLM server's OpenCV decoder can read. Anything else (notably AV1, common in YouTube downloads)
# is transcoded to H.264 first, as are files too big for the server's media size limit (25MB)
DECODABLE_CODECS = {"h264", "hevc", "vp9", "vp8", "mpeg4"}
MAX_VIDEO_MB = 20

def prepare_video(video_path, ext):
    """Return the video's bytes and extension to send, transcoding to H.264 mp4 if the server can't decode it or it's too large"""
    streams = ffmpeg.probe(video_path, select_streams='v')['streams']
    codec = streams[0]['codec_name'] if streams else None
    if codec in DECODABLE_CODECS and os.path.getsize(video_path) <= MAX_VIDEO_MB * 1e6:
        with open(video_path, "rb") as video_file:
            return video_file.read(), ext
    with tempfile.NamedTemporaryFile(suffix=".mp4") as tmp:
        (
            ffmpeg.input(video_path)
            .output(tmp.name, vcodec="libx264", preset="veryfast", crf=28, vf="scale=-2:'min(1280,ih)'", acodec="aac")
            .overwrite_output()
            .run(quiet=True)
        )
        return tmp.read(), "mp4"


def get_prompt_supplements(data):
    return f"""This is a video downloaded from {data['extractor']}. Here's the description of the video: {data.get('description', 'No description available')}.

        The creator of the video is {data.get('channel', 'an unknown channel')} ({data.get('uploader', 'an unknown uploader')})
        It has {data.get('like_count', 'an unknown number of')} likes, {data.get('view_count', 'an unknown number of')} views, and {data.get('comment_count', 'an unknown number of')} comments.
        Taking into account this description, and the video, extract the following information, in JSON format:
        description: What is happening in the video? Provide a detailed description of the actions, context, and any notable elements present in the video.
        transcript: If there is any spoken content in the video, transcribe it into English. If there is no spoken content, indicate "No spoken content".
        tone: What is the overall tone or mood of the video? Is it humorous, serious, educational, emotional, etc.?
        supplements: Does the video mention any supplements, vitamins, or medications? If so, list them. If not, indicate "No supplements mentioned".
        active_ingredients: If any supplements are mentioned, list the active ingredients in those supplements. If no supplements are mentioned, indicate "No active ingredients mentioned".
        supplement_categories: Classify each supplement listed in the supplements field into exactly one of the categories below. Return a comma separated string with one category per supplement, in the same order as the supplements field. If no supplements are mentioned, indicate "No supplements mentioned". The categories are:
            Medicine or hormone therapy - a prescription or pharmaceutical product, including hormone replacement therapy, oestrogen, progesterone, testosterone, antidepressants and other medicines.
            Menopause formulation - a branded multi-ingredient product explicitly marketed for menopause, perimenopause or menopausal symptoms.
            Functional product - a branded multi-ingredient product explicitly marketed for a body system or symptom rather than for a named ingredient, for example gut health, sleep, skin, hair, bone, mood or energy products.
            Single ingredient - a product identified by one substance rather than by a brand or a symptom, for example magnesium, vitamin D, collagen, black cohosh, creatine.
            General or unclear - a supplement that is mentioned too vaguely to classify, for example "my supplements", "a multivitamin" or an unnamed product.
        ingredient_types: For each supplement you classified as "Single ingredient", give its substance type. Return a comma separated string with one entry per supplement, in the same order as the supplements field, using "Not applicable" for supplements in any other category. Each substance type must be exactly one of: vitamin, mineral, herbal or botanical, amino acid or derivative, protein or peptide, fatty acid, probiotic, hormone precursor, other. If no supplements are mentioned, indicate "No supplements mentioned".
        primary_supplement_category: Of the supplements mentioned, which single category does the video mainly focus on? Exactly one of: Medicine or hormone therapy, Menopause formulation, Functional product, Single ingredient, General or unclear, No supplements mentioned.
        health_claims: Does the video make any health claims about a supplement? List each claim in the form "Supplement - Claim - Target", for example "Omega 3 - improves HDL - cholesterol". Separate multiple claims with semicolons. If no claims are made, indicate "No health claims".
        claim_types: For each claim in the health_claims field, is it a benefit claim, a risk claim, or informational? Return a comma separated string with one entry per claim, in the same order as the health_claims field. Each entry must be exactly one of: benefit, risk, informational. If no claims are made, indicate "No health claims".
        claim_strength: For each claim in the health_claims field, how strong is the claim language? Return a comma separated string with one entry per claim, in the same order as the health_claims field. Each entry must be exactly one of: cures or eliminates, reduces, supports, may help. If no claims are made, indicate "No health claims".
        claim_target_categories: For each claim in the health_claims field, what does the claim target? Return a comma separated string with one entry per claim, in the same order as the health_claims field. Each entry must be exactly one of: vasomotor symptom relief, physical symptom relief, psychological symptom relief, health and metabolic, antioxidant, hormone regulation, general health and wellness. If no claims are made, indicate "No health claims".
        evidence: Does the video cite any evidence to support its claims about supplements? Exactly one of: a study or research, a guideline, a clinician or expert, a mechanism explanation, a testimonial or personal anecdote, traditional use, no evidence cited, no claims made.
        evidence_quote: Quote the specific phrase or sentence from the video that cites this evidence. If no evidence is cited, indicate "No evidence cited".
        symptoms: Does the video mention any specific symptoms, conditions, or health issues? If so, list them. If not, indicate "No symptoms mentioned".
        symptom_categories: Classify each symptom listed in the symptoms field into exactly one category. Return a comma separated string with one category per symptom, in the same order as the symptoms field. Each category must be exactly one of: vasomotor (hot flushes, night sweats), physical (genitourinary symptoms, musculoskeletal discomfort, skin and hair changes, headaches, insomnia), psychological (mental health, brain fog, mood, anxiety, irritability), health and metabolic (cardiovascular health, metabolism, glucose control), non-specific or prevention. Use only the category name before the parentheses in your answer. If no symptoms are mentioned, indicate "No menopause symptoms mentioned".
        symptom_framing: What type of language does the video use when talking about menopause symptoms? A comma separated string, one or more of the following: burden or suffering, loss or decline, deficiency or imbalance, general ageing, normalised. If no symptoms are discussed, indicate "No symptoms discussed".
        menopause: Is the video specifically targeting the supplement towards menopause-related symptoms or conditions? Answer True or False.
        language: What language is this video in?
        marketing: Is this video promoting or advertising any product, service, brand, or organization? If so, what is it? Otherwise, indicate "No marketing content".
        job: For the main speaker, what is their job or profession? If it is not mentioned in the video, indicate "No job information". A comma separated string, one or more of the following: therapist, psychologist, pediatrician, doctor, nurse, teacher, professor, social worker, counselor, coach, influencer, content creator?
        sentiment: Does this video recommend a particular supplement, discourage it, or is it neutral? One of negative, neutral or positive
        criticism: If the video is critical of a particular supplement, what are the main criticisms mentioned? 
        alternative_strategies: Does the video mention any alternative strategies to supplements? If so, what are they? A comma separated string. If no alternatives are mentioned, indicate "No alternative strategies mentioned".
        usefulness: Rate the overall usefulness of the video on a scale from 1 to 10, where 1 is not useful at all and 10 is extremely useful.
        usefulness_reason: In one or two sentences, explain what specifically in the video led you to give that usefulness rating.
        misleading: Rate the extent to which the video contains misleading or inaccurate information on a scale from 1 to 10, where 1 is not misleading at all and 10 is extremely misleading.
        misleading_reason: In one or two sentences, explain what specifically in the video led you to give that misleading rating, naming any claims you considered inaccurate.
        quality: Rate the overall quality of the video on a scale from 1 to 10, where 1 is very poor quality and 10 is excellent quality.
        quality_reason: In one or two sentences, explain what specifically in the video led you to give that quality rating.
        personal_experience: Does the speaker mention any personal experience with supplements? If so, briefly summarize it.
        content_type: What is this video predominantly? Exactly one of: predominantly informative, predominantly marketing, predominantly personal commentary. Use "predominantly personal commentary" for videos that are neither informative nor marketing, for example personal stories or anecdotes, opinions, lifestyle content or general chat, without substantive information and without promoting a specific product.
        content_type_evidence: Quote the specific words, phrases or elements of the video that led you to that content_type classification.
        problem_solution: Does the post follow a problem-solution structure, where a problem is first presented and a product or strategy is then offered as the solution? Answer True or False.
        primary_focus: Is the video predominantly about menopause symptoms and the experience of menopause, or predominantly about supplements and remedies? Exactly one of: symptoms and experience, supplements and remedies, both equally, neither.
        health_framework: What health or medical framework does the knowledge in the video draw on? Exactly one of: western biomedical, traditional chinese medicine, ayurvedic, naturopathic or holistic, other traditional or indigenous, mixed, unclear.
        cultural_background: What cultural background does the main speaker appear to come from, based only on what is visible or audible in the video and its metadata (language, setting, self-description)? If there is not enough information, indicate "Unclear".
        menopause_framing: How is menopause itself framed? Exactly one of: symptom burden or suffering, medical problem to be treated, neutral or matter of fact, natural life stage, positive or empowering, unclear.
        emotional_tone: What is the dominant emotional tone of the main speaker? A comma separated string, one or more of the following: hopeful, relieved, excited, enthusiastic, reassuring, empathetic, neutral, concerned, anxious, disappointed, frustrated, angry, dismissive, humorous.
        emotional_intensity: Rate how emotionally intense or enthusiastic the main speaker is when talking about menopause or supplements, on a scale from 1 to 10, where 1 is flat and detached and 10 is highly emotional or highly enthusiastic.
        supplement_sentiment: Considering only the parts of the video that talk about supplements, is the speaker positive, negative or neutral about them? One of negative, neutral, positive, or "No supplements discussed".
        credentials: What credentials does the main speaker claim or display? Exactly one of: qualified health professional, researcher or academic, company or brand account, influencer or content creator with no stated qualifications, person speaking from personal experience only, unclear. Base this only on the video and its metadata; do not guess beyond what is stated or shown.
        credentials_evidence: What in the video or its metadata supports the credentials answer (e.g. a title in the channel name, a stated qualification, a clinic setting)? If there is nothing, indicate "No evidence".

        Do not include comments in your JSON response. Only respond with the JSON object. Make sure the JSON is valid
    """


def get_prompt_timeout(data):
    return f"""This is a video downloaded from {data['extractor']}. Here's the description of the video: {data['description']}.

        The creator of the video is {data.get('channel', 'an unknown channel')} ({data.get('uploader', 'an unknown uploader')})
        It has {data.get('like_count', 'an unknown number of')} likes, {data.get('view_count', 'an unknown number of')} views, and {data.get('comment_count', 'an unknown number of')} comments.
        Taking into account this description, and the video, extract the following information, in JSON format:
        description: What is happening in the video? Provide a detailed description of the actions, context, and any notable elements present in the video.
        transcript: If there is any spoken content in the video, transcribe it accurately. If there is no spoken content, indicate "No spoken content". Do not repeat any sentences in the transcript. If the spoken language isn't English, translate it to English.
        tone: What is the overall tone or mood of the video? Is it humorous, serious, educational, emotional, etc.?
        timeout: Is this video talking about timeout for children (as a parenting punishment strategy)? a boolean true or false
        parenting_approach: What is the overall parenting approach shown in the video? (e.g., authoritative, permissive, gentle parenting, etc.)
        child_age: What age range of children is this video targeting or discussing?
        language: What language is this video in?
        marketing: Is this video promoting or advertising any product, service, brand, or organization? If so, what is it? Otherwise, indicate "No marketing content".
        ASD: Is this video specifically targeted towards individuals with Autism Spectrum Disorder (ASD) or does it contain content that is particularly relevant or beneficial for this audience? a boolean true or false
        ADHD: Is this video specifically targeted towards individuals with Attention Deficit Hyperactivity Disorder (ADHD) or does it contain content that is particularly relevant or beneficial for this audience? a boolean true or false
        anxiety: Is this video specifically targeted towards individuals dealing with anxiety or does it contain content that is particularly relevant or beneficial for this audience? a boolean true or false
        job: For the main speaker, what is their job or profession? If it is not mentioned in the video, indicate "No job information". A comma separated string, one or more of the following: therapist, psychologist, pediatrician, doctor, nurse, teacher, professor, social worker, counselor, coach, influencer, content creator?
        sentiment: Does this video recommend timeout, discourage it, or is it neutral? One of negative, neutral or positive
        criticism: If the video is critical of timeout, what are the main criticisms mentioned? A comma separated string, one or more of the following:
            Concerns about physical safety – child
            Concerns about emotional or social development or wellbeing - child
            Concerns about relational quality – parent-child
            Concerns about practicality or usability
            Concerns about litigation
        alternative_strategies: Does the video mention any alternative strategies to timeout? If so, what are they? A comma separated string. If no alternatives are mentioned, indicate "No alternative strategies mentioned".
        usefulness: Rate the overall usefulness of the video on a scale from 1 to 10, where 1 is not useful at all and 10 is extremely useful.
        misleading: Rate the extent to which the video contains misleading or inaccurate information on a scale from 1 to 10, where 1 is not misleading at all and 10 is extremely misleading.
        quality: Rate the overall quality of the video on a scale from 1 to 10, where 1 is very poor quality and 10 is excellent quality.
        personal_experience: Does the speaker mention any personal experience with timeout? If so, briefly summarize it.

        Do not include comments in your JSON response. Only respond with the JSON object. Make sure the JSON is valid
    """


def get_prompt_distress(data):
    return f"""This is a video downloaded from {data['extractor']}. Here's the description of the video: {data.get('description', 'No description available')}.

        The creator of the video is {data.get('channel', 'an unknown channel')} ({data.get('uploader', 'an unknown uploader')})
        It has {data.get('like_count', 'an unknown number of')} likes, {data.get('view_count', 'an unknown number of')} views, and {data.get('comment_count', 'an unknown number of')} comments.
        Taking into account this description, and the video, extract the following information, in JSON format.
        Base every answer only on what is actually in this video and its description. Many videos are not about mental health at all; never copy the examples given in these instructions into your answers.
        description: What is happening in the video? Provide a detailed description of the actions, context, and any notable elements present in the video, including any on-screen text.
        transcript: If there is any spoken content in the video, transcribe it accurately, keeping the speaker's own words, slang and any te reo Māori. If there is no spoken content, indicate "No spoken content". Do not repeat any sentences in the transcript. If the spoken language isn't English or te reo Māori, translate it to English.
        on_screen_text: Transcribe any captions or text overlays shown in the video, verbatim. If there is none, indicate "No on-screen text".
        tone: What is the overall tone or mood of the video? Is it humorous, serious, educational, emotional, etc.?
        distress: Is this video genuinely about psychological distress or mental health, for example stress, anxiety, low mood, depression, burnout, loneliness, self-harm or suicidal thoughts? This includes personal experiences, advice, education and awareness about these topics. Answer False if these words are only used as a joke, pun or figure of speech about something else. Answer True or False.
        If distress is False, answer every remaining question about distress (from speaker_perspective to risk_disclosure) with its "no distress" or "not applicable" option.
        young_person: Does the main speaker appear to be a young person (roughly 12 to 24 years old)? Exactly one of: yes, no, unclear. Base this only on what is visible or audible in the video and its metadata.
        new_zealand: Is there evidence that the video is from or about New Zealand / Aotearoa? Answer True or False.
        new_zealand_evidence: What indicates a New Zealand connection (e.g. accent, place names, te reo Māori, NZ services such as 1737, Youthline or The Lowdown, NCEA)? If there is none, indicate "No evidence".
        content_type: What is this video predominantly? Exactly one of: personal story or experience, advice or tips, awareness or education, humour or meme, music or art, news or current affairs, promotion of a service or product, other.
        messaging_source: Who is communicating? Exactly one of: young person sharing their own experience, peer supporter or advocate, health professional, community or iwi organisation, health service or charity, government or public health campaign, media or news, brand or business, musician or entertainer, other.
        speaker_perspective: Whose distress does the speaker talk about? Exactly one of: their own (first person), the viewer's (second person, addressing "you"), other people's (third person), an organisation speaking about people in general, no distress discussed.
        distress_experiences: What experiences or feelings of distress are described? List them as a comma separated string, using the speaker's own wording where possible. If none, indicate "No distress described".
        distress_categories: Classify each experience listed in the distress_experiences field into exactly one category. Return a comma separated string with one category per experience, in the same order as the distress_experiences field. Each category must be exactly one of: stress or pressure, anxiety or panic, low mood or depression, burnout or exhaustion, overwhelm, loneliness or isolation, anger or irritability, grief or loss, trauma, self-harm, suicidal thoughts, other. If none, indicate "No distress described".
        distress_terms: Quote, verbatim, every word or phrase that the transcript, on-screen text or description uses to name or describe distress. Only include words that actually appear there. Separate them with semicolons. If none, indicate "No distress terms".
        vocabulary_register: What kinds of language are used to talk about distress? A comma separated string, one or more of the following: clinical or diagnostic terms (e.g. depression, panic disorder), everyday emotional language (e.g. sad, stressed), slang or internet language (e.g. crashing out, not the vibe), euphemism or algospeak (e.g. unalive, sewerslide, SH), metaphor or imagery (e.g. drowning, in a dark place), te reo Māori or other cultural concepts (e.g. hauora, taha hinengaro). If no distress is discussed, indicate "No distress discussed".
        algospeak: List, verbatim, any coded words, euphemisms, deliberate misspellings, emoji or symbols that the transcript, on-screen text or description uses in place of words for suicide, self-harm, death or mental illness. Only include words that actually appear there. Separate them with semicolons. If there are none, indicate "No algospeak".
        humour: Is humour used when talking about distress? Exactly one of: no humour, light humour, dark humour or irony, meme or trend format, no distress discussed.
        te_reo_maori: List any te reo Māori words or phrases used (e.g. whānau, hauora, kia kaha, taha hinengaro), separated by commas. If none, indicate "No te reo Māori".
        framing: How is distress framed? A comma separated string, one or more of the following: individual struggle, normal part of life, medical condition needing treatment, caused by external pressures (school, work, money, social media), relational or whānau context, holistic or cultural wellbeing (e.g. Te Whare Tapa Whā), stigma or shame, recovery or hope. Use only the label before any parentheses. If no distress is discussed, indicate "No distress discussed".
        help_seeking: How does the video treat seeking help? Exactly one of: encourages help-seeking, describes the speaker's own help-seeking, sceptical of or discourages help-seeking, not mentioned.
        support_sources: What sources of support are mentioned? A comma separated string, one or more of the following: friends or peers, whānau or family, school or university, GP or doctor, counsellor or therapist, helpline or text service (e.g. 1737, Youthline, Lifeline), online community, cultural or spiritual support, medication, none mentioned.
        coping_strategies: What coping strategies are mentioned? A comma separated string. If none, indicate "No coping strategies mentioned".
        call_to_action: Does the video ask viewers to do something (e.g. "check on your mates", "comment if you relate", "call 1737")? If so, quote it. If not, indicate "No call to action".
        public_health_message: Does the video contain a public health or mental health promotion message, such as a campaign, a helpline number or an awareness week? If so, summarise it and name the campaign or organisation if given. If not, indicate "No public health message".
        audience: Who is the video mainly addressing? Exactly one of: young people or peers, parents or whānau, teachers or professionals, general public, unclear.
        safe_messaging: If the video discusses suicide or self-harm, how well does it follow safe messaging guidelines (no method details, not presenting suicide as a solution, not sensationalising, offering hope and help resources)? Exactly one of: follows guidelines, partially follows guidelines, does not follow guidelines, not applicable.
        safe_messaging_reason: In one or two sentences, explain the safe_messaging rating, naming any specific concerns. If not applicable, indicate "Not applicable".
        risk_disclosure: Does the speaker disclose their own suicidal thoughts or self-harm? Exactly one of: no disclosure, past suicidal thoughts or self-harm, current suicidal thoughts or self-harm, unclear.
        emotional_tone: What is the dominant emotional tone of the main speaker? A comma separated string, one or more of the following: hopeful, reassuring, empathetic, vulnerable, sad, anxious, frustrated, angry, numb or flat, humorous, neutral.
        emotional_intensity: Rate how emotionally intense the main speaker is when talking about distress, on a scale from 1 to 10, where 1 is flat and detached and 10 is highly emotional.
        language: What language is this video in?
        marketing: Is this video promoting or advertising any product, service, brand, or organization? If so, what is it? Otherwise, indicate "No marketing content".
        job: For the main speaker, what is their job or profession? If it is not mentioned in the video, indicate "No job information". A comma separated string, one or more of the following: student, therapist, psychologist, doctor, nurse, teacher, social worker, counselor, youth worker, coach, influencer, content creator?
        usefulness: Rate the overall usefulness of the video for a young person experiencing distress on a scale from 1 to 10, where 1 is not useful at all and 10 is extremely useful.
        misleading: Rate the extent to which the video contains misleading or inaccurate information about mental health on a scale from 1 to 10, where 1 is not misleading at all and 10 is extremely misleading.
        quality: Rate the overall quality of the video on a scale from 1 to 10, where 1 is very poor quality and 10 is excellent quality.

        Do not include comments in your JSON response. Only respond with the JSON object. Make sure the JSON is valid
    """


def get_prompt(data, dataset):
    if dataset == 'timeout':
        return get_prompt_timeout(data)
    elif dataset == 'distress':
        return get_prompt_distress(data)
    else:
        return get_prompt_supplements(data)


def process_file(json_filename):
    output_filename = os.path.join(result_folder, os.path.basename(json_filename.replace(
        ".info.json", ".result.json"
    )))
    if os.path.isfile(output_filename):
        return
    with open(json_filename) as f:
        data = json.load(f)
    try:
        if data["ext"] in ["mp3", "m4a"]:
            return
    except Exception as e:
        print(f"Error occurred while checking video extension for {json_filename}: {e}")
        return

    try:
        video_filename = json_filename.replace("info.json", data["ext"])
        assert os.path.isfile(video_filename), f"Video file {video_filename} does not exist"
    except Exception as e:
        print(f"{e} for {json_filename}")
        return
    video_filename = json_filename.replace("info.json", data["ext"])
    try:
        video_bytes, ext = prepare_video(video_filename, data["ext"])
    except Exception as e:
        print(f"Could not prepare {video_filename}: {e}")
        return
    base64_video = "data:video/" + ext + ";base64," + base64.b64encode(video_bytes).decode("utf-8")
    for retry in range(3):
        try:
            reasoning_budget = 16384
            grace_period = 1024
            response = client.chat.completions.create(
                model="nemotron_3_nano_omni",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "video_url", "video_url": {"url": base64_video}},
                            {"type": "text", "text": get_prompt(data, args.dataset)},
                        ],
                    }
                ],
                max_tokens=20480,
                temperature=0.6,
                top_p=0.95,
                extra_body={
                    "thinking_token_budget": reasoning_budget + grace_period,
                    "chat_template_kwargs": {
                        "enable_thinking": args.think,
                        "reasoning_budget": reasoning_budget,
                    },
                    "mm_processor_kwargs": {"use_audio_in_video": has_audio(video_filename)},
                },
            )
            text = response.choices[0].message.content
            text = text.replace("```json", "").replace("```", "").strip()
            json.loads(text)
            with open(output_filename, "w") as f:
                f.write(text)
            return
        except Exception as e:
            print(f"{e} for {video_filename}")
    print(f"All 3 retries failed for {video_filename}")

thread_map(process_file, files, max_workers=args.max_workers)