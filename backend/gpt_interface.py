# backend/gpt_interface.py

import json
import streamlit as st
from openai import OpenAI
from pydantic import BaseModel, Field

# Initialize the OpenAI client with the API key from st.secrets
client = OpenAI(api_key=st.secrets["openai"]["api_key"])

# Single source of truth for the model to ensure it's used everywhere
MODEL = "gpt-5.2-2025-12-11"


# ----------------------------
# Structured output schemas
# ----------------------------
class Flashcard(BaseModel):
    upload: str
    question: str
    answer: list[str] = Field(min_length=1)
    page: int


class Mindmap(BaseModel):
    nodes: list[str] = Field(default_factory=list)
    edges: list[list[str]] = Field(default_factory=list)


# ----------------------------
# Flashcard generation (text + image)
# ----------------------------
def analyze_image_for_flashcard_base64(
    base64_image: str,
    upload_name: str,
    page_number: int,
    page_text: str,
) -> str:
    """
    Analyze a PDF page using BOTH extracted text and rendered page image.
    Returns a JSON string that conforms to the Flashcard schema (Structured Outputs).
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
            # Structured Outputs (strict) using Pydantic schema:
            text_format=Flashcard,
            temperature=0.3,
            max_output_tokens=800,
        )

        card: Flashcard = response.output_parsed

        # Enforce deterministic metadata (prevents accidental drift)
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


# ----------------------------
# Mindmap generation (text)
# ----------------------------
def generate_mindmap_from_text(full_text: str, document_name: str) -> str:
    """
    Generates a mindmap JSON with keys: nodes, edges.
    Uses the Responses API and enforces Structured Outputs with a schema.
    Returns a JSON string.
    """
    prompt = f"""
Erstelle eine Mindmap aus dem folgenden Text. Das zentrale Thema heißt "{document_name}".
Die Mindmap soll oberflächlich sein und nur die wichtigsten Hauptthemen und deren Hierarchie darstellen.
Das zentrale Thema soll in der Mitte stehen.

Bitte gib das Ergebnis als JSON-Objekt mit zwei Schlüsseln aus: "nodes" und "edges".
- "nodes" soll eine Liste von eindeutigen Konzeptnamen (Strings) sein.
- "edges" soll eine Liste von Paaren [Quelle, Ziel] sein, die die Beziehungen zwischen den Konzepten darstellen.

Wichtige Hinweise:
- Verwende kurze, prägnante Begriffe
- Stelle sicher, dass die Ausgabe valides JSON ist

Text des Dokuments:
{full_text}
""".strip()

    try:
        response = client.responses.parse(
            model=MODEL,
            input=prompt,
            text_format=Mindmap,
            temperature=0.3,
            max_output_tokens=1200,
        )

        mindmap: Mindmap = response.output_parsed
        return json.dumps(mindmap.model_dump(), ensure_ascii=False)

    except Exception as e:
        raise Exception(f"Error generating mindmap from text: {e}")
