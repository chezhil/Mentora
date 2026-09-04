# Vendored: Wav2Lip

This directory contains the model definition and mel front-end from
**[github.com/Rudrabha/Wav2Lip](https://github.com/Rudrabha/Wav2Lip)** —
the code for *"A Lip Sync Expert Is All You Need for Speech to Lip
Generation In the Wild"* (ACM Multimedia 2020).

**License note:** upstream distributes this code for **research and
non-commercial use** (their repository changed from MIT to that status in
late 2020 — see upstream issue #104), and the vendored files carry no
LICENSE file of their own. Avatar Studio uses it accordingly; a commercial
deployment must first verify terms with the upstream repository.

**Provenance:** only four files are vendored (`audio.py`, `conv.py`,
`hparams.py`, `wav2lip.py`) plus an empty package `__init__.py`. They are
kept verbatim from upstream except for two patches, each marked
`PATCHED` in the code, so the files can be diffed against upstream:

- `audio.py`: relative imports (`from .hparams import hparams`) and a
  librosa ≥ 0.10 keyword-argument fix for `librosa.filters.mel`.
- Everything else is byte-for-byte upstream.