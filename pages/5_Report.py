import streamlit as st
import orchestrator as orch
import os

st.set_page_config(page_title="Report - Mentora", page_icon="🎓", layout="wide")
import ui
ui.apply_theme()

st.title("Lesson Report")

# Guard page
session = st.session_state.get("session")
report = st.session_state.get("report")

if session is None or report is None:
    st.info("Complete a lesson and quiz to see your report.")
    st.stop()

st.subheader(f"Final Score: {report.score}%")
st.progress(report.score / 100.0)

col1, col2 = st.columns(2)

with col1:
    st.markdown("### 🌟 Strong Areas")
    if report.strong:
        for s in report.strong:
            st.write(f"- {s}")
    else:
        st.write("- None identified yet")
        
    st.markdown("### ⚠️ Misconceptions to Fix")
    if report.misconceptions:
        for m in report.misconceptions:
            st.error(f"- {m}")
    else:
        st.write("- No major misconceptions!")

with col2:
    st.markdown("### 📈 Weak Areas")
    if report.weak:
        for w in report.weak:
            st.write(f"- {w}")
    else:
        st.write("- None identified")
        
    st.markdown("### 📚 Recommended Revision")
    if report.revise:
        for r in report.revise:
            st.warning(f"- {r}")
    else:
        st.write("- No specific revision needed.")

st.markdown("---")
st.markdown("### ➡️ Next Topic")
st.write(f"**{report.next_topic}**")

st.markdown("---")
st.markdown("### 🎬 Full Lesson Video")
with st.spinner("Stitching your lesson video..."):
    video_path = orch.lesson_video(session)
    if video_path and os.path.exists(video_path):
        st.video(video_path)
    else:
        st.info("Lesson video is not available.")
