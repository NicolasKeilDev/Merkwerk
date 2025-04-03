# backend/mindmap_manager.py

from pathlib import Path

def get_mindmap_html(fach_name, pdf_name):
    """
    Retrieve the mindmap HTML content for the given Fach and PDF.
    Returns the HTML as a string if it exists, or None otherwise.
    """
    mindmap_dir = Path("mindmap") / fach_name
    mindmap_file = mindmap_dir / f"{pdf_name.split('.')[0]}_mindmap.html"
    if mindmap_file.exists():
        return mindmap_file.read_text(encoding="utf-8")
    return None

def save_mindmap_html(fach_name, pdf_name, html_content):
    """
    Save the mindmap HTML content for the given Fach and PDF.
    This function creates the folder if it doesn't exist.
    """
    mindmap_dir = Path("mindmap") / fach_name
    mindmap_file = mindmap_dir / f"{pdf_name.split('.')[0]}_mindmap.html"
    mindmap_file.write_text(html_content, encoding="utf-8")

def list_mindmaps(fach_name):
    """
    List all mindmap HTML files for the given Fach.
    Returns a list of Path objects.
    """
    mindmap_dir = Path("mindmap") / fach_name
    if mindmap_dir.exists():
        return list(mindmap_dir.glob("*.html"))
    return []