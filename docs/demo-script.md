# Mentora — demo video script

Target **5:00** (brief allows 3–7). Covers the seven required beats:
Upload/Topic → Planning → Teaching Video → Interaction → Adaptation →
Assessment → Feedback.

---

## PRE-FLIGHT — do this before you hit record (~15 min)

Nothing kills a demo like waiting on a generation. Every lesson response is
cached in `.cache/llm` keyed on prompt+model, so **a lesson you have already
run once replays instantly and for free.** Run the whole thing once, then
record the second run.

1. **Seed the classroom** so the teacher view has a class in it:
   ```bash
   .venv/bin/python seed_demo_class.py --clear
   ```
2. **Start the server:**
   ```bash
   .venv/bin/uvicorn web.server:app --port 8000
   ```
3. **Dry-run the exact lesson you will record** — same topic, same language,
   same teacher, same minutes. Let it finish. Answer one question wrong on
   purpose so the adaptation branch is cached too.
4. Log in as `student`. Check the dashboard shows that lesson under Recent.
5. **Groq's daily token cap is spent** — if generation 429s, the cache still
   serves the dry-run lesson. Do not change the topic on camera.
6. Close every other tab. Hide bookmarks. Browser zoom 110%. Record at 1080p.

---

## 0:00 – 0:25 · The problem

> *(Screen: the Mentora login page.)*

"Digital learning today is either a recorded lecture or a chatbot. A recorded
lecture can't notice you didn't follow step three. A chatbot answers what you
asked and never asks anything back.

This is **Mentora**. It reads your material, plans a lesson, teaches it on a
board with a teacher you can see, asks you questions — and changes the lesson
when your answers say it should."

---

## 0:25 – 0:50 · Upload or topic → the plan

> *(Log in as a student. Land on the dashboard. Click Start a new lesson.
> Drop in a PDF — one you have already run.)*

"I give it a document. It's chunked on sentence boundaries, embedded with
BGE-M3, and stored in a vector database — so everything it teaches is grounded
in *my* material, not the model's memory. Or I can just name a topic and it
plans the lesson anyway.

I pick my level, my language, and how long I've got — one to sixty minutes."

> *(Click Start Lesson. Point at the plan as it appears.)*

"It plans first: the concepts, the order to teach them in, and the minutes each
one gets. The time budget is real — twenty minutes covers fewer concepts,
deeper."

---

## 0:50 – 1:45 · The teaching video

> *(Play the first segment. Let it run 20–25 seconds — do not talk over the
> whole thing. Let the jury hear the narration and watch the board build.)*

"This is a generated video, not a slideshow.

The board draws itself as the narration reaches it — each element appears at
the moment it's spoken about. The teacher is **rendered into the frame**, not
a floating head laid over the top. She's lip-synced to the narration and she
glances at each element as it lands.

Six characters, eighteen languages, each with its own neural voice and the font
its script needs."

> *(Hover the citation on the segment.)*

"And every segment cites the chunk of my document it came from."

---

## 1:45 – 2:25 · Interaction

> *(The lesson stops at a question. Answer it WRONG — the one you rehearsed.)*

"It stops and asks. And I have to answer to move on — I can't skip ahead.

Watch what it does with a wrong answer."

> *(Pause on the feedback.)*

"It doesn't say 'incorrect.' It names **the misconception** — it works out what
I actually believe that made me answer that way."

---

## 2:25 – 3:05 · Adaptation  ⟵ *the most important 40 seconds*

> *(Open the adaptation panel.)*

"This is the part that makes it a teacher rather than a talking avatar.

That misconception goes back into the plan. It re-teaches the same concept with
a **different analogy** — not the same explanation louder. Two wrong answers
and it simplifies the route. Two quick right ones and it hardens it.

The lesson I get is not the lesson the student next to me gets."

---

## 3:05 – 3:30 · Multilingual

> *(Switch language, show the same lesson in Hindi or Tamil.)*

"Eighteen languages. And it's not subtitles — the narration, the board labels
and the questions are all generated in that language, with a native voice."

---

## 3:30 – 3:55 · Voice mode

> *(Open Talk out loud. Click Start talking. Ask one short question aloud.)*

"I can also just talk to it. It answers aloud — and it still draws while it
explains. The teacher is right there in the conversation."

---

## 3:55 – 4:25 · Assessment and feedback

> *(Finish the lesson → the report.)*

"At the end: a scored report, what I got wrong, the misconceptions it found,
and what to revise next.

Those turn into flashcards on an SM-2 spaced-repetition schedule, so the
material comes back on the day I'm about to forget it. And the full transcript
downloads."

---

## 4:25 – 4:50 · The teacher's view

> *(Sign out. Log in as the teacher. Show the classroom.)*

"Teachers get the other side of it. Class average, a row per student — and the
**reteach list**: misconceptions that more than one student is holding.

That's the thing a teacher actually wants. Not 'the class scored 61%', but
'six of them think current gets used up in the circuit.'"

---

## 4:50 – 5:10 · Close

> *(Architecture diagram or the README.)*

"Upload, retrieve, plan, teach, question, evaluate, adapt, assess. One engine
behind a web app and a Streamlit app — so neither is a mock of the other.

Mentora. Team Winners."

---

## If you're running out of time — cut in this order

1. Voice mode (3:30) — nice, not scored heavily
2. Multilingual (3:05) — trim to one sentence over a still
3. The close (4:50) — end on the classroom view instead

**Never cut Adaptation (2:25).** It is 20 of the 100 marks, and the brief
warns twice that a talking avatar reading a script will not score.

## Don't say
- "it should", "normally this works", "if the API is up" — narrate what is on
  screen, nothing else
- any word about quota, cache, or bugs
