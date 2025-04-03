# backend/pdf_parser.py
import fitz  # PyMuPDF
from pathlib import Path

def extract_text_from_pdf(pdf_input):
    text = ""

    # Fall 1: Datei ist ein Pfad (Path oder str)
    if isinstance(pdf_input, (str, Path)):
        doc = fitz.open(pdf_input)
    else:
        # Fall 2: Datei ist ein Upload-Objekt (BytesIO)
        doc = fitz.open(stream=pdf_input.read(), filetype="pdf")

    with doc:
        for page in doc:
            text += page.get_text()
    return text

def extract_content_from_pdf(pdf_path, image_pages=None, excluded_pages=None):
    """
    Extract content from PDF with mixed mode - text for normal pages,
    image recognition for specified pages.
    
    Args:
        pdf_path: Path to the PDF file
        image_pages: List of page numbers (1-based) to use image recognition instead of text
        excluded_pages: List of page numbers (1-based) to completely exclude from processing
    
    Returns:
        dict: Contains extracted text and references to saved images
    """
    result = {
        "text": "",
        "images": []
    }
    
    image_pages = image_pages or []
    excluded_pages = excluded_pages or []
    doc = fitz.open(pdf_path)
    
    for page_num, page in enumerate(doc):
        page_num_human = page_num + 1  # Convert to 1-based page numbering
        
        # Skip excluded pages completely
        if page_num_human in excluded_pages:
            continue
        
        if page_num_human in image_pages:
            # Save page as image for later processing
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))  # Higher resolution
            image_path = f"{pdf_path.stem}_page_{page_num_human}.png"
            save_path = Path(pdf_path).parent.parent / "images" / image_path
            pix.save(save_path)
            result["images"].append({
                "page": page_num_human,
                "path": str(save_path)
            })
            result["text"] += f"\n[IMAGE EXTRACTION FOR PAGE {page_num_human}]\n"
        else:
            # Regular text extraction
            result["text"] += page.get_text()
    
    return result
