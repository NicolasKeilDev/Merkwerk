# backend/fach_manager.py

import io
import base64
import streamlit as st
from supabase import create_client

# --- Setup Supabase client using secrets ---
url = st.secrets["supabase"]["url"]
key = st.secrets["supabase"]["key"]
bucket_name = st.secrets["supabase"]["bucket"]
supabase = create_client(url, key)


def get_all_faecher():
    """
    Returns a sorted list of fach names by listing top-level folders in the bucket,
    excluding any folders that are just placeholders (like .emptyFolderPlaceholder).
    """
    try:
        files = supabase.storage.from_(bucket_name).list()
    except Exception as e:
        st.error(f"Error listing files: {e}")
        return []
    faecher = set()
    for file in files:
        parts = file["name"].split("/")
        if parts and not parts[0].startswith("."):
            faecher.add(parts[0])
    return sorted(list(faecher))


# --- Create a new fach folder structure ---
def create_fach(name):
    """
    Creates a new fach folder with subfolders and a flashcard.js file.
    """
    # Create subfolders: uploads, images, mindmaps by uploading a placeholder file
    for subfolder in ["uploads", "images", "mindmaps"]:
        placeholder_path = f"{name}/{subfolder}/placeholder.txt"
        try:
            supabase.storage.from_(bucket_name).upload(placeholder_path, "".encode("utf-8"))
        except Exception:
            pass  # Ignore if the placeholder already exists

    # Create flashcards.json file if it doesn't exist
    flashcard_path = f"{name}/flashcards.json"
    try:
        supabase.storage.from_(bucket_name).download(flashcard_path)
    except Exception:
        try:
            supabase.storage.from_(bucket_name).upload(flashcard_path, "[]".encode("utf-8"))
        except Exception as e2:
            st.error(f"Error creating flashcards.json: {e2}")

# --- Delete a fach folder (all files under the fach prefix) ---
def delete_fach(fach_name):
    """
    Deletes all files under the fach folder.
    Note: This implementation assumes that list() returns all objects under the prefix.
    """
    try:
        # List files under the fach folder
        files = supabase.storage.from_(bucket_name).list(fach_name, limit=1000)
    except Exception as e:
        st.error(f"Error listing files for deletion: {e}")
        return

    # Build full paths for deletion (e.g. "fach/uploads/filename")
    to_delete = [f"{fach_name}/{file['name']}" for file in files]
    
    # Remove files if any
    if to_delete:
        try:
            supabase.storage.from_(bucket_name).remove(to_delete)
        except Exception as e:
            st.error(f"Error deleting files: {e}")

# --- Rename a fach folder ---
def rename_fach(old_name, new_name):
    """
    Renames a fach folder by copying all files from old_name to new_name and then deleting old files.
    """
    try:
        files = supabase.storage.from_(bucket_name).list(old_name, limit=1000)
    except Exception as e:
        st.error(f"Error listing files for renaming: {e}")
        return

    for file in files:
        old_path = f"{old_name}/{file['name']}"
        new_path = f"{new_name}/{file['name']}"
        
        # Download file from the old path
        try:
            data = supabase.storage.from_(bucket_name).download(old_path)
            file_bytes = data.read()  # data is a BytesIO object
        except Exception as e:
            st.error(f"Error downloading file {old_path}: {e}")
            continue
        
        # Upload file to the new path
        try:
            supabase.storage.from_(bucket_name).upload(new_path, file_bytes)
        except Exception as e:
            st.error(f"Error uploading file {new_path}: {e}")
            continue

    # After copying, remove the old files
    try:
        old_files = [f"{old_name}/{file['name']}" for file in files]
        if old_files:
            supabase.storage.from_(bucket_name).remove(old_files)
    except Exception as e:
        st.error(f"Error deleting old files after renaming: {e}")
