import json
import streamlit as st
import re
import base64
from openai import OpenAI

# Initialize the OpenAI client with the API key from st.secrets
client = OpenAI(api_key=st.secrets["openai"]["api_key"])

def generate_card_from_text(text, upload_name, page_number):
    prompt = f"""
    Erstelle eine Lernkarte im JSON-Format im Frage-Antwort-Stil aus dem folgenden Textauszug.
    Die Antwort sollte als Liste von kurzen, prägnanten Stichpunkten verfasst sein.
    Jeder Stichpunkt soll mit dem Bullet "•" beginnen und als Halbsatz formuliert sein.
    Verwende dabei ausschließlich einfache und verständliche Sprache.
    Erkläre alle Fachbegriffe und themenbezogene Begriffe jeweils in einfachen Worten.
    Inkludiere alle auf der Seite vorkommenden Fachbegriffe in der Karteikarte.
    Dokument: {upload_name}
    
    Text:
    {text}
    
    Format:
    {{
      "upload": "{upload_name}",
      "question": "...",
      "answer": [
        "• Stichpunkt 1",
        "• Stichpunkt 2"
      ],
      "page": {page_number}
    }}
    
    WICHTIG: Deine gesamte Antwort muss ausschließlich aus validem JSON bestehen, ohne zusätzlichen Text, Kommentare oder Erklärungen.
    """
    try:
        response = client.chat.completions.create(
            model="o3-mini-2025-01-31",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}  # Force JSON output
        )
        content = response.choices[0].message.content
        
        # Validate that we have valid JSON before returning
        try:
            json.loads(content)  # Just to validate
            return content
        except json.JSONDecodeError:
            # If we still get invalid JSON, try to extract just the JSON part
            json_match = re.search(r'(\{.*\})', content, re.DOTALL)
            if json_match:
                potential_json = json_match.group(1)
                json.loads(potential_json)  # Will raise exception if still invalid
                return potential_json
            else:
                # Fallback JSON response
                fallback_json = {
                    "upload": upload_name,
                    "question": f"Content from page {page_number} (Error: API returned invalid JSON)",
                    "answer": ["The API response couldn't be parsed properly.", f"Please check page {page_number} directly."],
                    "page": page_number
                }
                return json.dumps(fallback_json)
    except Exception as e:
        # Return an error response in valid JSON format
        error_json = {
            "upload": upload_name,
            "question": f"Error processing page {page_number}",
            "answer": [f"An error occurred: {str(e)}", "Please try regenerating this card or check the text input."],
            "page": page_number
        }
        return json.dumps(error_json)

def analyze_image_for_flashcard_base64(base64_image, upload_name, page_number):
    """
    Uses a base64 image (as generated from PDF) to query GPT for flashcard content.
    """
    prompt = f"""
    Analysiere dieses Folienbild und erstelle eine Lernkarte im JSON-Format im Frage-Antwort-Stil.
    Die Antwort sollte als Liste von kurzen, prägnanten Stichpunkten formuliert sein.
    Jeder Stichpunkt soll mit dem Bullet "•" beginnen und als Halbsatz formuliert sein.
    Verwende dabei einfache und leicht verständliche Sprache.
    Erkläre alle Fachbegriffe und themenbezogene Begriffe immer in einfachen Worten.
    Inkludiere alle auf der Seite vorkommenden Fachbegriffe in der Karteikarte.
    Dokument: {upload_name}
    
    Erstelle eine präzise, aber umfassende Frage, die das Hauptthema des Bildes abdeckt.
    Die Antwort-Stichpunkte sollten:
    - Klar und prägnant sein,
    - Die wichtigsten Konzepte und Details enthalten,
    - In logischer Reihenfolge angeordnet sein.
    
    Format:
    {{
      "upload": "{upload_name}",
      "question": "...",
      "answer": [
        "• Stichpunkt 1",
        "• Stichpunkt 2"
      ],
      "page": {page_number}
    }}
    
    WICHTIG: Deine gesamte Antwort muss ausschließlich aus validem JSON bestehen, ohne zusätzlichen Text, Kommentare oder Erklärungen.
    """
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64_image}"}}
                ]
            }],
            temperature=0.3,
            max_tokens=800
        )
        content = response.choices[0].message.content
        
        try:
            json.loads(content)  # Validate JSON
            return content
        except json.JSONDecodeError:
            json_match = re.search(r'(\{.*\})', content, re.DOTALL)
            if json_match:
                potential_json = json_match.group(1)
                json.loads(potential_json)
                return potential_json
            else:
                fallback_json = {
                    "upload": upload_name,
                    "question": f"Content from image on page {page_number} (Error: API returned invalid JSON)",
                    "answer": ["The API response couldn't be parsed properly.", f"Please check the image on page {page_number} directly."],
                    "page": page_number
                }
                return json.dumps(fallback_json)
    except Exception as e:
        error_json = {
            "upload": upload_name,
            "question": f"Error processing image on page {page_number}",
            "answer": [f"An error occurred: {str(e)}", "Please try regenerating this card or check the image."],
            "page": page_number
        }
        return json.dumps(error_json)

def generate_mindmap_from_text(full_text, document_name):
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
    """
    try:
        response = client.chat.completions.create(
            model="o3-mini-2025-01-31",
            messages=[{"role": "user", "content": prompt}]
        )
    except Exception as e:
        raise Exception(f"Error generating mindmap from text: {e}")
    return response.choices[0].message.content
