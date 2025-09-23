import streamlit as st
from firebase_admin import credentials, firestore, initialize_app, _apps
import json
import os
# import dotenv
from datetime import datetime
import pandas as pd
import matplotlib.pyplot as plt
import time
from utils import light_tagger, tag, reverse_tag
import random


# dotenv.load_dotenv()

openai_api_key = os.environ['openai_key']
emotions = ["Happy", "Sad", "Angry", "Neutral", "Surprised", "Fearful", "Disgusted"]


# Initialize Firebase if it hasn't been initialized yet
firebase_secrets = json.loads(os.environ['firebase_credentials'])
if not _apps:
    cred = credentials.Certificate(firebase_secrets)
    initialize_app(cred)

db = firestore.client()

# Function to load the next review item from a batch of 20 random documents
def load_next_text():
    # Fetch a batch of 20 documents where Status is "pending"
    docs = db.collection("stage_four_reviews").where("Status", "==", "pending").limit(20).stream()

    # Convert Firestore documents to a list
    doc_list = [doc for doc in docs]

    # If there are any documents available
    if doc_list:
        # Randomly pick one document
        random_doc = random.choice(doc_list)
        doc_id = random_doc.id
        doc_data = random_doc.to_dict()

        return doc_id, doc_data
    else:
        return None, None

# Function to save the review decision
def save_review(doc_id, review_data):
    review_data["Timestamp"] = datetime.utcnow()  # Add a timestamp to the review
    db.collection("stage_four_reviews").document(doc_id).update(review_data)

# Function to get the count of reviews done by the reviewer
def get_review_count(username):
    docs = db.collection("stage_four_reviews").where("reviewer", "==", username).stream()
    return sum(1 for _ in docs)

# Function to get the history of prompts reviewed by the user
def get_review_history(username, limit):
    docs = db.collection("stage_four_reviews").where("reviewer", "==", username).stream()
    history = []
    for doc in docs:
        data = doc.to_dict()
        if not data.get("pulled", False) and data.get("Timestamp") is not None:  # Filter out documents where "pulled" is True or Timestamp is None
            history.append({
                "doc_id": doc.id,
                "OriginalText": data.get("OriginalText"),
                "CodeSwitchedText": data.get("CodeSwitchedText"),
                "reviewed_text": data.get("reviewed_text"),
                "Status": data.get("Status"),
                "Timestamp": data.get("Timestamp"),
                "language_tags":data.get("language_tags"),
                "emotions": data.get("emotions")
            })
    # Sort history by Timestamp in descending order and limit results
    sorted_history = sorted(history, key=lambda x: x["Timestamp"], reverse=True)
    return sorted_history[:limit]

# Function to update a specific review
def update_review(doc_id, edited_text):
    db.collection("stage_four_reviews").document(doc_id).update({
        "reviewed_text": edited_text,
        "Timestamp": datetime.utcnow(),
        "Status": "edit"
    })

def undo_review(doc_id):
    db.collection("stage_four_reviews").document(doc_id).update({
        "Timestamp": datetime.utcnow(),
        "Status": "pending",
        "reviewer": None
    })

# Function to fetch review data for analytics
def fetch_review_data():
    docs = db.collection("stage_four_reviews").stream()
    data = []
    for doc in docs:
        record = doc.to_dict()
        if not record["pulled"]:
            data.append({
                "reviewer": record.get("reviewer", "unreviewed"),
                "Status": record["Status"]
            })
    data = pd.DataFrame(data)
    data["reviewer"] = data["reviewer"].str.strip()
    return data

def play_audio(file_path):
    """
    Plays an audio file with autoplay enabled.
    
    Parameters:
        file_path (str): Path to the audio file.
    """
    try:
        st.audio(file_path, format="audio/mp3", autoplay=True)
    except FileNotFoundError:
        st.error(f"Error: The file '{file_path}' was not found. Please check the path.")
    except Exception as e:
        st.error(f"An unexpected error occurred: {e}")


# Function to display the sentence with color-coding based on language tag
def display_colored_sentence(word_tags):
    colored_sentence = ""
    
    # Loop through the word-tags and create a color-coded sentence
    for word, tag in word_tags:
        if tag == 'en':
            color = 'blue'  # English - Blue
        else:
            color = 'red'   # Yoruba - Red
        
        # Add the word to the sentence with the appropriate color
        colored_sentence += f'<span style="color: {color};">{word}</span> '

    return(colored_sentence)

# Function to dynamically display buttons below the sentence
def display_buttons(word_tags, num_cols):
    # Create columns for button layout
    cols = st.columns(num_cols)

    # Loop through the word-tags and create a button for each word
    for i, (word, tag) in enumerate(word_tags):
        # Assign color based on the language tag
        if tag == 'en':  # English
            color = 'blue'
        else:  # Yoruba
            color = 'red'
        
        # Create button text with color or label (optional: add icons, tooltips)
        button_text = f"{word}"
        button_key = f"button_{i}"
        
        # Create the button in the corresponding column
        col = cols[i % num_cols]  # Cycle through columns for each word
        with col:
            button = st.button(button_text, key=button_key)

            # When the button is clicked, toggle the word's tag
            if button:
                toggle_tag(i)  # This function will toggle between 'en' and 'yo'

# Function to toggle language tag when a word is clicked
def toggle_tag(word_index):
    # Retrieve the current tag from the session state
    current_word, current_tag = st.session_state.word_tags[word_index]
    
    # Toggle the tag between 'en' and 'yo'
    new_tag = 'en' if current_tag == 'yo' else 'yo'
    
    # Update the word tag in session state
    st.session_state.word_tags[word_index] = (current_word, new_tag)
    st.rerun()
    # st.write(f"Tag for '{current_word}' changed to {new_tag}")  # Optional: Show immediate feedback

# Function to update the reflected text when the text area changes
def update_reflection():
    st.session_state.text_data["CodeSwitchedText"] = st.session_state.edited_text
    st.session_state.word_tags = None

# Streamlit App Layout
if "username" not in st.session_state:
    st.session_state.username = None

# Ensure "upload_started" and "processed_file_path" exist in session_state
if "upload_started" not in st.session_state:
    st.session_state.upload_started = False
if "processed_file_path" not in st.session_state:
    st.session_state.processed_file_path = None
if "dataframe" not in st.session_state:
    st.session_state.dataframe = None
if "new_text" not in st.session_state:
    st.session_state.new_text = None
if "new_emotions" not in st.session_state:
    st.session_state.new_emotions = None
if "new_tags" not in st.session_state:
    st.session_state.new_tags = None

if "word_tags" not in st.session_state:
    st.session_state.word_tags = None

if "text_data" not in st.session_state:
    st.session_state.text_data = None

if "doc_id" not in st.session_state:
    st.session_state.doc_id = None

if "max_num_cols" not in st.session_state:
    st.session_state.max_num_cols = 2


if st.session_state.username is None:
    # Prompt user to enter their name
    st.title("Welcome to the Senior Reviewer App")
    st.write("Please enter your name to begin the review session.")
    username = st.text_input("Your Name").lower().strip()

    if st.button("Start Review Session"):
        if username:
            st.session_state.username = username  # Save the username in session_state
            from utils import generate_speech, rephrase_text
            greeting = f"Hey! {username.split()[0]} Welcome back. Happy prompt reviewing. Godspeed"
            greeting = rephrase_text(openai_api_key,greeting)
            generate_speech(greeting,openai_api_key=openai_api_key, output_file= "welcome.mp3")
            play_audio("welcome.mp3")
            with st.spinner(f"Please hold up {username.split()[0].title()}, I'm setting up things for you!"):
                time.sleep(10)
                st.success("Done!")
                st.rerun()  # Reload the app to proceed to the review section
else:
    # Display the username and review count in the sidebar
    st.sidebar.title("Senior Reviewer")
    st.sidebar.write(f"Username: {st.session_state.username}")
    

    # Navigation Menu
    page = st.sidebar.radio("Navigate", ["Review", "History", "Analytics", "Upload Prompts"])
    st.session_state.max_num_cols = st.sidebar.slider(
        "Select the number of columns for word buttons",
        min_value=1,
        max_value=10,  # You can adjust the max value based on your needs
        value=7,  # Default value
        step=1
    )

    if page == "Review":
        # Get the review count for the current reviewer
        review_count = get_review_count(st.session_state.username)
        st.sidebar.write(f"Reviews Completed: {review_count}")

        st.markdown("### Review Process:")
        with st.expander("Review and Emotion Selection Instructions"):
            st.write("""
                    ### Instructions for Reviewing Text:
                    - **Editing**: Use the text box to edit the code-switched text if necessary. You can correct the sentence structure, grammar, or phrasing as needed to ensure clarity and correctness.
                    
                    - **Emotions**: Select one or more emotions from the list that best fit the tone of the sentence. You can select multiple emotions if the sentence has a mixed tone (e.g., both **Happy** and **Surprised**).

                    - **Language Tagging**: As you review the text, you can click on the **buttons next to each word** to change its language tag. Words tagged as **English (blue)** can be switched to **Yoruba (red)**, and vice versa. This helps ensure the language tags are accurate for each word based on its language. You can toggle the tag between **English** and **Yoruba** by clicking the buttons. 

                    - **Undo a Mistake**: If you submit a review by mistake, don't worry! You can go to the **History tab** to view your past reviews. If you need to, you can undo any review by clicking the **Undo Review** button for that specific entry. This will reset the review back to its initial "pending" state, allowing you to make corrections.

                    - **Contact Victor for Help**: If you're unsure about anything or need assistance, please **contact Victor**. Don't hesitate to ask for help to ensure you're reviewing correctly and following the right steps.

                    - **Important Note on Upload Prompts**: Do not go to the **Upload Prompts tab** if you're not sure about what you're doing. If you're unfamiliar with uploading prompts or setting batch numbers, please consult with Victor before proceeding. **Only go to this tab if you're confident in what you're uploading!**

                    By following these steps, you'll help me stay sane mentally. Thank you for your careful review!
                    """)


        # Load the next unreviewed text
        doc_id, text_data = load_next_text()

        if text_data:
            if st.session_state.text_data== None:
                st.session_state.text_data = text_data
                st.session_state.doc_id = doc_id
            corrected_tags = []
            # Display the Original Text, Code-Switched Text, and Creator's Name
            # st.title("Text Review")
            # st.write("#### Original Text")
            # st.write("###### " + text_data["OriginalText"])
            # st.write("Code-Switched Text")
            # st.write("##### " + text_data["CodeSwitchedText"])
            st.session_state.text_data["CodeSwitchedText"] = st.session_state.text_data["CodeSwitchedText"].strip('"')
            if st.session_state.word_tags==None:
                tagged_words = light_tagger(st.session_state.text_data["CodeSwitchedText"])
                st.session_state.word_tags = tagged_words
            else:
                tagged_words = st.session_state.word_tags
                # st.session_state.word_tags = tagged_words
            
            # st.write("Click on a word's button below to change its language tag (blue = English, red = Yoruba)")

            # Add the legend or indicator for language tags
            # st.write("### Legend:")
            import streamlit as st

            # Create two columns
            colA, colB = st.columns(2)

            # Use the first column for the blue text
            with colA:
                st.markdown("<p style='color:blue;'>Blue = English</p>", unsafe_allow_html=True)

            # Use the second column for the red text
            with colB:
                st.markdown("<p style='color:red;'>Red = Yorùbá</p>", unsafe_allow_html=True)

            st.markdown(f"<h3>{display_colored_sentence(st.session_state.word_tags)}</h3>", unsafe_allow_html=True)

            # Call the function to display the buttons
            display_buttons(st.session_state.word_tags,st.session_state.max_num_cols)

            # with st.expander("More details"):
            #     (st.write(dict(st.session_state.word_tags)))
            st.write("#### Creator's Name")
            st.write(st.session_state.text_data["CreatorName"])

            st.write("### Review Actions")
            action = st.radio("Choose Action", ["Approve", "Edit", "Reject"])
           
            # Emotion multi-select dropdown
            selected_emotions = st.multiselect(
                        "Select the emotions in which this sentence should be read",
                        emotions,
                        default=['Neutral']  # Default to no emotions selected
                    )


            # If the reviewer chooses "Edit", allow them to modify the text
            if action == "Edit":
                edited_text = st.text_area("Edited Code-Switched Text", st.session_state.text_data["CodeSwitchedText"],                                
                                           key="edited_text",
                               on_change=update_reflection)

            #             # Loop through each word and its current language tag
            # for word, lang in tagged_words:
            #     corrected_lang = st.selectbox(f"Correct the language tag for '{word}'", ["en", "yo"], index=["en", "yo"].index(lang))
            #     corrected_tags.append((word, corrected_lang))

            if st.button("Submit Review"):
                review_data = {
                    "Status": action.lower(),
                    "reviewer": st.session_state.username,
                    "reviewed_text": edited_text if action == "Edit" else st.session_state.text_data["CodeSwitchedText"],
                    "emotions": selected_emotions,
                    "language_tags": tag(st.session_state.word_tags)
                }
                save_review(st.session_state.doc_id, review_data)

                # Confirmation and auto-reload to fetch the next item
                st.success("Review submitted!")
                st.session_state.word_tags=None
                st.session_state.text_data = None
                st.rerun()  # Reloads the app to show the next item
        else:
            st.write("No more texts to review.")

    elif page == "History":
        st.title("Review History")

        # User specifies the number of records to retrieve
        num_records = st.number_input("Number of records to retrieve:", min_value=1, max_value=100, value=10)

        # Fetch and display the review history
        history = get_review_history(st.session_state.username, num_records)

        if history:
            for record in history:
                st.write("---")
                st.write(f"**Original Text:** {record['OriginalText']}")
                st.write(f"**Code-Switched Text:** {record['CodeSwitchedText']}")
                st.write(f"**Your Reviewed Text:** {record['reviewed_text']}")
                # st.write(str(record['language_tags']))
                st.markdown(f"**Your Reviewed Text (Blue:Eng):** {display_colored_sentence(reverse_tag(record['language_tags']))}", unsafe_allow_html=True)
                st.write(f"**Emotions:** {record['emotions']}")
                st.write(f"**Status:** {record['Status']}")
                st.write(f"**Timestamp:** {record['Timestamp']}")

                # # Option to edit the record
                # if st.button(f"Edit Review - {record['doc_id']}"):
                #     # Set a flag in session state to indicate which record is being edited
                #     st.session_state.editing_record = record['doc_id']
                #     st.session_state.new_text = record['reviewed_text']

                # Check if this record is being edited
                # if st.session_state.get('editing_record') == record['doc_id']:
                #     # Text area for editing the text
                #     st.session_state.new_text = st.text_area(
                #         "Edit the Code-Switched Text:", 
                #         st.session_state.new_text, 
                #         key=f"text_area_{record['doc_id']}"
                #     )
                    
                #     # Button to save changes
                # if st.button(f"Save Changes - {record['doc_id']}"):
                #         # Perform the update
                #         update_review(record['doc_id'], st.session_state.new_text)
                #         st.success("Review updated successfully!")
                #         # Clear the editing state
                #         del st.session_state.editing_record
                #         st.rerun()
                                    # Button to save changes
                if st.button(f"Undo Review - {record['doc_id']}"):
                        # Perform the update
                        undo_review(record['doc_id'])
                        st.success("Review undone successfully it'll go back to main page!")
                        # Clear the editing state
                        st.rerun()

        else:
            st.write("No history available.")

    elif page == "Analytics":
        st.title("Reviewer Analytics")

        # Fetch review data and compute analytics
        review_data = fetch_review_data()
        if not review_data.empty:
            review_data =  review_data.fillna("unreviewed")
            original_review_data = review_data.copy()
            review_data = review_data[(review_data["reviewer"] != "unreviewed") & (review_data["Status"] != "reject")]
            status_count = review_data.groupby(['reviewer', 'Status']).size().unstack(fill_value=0)
            try:
                status_count["sum"] = status_count["approve"] + status_count["edit"]
            except:
                status_count["sum"] = status_count["approve"]
            status_count = status_count.sort_values(by="sum").drop("sum", axis=1)
            
            # Plotting
            fig, ax = plt.subplots(figsize=(10, 6))
            bars = status_count.plot(kind='barh', stacked=True, ax=ax, )

            # # Annotate bars with totals
            # for bar in bars.patches:
            #     ax.annotate(str(int(bar.get_height())),
            #                 (bar.get_x() + bar.get_width() / 2, bar.get_height()),
            #                 ha='center', va='bottom', fontsize=9)

            # Add titles and labels
            plt.title("Review Status by Reviewer", fontsize=16)
            plt.ylabel("Reviewer", fontsize=12)
            plt.xlabel("Number of Reviews", fontsize=12)
            plt.xticks(rotation=0)
            plt.legend(title="Status", fontsize=10)
            plt.tight_layout()

            # Display the plot
            st.pyplot(fig)
            st.write("\n")
            st.write("Breakdown: Note that I've excluded your rejections, and this is data that has not been uploaded to the speech app")
            st.write(f"Right now, {status_count.index[-1].title()} is on 🔥🔥")

            st.write(review_data["reviewer"].value_counts())
            # st.write(original_review_data)
            unreviewed_df = original_review_data[(original_review_data["reviewer"]=="unreviewed") & (original_review_data["Status"] != "reject")]
            # st.write(unreviewed_df)
            st.write("Sum total is: ", str(review_data["reviewer"].value_counts().sum()), "prompts")
            st.write("Unreviwed Prompts: ", str(len(unreviewed_df)), "prompts")


        else:
            st.write("No review data available for analytics.")


    elif page == "Upload Prompts":
        st.title("Upload Prompts")

        # File uploader
        uploaded_file = st.file_uploader("Upload your prompt CSV file:", type=["csv", "xlsx"])
        
        if uploaded_file:
            # Read the file based on its extension
            if uploaded_file.name.endswith(".xlsx"):
                df = pd.read_excel(uploaded_file, header=None)
            elif uploaded_file.name.endswith(".csv"):
                df = pd.read_csv(uploaded_file, header=None)

            st.write("Preview of Uploaded Data:")
            st.write(df.head())  # Show a preview of the uploaded file

            # Perform sanity checks
            errors = []
            if len(df.columns) < 1:
                errors.append("The uploaded file must have at least one column for prompts.")
            elif df.isnull().any().any():
                errors.append("The file contains missing values. Please clean the data before uploading.")

            # Notify the user of errors
            if errors:
                st.error("Sanity checks failed! Please address the following issues:")
                for error in errors:
                    st.write(f"- {error}")
                st.warning("You cannot proceed with processing or uploading until these issues are resolved.")
            else:
                # If sanity checks pass, process the data
                st.success("Sanity checks passed!")
                st.warning("Please and Please if you don't understand anything here Ask Victor! Don't Guess! Ask!")

                # Prepare data
                df.columns = ["code-switched-text"]
                code_name = st.text_input("Enter the nick name or first name of the Prompt Creator and add the current data and time e.g, Mary140520250115, we use this to generate ID", value="Mary140520250115")
                set_num = st.text_input("Enter the SET number - Ask Victor if you don't know, this is essentially the batch number", value="4")
                df["ID"] = [f"{code_name}_Set_{set_num}_{i}" for i in range(len(df))]
                df["Original Text"] = "unknown"
                df["Creator's Name"] = st.text_input("Enter the Full Name of the Prompt Creator", value="Mary Magdalene")
                df["domain"] = st.text_input("Enter the domain for these prompts (e.g., Health):", value="General")
                df["Status"] = "pending"
                df["pulled"] = False
                df["code-switched-text"] = df["code-switched-text"].str.strip('"')

                # Save the processed file
                if st.button("Process and Save"):
                    processed_file_path = "processed_prompts.csv"
                    df.reset_index(drop=True).to_csv(processed_file_path, index=False)
                    st.session_state.processed_file_path = processed_file_path  # Save file path in session_state
                    st.session_state.dataframe = df  # Save the dataframe in session_state
                    st.success(f"File processed and saved as {processed_file_path}. Ready for upload.")
                    st.write("Preview of Uploaded Data:")
                    st.write(df.head())  # Show a preview of the uploaded file

                # Upload to Firestore
                if st.session_state.processed_file_path and st.button("Upload to Firestore"):
                    st.session_state.upload_started = True
                    with st.spinner("Uploading data to Firestore..."):
                        progress_bar = st.progress(0)  # Initialize the progress bar
                        total_rows = len(st.session_state.dataframe)  # Total number of rows to upload

                        for index, row in enumerate(st.session_state.dataframe.iterrows(), start=1):
                            _, data_row = row
                            doc_id = data_row["ID"]
                            data = {
                                "OriginalText": data_row["Original Text"],
                                "CodeSwitchedText": data_row["code-switched-text"],
                                "CreatorName": data_row["Creator's Name"],
                                "Status": data_row["Status"],
                                "domain": data_row["domain"],
                                "pulled": data_row["pulled"]
                            }
                            db.collection("stage_four_reviews").document(doc_id).set(data)

                            # Update progress bar
                            progress = int((index / total_rows) * 100)
                            progress_bar.progress(progress)

                    st.success("All data uploaded successfully!")
                    st.session_state.upload_started = False  # Reset the upload state