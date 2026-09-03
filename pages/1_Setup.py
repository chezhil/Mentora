import streamlit as st
import orchestrator as orch
from shared.models import LearnerProfile
import os
import tempfile

st.set_page_config(page_title="Setup - Mentora", page_icon="📝", layout="centered")

st.title("Welcome to Mentora")

student_id = st.session_state.get("student_id", "student")
past_reports = orch.past_reports(student_id)
if past_reports:
    st.info(f"Welcome back! You have {len(past_reports)} past lesson(s) completed.")
else:
    st.info("Welcome! Start your first lesson below.")

with st.form("setup_form"):
    st.subheader("Configure your Lesson")
    
    topic = st.text_input("What do you want to learn?", value="Electricity")
    
    col1, col2 = st.columns(2)
    with col1:
        level = st.selectbox("Your current level", ["beginner", "intermediate", "advanced"])
        language = st.selectbox("Language", ["en", "hi", "ta", "kn", "te", "bn", "hinglish"])
    with col2:
        time_minutes = st.selectbox("Time available (minutes)", [5, 20, 60], index=1)
        goal = st.text_input("Specific Goal (optional)", placeholder="e.g. Pass my exam tomorrow")
    
    known = st.text_input("What you already know (optional)", placeholder="e.g. I know basic maths")
    weak = st.text_input("What you struggle with (optional)", placeholder="e.g. Formulas are hard")
    
    uploaded_file = st.file_uploader("Upload material (PDF/DOCX/PPTX/TXT)", type=["pdf", "docx", "pptx", "txt"])
    
    submitted = st.form_submit_button("Start Lesson", type="primary")

if submitted:
    if not topic.strip() and not uploaded_file:
        st.error("Please enter a topic or upload a document.")
        st.stop()
        
    known_list = [k.strip() for k in known.split(",") if k.strip()] if known else []
    weak_list = [w.strip() for w in weak.split(",") if w.strip()] if weak else []
    
    profile = LearnerProfile(
        level=level,
        language=language,
        time_minutes=time_minutes,
        goal=goal.strip() if goal else None,
        known_concepts=known_list,
        weak_concepts=weak_list
    )
    
    file_path = None
    if uploaded_file is not None:
        # Save to temp file
        temp_dir = tempfile.gettempdir()
        file_path = os.path.join(temp_dir, uploaded_file.name)
        with open(file_path, "wb") as f:
            f.write(uploaded_file.getbuffer())
    
    with st.spinner("Preparing your personalized lesson..."):
        session = orch.start_session(topic, profile, file_path=file_path, student_id=student_id)
        
        # After start_session, we also need to get the first segment
        if not orch.is_finished(session):
            segment = orch.step(session)
            st.session_state.segment = segment
        else:
            st.session_state.segment = None
            
        st.session_state.session = session
        
    st.success("Lesson ready! Head over to the Lesson page.")
    if hasattr(st, "switch_page"):
        st.switch_page("pages/2_Lesson.py")
