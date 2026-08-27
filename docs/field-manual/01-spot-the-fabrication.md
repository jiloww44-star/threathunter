# Drill 01 — Spot the fabrication

**Objective:** prove (to yourself) that you check the evidence behind an AI
answer instead of trusting a confident paragraph. ~8 min.

## Setup

1. Open the Ops Node (`#/ops`).
2. Goal: `Is it true that Company X was sanctioned in August 2026?` — the
   seeded demo claim; its answer rides on the evidence pack (two wire
   accounts sharing one regulatory document + one copy-cat daily).

## Steps

1. Read the cortex's answer and confidence **without scrolling**. Write down
   what you'd stake money on from that paragraph alone.
2. Open the generated task tree → the report → **KEY EVIDENCE** and
   **SOURCES**. For the top three evidence items, click into the raw task
   output (every node exposes input/output JSON).
3. Answer for each: *independent source, or copy of another item?* The
   demo pack is built to train exactly this eye — `sources_independent`
   is deliberately smaller than `sources_total` because two outlets repeat
   one wire. Copy-chains count as one source (§1.6).
4. Compare with what you wrote in step 1.

## Expected honest behavior to recognize

- Confidence tracks *source independence*, not fluency.
- The **CONTRADICTIONS** section may be empty; that means none were found in
  the bounded pack, not that contradictions can't exist (UNVERIFIED ≠ FALSE).
- The **INTERPRETATION** block is labelled INFERENCE — it is not fact.

## Pass condition (self-judged)

You can name one claim the report makes that *the cited evidence does not
directly establish*, or state honestly that every top claim traces. If you
can't do either for three items, re-run until you can.
