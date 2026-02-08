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
try:
    import backend.gpt_interface as gpt_interface
except Exception as import_error:
    gpt_interface = None
    gpt_interface_import_error = str(import_error)
else:
    gpt_interface_import_error = None
from backend.flashcard_manager import save_flashcard, get_flashcards, update_flashcards, delete_document
from backend.storage_utils import get_image_as_data_url
from supabase import create_client
import urllib.parse
import time
import re
import unicodedata


def _to_storage_safe_component(value: str) -> str:
    """Convert arbitrary names (e.g., with umlauts) to Supabase-safe key components."""
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"\s+", "_", value)
    value = re.sub(r"[^A-Za-z0-9._-]", "_", value)
    return value.strip("._") or "file"


generate_mindmap_from_text = getattr(gpt_interface, "generate_mindmap_from_text", None) if gpt_interface else None
analyze_image_for_flashcard_base64 = getattr(gpt_interface, "analyze_image_for_flashcard_base64", None) if gpt_interface else None


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
        return 0  # Or handle appropriately

    indices = list(range(len(cards)))
    weights = []
    for card in cards:
        priority = card.get("priority", 2)  # Default to medium priority if missing
        if priority == 1:  # Schwer
            weights.append(5)
        elif priority == 2:  # Mittel
            weights.append(3)
        else:  # Leicht (Priority 1 or other)
            weights.append(1)

    # Avoid showing the same card twice in a row if possible
    last_index = st.session_state.get('last_shown_index', -1)
    chosen_index = -1

    # Try up to 10 times to get a different card than the last one
    for _ in range(10):
        if sum(weights) == 0:  # Handle case where all weights might be zero
            chosen_index = random.choice(indices) if indices else 0
            break
        chosen_index = random.choices(indices, weights=weights, k=1)[0]
        if len(cards) <= 1 or chosen_index != last_index:
            break
    else:
        # Fallback if it keeps picking the same one
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
    Generate an Anki package (.apkg) from flashcards.
    For flashcards with an 'image_base64', the image is saved and embedded.
    For flashcards with 'mindmap': True, the mindmap HTML is embedded directly as a
    data URL using an <iframe>.
    """
    # Define a minimal Anki model.
    my_model = genanki.Model(
        1607392319,  # Unique model ID – change if necessary.
        'Minimal Model',
        fields=[{'name': 'Question'}, {'name': 'Answer'}],
        templates=[{
            'name': 'Card 1',
            'qfmt': '{{Question}}',
            'afmt': '{{FrontSide}}<hr>{{Answer}}',
        }],
        css="""
/* Minimal styling */
body { font-family: sans-serif; }
"""
    )

    deck = genanki.Deck(random.randint(1000000, 9999999), deck_name)
    media_files = []  # This list will hold media filenames for images.

    for idx, card in enumerate(flashcards):
        question = card.get("question", "")
        answer_raw = card.get("answer", "")
        if isinstance(answer_raw, list):
            answer_text = "<br>".join(answer_raw)
        else:
            answer_text = answer_raw

        # Handle image flashcards: save image from base64 and embed it.
        if "image_base64" in card:
            image_filename = f"flashcard_{idx}_image.png"
            save_image_from_base64(card["image_base64"], image_filename)
            media_files.append(image_filename)
            answer_text += f"<br><img src='{image_filename}' />"

        # For mindmap flashcards, embed the HTML directly as a data URL.
        if card.get("mindmap", False):
            # Convert the entire mindmap HTML content into a base64-encoded data URL.
            encoded_html = base64.b64encode(answer_text.encode("utf-8")).decode("utf-8")
            answer_text = (
                f"<iframe src='data:text/html;base64,{encoded_html}' "
                f"width='100%' height='600px' frameborder='0'></iframe>"
            )

        note = genanki.Note(
            model=my_model,
            fields=[question, answer_text]
        )
        deck.add_note(note)

    package = genanki.Package(deck, media_files=media_files)
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
            # Define the function to process new Fach input
            def process_fach_input():
                if st.session_state.modal_fach_input.strip():
                    name = st.session_state.modal_fach_input.strip()
                    if create_fach(name):
                        st.session_state.last_created_fach = name
                        st.session_state.show_fach_modal = False
                        st.session_state.modal_fach_input = ""

            # Add the input field
            st.text_input(
                "Name des neuen Fachs:",
                key="modal_fach_input",
                on_change=lambda: process_fach_input()
            )

    # Select existing Fach
    faecher = get_all_faecher()
    if faecher:
        st.markdown("#### Fachauswahl")

        buttons_per_row = 3

        for i in range(0, len(faecher), buttons_per_row):
            cols = st.columns(buttons_per_row)

            for j in range(buttons_per_row):
                if i + j < len(faecher):
                    fach = faecher[i + j]

                    if st.session_state.get('last_created_fach') == fach:
                        st.success(f"Fach '{st.session_state.last_created_fach}' wurde angelegt!")
                        st.session_state.last_created_fach = None

                    if 'selected_fach' not in st.session_state:
                        st.session_state.selected_fach = faecher[0]

                    is_selected = st.session_state.selected_fach == fach
                    button_type = "primary" if is_selected else "secondary"

                    if cols[j].button(fach, key=f"fach_btn_{fach}", type=button_type, use_container_width=True):
                        st.session_state.selected_fach = fach
                        st.rerun()

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
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("#### Hochgeladene PDFs")

        safe_fach = _to_storage_safe_component(selected_fach)
        uploaded_files_resp = supabase.storage.from_(bucket_name).list(f"{safe_fach}/uploads/")
        uploaded_files = [file["name"] for file in uploaded_files_resp if file["name"] != "placeholder.txt"]

        if uploaded_files:
            col1, col2 = st.columns([0.8, 0.2])

            selected_existing_file = st.selectbox(
                "Bereits hochgeladene PDF auswählen:",
                options=[""] + uploaded_files,
                index=0,
                key="existing_file_select"
            )

            if selected_existing_file and st.session_state.get("uploaded_pdf") != selected_existing_file:
                st.session_state.uploaded_pdf = selected_existing_file
                safe_fach = _to_storage_safe_component(selected_fach)
                st.session_state.selected_file_path = f"supabase://{bucket_name}/{safe_fach}/uploads/{selected_existing_file}"
                st.session_state.uploaded_pdf_storage_name = selected_existing_file
                st.rerun()

            for f in uploaded_files:
                col1, col2 = st.columns([0.8, 0.2])
                col1.markdown(f"- {f}")
                if col2.button("Dokument löschen", key=f"del_{f}", type="tertiary"):
                    delete_document(selected_fach, f)
                    st.rerun()
        else:
            st.info("Noch keine PDFs hochgeladen.")

        if "uploaded_files_tracker" not in st.session_state:
            st.session_state.uploaded_files_tracker = []

        uploaded_pdf = st.file_uploader("PDF Upload", type="pdf")

        st.markdown("---")

        if uploaded_pdf is not None or 'uploaded_pdf' in st.session_state:
            upload_path = Path("data") / selected_fach / "uploads"

            if uploaded_pdf is not None:
                upload_file_path = upload_path / uploaded_pdf.name
                file_name = uploaded_pdf.name

                if st.session_state.get('uploaded_pdf') != uploaded_pdf.name:
                    file_name = uploaded_pdf.name
                    safe_fach = _to_storage_safe_component(selected_fach)
                    safe_file_name = _to_storage_safe_component(file_name)
                    storage_file_path = f"{safe_fach}/uploads/{safe_file_name}"
                    supabase.storage.from_(bucket_name).upload(
                        storage_file_path,
                        bytes(uploaded_pdf.getbuffer()),
                        {"upsert": "true"}
                    )
                    st.success(f"Datei '{file_name}' wurde in Supabase gespeichert im Fach '{selected_fach}'")
                    st.session_state.uploaded_pdf = file_name
                    st.session_state.uploaded_pdf_storage_name = safe_file_name
                    st.session_state.selected_file_path = f"supabase://{bucket_name}/{storage_file_path}"
                    st.rerun()
            else:
                file_name = st.session_state.uploaded_pdf
                upload_file_path = st.session_state.selected_file_path

            st.subheader("Karteikarten erstellen / Mindmap generieren")

            if "uploaded_pdf" in st.session_state:
                file_name = st.session_state.uploaded_pdf
            else:
                safe_fach = _to_storage_safe_component(selected_fach)
                uploaded_files_resp = supabase.storage.from_(bucket_name).list(f"{safe_fach}/uploads/")
                files = [f for f in uploaded_files_resp if f["name"] != "placeholder.txt"]
                if files:
                    newest_file = sorted(files, key=lambda x: x.get("created_at", ""), reverse=True)[0]
                    file_name = newest_file["name"]
                else:
                    st.error("No PDF available for processing.")
                    st.stop()

            safe_fach = _to_storage_safe_component(selected_fach)
            storage_file_name = st.session_state.get("uploaded_pdf_storage_name", file_name)
            download_response = supabase.storage.from_(bucket_name).download(f"{safe_fach}/uploads/{storage_file_name}")
            pdf_bytes = download_response if isinstance(download_response, bytes) else download_response.content

            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            page_count = doc.page_count

            if 'excluded_pages' not in st.session_state:
                st.session_state.excluded_pages = {}

            temp_excluded_pages = st.multiselect(
                "Seiten komplett ausschließen (werden nicht in Lernkarten oder Mindmap verwendet):",
                options=list(range(1, page_count + 1)),
                default=st.session_state.excluded_pages.get(file_name, []),
                key=f"excluded_pages_{file_name}"
            )

            st.session_state.excluded_pages[file_name] = temp_excluded_pages

            if "deck_name" not in st.session_state:
                st.session_state.deck_name = ""
            st.session_state.deck_name = st.text_input(
                "Bitte geben Sie den Namen des Anki-Decks ein:",
                value=st.session_state.deck_name,
                key="anki_deck_name"
            )

            if st.button("Lernkarten und Mindmap erstellen", key="create_all", use_container_width=True, icon=":material/article:"):
                if analyze_image_for_flashcard_base64 is None or generate_mindmap_from_text is None:
                    details = f" ({gpt_interface_import_error})" if gpt_interface_import_error else ""
                    st.error(f"GPT-Funktionen konnten nicht geladen werden. Bitte prüfe backend/gpt_interface.py und den letzten Deploy.{details}")
                    st.stop()
                with st.spinner("Erstelle Lernkarten und Mindmap..."):
                    # ---------- Step 1: Generate New Flashcards (each page analyzed with BOTH text + image) ----------
                    new_flashcards = []
                    progress_bar = st.progress(0)

                    for page_num in range(doc.page_count):
                        page = doc[page_num]
                        page_num_human = page_num + 1
                        current_progress = ((page_num + 1) / doc.page_count) * 0.5

                        if page_num_human in st.session_state.excluded_pages.get(file_name, []):
                            progress_bar.progress(current_progress)
                            continue

                        try:
                            # Render page image
                            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
                            base64_image = base64.b64encode(pix.tobytes()).decode('utf-8')

                            # Extract page text (same page)
                            page_text = page.get_text("text") or ""

                            # Analyze with BOTH inputs (text + image)
                            gpt_output = analyze_image_for_flashcard_base64(
                                base64_image=base64_image,
                                upload_name=file_name,
                                page_number=page_num_human,
                                page_text=page_text
                            )

                            try:
                                flashcard = json.loads(gpt_output)

                                if "priority" not in flashcard:
                                    flashcard["priority"] = 2

                                # Keep current "image_base64" field for Anki export compatibility
                                flashcard["image_base64"] = base64_image

                                # ALSO store images[] structure for Learning Studio image rendering
                                # (Learning Studio expects: current_card.get('images')[0].get('base64'))
                                flashcard["images"] = [{"page": page_num_human, "base64": base64_image}]

                                # Ensure page key exists for Learning Studio sidebar (your code uses card['page'])
                                flashcard["page"] = page_num_human

                                new_flashcards.append(flashcard)

                            except json.JSONDecodeError as e:
                                st.error(f"Fehler beim Parsen der JSON-Antwort für Seite {page_num_human}: {str(e)}")
                                st.code(gpt_output, language="json")
                            finally:
                                # Pause to prevent rate limiting (your original behavior)
                                time.sleep(20)

                            progress_bar.progress(current_progress)

                        except Exception as e:
                            st.error(f"Fehler bei Seite {page_num_human}: {str(e)}")

                    export_flashcards = new_flashcards.copy()
                    progress_bar.progress(0.5)

                    # ---------- Step 2: Generate the Mindmap ----------
                    try:
                        # Build full text from ALL non-excluded pages (robust; no dependency on pdf_parser)
                        full_text_parts = []
                        for page_num in range(doc.page_count):
                            page_num_human = page_num + 1
                            if page_num_human in st.session_state.excluded_pages.get(file_name, []):
                                continue
                            full_text_parts.append(doc[page_num].get_text("text") or "")
                        full_text = "\n\n".join(full_text_parts)

                        mindmap_json = generate_mindmap_from_text(full_text, file_name)
                        mindmap_data = json.loads(mindmap_json)

                        from pyvis.network import Network
                        net = Network(height="600px", width="100%", directed=True, notebook=False)
                        for node in mindmap_data["nodes"]:
                            net.add_node(node, label=node)
                        for edge in mindmap_data["edges"]:
                            net.add_edge(edge[0], edge[1])

                        mindmap_html = net.generate_html()

                        custom_style = """
<style>
body {
    background-color: #f0f0f0;
    margin: 0;
    padding: 10px;
}
* {
    font-family: 'Calibri', sans-serif;
}
</style>
"""
                        mindmap_html = mindmap_html.replace("</head>", custom_style + "</head>")

                        st.success("✅ Mindmap wurde erstellt!")

                        # ---------- Step 3: Create a Mindmap Flashcard ----------
                        mindmap_flashcard = {
                            "upload": file_name,
                            "question": f"Mindmap für {file_name}",
                            "answer": mindmap_html,
                            "mindmap": True,
                            "page": None,
                            "priority": 2
                        }
                        export_flashcards.append(mindmap_flashcard)

                        update_flashcards(selected_fach, export_flashcards)

                        progress_bar.progress(1.0)

                    except Exception as e:
                        st.error(f"❌ Fehler beim Erstellen der Mindmap: {str(e)}")
                        progress_bar.progress(0.5)

                    # ---------- Step 4: Generate the APKG File ----------
                    if st.session_state.deck_name:
                        apkg_bytes = generate_anki_package(st.session_state.deck_name, export_flashcards)
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
        st.markdown("---")

        st.markdown("#### Fachauswahl")

        if 'learn_selected_fach' not in st.session_state:
            st.session_state.learn_selected_fach = faecher[0]

        buttons_per_row = 3

        for i in range(0, len(faecher), buttons_per_row):
            cols = st.columns(buttons_per_row)

            for j in range(buttons_per_row):
                if i + j < len(faecher):
                    fach = faecher[i + j]

                    is_selected = st.session_state.learn_selected_fach == fach
                    button_type = "primary" if is_selected else "secondary"

                    if cols[j].button(fach, key=f"learn_fach_btn_{fach}", type=button_type, use_container_width=True):
                        st.session_state.learn_selected_fach = fach
                        st.rerun()

        selected_fach = st.session_state.learn_selected_fach

        if selected_fach:
            flashcards_all = get_flashcards(selected_fach)

            if "current_card_index" not in st.session_state:
                st.session_state.current_card_index = 0
            if "revealed" not in st.session_state:
                st.session_state.revealed = False
            if "editing_flashcard" not in st.session_state:
                st.session_state.editing_flashcard = False
            if 'last_shown_index' not in st.session_state:
                st.session_state.last_shown_index = -1
            if 'learn_selected_fach' not in st.session_state:
                st.session_state.learn_selected_fach = selected_fach
            if 'learn_selected_upload' not in st.session_state:
                st.session_state.learn_selected_upload = None

            st.markdown("<br>", unsafe_allow_html=True)

            upload_files = sorted(list(set(card.get("upload", "Unbekannt") for card in flashcards_all)))

            try:
                safe_fach = _to_storage_safe_component(selected_fach)
                mindmap_files_resp = supabase.storage.from_(bucket_name).list(f"{safe_fach}/mindmaps/")
            except Exception:
                mindmap_files_resp = []

            if mindmap_files_resp:
                mindmap_basenames = []
                for file in mindmap_files_resp:
                    if file.get("name") == "placeholder.txt":
                        continue
                    base_name = file["name"].replace("_mindmap.html", ".pdf")
                    mindmap_basenames.append(base_name)

                for basename in mindmap_basenames:
                    if basename not in upload_files:
                        upload_files.append(basename)

                upload_files = sorted(upload_files)

            if not upload_files:
                st.warning("Keine Lernkarten oder Mindmaps in diesem Fach gefunden.")
            else:
                selected_upload = st.selectbox("Wähle einen Upload zum Lernen:", upload_files, key="learn_upload_select")

                if selected_upload:
                    mindmap_filename = f"{selected_upload.split('.')[0]}_mindmap.html"
                    safe_fach = _to_storage_safe_component(selected_fach)
                    mindmap_file_path = f"{safe_fach}/mindmaps/{mindmap_filename}"

                    try:
                        download_response = supabase.storage.from_(bucket_name).download(mindmap_file_path)
                        if isinstance(download_response, bytes):
                            mindmap_html = download_response.decode("utf-8")
                        else:
                            mindmap_html = download_response.content.decode("utf-8")

                        st.subheader("Mindmap")
                        components.html(mindmap_html, height=600)
                    except Exception:
                        st.info("Keine Mindmap für dieses Dokument vorhanden. Erstelle eine im Creator Studio.")

                fach_changed = st.session_state.learn_selected_fach != selected_fach
                upload_changed = st.session_state.learn_selected_upload != selected_upload

                if fach_changed or upload_changed:
                    st.session_state.revealed = False
                    st.session_state.editing_flashcard = False
                    st.session_state.last_shown_index = -1
                    st.session_state.learn_selected_fach = selected_fach
                    st.session_state.learn_selected_upload = selected_upload
                    cards_for_selection = [card for card in flashcards_all if card.get("upload", "Unbekannt") == selected_upload]
                    st.session_state.current_card_index = select_next_card(cards_for_selection)
                    st.rerun()

                cards_for_selected_upload = [card for card in flashcards_all if card.get("upload", "Unbekannt") == selected_upload]

                def get_page_number(card):
                    images = card.get('images', [])
                    if images and len(images) > 0:
                        return images[0].get('page', float('inf'))
                    return float('inf')

                cards_to_learn = sorted(cards_for_selected_upload, key=get_page_number)

                if not cards_to_learn:
                    st.warning(f"Keine Lernkarten für den Upload '{selected_upload}' gefunden.")
                    st.stop()

                if st.session_state.current_card_index >= len(cards_to_learn):
                    st.session_state.current_card_index = select_next_card(cards_to_learn)
                    if not cards_to_learn:
                        st.warning("Alle Karten für diesen Upload wurden gelöscht oder es gibt keine Karten mehr.")
                        st.stop()

                st.sidebar.markdown("##  Alle Karten")

                for idx, card in enumerate(cards_to_learn):
                    page_info = card.get('page')
                    page_num = f"{page_info}  " if page_info else ""
                    question_text = f"{page_num}{card.get('question','')}"
                    priority = card.get('priority', 1)

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

                current_card = cards_to_learn[st.session_state.current_card_index]

                control_col, card_col = st.columns([1, 4])

                with control_col:
                    st.markdown("### Steuerung")

                    if st.button("Umdrehen", key="flip_button", icon=":material/autorenew:", type="tertiary"):
                        st.session_state.revealed = not st.session_state.revealed
                        st.rerun()

                    if st.button("Bearbeiten", key="edit_flashcard", icon=":material/draw:", type="tertiary"):
                        st.session_state.editing_flashcard = True
                        st.rerun()

                    if st.button("Löschen", key="delete_flashcard", icon=":material/delete:", type="tertiary"):
                        original_index_to_delete = -1
                        for idx, card in enumerate(flashcards_all):
                            if card.get("upload", "Unbekannt") == selected_upload and card.get("question") == current_card.get("question") and card.get("answer") == current_card.get("answer"):
                                original_index_to_delete = idx
                                break

                        if original_index_to_delete != -1:
                            del flashcards_all[original_index_to_delete]
                            update_flashcards(selected_fach, flashcards_all)
                            st.success("Flashcard gelöscht!")

                            updated_cards_to_learn = [card for card in flashcards_all if card.get("upload", "Unbekannt") == selected_upload]

                            st.session_state.revealed = False
                            st.session_state.editing_flashcard = False
                            st.session_state.current_card_index = select_next_card(updated_cards_to_learn)
                            st.rerun()
                        else:
                            st.error("Karte zum Löschen nicht gefunden.")

                    if st.session_state.revealed and not st.session_state.editing_flashcard:
                        st.markdown("### Bewertung")

                        rating_changed = False

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
                            for idx, card in enumerate(flashcards_all):
                                if card.get("upload", "Unbekannt") == selected_upload and card.get("question") == current_card.get("question") and card.get("answer") == current_card.get("answer"):
                                    flashcards_all[idx] = current_card
                                    break

                            update_flashcards(selected_fach, flashcards_all)
                            st.session_state.revealed = False
                            st.session_state.current_card_index = select_next_card(cards_to_learn)
                            st.rerun()

                    st.markdown("### Info")
                    st.markdown(f"Datei: *{current_card.get('upload', 'Unbekannt')}*")
                    images_info = current_card.get('images', [])
                    if images_info:
                        st.markdown(f"Seite: {images_info[0].get('page', 'N/A')}")
                    else:
                        if current_card.get('page'):
                            st.markdown(f"Seite: {current_card.get('page')}")
                    st.markdown(f"Priorität: {current_card.get('priority', 'N/A')}")
                    st.markdown(f"Karten: {st.session_state.current_card_index + 1} / {len(cards_to_learn)}")

                with card_col:
                    if not st.session_state.editing_flashcard:
                        images = current_card.get('images', [])
                        img_info = images[0] if images else None

                        image_html = ""
                        if st.session_state.revealed and img_info:
                            try:
                                base64_img = img_info.get("base64")
                                if base64_img:
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

                        answer_list = current_card.get("answer", [])
                        if not isinstance(answer_list, list):
                            answer_list = [str(answer_list)]

                        st.markdown(f"""
                        <div class="flashcard" style="background-color: white; color: black; padding: 20px; border-radius: 8px;">
                            <div class="flashcard-question">
                                <h3>Frage:</h3>
                                <p>{current_card.get('question','')}</p>
                            </div>
                            {"<div class='flashcard-answer'><h3>Antwort:</h3>" + "".join(f"<li>{ans}</li>" for ans in answer_list) + "</div>" if st.session_state.revealed else ""}
                            {image_html}
                        </div>
                        """, unsafe_allow_html=True)

                    else:
                        st.markdown("### Flashcard bearbeiten")
                        edit_key_suffix = f"_{st.session_state.current_card_index}"
                        new_question = st.text_input("Frage", value=current_card.get("question",""), key=f"edit_q{edit_key_suffix}")
                        new_answer_str = "\n".join(current_card.get("answer", [])) if isinstance(current_card.get("answer", []), list) else str(current_card.get("answer",""))
                        new_answer = st.text_area("Antwort (jede Zeile ein Punkt)", value=new_answer_str, height=150, key=f"edit_a{edit_key_suffix}")

                        col_save, col_cancel = st.columns(2)

                        if col_save.button("Speichern", key=f"save_edit{edit_key_suffix}", type="tertiary"):
                            updated_flashcard = current_card.copy()
                            updated_flashcard["question"] = new_question
                            updated_flashcard["answer"] = [line.strip() for line in new_answer.split("\n") if line.strip()]

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
                                st.session_state.revealed = False
                                st.rerun()
                            else:
                                st.error("Originalkarte zum Aktualisieren nicht gefunden.")

                        if col_cancel.button("Abbrechen", key=f"cancel_edit{edit_key_suffix}", type="tertiary"):
                            st.session_state.editing_flashcard = False
                            try:
                                st.rerun()
                            except AttributeError:
                                st.warning("st.rerun() nicht verfügbar. Bitte aktualisieren Sie Streamlit.")
