"""Exam Mode — timed, exam-style assessment.

HEXAGON's Exam Mode simulates a real exam: timed, no re-explanations,
strict grading, final score with analysis. This screen generates exam
questions from the student's past lessons and shows a timer + progress.
"""

import time

import streamlit as st

import orchestrator as orch
from shared.models import StudentResponse
from ui.i18n import t


def render_exam(session, lang: str = "en") -> None:
    student_id = st.session_state.get("student_id", "student")

    # ── Exam setup ──────────────────────────────────────────────────────
    if "exam_questions" not in st.session_state:
        _setup_exam(session, student_id, lang)
        return

    # ── Exam in progress ────────────────────────────────────────────────
    _run_exam(session, student_id, lang)


def _setup_exam(session, student_id, lang):
    """Generate exam questions and let the student configure duration."""
    st.markdown(f"#### 🎯 {t('exam.title', lang)}")
    st.caption(t("exam.desc", lang))

    if session is None:
        st.info(t("exam.no_session", lang))
        return

    # Generate quiz questions from the plan
    questions = orch.quiz_questions(session)
    if not questions:
        st.warning(t("exam.no_questions", lang))
        return

    col1, col2 = st.columns(2)
    with col1:
        duration = st.slider(
            t("exam.duration", lang), min_value=5, max_value=60,
            value=min(20, len(questions) * 3), step=5,
        )
    with col2:
        st.metric(t("exam.question_count", lang), len(questions))

    if st.button(t("exam.start", lang), type="primary", use_container_width=True):
        st.session_state.exam_questions = questions
        st.session_state.exam_answers = {}
        st.session_state.exam_start_time = time.time()
        st.session_state.exam_duration = duration * 60  # seconds
        st.session_state.exam_current = 0
        st.session_state.exam_finished = False
        st.rerun()


def _run_exam(session, student_id, lang):
    """Drive the timed exam: one question at a time, countdown timer."""
    questions = st.session_state.exam_questions
    current = st.session_state.exam_current
    total = len(questions)

    # ── Timer ───────────────────────────────────────────────────────────
    elapsed = time.time() - st.session_state.exam_start_time
    remaining = max(0, st.session_state.exam_duration - elapsed)
    mins, secs = divmod(int(remaining), 60)

    if remaining <= 0:
        _finish_exam(session, student_id, lang)
        return

    # ── Header with timer + progress ────────────────────────────────────
    # JS auto-tick: data attributes let a small script update the countdown
    # every frame without waiting for a Streamlit rerun.
    start_epoch = st.session_state.exam_start_time
    duration_secs = st.session_state.exam_duration
    timer_color = "var(--nb-orange)" if remaining < 60 else "var(--nb-cyan)"
    timer_icon = "\U0001f534" if remaining < 60 else "\U0001f7e2"
    _tick_js = (
        '<script>(()=>{'
        'var el=document.getElementById("exam-timer");'
        'if(!el||el._ticking)return;el._ticking=true;'
        'var S=parseFloat(el.dataset.start),D=parseFloat(el.dataset.duration);'
        'function t(){'
        'var r=Math.max(0,D-(Date.now()/1000-S));'
        'var m=Math.floor(r/60),s=Math.floor(r%60);'
        'el.textContent=(r<60?"\U0001f534":"\U0001f7e2")+" "+m+":"+(s<10?"0":"")+s;'
        'el.style.color=r<60?"var(--nb-orange)":"var(--nb-cyan)";'
        'if(r>0)requestAnimationFrame(t);'
        '}t();'
        '})();</script>'
    )
    st.markdown(
        f'<div style="display:flex;justify-content:space-between;align-items:center;'
        f'margin-bottom:1rem;">'
        f'<span id="exam-timer" '
        f'data-start="{start_epoch}" data-duration="{duration_secs}" '
        f'style="font-family:JetBrains Mono;font-weight:900;font-size:1.5rem;'
        f'color:{timer_color};">'
        f'{timer_icon} {mins}:{secs:02d}</span>'
        f'<span style="font-family:JetBrains Mono;font-size:0.85rem;color:var(--nb-text-dim);">'
        f'{current + 1} / {total}</span></div>'
        f'{_tick_js}',
        unsafe_allow_html=True,
    )
    st.progress((current + 1) / total)

    # ── Question ────────────────────────────────────────────────────────
    if current >= total:
        _finish_exam(session, student_id, lang)
        return

    q = questions[current]
    st.markdown(f"**{q.prompt}**")

    if q.options:
        answer = st.radio(
            t("lesson.your_answer", lang), q.options,
            key=f"exam_q_{current}", index=None,
            label_visibility="collapsed",
        )
    else:
        answer = st.text_input(
            t("lesson.your_answer", lang),
            key=f"exam_q_{current}",
            label_visibility="collapsed",
            placeholder=t("exam.placeholder", lang),
        )

    col_prev, col_next = st.columns([1, 1])
    with col_prev:
        if current > 0:
            if st.button("← " + t("exam.prev", lang), use_container_width=True):
                # Save current answer before going back
                if answer:
                    st.session_state.exam_answers[q.id] = answer
                st.session_state.exam_current = current - 1
                st.rerun()
    with col_next:
        if answer:
            if current < total - 1:
                if st.button(t("exam.next", lang) + " →", type="primary",
                             use_container_width=True):
                    st.session_state.exam_answers[q.id] = answer
                    st.session_state.exam_current = current + 1
                    st.rerun()
            else:
                if st.button(t("exam.submit", lang), type="primary",
                             use_container_width=True):
                    st.session_state.exam_answers[q.id] = answer
                    _finish_exam(session, student_id, lang)

    # ── Question navigator ──────────────────────────────────────────────
    answered = len(st.session_state.exam_answers)
    st.caption(f"{answered}/{total} {t('exam.answered', lang)}")


def _finish_exam(session, student_id, lang):
    """Grade the exam and show results."""
    questions = st.session_state.exam_questions
    answers = st.session_state.get("exam_answers", {})

    # Grade each question
    correct = 0
    total = len(questions)
    details = []
    for q in questions:
        ans = answers.get(q.id, "")
        if not ans:
            details.append({"question": q.prompt, "answer": "", "correct": False,
                           "expected": q.expected})
            continue
        response = StudentResponse(question_id=q.id, answer=str(ans))
        evaluation = orch.answer(session, response, question=q)
        is_correct = evaluation.correct
        if is_correct:
            correct += 1
        details.append({
            "question": q.prompt, "answer": ans, "correct": is_correct,
            "expected": q.expected, "feedback": evaluation.feedback,
        })

    score = (correct / total * 100) if total else 0

    # Show results
    st.markdown("---")
    mark = "🟩" if score >= 75 else "🟨" if score >= 50 else "🟥"
    st.markdown(f"#### {mark} {t('exam.results', lang)}")
    st.metric(t("exam.score", lang), f"{score:.0f}%")
    st.caption(f"{correct}/{total} {t('exam.correct', lang)}")

    # Time taken
    elapsed = time.time() - st.session_state.exam_start_time
    emin, esec = divmod(int(elapsed), 60)
    st.caption(f"⏱ {t('exam.time_taken', lang)}: {emin}:{esec:02d}")

    st.divider()

    # Detailed breakdown
    for i, d in enumerate(details):
        icon = "✅" if d["correct"] else "❌"
        with st.expander(f"{icon} Q{i+1}: {d['question'][:60]}..."):
            if d["answer"]:
                st.write(f"**Your answer:** {d['answer']}")
            else:
                st.write("**Your answer:** *(skipped)*")
            if not d["correct"]:
                st.write(f"**Expected:** {d.get('expected', '—')}")
                if d.get("feedback"):
                    st.info(d["feedback"])

    # Cleanup
    if st.button(t("exam.try_again", lang), type="primary"):
        for key in ("exam_questions", "exam_answers", "exam_start_time",
                     "exam_duration", "exam_current", "exam_finished"):
            st.session_state.pop(key, None)
        st.rerun()
