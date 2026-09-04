"""Flashcards screen + the shared review-card widget.

Three views meet here:
  - review All cards from the current lesson (concepts + questions asked),
    plus DUE cards from earlier sessions, scheduled by spaced repetition;
  - review only what is DUE right now; and
  - Browse the whole persisted deck: per-card stats, edit, delete.

Every card is flipped, self-rated (Again / Good / Easy), and the rating is
persisted to history.db, so tomorrow's session opens with the cards you
flagged coming back first. Styling lives in ui/style.css (`.fc-card` etc.)
and matches the neo-brutalist dark theme everywhere else.

`review_card()` is the single interaction surface for a card. The dashboard's
due queue (screens/path.py) reuses it under its own namespace, so the same
card shown on both surfaces in one run never shares flip/rate state.
"""

import random
from datetime import datetime

import streamlit as st

import orchestrator as orch
from ui.i18n import t

_RATINGS = [("again", "🔁"), ("good", "👍"), ("easy", "⚡")]
_ICONS = dict(_RATINGS)
_SOURCE_KEYS = {"concept": "flashcards.source_concept",
                "question": "flashcards.source_question",
                "quiz": "flashcards.source_quiz"}
_TAG_KEYS = {"concept": "flashcards.tag_concept",
             "question": "flashcards.tag_question",
             "quiz": "flashcards.tag_quiz"}


def _short_date(iso: str | None, lang: str) -> str:
    if not iso:
        return t("flashcards.never", lang)
    try:
        return datetime.fromisoformat(iso).strftime("%d %b")
    except ValueError:
        return iso


def interval_note(ease: str, interval: float | None, lang: str = "en") -> str:
    """"Next review in N days" — the visible consequence of each rating."""
    icon = _ICONS.get(ease, "")
    name = t(f"flashcards.ease_{ease}", lang)
    if interval is None or interval <= 0:
        return t("flashcards.note_now", lang).format(icon=icon, name=name)
    if interval == 1:
        days = t("flashcards.day_one", lang).format(n="1")
    else:
        days = t("flashcards.day_many", lang).format(n=f"{interval:.0f}")
    return t("flashcards.note_later", lang).format(
        icon=icon, name=name, days=days)


def _source_tag(source: str, lang: str) -> str:
    return t(_TAG_KEYS.get(source, "flashcards.tag_question"), lang)


def _source_label(source: str, lang: str) -> str:
    return t(_SOURCE_KEYS.get(source, "flashcards.source_other"), lang)


def review_card(student_id: str, card: dict, lang: str, ns: str,
                position: str = "") -> tuple[str, float | None] | None:
    """Render one flippable, self-rated card.

    ``ns`` separates widget/session state between surfaces that can show the
    same card in a single run (the Flashcards review deck vs the dashboard's
    due queue), so a flip on one never reveals the other.

    Returns ``(ease, interval)`` when the student rated the card this run
    (already persisted through the SM-2 scheduler); ``None`` while the card
    is face-down or was just flipped. Callers advance their own queue and
    rerun.
    """
    state_key = f"{ns}:{card['card_key']}"
    revealed = st.session_state.get(f"{state_key}:revealed", False)
    tag = " · ".join(p for p in (position, _source_tag(card.get("source", ""), lang)) if p)
    front, back = card["front"], card["back"]

    if not revealed:
        st.markdown(
            f"""
            <div class="fc-card shine-hover" data-tilt>
              <span class="fc-tag">{tag}</span>
              <div class="fc-front">{front}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button(t("flashcards.flip", lang), type="primary",
                     key=f"{state_key}:flip", use_container_width=True):
            st.session_state[f"{state_key}:revealed"] = True
            st.rerun()
        return None

    st.markdown(
        f"""
        <div class="fc-card fc-open shine-hover" data-tilt>
          <span class="fc-tag">{tag}</span>
          <div class="fc-front">{front}</div>
          <div class="fc-divider"></div>
          <div class="fc-back">{back}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    cols = st.columns(len(_RATINGS))
    chosen = None
    for col, (ease, icon) in zip(cols, _RATINGS):
        with col:
            label = t(f"flashcards.ease_{ease}", lang)
            if st.button(f"{icon} {label}", key=f"{state_key}:rate_{ease}",
                         use_container_width=True):
                chosen = ease
    if chosen is None:
        return None
    interval = orch.record_flashcard(student_id, card, chosen)
    st.session_state[f"{state_key}:revealed"] = False
    return chosen, interval


def _deck_state_key(student_id: str) -> str:
    return f"fc_deck_{student_id}"


def _deleted_set(student_id: str) -> set:
    return st.session_state.setdefault(f"fc_deleted_{student_id}", set())


def _build_deck(session, student_id: str, due_only: bool) -> list[dict]:
    """Cards for the current view: lesson cards (All view) plus whatever is
    due, deduplicated by key — a question missed mid-lesson is persisted and
    due *and* still part of the sitting deck, so it must appear only once.
    Cards already rated this sitting (fc_done) or deleted this session
    (fc_deleted) never come back."""
    done = set(st.session_state.get("fc_done", set())) | _deleted_set(student_id)
    cards: dict[str, dict] = {}
    if not due_only and session is not None:
        for card in orch.flashcard_deck(session):
            if card["card_key"] not in done:
                cards[card["card_key"]] = card
    for card in orch.due_reviews(student_id):
        if card["card_key"] not in done:
            cards.setdefault(card["card_key"], card)
    return list(cards.values())


def _row_stats(card: dict, lang: str) -> str:
    """The per-card stat line shown in Browse: EF · interval · reviews ·
    last reviewed · due date."""
    parts = [t("flashcards.row_ef", lang).format(ef=f"{card['ease_factor']:.2f}")]
    ivl = card["interval_days"]
    if ivl == 1:
        parts.append(t("flashcards.day_one", lang).format(n="1"))
    else:
        parts.append(t("flashcards.day_many", lang).format(n=f"{ivl:.0f}"))
    reps = card["repetitions"]
    parts.append(
        t("flashcards.row_review" if reps == 1 else "flashcards.row_reviews",
          lang).format(n=str(reps))
    )
    parts.append(t("flashcards.row_last", lang).format(
        d=_short_date(card["last_reviewed"], lang)))
    parts.append(t("flashcards.row_due", lang).format(
        d=_short_date(card["next_review"], lang)))
    return " · ".join(parts)


def _render_browse(student_id: str, lang: str) -> None:
    """Every persisted card with stats, a source filter, and per-card
    Edit / Delete."""
    cards = orch.browse_flashcards(student_id)
    if not cards:
        st.info(t("flashcards.browse_empty", lang))
        return

    present = []
    for c in cards:
        if c["source"] not in present:
            present.append(c["source"])
    labels = {s: _source_label(s, lang) for s in present}

    filter_key = f"fc_filter_{student_id}"
    choice = st.selectbox(
        t("flashcards.filter_label", lang), ["__all__"] + present,
        format_func=lambda s: (t("flashcards.filter_all", lang)
                               if s == "__all__" else labels.get(s, s)),
        key=filter_key,
    )
    shown = [c for c in cards
             if choice == "__all__" or c["source"] == choice]

    for card in shown:
        key = card["card_key"]
        front = " ".join(card["front"].split())
        if len(front) > 160:
            front = front[:157].rstrip() + "…"
        tag = _source_tag(card["source"], lang)
        st.markdown(
            f"""
            <div class="pd-card">
              <div class="pd-card-row">
                <span class="pd-card-title">{front}</span>
                <span class="fc-tag">{tag}</span>
              </div>
              <div class="pd-card-hint">{_row_stats(card, lang)}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        col1, col2, _ = st.columns([1, 1, 6])
        editing = st.session_state.get(f"browse_edit:{key}", False)
        deleting = st.session_state.get(f"browse_del:{key}", False)
        if not editing and not deleting:
            with col1:
                if st.button(t("flashcards.edit_button", lang),
                             key=f"browse_edit_btn:{key}"):
                    st.session_state[f"browse_edit:{key}"] = True
                    st.rerun()
            with col2:
                if st.button(t("flashcards.delete_button", lang),
                             key=f"browse_del_btn:{key}"):
                    st.session_state[f"browse_del:{key}"] = True
                    st.rerun()
        elif editing:
            front_new = st.text_area(
                t("flashcards.front_label", lang), value=card["front"],
                key=f"browse_front:{key}")
            back_new = st.text_area(
                t("flashcards.back_label", lang), value=card["back"],
                key=f"browse_back:{key}")
            b1, b2 = st.columns(2)
            with b1:
                if st.button(t("flashcards.save_button", lang), type="primary",
                             key=f"browse_save:{key}"):
                    if front_new.strip() and back_new.strip():
                        orch.edit_flashcard(student_id, key,
                                            front_new.strip(), back_new.strip())
                        st.session_state.pop(f"browse_edit:{key}", None)
                        st.rerun()
                    else:
                        st.warning(t("flashcards.edit_invalid", lang))
            with b2:
                if st.button(t("flashcards.cancel_button", lang),
                             key=f"browse_cancel:{key}"):
                    st.session_state.pop(f"browse_edit:{key}", None)
                    st.rerun()
        elif deleting:
            st.warning(t("flashcards.delete_confirm", lang))
            d1, d2 = st.columns(2)
            with d1:
                if st.button(t("flashcards.delete_yes", lang),
                             type="primary", key=f"browse_del_yes:{key}"):
                    orch.delete_flashcard(student_id, key)
                    # Tombstone for this session: the live lesson still knows
                    # the question, so keep it out of review decks here even
                    # though the DB row is gone.
                    _deleted_set(student_id).add(key)
                    for k in (f"browse_edit:{key}", f"browse_del:{key}"):
                        st.session_state.pop(k, None)
                    st.rerun()
            with d2:
                if st.button(t("flashcards.cancel_button", lang),
                             key=f"browse_del_no:{key}"):
                    st.session_state.pop(f"browse_del:{key}", None)
                    st.rerun()
        st.divider()


def render_flashcards(session, lang: str = "en") -> None:
    student_id = st.session_state.get("student_id", "student")
    session_id = session.session_id if session is not None else "none"

    st.subheader(t("flashcards.title", lang))
    st.caption(t("flashcards.tagline", lang))

    # Today's goal, right where the work happens — same seam the dashboard
    # uses (orchestrator.goals_today), so there is no second source of truth.
    today = orch.goals_today(student_id)
    if today.get("goal"):
        st.caption(t("flashcards.goal_chip", lang).format(
            done=str(today["done"]), goal=str(today["goal"])))

    view = st.radio(
        t("flashcards.view_label", lang),
        [t("flashcards.view_all", lang), t("flashcards.view_due", lang),
         t("flashcards.view_browse", lang)],
        horizontal=True, label_visibility="collapsed",
        key=f"fc_view_{student_id}",
    )
    if view == t("flashcards.view_browse", lang):
        _render_browse(student_id, lang)
        return

    due_only = view == t("flashcards.view_due", lang)

    # A (session, view) pair owns one sitting: switching either starts fresh,
    # and so does any deck change made outside this sitting (a rating from the
    # dashboard queue, an edit/delete in Browse, a lesson miss) — detected via
    # the persisted-card signature so a stale card is never re-shown or
    # re-rated over a newer or deleted row.
    sitting = f"{session_id}|{view}"
    sig = orch.flashcard_signature(student_id)
    deck_key = _deck_state_key(student_id)

    fresh = st.session_state.get("fc_session") != sitting
    if not fresh and sig != st.session_state.get("fc_deck_sig"):
        fresh = True  # stale deck → invalidate the sitting
    if fresh:
        st.session_state.fc_session = sitting
        st.session_state.fc_done = set()
        st.session_state.fc_index = 0
        st.session_state.fc_tally = {"again": 0, "good": 0, "easy": 0}
        deck = _build_deck(session, student_id, due_only)
        if deck:
            random.shuffle(deck)
        st.session_state[deck_key] = deck
        st.session_state.fc_deck_sig = sig

    deck = st.session_state[deck_key]
    if not deck:
        if due_only and not orch.due_reviews(student_id):
            st.success(t("flashcards.caught_up", lang))
        else:
            st.info(t("flashcards.empty", lang))
        return

    index = st.session_state.fc_index
    if index >= len(deck):
        _summary(lang)
        return

    card = deck[index]
    position = t("flashcards.pos_review", lang).format(
        n=str(index + 1), total=str(len(deck)))
    result = review_card(student_id, card, lang, ns="fc_deck",
                         position=position)

    if result is not None:
        ease, interval = result
        st.session_state.fc_tally[ease] += 1
        st.session_state.fc_done.add(card["card_key"])
        st.session_state.fc_index += 1
        st.session_state.fc_last = (ease, interval)
        # This sitting made that change itself — the deck already advanced,
        # so the signature follows rather than invalidating the sitting.
        st.session_state.fc_deck_sig = orch.flashcard_signature(student_id)
        st.rerun()

    if st.session_state.get("fc_last"):
        ease, interval = st.session_state.fc_last
        st.caption(interval_note(ease, interval, lang))

    st.progress((index + 1) / len(deck), text=t("flashcards.progress", lang))

    # Running tally, so the student sees the session shaping up.
    tally = st.session_state.fc_tally
    if any(tally.values()):
        st.caption(t("flashcards.tally", lang).format(
            again=tally["again"], good=tally["good"], easy=tally["easy"]))


def _summary(lang: str) -> None:
    tally = st.session_state.fc_tally
    total = sum(tally.values()) or 1
    learned = tally["good"] + tally["easy"]

    st.markdown(f"### {t('flashcards.complete', lang)}")
    col1, col2, col3 = st.columns(3)
    col1.metric(t("flashcards.reviewed", lang), sum(tally.values()))
    col2.metric(t("flashcards.learned", lang), learned)
    col3.metric(t("flashcards.retry", lang), tally["again"])

    if learned / total >= 0.7:
        st.success(t("flashcards.encourage", lang))
    else:
        st.info(t("flashcards.encourage_again", lang))

    if st.button(t("flashcards.review_again", lang), type="primary"):
        st.session_state.fc_session = None   # force a fresh deck
        st.rerun()

    st.divider()
    st.caption(t("flashcards.footer", lang))
