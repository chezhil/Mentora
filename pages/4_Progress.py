"""Student Progress & Learning Path Page for Mentora AI Teacher.
OWNED BY UTKARSH (PAIR A).
"""
import streamlit as st
import orchestrator as orch
import ui

st.set_page_config(page_title="Learning Progress — Mentora", page_icon="📈", layout="wide")
ui.apply_theme()

student_id = st.session_state.get("student_id", "student")
session = st.session_state.get("session")
current_report = st.session_state.get("report")

# Load historical reports for student
past_reports = orch.past_reports(student_id)

# Include current session report in list if not already present
all_reports = list(past_reports)
if current_report and (not past_reports or past_reports[-1] != current_report):
    all_reports.append(current_report)

if session is None and not all_reports:
    st.info("💡 Start a lesson on the Setup page to begin tracking your learning progress.")
    st.stop()

st.title("📈 Student Learning Progress & Profile")
st.caption(f"Profile: **{student_id}** • Tracking long-term mastery, misconceptions & curriculum roadmaps")

# ---------------------------------------------------------------------------
# SECTION 1: HISTORICAL PERFORMANCE & PROFILE METRICS
# ---------------------------------------------------------------------------
st.subheader("📊 Performance Analytics")

if all_reports:
    scores = [r.score for r in all_reports]
    avg_score = sum(scores) / len(scores) if scores else 0.0

    all_strong = sorted(list(set(c for r in all_reports for c in r.strong)))
    all_weak = sorted(list(set(c for r in all_reports for c in r.weak if c not in all_strong)))
    all_misconceptions = sorted(list(set(m for r in all_reports for m in r.misconceptions)))

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Completed Sessions", len(all_reports))
    col2.metric("Average Score", f"{avg_score:.1f}%")
    col3.metric("Mastered Concepts", len(all_strong))
    col4.metric("Active Gaps to Review", len(all_weak))

    # Score Trend Chart if multiple sessions
    if len(all_reports) > 1:
        st.markdown("#### 📈 Score Progression Over Time")
        chart_data = {"Session": [f"Session {i+1}" for i in range(len(scores))], "Score (%)": scores}
        st.line_chart(chart_data, x="Session", y="Score (%)", color="#38bdf8")

    st.divider()

    col_strong, col_weak = st.columns(2)
    with col_strong:
        st.markdown("#### 🏆 Cumulative Strong Concepts")
        if all_strong:
            for s in all_strong:
                st.write(f"✨ **{s}**")
        else:
            st.caption("Complete more lessons to register mastered concepts.")

    with col_weak:
        st.markdown("#### 🎯 Active Concepts Needing Practice")
        if all_weak:
            for w in all_weak:
                st.write(f"⚠️ {w}")
        else:
            st.success("No unaddressed knowledge gaps recorded.")

        if all_misconceptions:
            st.markdown("#### 🧠 Diagnosed Knowledge Misconceptions")
            for m in all_misconceptions:
                st.warning(f"🔍 {m}")
else:
    st.info("No completed lesson records found yet. Complete a quiz to see long-term analytics.")

st.divider()

# ---------------------------------------------------------------------------
# SECTION 2: AI-GENERATED LEARNING PATH (Section 15 of Hackathon Brief)
# ---------------------------------------------------------------------------
active_topic = session.plan.topic if session else (all_reports[-1].next_topic if all_reports and all_reports[-1].next_topic else "Core Sciences & AI")
st.subheader(f"🗺️ AI-Generated Learning Path: {active_topic}")
st.caption("Structured curriculum sequence showing what to study next and pedagogical rationale.")

steps = orch.learning_path_for(active_topic)

if steps:
    for idx, step_item in enumerate(steps, start=1):
        if " - " in step_item:
            title, desc = step_item.split(" - ", 1)
        elif ": " in step_item:
            title, desc = step_item.split(": ", 1)
        else:
            title, desc = step_item, ""

        is_current = bool(session and (active_topic.lower() in title.lower() or title.lower() in active_topic.lower()))

        with st.container():
            if is_current:
                st.markdown(
                    f"""
                    <div style="background-color: #0c4a6e; border-left: 5px solid #38bdf8; padding: 12px 16px; border-radius: 6px; margin-bottom: 12px;">
                        <span style="background-color: #38bdf8; color: #082f49; font-weight: bold; padding: 2px 8px; border-radius: 12px; font-size: 0.85rem;">CURRENT FOCUS</span>
                        <h4 style="margin: 6px 0 2px 0; color: #f0f9ff;">Step {idx}: {title}</h4>
                        <p style="margin: 0; color: #bae6fd; font-size: 0.95rem;">{desc}</p>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
            else:
                st.markdown(
                    f"""
                    <div style="background-color: #1e293b; border-left: 4px solid #64748b; padding: 10px 14px; border-radius: 6px; margin-bottom: 10px;">
                        <h4 style="margin: 0 0 2px 0; color: #f8fafc;">Step {idx}: {title}</h4>
                        <p style="margin: 0; color: #94a3b8; font-size: 0.92rem;">{desc}</p>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
else:
    st.info(f"Generating learning path for {active_topic}...")
