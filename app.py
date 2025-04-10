# app.py

import streamlit as st
from pathlib import Path
import json
import base64
import fitz  # PyMuPDF
import random 
import genanki
import tempfile
import os

import streamlit.components.v1 as components

from backend.fach_manager import get_all_faecher, create_fach, delete_fach
from backend.pdf_parser import extract_text_from_pdf, extract_content_from_pdf
from backend.gpt_interface import generate_card_from_text, generate_mindmap_from_text, analyze_image_for_flashcard_base64
from backend.flashcard_manager import save_flashcard, get_flashcards, update_flashcards, delete_document
from backend.storage_utils import get_image_as_data_url
from supabase import create_client
import urllib.parse


# --- Setup Supabase client using secrets ---
url = st.secrets["supabase"]["url"]
key = st.secrets["supabase"]["key"]
bucket_name = st.secrets["supabase"]["bucket"]
supabase = create_client(url, key)


st.set_page_config(page_title="Merkwerk", layout="wide")
# Custom CSS to increase the default font size and button height
st.markdown("""
<style>
    html, body, [class*="css"] {
        font-size: 20px !important;
    }

    /* Update the primary button color */
    div[data-testid="stButton"] button[kind="primary"] {
        background-color: #4d4de4 !important;
        color: white !important;
        border-color: #4d4de4 !important;
        height: 5em !important;
    }

    /* Update the secondary (inactive) button color */
    div[data-testid="stButton"] button[kind="secondary"] {
        background-color: rgb(56, 59, 59) !important;  
        color: white !important;    
        border-color: rgb(56, 59, 59) !important;
        height: 5em !important;
    }

    /* Hover effects for Streamlit buttons */
    div[data-testid="stButton"] button[kind="secondary"]:hover {
        background-color: rgba(50, 50, 50, 0.8) !important;
        border-color: rgba(124, 124, 221, 0.3);
    }

    /* Update the tertiary button color */
    div[data-testid="stButton"] button[kind="tertiary"] {
        background-color:rgb(34, 38, 48) !important;
        color: white !important;
        border-color: #4d4de4 !important;
        padding: 10px !important;
        height: auto !important;
        min-height: unset !important;
        width: auto !important;
    }
""", unsafe_allow_html=True)

st.title("Merkwerk")


# Initialize the view mode in session state if it doesn't exist
if 'view_mode' not in st.session_state:
    st.session_state.view_mode = 'Creator Studio'

# Create columns for the buttons
col1, col2 = st.columns(2)

# Creator Studio button
with col1:
    if st.button('**Creator Studio**', 
                 use_container_width=True,
                 type='primary' if st.session_state.view_mode == 'Creator Studio' else 'secondary',
                 icon=":material/edit:"):
        st.session_state.view_mode = 'Creator Studio'
        st.rerun()

# Learning Studio button
with col2:
    if st.button('**Learning Studio**',
                 use_container_width=True,
                 type='primary' if st.session_state.view_mode == 'Learning Studio' else 'secondary',
                 icon=":material/psychology:"):
        st.session_state.view_mode = 'Learning Studio'
        st.rerun()

# Use the view_mode from session state for the main content
view_mode = st.session_state.view_mode

# ---------- Helper Function for Card Selection ----------
def select_next_card(cards):
    """Selects the next card index based on priority using weighted random selection."""
    if not cards:
        return 0 # Or handle appropriately

    indices = list(range(len(cards)))
    weights = []
    for card in cards:
        priority = card.get("priority", 2) # Default to medium priority if missing
        if priority == 1: # Schwer
            weights.append(5)
        elif priority == 2: # Mittel
            weights.append(3)
        else: # Leicht (Priority 1 or other)
            weights.append(1)

    # Avoid showing the same card twice in a row if possible
    last_index = st.session_state.get('last_shown_index', -1)
    chosen_index = -1

    # Try up to 10 times to get a different card than the last one
    for _ in range(10):
        if sum(weights) == 0: # Handle case where all weights might be zero (e.g., empty list)
             chosen_index = random.choice(indices) if indices else 0
             break
        chosen_index = random.choices(indices, weights=weights, k=1)[0]
        if len(cards) <= 1 or chosen_index != last_index:
            break
    else: # If loop finishes without break (all choices were the last index)
        # Fallback if it keeps picking the same one (should be rare with >1 card)
         if indices:
             chosen_index = random.choice(indices)


    st.session_state.last_shown_index = chosen_index
    return chosen_index

def save_image_from_base64(base64_str, filename):
    """Decode the base64 string and write it as a file."""
    image_data = base64.b64decode(base64_str)
    with open(filename, "wb") as f:
        f.write(image_data)
    return filename

def save_mindmap_html(html_content, filename):
    """Write the HTML content for the mindmap to disk."""
    with open(filename, "w", encoding="utf-8") as f:
        f.write(html_content)
    return filename

def generate_anki_package(deck_name, flashcards):
    """
    Generate an Anki package (.apkg) from a list of flashcard dictionaries.
    Each flashcard should be a dict with at least: 'question' and 'answer'.
    Optionally, it may have:
      - 'image_base64' : a base64 string (for an image to embed).
      - 'mindmap': True (to indicate that answer contains HTML for a mindmap).
    """
    # Define a simple Anki model with two fields.
    my_model = genanki.Model(
        1607392319,  # unique model ID (choose a random int)
        'Simple Model',
        fields=[{'name': 'Question'}, {'name': 'Answer'}],
        templates=[{
            'name': 'Card 1',
            'qfmt': '{{Question}}',
            'afmt': '{{FrontSide}}<hr id="answer">{{Answer}}',
        }]
    )
    
    # Create a deck with a random deck ID.
    deck = genanki.Deck(random.randint(1000000, 9999999), deck_name)
    
    media_files = []  # List to hold paths of media files
    
    # Process each flashcard.
    for idx, card in enumerate(flashcards):
        question = card.get("question", "")
        
        # Build the answer content.
        # If the answer is a list (e.g., points), join them with <br>.
        answer_raw = card.get("answer", "")
        if isinstance(answer_raw, list):
            answer_text = "<br>".join(answer_raw)
        else:
            answer_text = answer_raw
        
        # If the card contains a base64 image, save it and add an <img> tag.
        if "image_base64" in card:
            image_filename = f"flashcard_{idx}_image.png"
            save_image_from_base64(card["image_base64"], image_filename)
            media_files.append(image_filename)
            answer_text += f"<br><img src='{image_filename}' />"
        
        # If the card is the mindmap card, write its HTML content.
        if card.get("mindmap", False):
            # In this case, the answer contains the HTML for the mindmap.
            mindmap_filename = "mindmap.html"  # or use a unique name
            save_mindmap_html(answer_text, mindmap_filename)
            media_files.append(mindmap_filename)
            # Replace the answer with a link for a cleaner display.
            answer_text = f"Mindmap available: <a href='{mindmap_filename}'>Open Mindmap</a>"
        
        # Create a note with question and answer.
        note = genanki.Note(
            model=my_model,
            fields=[question, answer_text]
        )
        deck.add_note(note)
    
    # Create the Anki package including all media files.
    package = genanki.Package(deck, media_files=media_files)
    
    # Write the APKG file to a temporary file and return its bytes.
    with tempfile.NamedTemporaryFile(suffix=".apkg", delete=False) as tmp:
        package.write_to_file(tmp.name)
        tmp.seek(0)
        apkg_bytes = tmp.read()
    os.unlink(tmp.name)
    return apkg_bytes


if view_mode == "Creator Studio":
    # ------------------------------
    # Fachverwaltung: Create, Select and Delete Fach - Vertical layout (replacing columns)
    # ------------------------------
    
    st.markdown("---")  # Add a divider for visual separation
    
    # Initialize session state for modal visibility and input
    if 'show_fach_modal' not in st.session_state:
        st.session_state.show_fach_modal = False
    if 'last_created_fach' not in st.session_state:
        st.session_state.last_created_fach = None

    # Button to trigger modal
    if st.button("Fach erstellen", type="tertiary", icon=":material/construction:"):
        st.session_state.show_fach_modal = True
        # Reset any previous input
        if "modal_fach_input" in st.session_state:
            st.session_state.modal_fach_input = ""
        st.rerun()

    st.markdown("<br>", unsafe_allow_html=True)  # Add vertical spacing

    # Show modal when state is true
    if st.session_state.show_fach_modal:
        # Create a container for the input
        modal = st.container()
        with modal:
            # Add the input field
            new_fach_name = st.text_input("Name des neuen Fachs:", key="modal_fach_input", 
                                          on_change=lambda: process_fach_input())
            
            # Define the function to process new Fach input
            def process_fach_input():
                if st.session_state.modal_fach_input.strip():
                    # Get the name from session state (this is how we capture the latest input)
                    name = st.session_state.modal_fach_input.strip()
                    if create_fach(name):
                        # Save success state and newly created fach name
                        st.session_state.last_created_fach = name
                        # Hide the modal
                        st.session_state.show_fach_modal = False
                        # Clear the input
                        st.session_state.modal_fach_input = ""

    # Select existing Fach
    faecher = get_all_faecher()
    if faecher:
        # Replace dropdown with a grid of buttons
        st.markdown("#### Fachauswahl")
        
        # Calculate number of buttons per row (adjust as needed)
        buttons_per_row = 3
        
        # Split faecher into rows
        for i in range(0, len(faecher), buttons_per_row):
            # Create a row of columns
            cols = st.columns(buttons_per_row)
            
            # Add buttons to columns
            for j in range(buttons_per_row):
                if i + j < len(faecher):
                    fach = faecher[i + j]
                    # If this is the newly created fach, display success message
                    if st.session_state.get('last_created_fach') == fach:
                        st.success(f"Fach '{st.session_state.last_created_fach}' wurde angelegt!")
                        # Clear the last_created_fach so message doesn't show again on next refresh
                        st.session_state.last_created_fach = None
                    
                    # Initialize session state for selected fach if not present
                    if 'selected_fach' not in st.session_state:
                        st.session_state.selected_fach = faecher[0]
                    
                    # Create button with primary/secondary state based on selection
                    is_selected = st.session_state.selected_fach == fach
                    button_type = "primary" if is_selected else "secondary"
                    
                    if cols[j].button(fach, key=f"fach_btn_{fach}", type = button_type, use_container_width=True):
                        st.session_state.selected_fach = fach
                        st.rerun()
        
        # Use the selected fach from session state
        selected_fach = st.session_state.selected_fach
    else:
        st.warning("Noch keine Fächer vorhanden.")
    
    # Delete Fach button
    if faecher and 'selected_fach' in locals():
        if st.button("Fach löschen", type="tertiary", icon=":material/delete:"):
            delete_fach(selected_fach)
            faecher = get_all_faecher()
            st.rerun()

    # Now continue with the rest of the content, but only if we have fächer
    if faecher and 'selected_fach' in locals():
        # ------------------------------
        # Display Fach Contents and PDF Upload vertically
        # ------------------------------
        st.markdown("<br>", unsafe_allow_html=True)  # Add vertical spacing
        # Display Fach Contents (PDFs)
        st.markdown("#### Hochgeladene PDFs")

        uploaded_files_resp = supabase.storage.from_(bucket_name).list(f"{selected_fach}/uploads/")
        uploaded_files = [file["name"] for file in uploaded_files_resp if file["name"] != "placeholder.txt"]

        if uploaded_files:
            col1, col2 = st.columns([0.8, 0.2])
                        
            # Add a selectbox to choose an already uploaded file
            selected_existing_file = st.selectbox(
                "Bereits hochgeladene PDF auswählen:",
                options=[""] + uploaded_files,
                index=0,
                key="existing_file_select"
            )

            # Only update session state and rerun if the selection has changed.
            if selected_existing_file and st.session_state.get("uploaded_pdf") != selected_existing_file:
                st.session_state.uploaded_pdf = selected_existing_file
                st.session_state.selected_file_path = f"supabase://{bucket_name}/{selected_fach}/uploads/{selected_existing_file}"
                st.rerun()  # Rerun to update the interface
            
            # Display the list of uploaded files
            for f in uploaded_files:
                col1, col2 = st.columns([0.8, 0.2])
                col1.markdown(f"- {f}")
                if col2.button("Dokument löschen", key=f"del_{f}", type="tertiary"):
                    delete_document(selected_fach, f)
                    st.rerun()
        else:
            st.info("Noch keine PDFs hochgeladen.")


        # PDF Upload for the selected Fach
        # Initialize a session state variable to track uploaded files
        if "uploaded_files_tracker" not in st.session_state:
            st.session_state.uploaded_files_tracker = []
            
        uploaded_pdf = st.file_uploader("PDF Upload", type="pdf")
        
        st.markdown("---")  # Add a divider for visual separation

        # ------------------------------
        # PDF Preview and processing 
        # ------------------------------
        if uploaded_pdf is not None or 'uploaded_pdf' in st.session_state:
            # Define storage path and file path
            upload_path = Path("data") / selected_fach / "uploads"
            
            # Determine which file to use
            if uploaded_pdf is not None:
                # New upload case
                upload_file_path = upload_path / uploaded_pdf.name
                file_name = uploaded_pdf.name
                
                if uploaded_pdf is not None:
                    # Only upload if this file hasn't been processed already
                    if st.session_state.get('uploaded_pdf') != uploaded_pdf.name:
                        file_name = uploaded_pdf.name
                        supabase.storage.from_(bucket_name).upload(f"{selected_fach}/uploads/{file_name}", bytes(uploaded_pdf.getbuffer()))
                        st.success(f"Datei '{file_name}' wurde in Supabase gespeichert im Fach '{selected_fach}'")
                        st.session_state.uploaded_pdf = file_name
                        st.session_state.selected_file_path = f"supabase://{bucket_name}/{selected_fach}/uploads/{file_name}"
                        st.rerun()


            else:
                # Selected existing file case
                file_name = st.session_state.uploaded_pdf
                upload_file_path = st.session_state.selected_file_path
            


            # ------------------------------
            # Flashcard creation section
            # ------------------------------
            st.subheader("Karteikarten erstellen / Mindmap generieren")

            # Store selected pages for image recognition in session state if not already there
            if 'image_recognition_pages' not in st.session_state:
                st.session_state.image_recognition_pages = {}

            # Re-download PDF bytes for processing instead of using a local file path:
            if "uploaded_pdf" in st.session_state:
                file_name = st.session_state.uploaded_pdf
            else:
                # Fallback: List files and choose the newest file
                uploaded_files_resp = supabase.storage.from_(bucket_name).list(f"{selected_fach}/uploads/")
                files = [f for f in uploaded_files_resp if f["name"] != "placeholder.txt"]
                if files:
                    newest_file = sorted(files, key=lambda x: x.get("created_at", ""), reverse=True)[0]
                    file_name = newest_file["name"]
                else:
                    st.error("No PDF available for processing.")
                    st.stop()

            # Download the PDF bytes from Supabase
            download_response = supabase.storage.from_(bucket_name).download(f"{selected_fach}/uploads/{file_name}")
            pdf_bytes = download_response if isinstance(download_response, bytes) else download_response.content

            # Open the PDF from the in-memory bytes
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            page_count = doc.page_count


            # Store excluded pages in session state if not already there
            if 'excluded_pages' not in st.session_state:
                st.session_state.excluded_pages = {}

            # Multi-select for pages to exclude completely
            excluded_pages = st.multiselect(
                "Seiten komplett ausschließen (werden nicht in Lernkarten oder Mindmap verwendet):",
                options=list(range(1, page_count + 1)),
                default=st.session_state.excluded_pages.get(file_name, []),
                key=f"exclude_select_{file_name}"
            )
            # Save the exclusion selection in session state
            st.session_state.excluded_pages[file_name] = excluded_pages

            # Capture the multiselect value in a local variable (do not set a key to avoid auto-updating session state)
            temp_selected_pages = st.multiselect(
                "Seiten für Bilderkennung (optional):",
                options=list(range(1, page_count + 1)),
                default=st.session_state.image_recognition_pages.get(file_name, [])
            )



            # Combined flashcard and mindmap creation (replace the separate create_flashcards and mindmap_btn blocks)

            # Let the user enter a deck name if not already provided.
            if "deck_name" not in st.session_state:
                st.session_state.deck_name = ""
            st.session_state.deck_name = st.text_input("Bitte geben Sie den Namen des Anki-Decks ein:", value=st.session_state.deck_name, key="anki_deck_name")

            if st.button("Lernkarten und Mindmap erstellen", key="create_all", use_container_width=True, icon=":material/article:"):
                st.session_state.image_recognition_pages[file_name] = temp_selected_pages
                with st.spinner("Erstelle Lernkarten und Mindmap..."):
                    # ---------- Step 1: Generate Flashcards ----------
                    existing_flashcards = get_flashcards(selected_fach) or []
                    # Filter out flashcards coming from the currently processed document if needed
                    merged_flashcards = [card for card in existing_flashcards if card.get("upload", "Unbekannt") != file_name]
                    new_flashcards = []
                    progress_bar = st.progress(0)
                    
                    for page_num in range(doc.page_count):
                        page = doc[page_num]
                        page_num_human = page_num + 1
                        if page_num_human in st.session_state.excluded_pages.get(file_name, []):
                            progress_bar.progress((page_num + 1) / doc.page_count)
                            continue
                        
                        try:
                            # For pages flagged for image recognition:
                            if page_num_human in st.session_state.image_recognition_pages.get(file_name, []):
                                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
                                base64_image = base64.b64encode(pix.tobytes()).decode('utf-8')
                                gpt_output = analyze_image_for_flashcard_base64(base64_image, file_name, page_number=page_num_human)
                                try:
                                    flashcard = json.loads(gpt_output)
                                    if "priority" not in flashcard:
                                        flashcard["priority"] = 2
                                    flashcard["image_base64"] = base64_image  
                                    new_flashcards.append(flashcard)
                                except json.JSONDecodeError as e:
                                    st.error(f"Fehler beim Parsen der JSON-Antwort für Bild auf Seite {page_num_human}: {str(e)}")
                                    st.code(gpt_output, language="json")
                            else:
                                page_text = page.get_text()
                                if page_text.strip():
                                    gpt_output = generate_card_from_text(page_text, file_name, page_number=page_num_human)
                                    try:
                                        flashcard = json.loads(gpt_output)
                                        if "priority" not in flashcard:
                                            flashcard["priority"] = 2
                                        new_flashcards.append(flashcard)
                                    except json.JSONDecodeError as e:
                                        st.error(f"Fehler beim Parsen der JSON-Antwort für Text auf Seite {page_num_human}: {str(e)}")
                                        st.code(gpt_output, language="json")
                                        
                            progress_bar.progress((page_num + 1) / doc.page_count)
                        except Exception as e:
                            st.error(f"Fehler bei Seite {page_num_human}: {str(e)}")
                    
                    # Merge the new flashcards with existing ones.
                    merged_flashcards.extend(new_flashcards)
                    
                    # ---------- Step 2: Generate the Mindmap ----------
                    try:
                        import io
                        from pathlib import Path
                        pdf_stream = io.BytesIO(pdf_bytes)
                        content = extract_content_from_pdf(
                            pdf_stream, 
                            image_pages=st.session_state.image_recognition_pages.get(file_name, []),
                            excluded_pages=st.session_state.excluded_pages.get(file_name, [])
                        )
                        full_text = content["text"]
                        mindmap_json = generate_mindmap_from_text(full_text, file_name)
                        mindmap_data = json.loads(mindmap_json)
                        
                        from pyvis.network import Network
                        net = Network(height="600px", width="100%", directed=True, notebook=False)
                        for node in mindmap_data["nodes"]:
                            net.add_node(node, label=node)
                        for edge in mindmap_data["edges"]:
                            net.add_edge(edge[0], edge[1])
                        
                        mindmap_html = net.generate_html()
                        
                        # Optionally, upload the mindmap HTML to Supabase.
                        document_title = Path(file_name).stem
                        mindmap_filename = f"{document_title}_mindmap.html"
                        supabase.storage.from_(bucket_name).upload(
                            f"{selected_fach}/mindmaps/{mindmap_filename}", 
                            mindmap_html.encode("utf-8")
                        )
                        st.success("✅ Mindmap wurde erstellt und hochgeladen!")
                        
                        # ---------- Step 3: Create a Mindmap Flashcard ----------
                        mindmap_flashcard = {
                            "question": f"Mindmap für {file_name}",
                            "answer": f"Mindmap verfügbar: <a href='{mindmap_filename}'>Öffne Mindmap</a>",
                            "mindmap": True
                        }
                        merged_flashcards.append(mindmap_flashcard)
                        
                        # Optionally update flashcards in your backend:
                        update_flashcards(selected_fach, merged_flashcards)
                    except Exception as e:
                        st.error(f"❌ Fehler beim Erstellen der Mindmap: {str(e)}")
                    
                    # ---------- Step 4: Generate the APKG File ----------
                    if st.session_state.deck_name:
                        apkg_bytes = generate_anki_package(st.session_state.deck_name, merged_flashcards)
                        st.download_button(
                            label="Download Anki Deck (.apkg)",
                            data=apkg_bytes,
                            file_name=f"{st.session_state.deck_name}_flashcards.apkg",
                            mime="application/octet-stream"
                        )
                    else:
                        st.warning("Bitte geben Sie einen Namen für das Anki-Deck ein!")


                        

elif view_mode == "Learning Studio":
    faecher = get_all_faecher()
    if not faecher:
        st.warning("Bitte erstelle zuerst ein Fach im Creator Studio.")
    else:
        st.markdown("---")  # Add a divider for visual separation
        
        # Replace dropdown with grid of buttons
        st.markdown("#### Fachauswahl")
        
        # Initialize session state for selected fach if not present
        if 'learn_selected_fach' not in st.session_state:
            st.session_state.learn_selected_fach = faecher[0]
            
        # Calculate number of buttons per row (adjust as needed)
        buttons_per_row = 3
        
        # Split faecher into rows
        for i in range(0, len(faecher), buttons_per_row):
            # Create a row of columns
            cols = st.columns(buttons_per_row)
            
            # Add buttons to columns
            for j in range(buttons_per_row):
                if i + j < len(faecher):
                    fach = faecher[i + j]
                    
                    # Create button with primary/secondary state based on selection
                    is_selected = st.session_state.learn_selected_fach == fach
                    button_type = "primary" if is_selected else "secondary"
                    
                    if cols[j].button(fach, key=f"learn_fach_btn_{fach}", type=button_type, use_container_width=True):
                        st.session_state.learn_selected_fach = fach
                        st.rerun()
        
        # Use the selected fach from session state
        selected_fach = st.session_state.learn_selected_fach

        if selected_fach:
            # Load all flashcards for the selected Fach
            flashcards_all = get_flashcards(selected_fach)
            
            # --- Session State Initialization for Learning ---
            if "current_card_index" not in st.session_state:
                st.session_state.current_card_index = 0
            if "revealed" not in st.session_state:
                st.session_state.revealed = False
            if "editing_flashcard" not in st.session_state:
                st.session_state.editing_flashcard = False
            # Initialize last shown index tracking
            if 'last_shown_index' not in st.session_state:
                st.session_state.last_shown_index = -1
            # Store the currently selected fach to detect changes
            if 'learn_selected_fach' not in st.session_state:
                st.session_state.learn_selected_fach = selected_fach
            if 'learn_selected_upload' not in st.session_state:
                st.session_state.learn_selected_upload = None

            # Add some vertical spacing for better visual separation
            st.markdown("<br>", unsafe_allow_html=True)

            # Get unique upload filenames from flashcards
            upload_files = sorted(list(set(card.get("upload", "Unbekannt") for card in flashcards_all)))

            # Also check for mindmaps without cards using Supabase storage
            try:
                mindmap_files_resp = supabase.storage.from_(bucket_name).list(f"{selected_fach}/mindmaps/")
            except Exception as e:
                mindmap_files_resp = []

            if mindmap_files_resp:
                mindmap_basenames = []
                for file in mindmap_files_resp:
                    # Skip placeholders if any exist
                    if file.get("name") == "placeholder.txt":
                        continue
                    # Convert mindmap filename from "document_mindmap.html" to "document.pdf"
                    base_name = file["name"].replace("_mindmap.html", ".pdf")
                    mindmap_basenames.append(base_name)
                
                # Add mindmap files to the upload files list if they don't already exist
                for basename in mindmap_basenames:
                    if basename not in upload_files:
                        upload_files.append(basename)
                
                # Resort the list after adding new files
                upload_files = sorted(upload_files)

            if not upload_files:
                st.warning("Keine Lernkarten oder Mindmaps in diesem Fach gefunden.")
            else:
                selected_upload = st.selectbox("Wähle einen Upload zum Lernen:", upload_files, key="learn_upload_select")

                if selected_upload:
                    # Determine the expected mindmap file name from the selected PDF upload
                    mindmap_filename = f"{selected_upload.split('.')[0]}_mindmap.html"
                    # Build the file path in Supabase: <selected_fach>/mindmaps/<mindmap_filename>
                    mindmap_file_path = f"{selected_fach}/mindmaps/{mindmap_filename}"
                    
                    try:
                        # Attempt to download the mindmap HTML from Supabase
                        download_response = supabase.storage.from_(bucket_name).download(mindmap_file_path)
                        # If the download_response is bytes, decode it; else check for a .content attribute
                        if isinstance(download_response, bytes):
                            mindmap_html = download_response.decode("utf-8")
                        else:
                            mindmap_html = download_response.content.decode("utf-8")
                        
                        st.subheader("Mindmap")
                        components.html(mindmap_html, height=600)
                    except Exception as e:
                        st.info("Keine Mindmap für dieses Dokument vorhanden. Erstelle eine im Creator Studio.")


                # --- Reset state if Fach or Upload changes ---
                fach_changed = st.session_state.learn_selected_fach != selected_fach
                upload_changed = st.session_state.learn_selected_upload != selected_upload

                if fach_changed or upload_changed:
                    st.session_state.revealed = False
                    st.session_state.editing_flashcard = False
                    st.session_state.last_shown_index = -1 # Reset last shown index
                    st.session_state.learn_selected_fach = selected_fach
                    st.session_state.learn_selected_upload = selected_upload
                    # Select the first card for the new selection using the algorithm
                    cards_for_selection = [card for card in flashcards_all if card.get("upload", "Unbekannt") == selected_upload]
                    st.session_state.current_card_index = select_next_card(cards_for_selection)
                    # Need to rerun to apply the new index immediately after selection changes
                    st.rerun()


                # Filter cards based on selected upload
                # Sort cards by page number (if available) or keep original order
                cards_for_selected_upload = [card for card in flashcards_all if card.get("upload", "Unbekannt") == selected_upload]
                
                # Sort cards by page number
                def get_page_number(card):
                    images = card.get('images', [])
                    if images and len(images) > 0:
                        return images[0].get('page', float('inf'))  # Use infinity for cards without page number
                    return float('inf')  # Cards without images come last
                
                cards_to_learn = sorted(cards_for_selected_upload, key=get_page_number)

                if not cards_to_learn:
                    st.warning(f"Keine Lernkarten für den Upload '{selected_upload}' gefunden.")
                    st.stop() # Stop execution if no cards

                # --- Ensure current_card_index is valid ---
                if st.session_state.current_card_index >= len(cards_to_learn):
                     # If index is out of bounds (e.g., after deletion), select a new card
                    st.session_state.current_card_index = select_next_card(cards_to_learn)
                    # Handle the edge case where cards_to_learn might become empty after deletion
                    if not cards_to_learn:
                        st.warning("Alle Karten für diesen Upload wurden gelöscht oder es gibt keine Karten mehr.")
                        st.stop()

                # --- Always Show Sidebar with Cards ---
                st.sidebar.markdown("##  Alle Karten")

                
                # Display each card as a clickable button
                for idx, card in enumerate(cards_to_learn):
                    # Get page number from images if available
                    page_info = card['page']
                    page_num = f"{page_info}  " if page_info else ""
                    
                    # Use full question text (no truncation)
                    question_text = f"{page_num}{card['question']}"
                    
                    # Get the priority and set the appropriate CSS class
                    priority = card.get('priority', 1)  # Default to medium priority if not set
                    priority_class = f"priority-{priority}"
                    
                    # Create the button with custom styling
                    if st.sidebar.button(
                        question_text,
                        key=f"card_btn_{idx}",
                        use_container_width=True,
                        help=f"Priority: {priority}",
                        type="tertiary"
                    ):
                        st.session_state.current_card_index = idx
                        st.session_state.revealed = False
                        st.rerun()

                # --- Display Current Flashcard ---
                current_card = cards_to_learn[st.session_state.current_card_index]

                # Create a two-column layout with control panel (1/5) and flashcard (4/5) 
                control_col, card_col = st.columns([1, 4])

                # Control panel on the left (1/5 width)
                with control_col:
                    # Add class for styling the control buttons
                    
                    st.markdown("### Steuerung")

                    # Button to flip the card - update to toggle instead of disappearing
                    if st.button("Umdrehen", key="flip_button", icon=":material/autorenew:", type="tertiary"):
                        st.session_state.revealed = not st.session_state.revealed
                        st.rerun() # Rerun to update revealed state immediately

                    # Edit and delete buttons
                    if st.button("Bearbeiten", key="edit_flashcard", icon=":material/draw:", type="tertiary"):
                        st.session_state.editing_flashcard = True
                        st.rerun() # Rerun to switch to edit mode

                    if st.button("Löschen", key="delete_flashcard", icon=":material/delete:", type="tertiary"):
                        # Find the index in the original list to remove
                        original_index_to_delete = -1
                        for idx, card in enumerate(flashcards_all):
                            if card.get("upload", "Unbekannt") == selected_upload and card["question"] == current_card["question"] and card["answer"] == current_card["answer"]:
                                original_index_to_delete = idx
                                break

                        if original_index_to_delete != -1:
                            del flashcards_all[original_index_to_delete]
                            update_flashcards(selected_fach, flashcards_all)
                            st.success("Flashcard gelöscht!")

                            # Immediately select the next card using the algorithm
                            # Need to get the updated list of cards for the current selection
                            updated_cards_to_learn = [card for card in flashcards_all if card.get("upload", "Unbekannt") == selected_upload]

                            st.session_state.revealed = False
                            st.session_state.editing_flashcard = False # Ensure not in edit mode
                            # Select next card using the algorithm on the remaining cards
                            st.session_state.current_card_index = select_next_card(updated_cards_to_learn)
                            # No need to update last_shown_index here, select_next_card does it

                            st.rerun()
                        else:
                            st.error("Karte zum Löschen nicht gefunden.")

                    # Flashcard rating buttons (only when answer is revealed)
                    if st.session_state.revealed and not st.session_state.editing_flashcard:
                        st.markdown("### Bewertung")

                        rating_changed = False # Flag to check if rating happened

                        if st.button("Schwer", key="p1", icon=":material/looks_one:", type="tertiary"):
                            current_card["priority"] = 1
                            rating_changed = True

                        if st.button("Mittel", key="p2", icon=":material/looks_two:", type="tertiary"):
                            current_card["priority"] = 2
                            rating_changed = True

                        if st.button("Leicht", key="p3", icon=":material/looks_3:", type="tertiary"):
                            current_card["priority"] = 3
                            rating_changed = True

                        if rating_changed:
                            # Update the flashcard in the flashcards_all list immediately
                            # Find the correct card in the main list to update its priority
                            for idx, card in enumerate(flashcards_all):
                                # Match based on upload, question, and answer for better uniqueness
                                if card.get("upload", "Unbekannt") == selected_upload and card["question"] == current_card["question"] and card["answer"] == current_card["answer"]:
                                    flashcards_all[idx] = current_card
                                    break # Assume unique enough for now

                            update_flashcards(selected_fach, flashcards_all)
                            st.session_state.revealed = False
                            # Select next card using the algorithm
                            st.session_state.current_card_index = select_next_card(cards_to_learn)
                            # Rerun to show the next card
                            st.rerun()

                    # Display document info
                    st.markdown("### Info")
                    st.markdown(f"Datei: *{current_card.get('upload', 'Unbekannt')}*")
                    page_info = current_card.get('images', [])
                    if page_info:
                         st.markdown(f"Seite: {page_info[0].get('page', 'N/A')}")
                    st.markdown(f"Priorität: {current_card.get('priority', 'N/A')}")
                    # Display card count / progress
                    st.markdown(f"Karten: {st.session_state.current_card_index + 1} / {len(cards_to_learn)}")

                    # Close the control-column div
                    st.markdown('</div>', unsafe_allow_html=True)

                # Flashcard display on the right (4/5 width)
                with card_col:
                    if not st.session_state.editing_flashcard:
                        # Old code used open() on a local file; remove that.
                        images = current_card.get('images', [])
                        img_info = images[0] if images else None

                        image_html = ""
                        if st.session_state.revealed and img_info:
                            try:
                                # Check if the flashcard contains the base64 image data
                                base64_img = img_info.get("base64")
                                if base64_img:
                                    # Construct a data URL that Streamlit can render
                                    data_url = f"data:image/png;base64,{base64_img}"
                                    image_html = (
                                        f'<div class="flashcard-image" style="margin-top: 20px;">'
                                        f'<img src="{data_url}" style="max-width: 100%;">'
                                        f'<p style="text-align: center; font-style: italic;">Kontext (Seite {img_info.get("page", "N/A")})</p>'
                                        f'</div>'
                                    )
                                else:
                                    image_html = "<div class='flashcard-image' style='margin-top: 20px;'>Kein Bild vorhanden.</div>"
                            except Exception as e:
                                st.error(f"Error displaying image: {e}")

                        st.markdown(f"""
                        <div class="flashcard" style="background-color: white; color: black; padding: 20px; border-radius: 8px;">
                            <div class="flashcard-question">
                                <h3>Frage:</h3>
                                <p>{current_card['question']}</p>
                            </div>
                            {"<div class='flashcard-answer'><h3>Antwort:</h3>" + "".join(f"<li>{ans}</li>" for ans in current_card["answer"]) + "</div>" if st.session_state.revealed else ""}
                            {image_html}
                        </div>
                        """, unsafe_allow_html=True)


                    else:
                        # Editing mode: show a form to edit the flashcard
                        st.markdown("### Flashcard bearbeiten")
                        # Use unique keys for edit mode widgets based on current card index or question to avoid state issues
                        edit_key_suffix = f"_{st.session_state.current_card_index}"
                        new_question = st.text_input("Frage", value=current_card["question"], key=f"edit_q{edit_key_suffix}")
                        # Join the answer list into a multiline string
                        new_answer_str = "\n".join(current_card["answer"])
                        new_answer = st.text_area("Antwort (jede Zeile ein Punkt)", value=new_answer_str, height=150, key=f"edit_a{edit_key_suffix}")

                        col_save, col_cancel = st.columns(2)
                        
                        if col_save.button("Speichern", key=f"save_edit{edit_key_suffix}", type="tertiary"):
                            updated_flashcard = current_card.copy()
                            updated_flashcard["question"] = new_question
                            updated_flashcard["answer"] = [line.strip() for line in new_answer.split("\n") if line.strip()]

                            # Use object identity to locate the original card in flashcards_all
                            original_index_to_update = None
                            for idx, card in enumerate(flashcards_all):
                                if card is current_card:
                                    original_index_to_update = idx
                                    break

                            if original_index_to_update is not None:
                                flashcards_all[original_index_to_update] = updated_flashcard
                                update_flashcards(selected_fach, flashcards_all)
                                st.success("Flashcard aktualisiert!")
                                st.session_state.editing_flashcard = False
                                st.session_state.revealed = False  # Hide answer after saving edit
                                st.rerun()
                            else:
                                st.error("Originalkarte zum Aktualisieren nicht gefunden.")


                        if col_cancel.button("Abbrechen", key=f"cancel_edit{edit_key_suffix}", type="tertiary"):
                            st.session_state.editing_flashcard = False
                            try:
                                st.rerun()
                            except AttributeError:
                                st.warning("st.rerun() nicht verfügbar. Bitte aktualisieren Sie Streamlit.")
