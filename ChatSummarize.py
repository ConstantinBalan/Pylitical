import pathlib
import textwrap
from dotenv import load_dotenv
import os
import google.generativeai as genai

load_dotenv()

google_api_key = os.getenv("GOOGLE_API_KEY")
genai.configure(api_key=google_api_key)


def summarize_bill_info(bill_status, bill_name, bill_text):
    instruction = """You are going to be summarizing bills and resolutions that
    are currently being deliberated or have already been enrolled by the Michigan congress.
    In the prompt i'm going to pass you the state of the bill or resolution, the name of
    the bill or resolution, and the text of the bill. I want you to summarize the text into
    as many bullet points as you see fit. Prior to the bullet points also give me the status
    and name of the bill or resolution.
    """
    model = genai.GenerativeModel(
        model_name="gemini-1.5-pro-latest", system_instruction=instruction
    )
    prompt = bill_name + bill_status + bill_text
    response = model.generate_content(prompt)

    return response
