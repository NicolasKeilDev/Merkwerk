import json
import streamlit as st
from openai import OpenAI
from pydantic import BaseModel, Field

client = OpenAI(api_key=st.secrets["openai"]["api_key"])
MODEL = "gpt-5.2-2025-12-11"


class Flashcard(BaseModel):
    upload: str
    question: str
    answer: list[str] = Field(min_length=1)
    page: int


def analyze_image_for_flashcard_base64(
    base64_image: str,
    upload_name: str,
    page_number: int,
    page_text: str,
) -> str:
    """
    Analyze a PDF page using BOTH extracted text and rendered page image.
    Returns JSON string conforming to Flashcard schema (Structured Outputs).
    """
    prompt = f"""
Analysiere diese PDF-Seite und erstelle eine Lernkarte.

WICHTIG: Nutze BEIDE Inputs:
- Den extrahierten Text (unten)
- Das Folienbild (Bildinput)

Vorgaben:
- Formuliere eine präzise, aber umfassende Frage, die das Hauptthema der Seite abdeckt.
- Die Antwort muss eine Liste von kurzen, prägnanten Stichpunkten sein.
- Jeder Stichpunkt muss mit "•" beginnen und als Halbsatz formuliert sein.
- Verwende einfache, leicht verständliche Sprache.
- Erkläre alle Fachbegriffe und themenbezogenen Begriffe immer in einfachen Worten.
- Inkludiere alle auf der Seite vorkommenden Fachbegriffe in der Karteikarte.

Kontext:
- Dokument: {upload_name}
- Seite: {page_number}

Extrahierter Text der Seite (kann unvollständig sein, nutze zusätzlich das Bild):
{page_text}
""".strip()

    try:
        response = client.responses.parse(
            model=MODEL,
            input=[
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {
                            "type": "input_image",
                            "image_url": f"data:image/png;base64,{base64_image}",
                        },
                    ],
                }
            ],
            text_format=Flashcard,
            temperature=0.3,
            max_output_tokens=800,
        )

        card: Flashcard = response.output_parsed

        # enforce metadata deterministically
        card.upload = upload_name
        card.page = page_number

        return json.dumps(card.model_dump(), ensure_ascii=False)

    except Exception as e:
        error_json = {
            "upload": upload_name,
            "question": f"Error processing page {page_number}",
            "answer": [
                f"An error occurred: {str(e)}",
                "Please try regenerating this card or check the page.",
            ],
            "page": page_number,
        }
        return json.dumps(error_json, ensure_ascii=False)
