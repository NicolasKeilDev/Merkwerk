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

# --- Helper: Create a “directory marker” file ---
def create_folder_marker(path: str):
    """
    In Supabase Storage, folders are virtual.
    Here we simulate a folder by uploading an empty marker file.
    """
    try:
        # Try to upload an empty file (will fail if it already exists)
        supabase.storage.from_(bucket_name).upload(path, b"")
    except Exception as e:
        # Optionally ignore errors if the marker already exists.
        pass

# --- List all "Fächer" (folders) ---
def get_all_faecher():
    """
    Returns a sorted list of fach names (i.e. folders) by listing root files 
    and finding our directory markers (files named ".directory").
    """
    try:
        files = supabase.storage.from_(bucket_name).list("", limit=1000)
    except Exception as e:
        st.error(f"Error listing files: {e}")
        return []
    faecher = set()
    for file in files:
        # Look for markers like "fach_name/.directory"
        if "/" in file["name"]:
            parts = file["name"].split("/")
            if parts[-1] == ".directory" and len(parts) == 2:
                faecher.add(parts[0])
    return sorted(list(faecher))

# --- Create a new fach folder structure ---
def create_fach(name):
    """
    Creates a new fach folder with subfolders and a flashcards.json file.
    """
    # Create the main fach marker (e.g. "biology/.directory")
    fach_marker = f"{name}/.directory"
    create_folder_marker(fach_marker)
    
    # Create subfolders: uploads, images, mindmaps
    for subfolder in ["uploads", "images", "mindmaps"]:
        marker = f"{name}/{subfolder}/.directory"
        create_folder_marker(marker)
        
    # Create flashcards.json file if it doesn't exist
    flashcards_path = f"{name}/flashcards.json"
    try:
        # Attempt to download to check if it exists
        supabase.storage.from_(bucket_name).download(flashcards_path)
    except Exception:
        # If not found, create it with empty JSON array content
        try:
            supabase.storage.from_(bucket_name).upload(flashcards_path, "[]".encode("utf-8"))
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
