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

    st.success(f"🎉 Quiz evaluated successfully! Overall Score: **{report.score:.1f}%**")

    # Metrics Summary
    col1, col2, col3 = st.columns(3)
    col1.metric("Final Score", f"{report.score:.1f}%")
    col2.metric("Mastered Concepts", len(report.strong))
    col3.metric("Concepts to Review", len(report.weak))

    st.divider()
    
    col_left, col_right = st.columns(2)
    with col_left:
        st.markdown("### ✅ Strong Concepts")
        if report.strong:
            for s in report.strong:
                st.write(f"- **{s}**")
        else:
            st.caption("Keep practicing to master these topics.")

        if report.misconceptions:
            st.markdown("### 🔍 Diagnosed Misconceptions")
            for m in report.misconceptions:
                st.warning(f"⚠️ {m}")

    with col_right:
        if report.weak:
            st.markdown("### ⚠️ Areas for Improvement")
            for w in report.weak:
                st.write(f"- {w}")

        if report.revise:
            st.markdown("### 📖 Recommended Revision")
            for r in report.revise:
                st.info(f"📌 {r}")

        if report.next_topic:
            st.markdown("### 🚀 Next Recommended Topic")
            st.success(f"**{report.next_topic}**")

elif existing_report:
    st.info(f"Previous submission recorded. Current Score: **{existing_report.score:.1f}%**")
