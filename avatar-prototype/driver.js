/* The performance driver: audio in, avatar parameters out.
 *
 * This file knows NOTHING about how the character is drawn. It produces a
 * plain object of parameters once per frame and hands it to whatever backend
 * is plugged in — the SVG reference character here, a Live2D model later.
 * That seam is the whole point of the prototype: the driver is the part that
 * decides whether the avatar feels alive, and it is worth getting right
 * before committing to a model format.
 *
 * WHY AMPLITUDE AND NOT PHONEMES
 *
 * The obvious approach is text -> phonemes -> visemes. We measured the
 * alternative first: edge-tts, which generates all of Mentora's narration,
 * now returns only SentenceBoundary events — no per-word timing — for
 * English, Hindi and Tamil alike. So there is nothing to align against
 * without adding a forced aligner and a model per language.
 *
 * Amplitude-driven mouths are also what VTuber software actually does, and
 * it reads convincingly. It has the property we need most: it is completely
 * language-agnostic, so all eighteen of Mentora's languages work with no
 * per-language work at all.
 */

// ---------------------------------------------------------------------------
// Tuning. Every number here was arrived at by watching it, not by theory.
// ---------------------------------------------------------------------------

const TUNING = {
  // TRUE silence. Below this the mouth is shut whatever the adaptation says.
  absoluteGateDb: -55,

  // Everything else about loudness is measured RELATIVE to a running estimate
  // of how loud this voice is, not against fixed thresholds.
  //
  // Fixed thresholds were the first attempt and they failed badly. Measured
  // against real Mentora narration: TTS output is heavily compressed and sits
  // at about -16 dB RMS almost continuously, so a fixed -45..-12 dB window put
  // the mouth at a mean of 0.87 and it NEVER fully closed — the exact
  // slack-jawed look the gate above exists to prevent. Different voices,
  // languages and backends all sit at different levels, so the only thing that
  // works across eighteen languages is to follow the voice.
  dynamicRangeDb: 14,      // window below the running peak that maps to 0..1

  // Loudness in dB is not how far a jaw drops. Straight off the normalised
  // level, measured narration sat wide open (>0.8) for half of all frames and
  // read as shouting rather than speaking. Bending the response pulls the
  // ordinary middle of speech down without touching the extremes: silence is
  // still shut, an emphatic syllable still reaches full.
  openCurve: 2.2,
  peakDecayDbPerSec: 12,   // how fast that peak falls during a pause
  peakFloorDb: -50,        // never adapt below this, or mic hiss becomes speech
  peakRise: 0.5,           // so one click cannot pin the peak for a second

  // Mouths open faster than they close. This asymmetry is most of what
  // separates speech from flapping — with a single symmetric smoothing the
  // jaw lags the consonants and the whole thing looks dubbed.
  attackMs: 22,
  releaseMs: 110,

  // Frequency bands for picking the mouth SHAPE, not its size. Sibilants and
  // close vowels put energy up high; open vowels put it low. The ratio gives
  // a wide/narrow axis for free, which is enough variety that the mouth stops
  // looking like a single opening and closing hole.
  lowBand: [120, 1000],
  highBand: [2200, 6500],
  formSmoothMs: 90,
  formGain: 5.0,

  blinkMinMs: 2200,
  blinkMaxMs: 6000,
  blinkDurationMs: 130,

  // Eyes reach a target well before the head does. Getting this backwards is
  // uncanny in a way that is hard to name but easy to see.
  eyeFollow: 0.28,
  headFollow: 0.06,
  headLookAmount: 0.45,
};

const clamp = (v, lo, hi) => (v < lo ? lo : v > hi ? hi : v);
const lerp = (a, b, t) => a + (b - a) * t;

// A smoothing coefficient for a given time constant, frame-rate independent.
// Doing this per frame rather than with a fixed 0.9 means the motion looks
// the same on a 60Hz laptop and a 120Hz display.
const coef = (ms, dt) => 1 - Math.exp(-dt / (ms / 1000));

/* Layered sines at incommensurate frequencies. Cheaper than real noise and
 * indistinguishable at this amplitude; the irrational ratios stop it from
 * visibly repeating, which a single sine does within seconds. */
function drift(t, seed) {
  return (
    Math.sin(t * 0.31 + seed) * 0.55 +
    Math.sin(t * 0.73 + seed * 2.1) * 0.30 +
    Math.sin(t * 1.19 + seed * 3.7) * 0.15
  );
}

export class AvatarDriver {
  constructor() {
    this.ctx = null;
    this.analyser = null;
    this.source = null;
    this.timeBuf = null;
    this.freqBuf = null;

    this.mouthOpen = 0;
    this.mouthForm = 0;
    this.eyeOpen = 1;
    this.speaking = false;

    this._formRaw = 0;
    this._lookX = 0;
    this._lookY = 0;
    this._eyeX = 0;
    this._eyeY = 0;
    this._headX = 0;
    this._headY = 0;
    this._nextBlink = 0;
    this._blinkUntil = 0;
    this._last = 0;
    this._t = 0;
    this._energy = 0;
    this._peakDb = -60;
  }

  /* Lazily created: browsers refuse to start an AudioContext before a user
   * gesture, so this must be called from a click handler, never on load. */
  _audioContext() {
    if (!this.ctx) {
      this.ctx = new (window.AudioContext || window.webkitAudioContext)();
      this.analyser = this.ctx.createAnalyser();
      this.analyser.fftSize = 1024;
      // Our own attack/release below is doing the smoothing; letting the
      // analyser smooth as well just adds latency the mouth cannot hide.
      this.analyser.smoothingTimeConstant = 0;
      this.timeBuf = new Float32Array(this.analyser.fftSize);
      this.freqBuf = new Float32Array(this.analyser.frequencyBinCount);
    }
    if (this.ctx.state === "suspended") this.ctx.resume();
    return this.ctx;
  }

  /* Drive from an <audio> element. The element stays connected to the
   * speakers, so the lesson is audible as well as visible. */
  attachElement(el) {
    const ctx = this._audioContext();
    // Tear the graph down before rebuilding it. Reconnecting the analyser to
    // the destination on every attach relies on duplicate connections being a
    // no-op; making it explicit means there is exactly one path to the
    // speakers however many times this is called.
    if (this.source) {
      try { this.source.disconnect(); } catch { /* already gone */ }
    }
    try { this.analyser.disconnect(); } catch { /* not connected yet */ }

    // An element can only ever be the source of ONE MediaElementSourceNode;
    // creating a second throws. Cache it on the element itself.
    if (!el._avatarSource) el._avatarSource = ctx.createMediaElementSource(el);
    this.source = el._avatarSource;
    this.source.connect(this.analyser);
    this.analyser.connect(ctx.destination);
  }

  /* Drive from the microphone — the fastest way to see whether the rig looks
   * alive, because you control it directly. Deliberately NOT connected to the
   * destination: that is a feedback loop through the laptop speakers. */
  async attachMicrophone() {
    const ctx = this._audioContext();
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    if (this.source) this.source.disconnect();
    this.source = ctx.createMediaStreamSource(stream);
    this.source.connect(this.analyser);
  }

  _level(dt) {
    this.analyser.getFloatTimeDomainData(this.timeBuf);
    let sum = 0;
    for (let i = 0; i < this.timeBuf.length; i++) sum += this.timeBuf[i] ** 2;
    const rms = Math.sqrt(sum / this.timeBuf.length);
    const db = 20 * Math.log10(rms + 1e-9);

    const decayed = Math.max(this._peakDb - TUNING.peakDecayDbPerSec * dt,
                             TUNING.peakFloorDb);
    if (db < TUNING.absoluteGateDb) {
      this._peakDb = decayed;
      return 0;
    }
    this._peakDb = db > this._peakDb
      ? lerp(this._peakDb, db, TUNING.peakRise)
      : decayed;

    const floor = this._peakDb - TUNING.dynamicRangeDb;
    return clamp((db - floor) / (this._peakDb - floor), 0, 1);
  }

  /* Which mouth shape, from spectral tilt. 0 = round and open, 1 = wide and
   * narrow. Not real visemes — but it varies with the sound being made, and
   * that is the difference between a mouth and a hinge. */
  _form() {
    this.analyser.getFloatFrequencyData(this.freqBuf);
    const nyquist = this.ctx.sampleRate / 2;
    const bin = (hz) =>
      clamp(Math.round((hz / nyquist) * this.freqBuf.length), 0,
            this.freqBuf.length - 1);
    const band = ([lo, hi]) => {
      let total = 0, n = 0;
      for (let i = bin(lo); i <= bin(hi); i++) {
        total += Math.pow(10, this.freqBuf[i] / 20);
        n++;
      }
      return n ? total / n : 0;
    };
    const low = band(TUNING.lowBand);
    const high = band(TUNING.highBand);
    if (low + high < 1e-7) return this._formRaw;
    return clamp((high / (low + high)) * TUNING.formGain, 0, 1);
  }

  lookAt(x, y) {
    this._lookX = clamp(x, -1, 1);
    this._lookY = clamp(y, -1, 1);
  }

  /* One frame. Returns the parameter block for the rendering backend. */
  update(now) {
    const dt = this._last ? Math.min((now - this._last) / 1000, 0.1) : 0.016;
    this._last = now;
    this._t += dt;

    let level = 0;
    if (this.analyser) {
      level = this._level(dt);
      const f = this._form();
      this._formRaw = lerp(this._formRaw, f, coef(TUNING.formSmoothMs, dt));
    }

    const shaped = Math.pow(level, TUNING.openCurve);

    // Asymmetric attack/release — see TUNING.
    const rate = shaped > this.mouthOpen ? TUNING.attackMs : TUNING.releaseMs;
    this.mouthOpen = lerp(this.mouthOpen, shaped, coef(rate, dt));
    this.mouthForm = this._formRaw;
    this.speaking = this.mouthOpen > 0.06;

    // A slow envelope of how animated the speech is, so the head moves more
    // during an emphatic passage and settles when the teacher pauses.
    this._energy = lerp(this._energy, level, coef(400, dt));

    // --- gaze ------------------------------------------------------------
    // Eyes arrive first, head follows part of the way. Reversing this is the
    // single most uncanny thing you can do to a face.
    this._eyeX = lerp(this._eyeX, this._lookX, TUNING.eyeFollow);
    this._eyeY = lerp(this._eyeY, this._lookY, TUNING.eyeFollow);
    this._headX = lerp(this._headX, this._lookX * TUNING.headLookAmount,
                       TUNING.headFollow);
    this._headY = lerp(this._headY, this._lookY * TUNING.headLookAmount,
                       TUNING.headFollow);

    // --- blink -----------------------------------------------------------
    const ms = now;
    if (!this._nextBlink) this._nextBlink = ms + 1200;
    if (ms > this._nextBlink && ms > this._blinkUntil) {
      this._blinkUntil = ms + TUNING.blinkDurationMs;
      const span = TUNING.blinkMaxMs - TUNING.blinkMinMs;
      this._nextBlink = ms + TUNING.blinkMinMs + Math.random() * span;
    }
    if (ms < this._blinkUntil) {
      // Fast close, slightly slower open — a linear blink reads as a glitch.
      const p = 1 - (this._blinkUntil - ms) / TUNING.blinkDurationMs;
      this.eyeOpen = p < 0.4 ? 1 - p / 0.4 : (p - 0.4) / 0.6;
    } else {
      this.eyeOpen = 1;
    }

    // --- idle motion -----------------------------------------------------
    const life = 0.35 + this._energy * 0.9;
    return {
      mouthOpen: this.mouthOpen,
      mouthForm: this.mouthForm,
      eyeOpen: this.eyeOpen,
      eyeX: this._eyeX,
      eyeY: this._eyeY,
      angleX: this._headX * 26 + drift(this._t, 1.7) * 3.4 * life,
      angleY: this._headY * 18 + drift(this._t, 4.2) * 2.6 * life,
      angleZ: drift(this._t, 8.9) * 2.8 * life,
      breath: (Math.sin(this._t * 1.1) + 1) / 2,
      brow: this._energy * 0.7,
      speaking: this.speaking,
      level,
    };
  }
}

export { TUNING };
