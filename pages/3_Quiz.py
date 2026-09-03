"""Final Quiz Page for Mentora AI Teacher.
OWNED BY UTKARSH (PAIR A).
"""
import streamlit as st
import orchestrator as orch
import ui

st.set_page_config(page_title="Final Quiz — Mentora", page_icon="📝", layout="wide")
ui.apply_theme()

# --- Session Guard ---
session = st.session_state.get("session")
if session is None:
    st.info("💡 Please start a lesson on the Setup page first to generate a curriculum.")
    st.stop()

questions = orch.quiz_questions(session)
if not questions:
    st.info("💡 Complete the lesson to unlock the final quiz assessment.")
    st.stop()

st.title("📝 Final Assessment Quiz")
st.caption(f"Topic: **{session.plan.topic}** • {len(questions)} Question(s)")

# Check if report already exists in session state
existing_report = st.session_state.get("report")

with st.form("quiz_submission_form"):
    user_answers = {}
    for idx, q in enumerate(questions, start=1):
        st.markdown(f"#### Q{idx}. {q.prompt}")
        
        if q.kind == "mcq" and q.options:
            ans = st.radio(
                f"Select your answer for Question {idx}:",
                options=q.options,
                key=f"quiz_q_{q.id}",
                index=None,
                label_visibility="collapsed"
            )
            user_answers[q.id] = ans or ""
        else:
            ans = st.text_input(
                f"Enter your answer for Question {idx}:",
                key=f"quiz_q_{q.id}",
                placeholder="Type your explanation or response here...",
                label_visibility="collapsed"
            )
            user_answers[q.id] = ans or ""
        
        st.divider()

    submitted = st.form_submit_button("Submit Final Quiz", type="primary", use_container_width=True)

if submitted:
    unanswered = sum(1 for a in user_answers.values() if not str(a).strip())
    if unanswered > 0:
        st.warning(f"Note: {unanswered} question(s) were submitted blank.")

    with st.spinner("Evaluating your responses with pedagogical diagnosis..."):
        report = orch.submit_quiz(session, user_answers)
        st.session_state.report = report

    st.success("Quiz evaluated successfully!")
    if hasattr(st, "switch_page"):
        st.switch_page("pages/5_Report.py")
    else:
        st.info("Check out your full result on the Report page.")

elif existing_report:
    st.info(f"Previous submission recorded. Current Score: **{existing_report.score:.1f}%**")
    if hasattr(st, "switch_page"):
        if st.button("View Full Report"):
            st.switch_page("pages/5_Report.py")
