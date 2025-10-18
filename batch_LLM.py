#!/usr/bin/env python3

import pandas as pd
import os
pd.set_option("display.max_columns", None)
pd.set_option("display.max_colwidth", 100)
from pprint import pprint
import json5 as json  # This is a more forgiving JSON parser that can handle comments, single quotes, and trailing commas
from glob import glob
from tqdm import tqdm
from transformers import Qwen3OmniMoeForConditionalGeneration, Qwen3OmniMoeProcessor
from qwen_omni_utils import process_mm_info
import torch

files = []
for f in glob("videos/*.json"):
    output_filename = f.replace("videos/", "results/").replace(
        ".info.json", ".result.json"
    )
    if not os.path.isfile(output_filename):
        files.append(f)
print(len(files))

MODEL_PATH = "Qwen/Qwen3-Omni-30B-A3B-Instruct"
# Uses about 78GB VRAM
model = Qwen3OmniMoeForConditionalGeneration.from_pretrained(
    MODEL_PATH,
    dtype=torch.bfloat16,
    device_map="auto",
    attn_implementation="flash_attention_2",
)
model.disable_talker()
processor = Qwen3OmniMoeProcessor.from_pretrained(MODEL_PATH)


def get_prompt(data):
    return f"""This is a video downloaded from {data['extractor']}. Here's the description of the video: {data['description']}.

        The creator of the video is {data.get('channel', 'an unknown channel')} ({data.get('uploader', 'an unknown uploader')})
        It has {data.get('like_count', 'an unknown number of')} likes, {data.get('view_count', 'an unknown number of')} views, and {data.get('comment_count', 'an unknown number of')} comments.
        Taking into account this description, and the video, extract the following information, in JSON format:
        description: What is happening in the video? Provide a detailed description of the actions, context, and any notable elements present in the video.
        transcript: If there is any spoken content in the video, transcribe it accurately. If there is no spoken content, indicate "No spoken content". Do not repeat any sentances in the transcript.
        tone: What is the overall tone or mood of the video? Is it humorous, serious, educational, emotional, etc.?
        timeout: Is this video talking about timeout for children (as a parenting punishement strategy)? a boolean true or false
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


for json_filename in tqdm(files):
    output_filename = json_filename.replace("videos/", "results/").replace(
        ".info.json", ".result.json"
    )
    if os.path.isfile(output_filename):
        continue
    print(f"{json_filename}")
    with open(json_filename) as f:
        data = json.load(f)
    video_filename = json_filename.replace("info.json", data["ext"])
    assert os.path.isfile(video_filename)
    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "video",
                    "video": video_filename,
                    "max_pixels": 360 * 420,
                },
                {"type": "text", "text": get_prompt(data)},
            ],
        }
    ]
    # Set whether to use audio in video
    USE_AUDIO_IN_VIDEO = True

    # Preparation for inference
    text = processor.apply_chat_template(
        messages, add_generation_prompt=True, tokenize=False
    )
    audios, images, videos = process_mm_info(
        messages, use_audio_in_video=USE_AUDIO_IN_VIDEO
    )
    inputs = processor(
        text=text,
        audio=audios,
        images=images,
        videos=videos,
        return_tensors="pt",
        padding=True,
        use_audio_in_video=USE_AUDIO_IN_VIDEO,
    )
    inputs = inputs.to(model.device).to(model.dtype)

    # Inference: Generation of the output text and audio
    text_ids, audio = model.generate(
        **inputs,
        thinker_return_dict_in_generate=True,
        use_audio_in_video=USE_AUDIO_IN_VIDEO,
    )

    text = processor.batch_decode(
        text_ids.sequences[:, inputs["input_ids"].shape[1] :],
        skip_special_tokens=True,
        clean_up_tokenization_spaces=False,
    )[0]
    text = text.replace("```json", "").replace("```", "").strip()
    with open(output_filename, "w") as f:
        f.write(text)
    print(f"Wrote results to {output_filename}")
