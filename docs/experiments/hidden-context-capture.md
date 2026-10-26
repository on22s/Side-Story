# Raw hidden-context capture (#1258)

The existing owned continuity controller can capture two raw variants for an
interior passage row. Both use the selected speaker's same materialized voice,
seed and baseline instruction. The explicit `pause_after` choice is preserved as
assembly metadata; it is not applied to either raw WAV. One appends up to five
words from the following row; the other also prepends up to five words from the
preceding row. The 256-character cap applies to each context side separately,
excluding the added single-space separators. Over-cap context is refused without
cutting a word. Offsets and character caps use Unicode code points. The authored
text, case and punctuation remain unchanged in each request. The full raw
request must also fit the existing `synthesis_input.MAX_TEXT` character limit;
over-limit context expansion is refused before model initialization. Speech
preparation can still change the submitted string, whose actual proof is
checked after generation as described below.

From `app/` in a clean committed checkout, using synthetic or rights-cleared
source and the existing explicit local configuration:

```sh
python -m experiments.run_dialogue_continuity \
  --input experiments/fixtures/dialogue_continuity_passage.json \
  --voices /your/voices.json --config /your/config.json \
  --row 1 --out /your/new/context-run --capture-hidden-context
```

The default command still captures baseline/deterministic pairs. This option
uses the same audio ownership, cancellation, model cleanup, new-destination
publication and observed-input checks. It makes exactly two top-level rendering
requests and adds no candidate-search retry loop.

The output WAVs contain the hidden speech. They are research inputs, **not
authored takes for delivery**. Receipts preserve each complete request, its
context contract and requested character offsets, source-row/speaker/span
provenance, the actual observed submitted
text, audio hashes, selected voice inputs/seeds, model settings and render time.
The context contract digest covers request choices and the recorded assembly
pause metadata. `pause_after_application` explicitly records
`not_applied_to_raw_audio`; the digest is not an audio-only identity or take-reuse
authority. The controller also retains its ordinary full-source provenance.
Hidden captures use receipt version 2 and kind `hidden_context_raw_capture`;
baseline/deterministic captures retain their existing version 1 format.

Context can come from a neighboring row attributed to another source speaker.
The complete experimental request is performed by the selected target speaker;
it does not switch voices at those source boundaries. The receipt records the
neighbor attribution separately from the audible context contract.

Speech preparation runs through the existing TTS path. No comma/lowercase
transform or extra preparation pass is added. If observed text differs from
the request, `authored_span_in_submitted` is null and its status is
`unresolved_preparation`. Request coordinates must not be applied to that
submitted text or turned into crop authority. An exact request match still
does not establish what words or phonemes were spoken.

As with the existing controller, model cleanup must finish before task ownership
is released. Cleanup failure exits with code 70 and records a failure; already
captured raw files can remain for diagnosis and do not make that run successful.

There is no cropping, alignment pass, automatic selection or application-default
change. Forced-transcript coverage and a verifier's `no_content_candidate` are
not endpoint-preservation certificates. Native serving/model qualification,
safe cropping, independent content/endpoint checks, drift, resource measurements
and blind listening remain separate requirements of #1258.
