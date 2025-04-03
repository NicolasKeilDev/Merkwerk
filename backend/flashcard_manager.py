# backend/flashcard_manager.py
import json
from pathlib import Path

def get_flashcards(fach_name):
    path = Path("data") / fach_name / "flashcards.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return []

def save_flashcard(fach_name, flashcard_dict):
    path = Path("data") / fach_name / "flashcards.json"
    cards = get_flashcards(fach_name)
    cards.append(flashcard_dict)
    path.write_text(json.dumps(cards, indent=2, ensure_ascii=False), encoding="utf-8")

def update_flashcards(fach_name, flashcards):
    path = Path("data") / fach_name / "flashcards.json"
    path.write_text(json.dumps(flashcards, indent=2, ensure_ascii=False), encoding="utf-8")

def delete_document(fach_name, document_name):
    """Delete a PDF document, remove its flashcards and corresponding mindmap file."""
    pdf_path = Path("data") / fach_name / "uploads" / document_name
    if pdf_path.exists():
        pdf_path.unlink()
    # Remove all flashcards that belong to this document
    flashcards = get_flashcards(fach_name)
    original_count = len(flashcards)
    flashcards = [card for card in flashcards if card.get("upload", "Unbekannt") != document_name]
    if len(flashcards) < original_count:
        update_flashcards(fach_name, flashcards)
    # Remove corresponding mindmap if it exists
    mindmap_file = Path("mindmap") / fach_name / f"{document_name.split('.')[0]}_mindmap.html"
    if mindmap_file.exists():
        mindmap_file.unlink()

def update_flashcards(fach_name, flashcards):
    """Update the flashcards JSON file with new content."""
    path = Path("data") / fach_name / "flashcards.json"
    with open(path, 'w', encoding="utf-8") as f:
        json.dump(flashcards, f, ensure_ascii=False, indent=2)
