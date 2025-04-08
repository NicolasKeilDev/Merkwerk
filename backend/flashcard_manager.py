# backend/flashcard_manager.py
import json
import streamlit as st
from supabase import create_client

# Initialize Supabase client using secrets
url = st.secrets["supabase"]["url"]
key = st.secrets["supabase"]["key"]
bucket_name = st.secrets["supabase"]["bucket"]
supabase = create_client(url, key)

def get_flashcards(fach_name):
    """
    Download flashcards.json from Supabase storage and return the flashcards list.
    If the file doesn't exist, return an empty list.
    """
    file_path = f"{fach_name}/flashcards.json"
    try:
        response = supabase.storage.from_(bucket_name).download(file_path)
        # response may be bytes or have a content attribute
        if isinstance(response, bytes):
            content = response.decode('utf-8')
        else:
            content = response.content.decode('utf-8')
        return json.loads(content)
    except Exception:
        # File doesn't exist or another error occurred: return empty list
        return []

def update_flashcards(fach_name, flashcards):
    """
    Update flashcards.json in Supabase storage with the new flashcards content.
    This removes any existing file and uploads the new content.
    """
    file_path = f"{fach_name}/flashcards.json"
    content = json.dumps(flashcards, indent=2, ensure_ascii=False)
    try:
        # Remove the existing file if it exists (ignore error if not)
        try:
            supabase.storage.from_(bucket_name).remove([file_path])
        except Exception:
            pass
        # Upload the new content (encoded as bytes)
        supabase.storage.from_(bucket_name).upload(file_path, content.encode('utf-8'))
    except Exception as e:
        st.error(f"Error updating flashcards: {e}")

def save_flashcard(fach_name, flashcard_dict):
    """
    Append a new flashcard to the flashcards.json file stored in Supabase.
    """
    flashcards = get_flashcards(fach_name)
    flashcards.append(flashcard_dict)
    update_flashcards(fach_name, flashcards)

def delete_document(fach_name, document_name):
    """
    Delete a PDF document from the uploads folder, remove its flashcards,
    and delete the corresponding mindmap file and images from Supabase storage.
    """
    # Delete the PDF document from uploads
    pdf_path = f"{fach_name}/uploads/{document_name}"
    try:
        supabase.storage.from_(bucket_name).remove([pdf_path])
    except Exception as e:
        st.error(f"Error deleting PDF: {e}")

    # Remove flashcards belonging to this document
    flashcards = get_flashcards(fach_name)
    original_count = len(flashcards)
    flashcards = [card for card in flashcards if card.get("upload", "Unbekannt") != document_name]
    if len(flashcards) < original_count:
        update_flashcards(fach_name, flashcards)

    # Delete the corresponding mindmap file from the mindmaps folder
    mindmap_path = f"{fach_name}/mindmaps/{document_name.split('.')[0]}_mindmap.html"
    try:
        supabase.storage.from_(bucket_name).remove([mindmap_path])
    except Exception as e:
        st.error(f"Error deleting mindmap: {e}")

    # Delete the corresponding images from the images folder
    try:
        images_folder = f"{fach_name}/images/"
        # List all files in the images folder
        images_list = supabase.storage.from_(bucket_name).list(images_folder)
        document_stem = document_name.split('.')[0]
        images_to_delete = []
        # Filter files that start with the document stem (e.g. "DocumentName_page_")
        for file in images_list:
            if file["name"].startswith(f"{document_stem}_page_"):
                images_to_delete.append(f"{fach_name}/images/{file['name']}")
        if images_to_delete:
            supabase.storage.from_(bucket_name).remove(images_to_delete)
    except Exception as e:
        st.error(f"Error deleting images: {e}")
